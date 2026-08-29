"""Orchestrate recovery evaluation without executing external actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
import threading
from typing import Callable, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas import (
    CustomerRiskContext,
    MerchantPolicy,
    PaymentRiskInput,
    RecoveryHistory,
)
from app.schemas.razorpay import RazorpayPayment
from app.schemas.workflow import RecoveryActionResult, RecoveryEvent, RecoveryWorkflowResponse
from app.database import SessionLocal, create_tables
from app.models import Customer, Payment, RecoveryAttempt
from app.services.llm_client import FakeLLMClient, LLMClient, OpenAICompatibleLLMClient
from app.services.recovery_context import build_recovery_context
from app.services.recovery_decision import RecoveryDecisionService
from app.services.revenue_risk import RevenueRiskEngine
from app.services.razorpay_client import RazorpayClient
from app.services.action_executor import ActionExecutor, DryRunActionExecutor, RazorpayActionExecutor
from app.services.recovery_state import RecoveryStateMachine


class WorkflowPaymentClient(Protocol):
    """Minimal provider boundary needed when an event omits payment evidence."""

    def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        """Retrieve one normalized payment."""


class RecoveryWorkflowService:
    """Evaluate authenticated events and return dry-run action requests."""

    def __init__(
        self,
        payment_client: WorkflowPaymentClient | None = None,
        llm_client: LLMClient | None = None,
        policy: MerchantPolicy | None = None,
        session_factory: Callable[[], Session] | None = None,
        action_executor: ActionExecutor | None = None,
    ) -> None:
        self._payment_client = payment_client
        self._llm_client = llm_client
        self._policy = policy or MerchantPolicy()
        self._session_factory = session_factory
        self._action_executor = action_executor or RazorpayActionExecutor.from_settings()
        self._processed: dict[str, RecoveryWorkflowResponse] = {}
        self._lock = threading.Lock()

    def process(self, event: RecoveryEvent) -> RecoveryWorkflowResponse:
        """Evaluate one event and return the cached result for duplicates."""
        event_id = event.event_id or self._derived_event_id(event)
        with self._lock:
            previous = self._processed.get(event_id)
        if previous is not None:
            return previous.model_copy(update={"duplicate": True})

        payment, customer = self._build_inputs(event)
        history = RecoveryHistory(recovery_attempt_count=event.recovery_attempt_count)
        risk_result = RevenueRiskEngine().evaluate(payment, customer, history, self._policy)
        context = build_recovery_context(payment, customer, history, risk_result, self._policy)
        decision = RecoveryDecisionService(self._decision_client()).decide(context)

        current_state = RecoveryStateMachine.for_payment_status(payment.status)
        if current_state == "stopped":
            decision = decision.model_copy(update={"action": "STOP", "requires_approval": False})
            decision = decision.model_copy(update={"recovery_eligible": False, "validation_status": "OVERRIDDEN", "validation_notes": ["Payment is not in a recoverable failed state."]})
        if decision.action == "STOP":
            current_state = "stopped"
        elif decision.requires_approval:
            current_state = "approval_required"
        elif decision.recovery_eligible:
            current_state = "eligible"
        else:
            current_state = "ignored"

        if current_state in {"duplicate", "ignored", "failed", "recovered"}:
            RecoveryStateMachine.ensure_execution_allowed(current_state)

        provisional_result = DryRunActionExecutor().execute(decision)
        provisional_response = RecoveryWorkflowResponse.from_decision(
            event_id, decision, provisional_result
        )
        if self._session_factory is not None:
            persisted_response = self._persist_evaluation(
                event_id, payment, provisional_response, event.recovery_attempt_count + 1, current_state
            )
            if persisted_response.duplicate:
                return persisted_response
        result = self._action_executor.execute(
            decision,
            amount=payment.amount,
            currency=payment.currency,
            event_id=event_id,
            recipient=customer.customer_id,
            recovery_attempt_count=event.recovery_attempt_count,
            max_customer_notifications=self._policy.max_customer_notifications,
        )
        response = provisional_response.model_copy(update={"result": result})
        if self._session_factory is not None:
            self._update_execution_metadata(event_id, result, current_state)

        with self._lock:
            existing = self._processed.setdefault(event_id, response)
        if existing is not response:
            return existing.model_copy(update={"duplicate": True})
        return response

    def _persist_evaluation(
        self,
        event_id: str,
        payment: PaymentRiskInput,
        response: RecoveryWorkflowResponse,
        attempt_number: int,
        recovery_state: str | None = None,
    ) -> RecoveryWorkflowResponse:
        """Commit one audit record, relying on the database for cross-process uniqueness."""
        create_tables()
        session = self._session_factory()
        try:
            existing = session.scalar(
                select(RecoveryAttempt).where(RecoveryAttempt.event_id == event_id)
            )
            if existing is not None:
                return self._response_from_attempt(existing)

            stored_payment = session.scalar(
                select(Payment).where(Payment.razorpay_payment_id == payment.payment_id)
            )
            if stored_payment is None:
                customer = Customer(
                    name=f"Recovery customer {payment.payment_id}",
                    email=f"{payment.payment_id}@reclaim.invalid",
                )
                stored_payment = Payment(
                    razorpay_payment_id=payment.payment_id,
                    customer=customer,
                    amount=payment.amount,
                    currency=payment.currency,
                    status=payment.status,
                    failure_reason=payment.failure_reason,
                )
                session.add(stored_payment)
                session.flush()

            attempt = RecoveryAttempt(
                payment=stored_payment,
                event_id=event_id,
                attempt_number=attempt_number,
                execution_mode=response.result.execution_mode,
                provider_called=response.result.provider_called,
                execution_succeeded=response.result.execution_succeeded,
                notification_generated=response.result.notification_generated,
                executed_at=response.result.executed_at,
                action=response.action,
                status=response.result.status,
                recovery_state=recovery_state or "detected",
                state_reason=response.result.message,
                provider_payment_id=response.result.provider_payment_id,
                provider_payment_link_id=response.result.provider_payment_link_id,
                provider_reference_id=response.result.provider_reference_id,
                risk_score=response.decision.risk_score,
                risk_level=response.decision.priority,
                eligibility_result=response.decision.recovery_eligible,
                eligibility_reason=" ".join(response.decision.validation_notes),
                decision_confidence=response.decision.confidence,
                approval_required=response.decision.requires_approval,
                validation_status=response.decision.validation_status,
                policy_override_reason=(
                    " ".join(response.decision.validation_notes)
                    if response.decision.validation_status == "OVERRIDDEN"
                    else None
                ),
                decision_diagnosis=response.decision.diagnosis,
                decision_reasoning=response.decision.reasoning,
                policy_constraints=json.dumps(response.decision.policy_constraints),
                amount=payment.amount,
            )
            session.add(attempt)
            session.commit()
            return response
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(RecoveryAttempt).where(RecoveryAttempt.event_id == event_id)
            )
            if existing is not None:
                return self._response_from_attempt(existing)
            raise
        finally:
            session.close()

    def _update_execution_metadata(
        self,
        event_id: str,
        result: RecoveryActionResult,
        recovery_state: str | None = None,
    ) -> None:
        """Record the final safe execution outcome after the audit insert."""
        session = self._session_factory()
        try:
            attempt = session.scalar(
                select(RecoveryAttempt).where(RecoveryAttempt.event_id == event_id)
            )
            if attempt is not None:
                attempt.status = result.status
                attempt.execution_mode = result.execution_mode
                attempt.provider_called = result.provider_called
                attempt.execution_succeeded = result.execution_succeeded
                attempt.notification_generated = result.notification_generated
                attempt.executed_at = result.executed_at
                attempt.provider_payment_id = result.provider_payment_id or attempt.provider_payment_id
                attempt.provider_payment_link_id = result.provider_payment_link_id or attempt.provider_payment_link_id
                attempt.provider_reference_id = result.provider_reference_id or attempt.provider_reference_id
                attempt.recovery_state = recovery_state or attempt.recovery_state or "detected"
                attempt.state_reason = result.message
                session.commit()
        finally:
            session.close()

    @staticmethod
    def _response_from_attempt(attempt: RecoveryAttempt) -> RecoveryWorkflowResponse:
        """Return a stable duplicate response from a persisted audit record."""
        result = RecoveryActionResult(
            payment_id=attempt.payment.razorpay_payment_id or str(attempt.payment_id),
            action=attempt.action,
            status=attempt.status,
            message={
                "RETRY": "A payment retry would be requested; no payment operation was performed.",
                "PAYMENT_LINK": "A payment link would be requested; no link was created or sent.",
                "REMINDER": "A customer reminder would be requested; no notification was sent.",
                "ESCALATE": "Merchant escalation would be requested for review.",
                "STOP": "Recovery is stopped; no external action was requested.",
            }[attempt.action],
            execution_mode=attempt.execution_mode,
            provider_called=attempt.provider_called,
            execution_succeeded=attempt.execution_succeeded,
            event_id=attempt.event_id,
            executed_at=attempt.executed_at or attempt.created_at,
        )
        return RecoveryWorkflowResponse(
            event_id=attempt.event_id or "",
            duplicate=True,
            payment_id=result.payment_id,
            risk_score=0,
            eligible=attempt.action != "STOP",
            requires_approval=attempt.action == "ESCALATE",
            action=attempt.action,
            confidence=0.0,
            validation_status="VALID",
            priority="LOW",
            decision={
                "action": attempt.action,
                "diagnosis": "Previously evaluated recovery event.",
                "reasoning": "The persisted audit record was returned for this duplicate event.",
                "confidence": 0.0,
                "requires_approval": attempt.action == "ESCALATE",
                "priority": "LOW",
                "policy_constraints": [],
                "expected_outcome": "No external action was performed.",
                "payment_id": result.payment_id,
                "risk_score": 0,
                "recovery_eligible": attempt.action != "STOP",
                "validation_status": "VALID",
                "validation_notes": ["Duplicate event loaded from persistence."],
                "decided_at": attempt.created_at,
            },
            result=result,
        )

    def clear_idempotency(self) -> None:
        """Clear process-local event state for tests and local development."""
        with self._lock:
            self._processed.clear()

    def _decision_client(self) -> LLMClient:
        if self._llm_client is not None:
            return self._llm_client
        try:
            return OpenAICompatibleLLMClient.from_environment()
        except Exception:
            return FakeLLMClient()

    def _build_inputs(
        self, event: RecoveryEvent
    ) -> tuple[PaymentRiskInput, CustomerRiskContext]:
        if event.payment is not None:
            if event.payment.payment_id != event.payment_id:
                raise ValueError("payment_id must match payment.payment_id")
            payment = event.payment
        else:
            provider_payment = self._provider().fetch_payment(event.payment_id)
            payment = self._payment_from_provider(provider_payment, event.timestamp)

        customer = event.customer or CustomerRiskContext(
            customer_id=f"unknown:{event.payment_id}",
            customer_age_days=0,
            previous_successful_payments=0,
            previous_failed_payments=0,
            previous_recovery_attempts=0,
            customer_lifetime_value=0,
            average_previous_payment=0,
            recent_payment_frequency=0,
        )
        return payment, customer

    def _provider(self) -> WorkflowPaymentClient:
        return self._payment_client or RazorpayClient.from_settings()

    @staticmethod
    def _payment_from_provider(
        payment: RazorpayPayment, event_timestamp: datetime
    ) -> PaymentRiskInput:
        method = payment.method or "card"
        if method not in {"upi", "card", "netbanking", "wallet"}:
            raise ValueError("Razorpay payment method is not supported by the risk engine")
        failed_at = payment.created_at or event_timestamp
        elapsed_hours = max(
            0, int((event_timestamp - failed_at).total_seconds() // 3600)
        )
        status = "successful" if payment.status.lower() in {"captured", "successful"} else payment.status
        return PaymentRiskInput(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=method,
            status=status,
            failure_reason=payment.error.code if payment.error else None,
            failed_at=failed_at,
            time_since_failure_hours=elapsed_hours,
        )

    @staticmethod
    def _derived_event_id(event: RecoveryEvent) -> str:
        digest = hashlib.sha256(event.model_dump_json().encode("utf-8")).hexdigest()
        return f"derived-{digest}"


workflow_service = RecoveryWorkflowService(session_factory=SessionLocal)
