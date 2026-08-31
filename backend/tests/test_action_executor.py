"""Tests for the safe recovery action execution boundary."""

from datetime import UTC, datetime

import pytest

from app.schemas.recovery_decision import ValidatedRecoveryDecision
from app.services.action_executor import DryRunActionExecutor
from app.services.action_executor import RazorpayActionExecutor
from app.services.razorpay_client import RazorpayClient, RazorpayUpstreamError
from app.schemas.razorpay import RazorpayPaymentLink


@pytest.fixture
def decision() -> ValidatedRecoveryDecision:
    return ValidatedRecoveryDecision(
        action="RETRY",
        diagnosis="Payment failed.",
        reasoning="A retry may recover the payment.",
        confidence=0.8,
        requires_approval=False,
        priority="HIGH",
        policy_constraints=[],
        expected_outcome="Payment may recover.",
        payment_id="pay-executor-test",
        risk_score=80,
        recovery_eligible=True,
        validation_status="VALID",
        validation_notes=[],
        decided_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("action", ["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE"])
def test_supported_actions_are_dry_run(decision: ValidatedRecoveryDecision, action: str) -> None:
    result = DryRunActionExecutor().execute(decision.model_copy(update={"action": action}))

    assert result.action == action
    assert result.mode == "dry_run"
    assert result.status == "queued"
    assert result.message


def test_stop_is_terminal_without_side_effects(decision: ValidatedRecoveryDecision) -> None:
    result = DryRunActionExecutor().execute(decision.model_copy(update={"action": "STOP"}))

    assert result.action == "STOP"
    assert result.status == "terminal"
    assert "no external action" in result.message.lower()


def test_approval_required_does_not_execute(decision: ValidatedRecoveryDecision) -> None:
    result = DryRunActionExecutor().execute(
        decision.model_copy(update={"requires_approval": True})
    )

    assert result.action == "RETRY"
    assert result.mode == "dry_run"
    assert "approval" in result.message.lower()


def test_ineligible_decision_does_not_execute(decision: ValidatedRecoveryDecision) -> None:
    result = DryRunActionExecutor().execute(
        decision.model_copy(update={"recovery_eligible": False})
    )

    assert result.action == "RETRY"
    assert result.mode == "dry_run"
    assert "ineligible" in result.message.lower()


def test_duplicate_decision_does_not_execute(decision: ValidatedRecoveryDecision) -> None:
    result = DryRunActionExecutor().execute(decision, duplicate=True)

    assert result.mode == "dry_run"
    assert "duplicate" in result.message.lower()


class PaymentLinkClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str, str]] = []

    def create_payment_link(self, amount: int, currency: str, reference_id: str, description: str) -> RazorpayPaymentLink:
        self.calls.append((amount, currency, reference_id, description))
        return RazorpayPaymentLink(
            id="plink_test",
            amount=amount,
            currency=currency,
            status="created",
            short_url="https://rzp.io/i/test",
            reference_id=reference_id,
        )


def test_payment_link_uses_provider_when_enabled(decision: ValidatedRecoveryDecision) -> None:
    client = PaymentLinkClient()
    payment_link_decision = decision.model_copy(update={"action": "PAYMENT_LINK"})
    result = RazorpayActionExecutor(client, enabled=True).execute(payment_link_decision, amount=125000)

    assert result.mode == "dry_run"
    assert client.calls == [(125000, "INR", "pay-executor-test", "Recovery payment for pay-executor-test")]
    assert "https://rzp.io/i/test" in result.message


def test_payment_link_provider_failure_is_safe(decision: ValidatedRecoveryDecision) -> None:
    class FailingClient:
        def create_payment_link(self, **kwargs: object) -> RazorpayPaymentLink:
            raise RazorpayUpstreamError("upstream failure")

    payment_link_decision = decision.model_copy(update={"action": "PAYMENT_LINK"})
    result = RazorpayActionExecutor(FailingClient(), enabled=True).execute(payment_link_decision, amount=125000)

    assert result.status == "terminal"
    assert result.mode == "dry_run"
    assert "no further action" in result.message.lower()


def test_payment_link_provider_failure_logs_diagnostic_details_without_leaking_secrets(
    decision: ValidatedRecoveryDecision, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingClient:
        def create_payment_link(self, **kwargs: object) -> RazorpayPaymentLink:
            raise RazorpayUpstreamError(
                "upstream failure",
                status_code=500,
                provider_code="SERVER_ERROR",
                response_body={
                    "error": {
                        "code": "SERVER_ERROR",
                        "description": "upstream failed",
                        "customer": {"email": "test@example.com"},
                    },
                    "authorization": "Basic secret-key",
                },
            )

    payment_link_decision = decision.model_copy(update={"action": "PAYMENT_LINK"})

    with caplog.at_level("WARNING"):
        result = RazorpayActionExecutor(FailingClient(), enabled=True).execute(
            payment_link_decision, amount=125000
        )

    assert result.status == "terminal"
    assert result.mode == "dry_run"
    assert "no further action" in result.message.lower()
    assert "status_code=500" in caplog.text
    assert "SERVER_ERROR" in caplog.text
    assert "test@example.com" not in caplog.text
    assert "Basic secret-key" not in caplog.text


def test_payment_link_provider_is_not_called_for_approval_or_duplicate(
    decision: ValidatedRecoveryDecision,
) -> None:
    client = PaymentLinkClient()
    executor = RazorpayActionExecutor(client, enabled=True)
    payment_link_decision = decision.model_copy(update={"action": "PAYMENT_LINK"})

    approval = executor.execute(payment_link_decision.model_copy(update={"requires_approval": True}), amount=125000)
    duplicate = executor.execute(payment_link_decision, amount=125000, duplicate=True)

    assert approval.mode == "dry_run"
    assert duplicate.mode == "dry_run"
    assert client.calls == []


def test_payment_link_without_provider_configuration_stays_dry_run(
    decision: ValidatedRecoveryDecision,
) -> None:
    payment_link_decision = decision.model_copy(update={"action": "PAYMENT_LINK"})

    result = RazorpayActionExecutor(None, enabled=True).execute(
        payment_link_decision, amount=125000
    )

    assert result.mode == "dry_run"
    assert result.status == "queued"
