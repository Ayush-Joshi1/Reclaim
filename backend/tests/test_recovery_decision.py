"""Tests for constrained LLM recovery decisions and deterministic guardrails."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas import (
    CustomerRiskContext,
    MerchantPolicy,
    PaymentRiskInput,
    RecoveryDecision,
    RecoveryHistory,
)
from app.services.decision_validator import DecisionValidator
from app.services.recovery_context import build_recovery_context
from app.services.recovery_decision import RecoveryDecisionService
from app.services.revenue_risk import RevenueRiskEngine

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
POLICY = MerchantPolicy()


class StaticLLMClient:
    """Fake provider that returns a supplied JSON object."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def generate_recovery_decision(self, context: Any) -> dict[str, Any]:
        return self._response


def _context(
    *,
    payment_overrides: dict[str, object] | None = None,
    history_count: int = 0,
) -> Any:
    payment_data: dict[str, object] = {
        "payment_id": "payment-1",
        "amount": 199_900,
        "currency": "INR",
        "payment_method": "card",
        "status": "failed",
        "failure_reason": "card_declined",
        "failed_at": NOW - timedelta(hours=2),
        "time_since_failure_hours": 2,
    }
    payment_data.update(payment_overrides or {})
    payment = PaymentRiskInput(**payment_data)
    customer = CustomerRiskContext(
        customer_id="customer-1",
        customer_age_days=365,
        previous_successful_payments=6,
        previous_failed_payments=0,
        previous_recovery_attempts=0,
        customer_lifetime_value=1_500_000,
        average_previous_payment=150_000,
        recent_payment_frequency=4,
    )
    history = RecoveryHistory(recovery_attempt_count=history_count)
    risk = RevenueRiskEngine().evaluate(payment, customer, history, POLICY)
    return build_recovery_context(payment, customer, history, risk, POLICY)


def _decision(action: str = "RETRY", **overrides: object) -> RecoveryDecision:
    values: dict[str, object] = {
        "action": action,
        "diagnosis": "A recoverable payment failure was detected.",
        "reasoning": "The evidence supports a limited recovery recommendation.",
        "confidence": 0.75,
        "requires_approval": False,
        "priority": "HIGH",
        "policy_constraints": [],
        "expected_outcome": "The recommendation will be reviewed before any future execution.",
    }
    values.update(overrides)
    return RecoveryDecision.model_validate(values)


def test_valid_payment_link_decision_is_preserved() -> None:
    result = DecisionValidator().validate(_decision("PAYMENT_LINK"), _context())

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "VALID"


def test_valid_retry_decision_is_preserved() -> None:
    result = DecisionValidator().validate(_decision("RETRY"), _context())

    assert result.action == "RETRY"


def test_valid_escalate_decision_is_preserved() -> None:
    result = DecisionValidator().validate(_decision("ESCALATE"), _context())

    assert result.action == "ESCALATE"


def test_invalid_action_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        _decision("REFUND")


@pytest.mark.parametrize("confidence", [1.1, -0.1])
def test_invalid_confidence_is_rejected_by_schema(confidence: float) -> None:
    with pytest.raises(ValidationError):
        _decision(confidence=confidence)


def test_ineligible_payment_is_forced_to_stop() -> None:
    context = _context(payment_overrides={"time_since_failure_hours": 49, "failed_at": NOW - timedelta(hours=49)})
    result = DecisionValidator().validate(_decision("PAYMENT_LINK"), context)

    assert result.action == "STOP"
    assert result.recovery_eligible is False


def test_expired_recovery_window_is_forced_to_stop() -> None:
    context = _context(payment_overrides={"time_since_failure_hours": 49, "failed_at": NOW - timedelta(hours=49)})
    result = DecisionValidator().validate(_decision("RETRY"), context)

    assert result.action == "STOP"
    assert any("Recovery window" in note for note in result.validation_notes)


def test_maximum_recovery_attempts_is_forced_to_stop() -> None:
    context = _context(history_count=POLICY.max_recovery_attempts)
    result = DecisionValidator().validate(_decision("REMINDER"), context)

    assert result.action == "STOP"
    assert any("Maximum recovery attempts" in note for note in result.validation_notes)


def test_high_value_payment_remains_approval_required() -> None:
    context = _context(payment_overrides={"amount": 2_500_000})
    result = DecisionValidator().validate(_decision("ESCALATE", requires_approval=False), context)

    assert result.action == "ESCALATE"
    assert result.requires_approval is True
    assert result.validation_status == "OVERRIDDEN"


def test_successful_payment_is_forced_to_stop() -> None:
    context = _context(payment_overrides={"status": "successful"})
    result = DecisionValidator().validate(_decision("RETRY"), context)

    assert result.action == "STOP"
    assert any("successful" in note.lower() for note in result.validation_notes)


def test_malformed_llm_output_returns_safe_failure_result() -> None:
    service = RecoveryDecisionService(StaticLLMClient({"action": "UNSAFE"}))

    result = service.decide(_context())

    assert result.action == "ESCALATE"
    assert result.validation_status == "FAILED"
    assert result.requires_approval is True
