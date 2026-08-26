"""Tests for deterministic revenue-risk scoring and policy eligibility."""

from datetime import UTC, datetime, timedelta

from app.schemas import CustomerRiskContext, MerchantPolicy, PaymentRiskInput, RecoveryHistory
from app.services.revenue_risk import RevenueRiskEngine

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
ENGINE = RevenueRiskEngine()
POLICY = MerchantPolicy()


def _payment(**overrides: object) -> PaymentRiskInput:
    values: dict[str, object] = {
        "payment_id": "payment-1",
        "amount": 199_900,
        "currency": "INR",
        "payment_method": "upi",
        "status": "failed",
        "failure_reason": "network_error",
        "failed_at": NOW - timedelta(hours=2),
        "time_since_failure_hours": 2,
    }
    values.update(overrides)
    return PaymentRiskInput(**values)


def _customer(**overrides: object) -> CustomerRiskContext:
    values: dict[str, object] = {
        "customer_id": "customer-1",
        "customer_age_days": 365,
        "previous_successful_payments": 6,
        "previous_failed_payments": 0,
        "previous_recovery_attempts": 0,
        "customer_lifetime_value": 1_500_000,
        "average_previous_payment": 150_000,
        "recent_payment_frequency": 4,
    }
    values.update(overrides)
    return CustomerRiskContext(**values)


def _result(**overrides: object):
    payment = _payment(**overrides.pop("payment", {}))
    customer = _customer(**overrides.pop("customer", {}))
    recovery_history = RecoveryHistory(**overrides.pop("history", {"recovery_attempt_count": 0}))
    return ENGINE.evaluate(payment, customer, recovery_history, POLICY)


def test_first_failure_with_strong_history_has_high_recovery_score() -> None:
    result = _result()

    assert result.risk_score >= 80
    assert result.recovery_eligible is True
    assert result.urgency == "HIGH"


def test_repeated_failures_lower_the_score() -> None:
    strong_result = _result()
    repeated_result = _result(customer={"previous_successful_payments": 1, "previous_failed_payments": 6})

    assert repeated_result.risk_score < strong_result.risk_score


def test_expired_recovery_window_is_not_eligible() -> None:
    result = _result(payment={"time_since_failure_hours": 49, "failed_at": NOW - timedelta(hours=49)})

    assert result.recovery_eligible is False
    assert result.should_stop is True


def test_maximum_recovery_attempts_is_not_eligible() -> None:
    result = _result(history={"recovery_attempt_count": 2})

    assert result.recovery_eligible is False
    assert result.should_stop is True


def test_high_value_payment_requires_merchant_approval() -> None:
    result = _result(payment={"amount": 2_500_000})

    assert result.recovery_eligible is True
    assert result.requires_merchant_approval is True
    assert result.auto_action_eligible is False


def test_successful_payment_is_not_eligible() -> None:
    result = _result(payment={"status": "successful"})

    assert result.recovery_eligible is False
    assert result.should_stop is True
    assert result.revenue_at_risk == 0


def test_recent_failure_has_higher_urgency_than_old_failure() -> None:
    recent = _result()
    old = _result(payment={"time_since_failure_hours": 30, "failed_at": NOW - timedelta(hours=30)})

    assert recent.urgency == "HIGH"
    assert old.urgency == "LOW"


def test_risk_factors_are_explainable_and_output_is_deterministic() -> None:
    first = _result()
    second = _result()

    assert first == second
    assert first.risk_factors
    assert any("Strong successful payment history" in factor for factor in first.risk_factors)
