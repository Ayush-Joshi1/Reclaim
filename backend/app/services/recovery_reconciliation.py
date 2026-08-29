"""Synchronize persisted recovery attempts with Razorpay Payment Links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, settings
from app.database import SessionLocal, create_tables
from app.models import RecoveryAttempt
from app.schemas.revenue_risk import MerchantPolicy
from app.services.recovery_state import RecoveryStateMachine
from app.services.razorpay_client import RazorpayClient, RazorpayClientError


class PaymentLinkClient(Protocol):
    def get_payment_link(self, payment_link_id: str):
        """Retrieve one normalized provider Payment Link."""


@dataclass(frozen=True)
class ReconciliationResult:
    """Safe, auditable outcome for one reconciliation attempt."""

    attempt_id: str
    payment_id: str
    provider_payment_link_id: str
    status: str
    previous_state: str | None
    provider_state: str | None
    resulting_state: str | None
    reason: str


class RecoveryReconciliationService:
    """Reconcile only Payment Links previously created by Reclaim."""

    def __init__(
        self,
        client: PaymentLinkClient | None = None,
        session_factory=SessionLocal,
        configured: Settings = settings,
        policy: MerchantPolicy | None = None,
    ) -> None:
        self._client = client or RazorpayClient.from_settings(configured)
        self._session_factory = session_factory
        self._configured = configured
        self._policy = policy or MerchantPolicy()

    def reconcile_attempt(self, attempt_id: str) -> ReconciliationResult:
        """Reconcile one persisted Payment Link attempt."""
        create_tables()
        with self._session_factory() as session:
            attempt = session.scalar(
                select(RecoveryAttempt)
                .options(joinedload(RecoveryAttempt.payment))
                .where(RecoveryAttempt.id == attempt_id)
            )
            if attempt is None:
                raise ValueError("Recovery attempt was not found.")
            return self._reconcile(session, attempt)

    def reconcile_payment(self, payment_id: str) -> list[ReconciliationResult]:
        """Reconcile the latest eligible Payment Link attempt for a payment."""
        create_tables()
        with self._session_factory() as session:
            attempts = session.scalars(
                select(RecoveryAttempt)
                .options(joinedload(RecoveryAttempt.payment))
                .where(RecoveryAttempt.payment.has(razorpay_payment_id=payment_id))
                .order_by(desc(RecoveryAttempt.created_at))
            ).all()
            return [self._reconcile(session, attempt) for attempt in attempts if self._is_candidate(attempt)]

    def reconcile_eligible(self) -> list[ReconciliationResult]:
        """Reconcile all currently eligible Reclaim-created Payment Links."""
        create_tables()
        with self._session_factory() as session:
            attempts = session.scalars(
                select(RecoveryAttempt)
                .options(joinedload(RecoveryAttempt.payment))
                .where(
                    RecoveryAttempt.action == "PAYMENT_LINK",
                    RecoveryAttempt.provider_called.is_(True),
                    RecoveryAttempt.provider_payment_link_id.is_not(None),
                )
                .order_by(desc(RecoveryAttempt.created_at))
            ).all()
            return [self._reconcile(session, attempt) for attempt in attempts if self._is_candidate(attempt)]

    def _reconcile(self, session: Session, attempt: RecoveryAttempt) -> ReconciliationResult:
        previous_state = attempt.recovery_state
        payment_id = attempt.payment.razorpay_payment_id or str(attempt.payment_id)
        link_id = attempt.provider_payment_link_id
        if not link_id:
            return self._record(
                session, attempt, "skipped", previous_state, None, previous_state,
                "No Reclaim-created Payment Link is recorded.", increment=False,
            )
        if not self._is_candidate(attempt):
            return self._record(
                session, attempt, "skipped", previous_state, None, previous_state,
                "Recovery attempt is outside reconciliation eligibility.", increment=False,
            )

        attempt.reconciliation_attempts += 1
        try:
            provider_link = self._client.get_payment_link(link_id)
        except RazorpayClientError:
            session.commit()
            return self._record(
                session, attempt, "failed", previous_state, None, previous_state,
                "Razorpay Payment Link state could not be retrieved; local state was unchanged.",
            )

        provider_state = (provider_link.status or "").lower()
        state_map = {
            "created": ("unchanged", previous_state, "Payment Link remains active."),
            "active": ("unchanged", previous_state, "Payment Link remains active."),
            "paid": ("recovered", "recovered", "Razorpay reports the Payment Link as paid."),
            "expired": ("failed", "failed", "Razorpay reports the Payment Link as expired."),
            "cancelled": ("stopped", "stopped", "Razorpay reports the Payment Link as cancelled."),
            "closed": ("stopped", "stopped", "Razorpay reports the Payment Link as closed."),
        }
        mapped = state_map.get(provider_state)
        if mapped is None:
            session.commit()
            return self._record(
                session, attempt, "unknown_state", previous_state, provider_state, previous_state,
                "Razorpay returned an unsupported Payment Link state; local state was unchanged.",
            )

        result_status, resulting_state, reason = mapped
        if provider_state == "paid" and previous_state in {"recovered", "stopped", "duplicate", "ignored"}:
            resulting_state = previous_state
            result_status = "unchanged"
            reason = "Local terminal state is protected from provider-state regression or override."
        elif resulting_state != previous_state:
            try:
                resulting_state = RecoveryStateMachine.transition(previous_state or "detected", resulting_state)
            except ValueError:
                resulting_state = previous_state
                result_status = "unchanged"
                reason = "Provider state could not safely transition the local recovery state; local state was unchanged."

        if resulting_state == "recovered" and previous_state != "recovered":
            attempt.payment.status = "successful"
            attempt.payment.recovery_state = "recovered"
            attempt.payment.failure_reason = None
            attempt.payment.state_updated_at = datetime.now(UTC)
            attempt.provider_payment_id = attempt.provider_payment_id or None
            attempt.execution_succeeded = True
            attempt.completed_at = datetime.now(UTC)
        elif resulting_state == "failed" and previous_state != "failed":
            attempt.status = "terminal"
        elif resulting_state == "stopped" and previous_state != "stopped":
            attempt.payment.status = "closed"
            attempt.payment.recovery_state = "stopped"
            attempt.payment.state_updated_at = datetime.now(UTC)
            attempt.status = "terminal"

        if resulting_state != previous_state:
            attempt.recovery_state = resulting_state
        session.commit()
        return self._record(
            session, attempt, result_status, previous_state, provider_state, resulting_state, reason,
        )

    def _is_candidate(self, attempt: RecoveryAttempt) -> bool:
        if attempt.action != "PAYMENT_LINK" or not attempt.provider_called or not attempt.provider_payment_link_id:
            return False
        if attempt.recovery_state in {"recovered", "stopped", "duplicate", "ignored"}:
            return False
        if attempt.reconciliation_attempts >= self._configured.reconciliation_max_attempts:
            return False
        created_at = attempt.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age_hours = (datetime.now(UTC) - created_at).total_seconds() / 3600
        return age_hours <= self._policy.recovery_window_hours

    @staticmethod
    def _record(
        session: Session,
        attempt: RecoveryAttempt,
        status: str,
        previous_state: str | None,
        provider_state: str | None,
        resulting_state: str | None,
        reason: str,
        *,
        increment: bool = True,
    ) -> ReconciliationResult:
        if increment:
            attempt.reconciliation_attempts = max(attempt.reconciliation_attempts, 1)
        attempt.reconciliation_status = status
        attempt.reconciliation_previous_state = previous_state
        attempt.reconciliation_provider_state = provider_state
        attempt.reconciliation_resulting_state = resulting_state
        attempt.reconciliation_reason = reason
        attempt.reconciled_at = datetime.now(UTC)
        session.commit()
        return ReconciliationResult(
            attempt_id=str(attempt.id),
            payment_id=attempt.payment.razorpay_payment_id or str(attempt.payment_id),
            provider_payment_link_id=attempt.provider_payment_link_id or "",
            status=status,
            previous_state=previous_state,
            provider_state=provider_state,
            resulting_state=resulting_state,
            reason=reason,
        )
