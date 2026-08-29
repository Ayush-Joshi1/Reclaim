"""Persistent, policy-aware follow-up processing for recovery attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, settings
from app.database import SessionLocal, create_tables
from app.models import Payment, RecoveryAttempt
from app.schemas import CustomerRiskContext, MerchantPolicy, PaymentRiskInput
from app.schemas.workflow import RecoveryEvent
from app.services.recovery_reconciliation import RecoveryReconciliationService
from app.services.recovery_state import RecoveryStateMachine
from app.services.recovery_workflow import RecoveryWorkflowService


@dataclass(frozen=True)
class FollowUpResult:
    """Outcome for one claimed or skipped follow-up."""

    attempt_id: str
    payment_id: str
    status: str
    reason: str
    new_attempt_id: str | None = None


@dataclass(frozen=True)
class FollowUpSummary:
    """Bounded batch counters suitable for an authenticated job endpoint."""

    processed_count: int
    recovered_count: int
    retried_count: int
    stopped_count: int
    skipped_count: int
    failure_count: int
    results: list[FollowUpResult]


class RecoveryFollowUpService:
    """Claim, reconcile, and safely re-evaluate persisted recovery attempts."""

    def __init__(
        self,
        reconciler: RecoveryReconciliationService | None = None,
        workflow: RecoveryWorkflowService | None = None,
        session_factory=SessionLocal,
        configured: Settings = settings,
        policy: MerchantPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._configured = configured
        self._policy = policy or MerchantPolicy()
        self._reconciler = reconciler or RecoveryReconciliationService(configured=configured, policy=self._policy)
        self._workflow = workflow or RecoveryWorkflowService(
            session_factory=session_factory, policy=self._policy
        )

    def process_attempt(self, attempt_id: str) -> FollowUpResult:
        """Process one persisted Payment Link follow-up, if it is claimable."""
        create_tables()
        claimed = self._claim(attempt_id)
        if claimed is None:
            return FollowUpResult(attempt_id, "", "skipped", "Attempt is not eligible or is already claimed.")

        attempt_id, payment_id = claimed
        reconciliation = self._reconciler.reconcile_attempt(attempt_id)
        attempt = self._load_attempt(attempt_id)
        if attempt is None:
            return FollowUpResult(attempt_id, payment_id, "failed", "Recovery attempt disappeared during processing.")

        if attempt.recovery_state == "recovered" or attempt.payment.recovery_state == "recovered":
            self._finish(attempt_id, "recovered", "Payment is recovered; no follow-up action is required.")
            return FollowUpResult(attempt_id, payment_id, "recovered", "Payment is recovered; no follow-up action is required.")

        if reconciliation.provider_state in {"created", "active"}:
            self._finish(attempt_id, "waiting", "Payment Link remains active and unpaid; waiting for provider outcome.")
            return FollowUpResult(attempt_id, payment_id, "waiting", "Payment Link remains active and unpaid.")

        if reconciliation.status in {"unknown_state", "failed"} and attempt.recovery_state not in {"failed", "stopped"}:
            self._finish(attempt_id, "waiting", reconciliation.reason)
            return FollowUpResult(attempt_id, payment_id, "waiting", reconciliation.reason)

        if attempt.recovery_state == "stopped":
            self._finish(attempt_id, "stopped", "Recovery is terminal and cannot be retried.")
            return FollowUpResult(attempt_id, payment_id, "stopped", "Recovery is terminal and cannot be retried.")

        if not self._retry_allowed(attempt):
            self._stop(attempt_id, "Recovery retry limit or recovery window has been reached.")
            return FollowUpResult(attempt_id, payment_id, "stopped", "Recovery retry limit or recovery window has been reached.")

        return self._reevaluate(attempt)

    def process_payment(self, payment_id: str) -> list[FollowUpResult]:
        """Process all eligible follow-ups for one payment, newest first."""
        attempt_ids = self._eligible_attempt_ids(payment_id=payment_id)
        return [self.process_attempt(attempt_id) for attempt_id in attempt_ids]

    def process_pending(self, limit: int = 20) -> FollowUpSummary:
        """Process a bounded batch of eligible follow-ups."""
        bounded_limit = max(1, min(limit, 100))
        attempt_ids = self._eligible_attempt_ids(limit=bounded_limit)
        results = [self.process_attempt(attempt_id) for attempt_id in attempt_ids]
        return FollowUpSummary(
            processed_count=sum(result.status not in {"skipped"} for result in results),
            recovered_count=sum(result.status == "recovered" for result in results),
            retried_count=sum(result.status == "retried" for result in results),
            stopped_count=sum(result.status == "stopped" for result in results),
            skipped_count=sum(result.status == "skipped" for result in results),
            failure_count=sum(result.status == "failed" for result in results),
            results=results,
        )

    def _claim(self, attempt_id: str) -> tuple[str, str] | None:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            try:
                parsed_id = UUID(attempt_id)
            except ValueError:
                return None
            attempt = session.scalar(
                select(RecoveryAttempt)
                .where(RecoveryAttempt.id == parsed_id)
                .with_for_update()
            )
            if attempt is None or not self._eligible(attempt, now):
                return None
            payment_id = attempt.payment.razorpay_payment_id or str(attempt.payment_id)
            attempt.follow_up_status = "claimed"
            attempt.follow_up_claimed_until = now + timedelta(seconds=self._configured.follow_up_lease_seconds)
            attempt.follow_up_last_run_at = now
            session.commit()
            return str(attempt.id), payment_id

    def _eligible_attempt_ids(self, payment_id: str | None = None, limit: int | None = None) -> list[str]:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            statement = (
                select(RecoveryAttempt)
                .options(joinedload(RecoveryAttempt.payment))
                .where(
                    RecoveryAttempt.action == "PAYMENT_LINK",
                    RecoveryAttempt.provider_called.is_(True),
                    RecoveryAttempt.provider_payment_link_id.is_not(None),
                    or_(RecoveryAttempt.follow_up_next_at.is_(None), RecoveryAttempt.follow_up_next_at <= now),
                )
                .order_by(desc(RecoveryAttempt.created_at))
            )
            if payment_id is not None:
                statement = statement.where(RecoveryAttempt.payment.has(razorpay_payment_id=payment_id))
            if limit is not None:
                statement = statement.limit(limit)
            attempts = session.scalars(statement).all()
            return [str(attempt.id) for attempt in attempts if self._eligible(attempt, now)]

    def _eligible(self, attempt: RecoveryAttempt, now: datetime) -> bool:
        if attempt.action != "PAYMENT_LINK" or not attempt.provider_called or not attempt.provider_payment_link_id:
            return False
        if attempt.recovery_state in {"recovered", "stopped", "duplicate", "ignored"}:
            return False
        if attempt.follow_up_status in {"superseded", "recovered", "stopped"}:
            return False
        if attempt.follow_up_claimed_until is not None and attempt.follow_up_claimed_until > now:
            return False
        return True

    def _load_attempt(self, attempt_id: str) -> RecoveryAttempt | None:
        with self._session_factory() as session:
            return session.scalar(
                select(RecoveryAttempt)
                .options(joinedload(RecoveryAttempt.payment).joinedload(Payment.customer))
                .where(RecoveryAttempt.id == UUID(attempt_id))
            )

    def _retry_allowed(self, attempt: RecoveryAttempt) -> bool:
        if attempt.recovery_state != "failed":
            return False
        attempt_age = attempt.created_at
        if attempt_age.tzinfo is None:
            attempt_age = attempt_age.replace(tzinfo=UTC)
        if (datetime.now(UTC) - attempt_age).total_seconds() / 3600 > self._policy.recovery_window_hours:
            return False
        with self._session_factory() as session:
            count = session.scalar(
                select(RecoveryAttempt.attempt_number)
                .where(RecoveryAttempt.payment_id == attempt.payment_id)
                .order_by(desc(RecoveryAttempt.attempt_number))
                .limit(1)
            ) or 0
        return count < self._policy.max_recovery_attempts

    def _reevaluate(self, attempt: RecoveryAttempt) -> FollowUpResult:
        payment = attempt.payment
        now = datetime.now(UTC)
        failed_at = attempt.created_at
        if failed_at.tzinfo is None:
            failed_at = failed_at.replace(tzinfo=UTC)
        elapsed_hours = max(0, int((now - failed_at).total_seconds() // 3600))
        event_id = f"follow-up-{attempt.id}-{(attempt.attempt_number or 0) + 1}"
        event = RecoveryEvent(
            event_id=event_id,
            payment_id=attempt.payment.razorpay_payment_id or str(attempt.payment_id),
            event_type="recovery_requested",
            timestamp=now,
            source="recovery-follow-up",
            payment=PaymentRiskInput(
                payment_id=attempt.payment.razorpay_payment_id or str(attempt.payment_id),
                amount=payment.amount,
                currency=payment.currency,
                payment_method="card",
                status="failed",
                failure_reason=payment.failure_reason,
                failed_at=failed_at,
                time_since_failure_hours=elapsed_hours,
            ),
            customer=CustomerRiskContext(
                customer_id=str(payment.customer_id),
                customer_age_days=0,
                previous_successful_payments=0,
                previous_failed_payments=0,
                previous_recovery_attempts=max(0, (attempt.attempt_number or 1) - 1),
                customer_lifetime_value=0,
                average_previous_payment=0,
                recent_payment_frequency=0,
            ),
            recovery_attempt_count=attempt.attempt_number or 0,
        )
        response = self._workflow.process(event)
        new_attempt = self._load_by_event(event_id)
        self._finish(str(attempt.id), "superseded", "A new validated recovery attempt was created.")
        if new_attempt is not None:
            status = "stopped" if new_attempt.recovery_state == "stopped" else "retried"
            if status == "retried":
                self._finish(str(new_attempt.id), "waiting", "Waiting for the new recovery action outcome.")
            return FollowUpResult(str(attempt.id), event.payment_id, status, response.result.message, str(new_attempt.id))
        return FollowUpResult(str(attempt.id), event.payment_id, "failed", "Follow-up evaluation was not persisted.")

    def _load_by_event(self, event_id: str) -> RecoveryAttempt | None:
        with self._session_factory() as session:
            return session.scalar(
                select(RecoveryAttempt)
                .options(joinedload(RecoveryAttempt.payment))
                .where(RecoveryAttempt.event_id == event_id)
            )

    def _finish(self, attempt_id: str, status: str, reason: str) -> None:
        with self._session_factory() as session:
            attempt = session.scalar(select(RecoveryAttempt).where(RecoveryAttempt.id == UUID(attempt_id)))
            if attempt is not None:
                attempt.follow_up_status = status
                attempt.follow_up_last_reason = reason
                attempt.follow_up_last_run_at = datetime.now(UTC)
                attempt.follow_up_claimed_until = None
                session.commit()

    def _stop(self, attempt_id: str, reason: str) -> None:
        with self._session_factory() as session:
            attempt = session.scalar(select(RecoveryAttempt).where(RecoveryAttempt.id == UUID(attempt_id)))
            if attempt is None:
                return
            if attempt.recovery_state != "stopped":
                attempt.recovery_state = RecoveryStateMachine.transition(attempt.recovery_state or "failed", "stopped")
                attempt.status = "terminal"
                attempt.payment.recovery_state = "stopped"
                attempt.payment.status = "closed"
            attempt.follow_up_status = "stopped"
            attempt.follow_up_last_reason = reason
            attempt.follow_up_last_run_at = datetime.now(UTC)
            attempt.follow_up_claimed_until = None
            session.commit()
