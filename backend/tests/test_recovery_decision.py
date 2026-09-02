"""Tests for constrained LLM recovery decisions and deterministic guardrails."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
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
from app.services.llm_client import LLMClientError, OpenAICompatibleLLMClient
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


class FailingLLMClient:
    """Fake provider that simulates an unavailable model."""

    def generate_recovery_decision(self, context: Any) -> dict[str, Any]:
        raise RuntimeError("LLM unavailable")


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

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "OVERRIDDEN"


def test_valid_escalate_decision_is_preserved() -> None:
    result = DecisionValidator().validate(_decision("ESCALATE"), _context())

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "OVERRIDDEN"


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


def test_valid_llm_recommendation_is_preserved() -> None:
    context = _context()
    service = RecoveryDecisionService(
        StaticLLMClient(
            {
                "action": "RETRY",
                "diagnosis": "The failure appears transient and within policy.",
                "reasoning": "The payment is recoverable and the cause is a short-lived transient issue.",
                "confidence": 0.82,
                "requires_approval": False,
                "priority": context.risk.urgency,
                "policy_constraints": [],
                "expected_outcome": "A retry should be attempted under the policy rules.",
            }
        )
    )

    result = service.decide(context)

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "OVERRIDDEN"


def test_high_confidence_card_decline_prefers_payment_link() -> None:
    payment = PaymentRiskInput(
        payment_id="payment-link-target",
        amount=150_000,
        currency="INR",
        payment_method="card",
        status="failed",
        failure_reason="card_declined",
        failed_at=NOW - timedelta(hours=2),
        time_since_failure_hours=2,
    )
    customer = CustomerRiskContext(
        customer_id="customer-link-target",
        customer_age_days=420,
        previous_successful_payments=12,
        previous_failed_payments=0,
        previous_recovery_attempts=0,
        customer_lifetime_value=4_000_000,
        average_previous_payment=240_000,
        recent_payment_frequency=7,
    )
    history = RecoveryHistory(recovery_attempt_count=0)
    risk = RevenueRiskEngine().evaluate(payment, customer, history, POLICY)
    assert risk.risk_score >= 70
    assert risk.recovery_eligible is True
    assert risk.requires_merchant_approval is False

    context = build_recovery_context(payment, customer, history, risk, POLICY)
    service = RecoveryDecisionService(
        StaticLLMClient(
            {
                "action": "PAYMENT_LINK",
                "diagnosis": "The customer is high-confidence and the card decline is non-transient.",
                "reasoning": "The payment is within policy, eligible for recovery, and a strong recent-paying customer is likely to complete a payment link.",
                "confidence": 0.9,
                "requires_approval": False,
                "priority": context.risk.urgency,
                "policy_constraints": [],
                "expected_outcome": "A payment link should be offered to recover the failed payment without additional approval.",
            }
        )
    )

    result = service.decide(context)

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "VALID"
    assert result.requires_approval is False


def test_invalid_llm_action_is_rejected() -> None:
    service = RecoveryDecisionService(
        StaticLLMClient(
            {
                "action": "REFUND",
                "diagnosis": "This is not an allowed action.",
                "reasoning": "The model produced an unsupported recovery action.",
                "confidence": 0.5,
                "requires_approval": False,
                "priority": "MEDIUM",
                "policy_constraints": [],
                "expected_outcome": "Reject the unsupported action.",
            }
        )
    )

    result = service.decide(_context())

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "FAILED"


def test_malformed_llm_response_returns_safe_failure_result() -> None:
    service = RecoveryDecisionService(StaticLLMClient(["not", "a", "decision"]))

    result = service.decide(_context())

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "FAILED"
    assert result.requires_approval is False


def test_llm_unavailable_returns_safe_failure_result() -> None:
    service = RecoveryDecisionService(FailingLLMClient())

    result = service.decide(_context())

    assert result.action == "PAYMENT_LINK"
    assert result.validation_status == "FAILED"


def test_policy_overrides_unsafe_llm_recommendation() -> None:
    context = _context(payment_overrides={"time_since_failure_hours": 49, "failed_at": NOW - timedelta(hours=49)})
    service = RecoveryDecisionService(
        StaticLLMClient(
            {
                "action": "RETRY",
                "diagnosis": "The model wants to retry despite the age.",
                "reasoning": "A retry should still be attempted because the model prefers retention.",
                "confidence": 0.9,
                "requires_approval": False,
                "priority": "HIGH",
                "policy_constraints": [],
                "expected_outcome": "Recovery should proceed even though the window is expired.",
            }
        )
    )

    result = service.decide(context)

    assert result.action == "STOP"
    assert result.validation_status == "OVERRIDDEN"
    assert any("Recovery window" in note for note in result.validation_notes)


def test_gemini_structured_response_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"action": "RETRY", "diagnosis": "Transient failure", "reasoning": "Retry is appropriate.", "confidence": 0.8, "requires_approval": false, "priority": "HIGH", "policy_constraints": [], "expected_outcome": "Retry the payment."}'
                                }
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: DummyResponse())

    result = client.generate_recovery_decision(_context())

    assert result["action"] == "RETRY"
    assert result["confidence"] == 0.8


def test_markdown_fenced_json_response_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
    )

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        @property
        def status_code(self) -> int:
            return 200

        @property
        def headers(self) -> dict[str, str]:
            return {"content-type": "application/json"}

        @property
        def text(self) -> str:
            return '{"choices":[{"message":{"content":"```json\\n{\\"action\\":\\"PAYMENT_LINK\\",\\"diagnosis\\":\\"Strong customer signal\\",\\"reasoning\\":\\"High-confidence card decline with recent payment history\\",\\"confidence\\":0.9,\\"requires_approval\\":false,\\"priority\\":\\"HIGH\\",\\"policy_constraints\\":[],\\"expected_outcome\\":\\"Offer a payment link for this eligible customer\\"}\\n```"}}]}'

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"action":"PAYMENT_LINK","diagnosis":"Strong customer signal",'
                                '"reasoning":"High-confidence card decline with recent payment history",'
                                '"confidence":0.9,"requires_approval":false,"priority":"HIGH",'
                                '"policy_constraints":[],"expected_outcome":"Offer a payment link for this eligible customer"}'
                                "\n```"
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: DummyResponse())

    result = client.generate_recovery_decision(_context())

    assert result["action"] == "PAYMENT_LINK"
    assert result["confidence"] == 0.9


def test_live_gemini_response_shape_with_extra_content_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="gemini-3.5-flash-lite",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        @property
        def status_code(self) -> int:
            return 200

        @property
        def headers(self) -> dict[str, str]:
            return {"content-type": "application/json"}

        @property
        def text(self) -> str:
            return '{"choices":[{"finish_reason":"stop","index":0,"message":{"content":"{\\n\\t\\"action\\": \\\"PAYMENT_LINK\\\",\\n\\t\\"diagnosis\\": \\\"The payment failed due to a non-transient card decline on a high-value customer with strong historical payments.\\\",\\n\\t\\"reasoning\\": \\\"The payment is eligible, requires_approval is false, the failure reason is a card_declined decline, there are no previous recovery attempts, the failure occurred recently within 2 hours, and the deterministic risk score is 87 with a strong customer payment history.\\\",\\n\\t\\"confidence\\": 0.90,\\n\\t\\"requires_approval\\": false,\\n\\t\\"priority\\": \\\"HIGH\\\",\\n\\t\\"policy_constraints\\": [\\\"Payment is within the recovery window and below attempt limits.\\\", \\\"Amount is within the automatic action limit.\\\"],\\n\\t\\"expected_outcome\\": \\\"Sending a payment link may allow the customer to successfully complete the payment using an alternate or updated card without executing the transaction automatically.\\\"\\n}","extra_content":{"google":{"thought_signature":"abc"}},"role":"assistant"}}]}'

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "index": 0,
                        "message": {
                            "content": (
                                '{\n\t"action": "PAYMENT_LINK",\n\t"diagnosis": "The payment failed due to a non-transient card decline on a high-value customer with strong historical payments.",\n\t"reasoning": "The payment is eligible, requires_approval is false, the failure reason is a card_declined decline, there are no previous recovery attempts, the failure occurred recently within 2 hours, and the deterministic risk score is 87 with a strong customer payment history.",\n\t"confidence": 0.90,\n\t"requires_approval": false,\n\t"priority": "HIGH",\n\t"policy_constraints": ["Payment is within the recovery window and below attempt limits.", "Amount is within the automatic action limit."],\n\t"expected_outcome": "Sending a payment link may allow the customer to successfully complete the payment using an alternate or updated card without executing the transaction automatically."\n}'
                            ),
                            "extra_content": {"google": {"thought_signature": "abc"}},
                            "role": "assistant",
                        },
                    }
                ]
            }

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: DummyResponse())

    result = client.generate_recovery_decision(_context())

    assert result["action"] == "PAYMENT_LINK"
    assert result["confidence"] == 0.9
    assert result["priority"] == "HIGH"


def test_gemini_request_uses_bearer_auth_without_logging_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    api_key = "gemini-test-key"
    client = OpenAICompatibleLLMClient(
        api_key=api_key,
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )
    captured_headers: dict[str, str] = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"action": "RETRY", "diagnosis": "Transient failure", "reasoning": "Retry is appropriate.", "confidence": 0.8, "requires_approval": false, "priority": "HIGH", "policy_constraints": [], "expected_outcome": "Retry the payment."}'
                        }
                    }
                ]
            }

    def mock_post(*args: Any, **kwargs: Any) -> DummyResponse:
        captured_headers.update(kwargs["headers"])
        return DummyResponse()

    monkeypatch.setattr(httpx, "post", mock_post)

    client.generate_recovery_decision(_context())

    assert captured_headers["Authorization"] == f"Bearer {api_key}"
    assert "x-goog-api-key" not in captured_headers
    assert api_key not in caplog.text


def test_gemini_malformed_response_raises_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "not-json"}]
                        }
                    }
                ]
            }

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: DummyResponse())

    with pytest.raises(LLMClientError):
        client.generate_recovery_decision(_context())


def test_http_failure_returns_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAICompatibleLLMClient(
        api_key="bad-key",
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )

    def mock_post(*args: Any, **kwargs: Any) -> Any:
        raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", mock_post)

    with pytest.raises(LLMClientError):
        client.generate_recovery_decision(_context())


@pytest.mark.parametrize("action", ["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"])
def test_supported_actions_remain_accepted_by_validation(action: str) -> None:
    result = DecisionValidator().validate(_decision(action), _context())

    assert result.action == "PAYMENT_LINK"
