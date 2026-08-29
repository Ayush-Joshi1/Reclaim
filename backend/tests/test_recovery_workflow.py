"""Tests for the authenticated n8n recovery orchestration boundary."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import RecoveryAttempt
from app.schemas import CustomerRiskContext, PaymentRiskInput, RecoveryEvent
from app.schemas.razorpay import RazorpayPaymentLink
from app.services.action_executor import RazorpayActionExecutor
from app.services.recovery_workflow import RecoveryWorkflowService, workflow_service
from app.services.razorpay_client import RazorpayNotFoundError

SECRET = "workflow-test-secret"
NOW = datetime(2026, 8, 26, tzinfo=UTC)


def payment_data(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "payment_id": "pay_workflow_test",
        "amount": 199_900,
        "currency": "INR",
        "payment_method": "card",
        "status": "failed",
        "failure_reason": "network_error",
        "failed_at": (NOW - timedelta(hours=2)).isoformat(),
        "time_since_failure_hours": 2,
    }
    values.update(overrides)
    return values


def event_data(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event_id": "evt_workflow_test",
        "payment_id": "pay_workflow_test",
        "event_type": "payment_failed",
        "timestamp": NOW.isoformat(),
        "source": "n8n",
        "payment": payment_data(),
    }
    values.update(overrides)
    return values


@pytest.fixture(autouse=True)
def workflow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret=SECRET),
    )
    workflow_service._payment_client = None
    workflow_service.clear_idempotency()


def test_valid_workflow_event_reaches_decision_layer() -> None:
    response = TestClient(app).post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": SECRET},
        json=event_data(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payment_id"] == "pay_workflow_test"
    assert body["action"] == "RETRY"
    assert body["result"] == {
        "payment_id": "pay_workflow_test",
        "action": "RETRY",
        "mode": "dry_run",
        "status": "queued",
        "message": "A payment retry would be requested; no payment operation was performed.",
        "execution_mode": "dry_run",
        "provider_called": False,
        "execution_succeeded": True,
        "notification_generated": False,
        "event_id": "evt_workflow_test",
        "executed_at": body["result"]["executed_at"],
    }


def test_validated_decision_lineage_is_persisted() -> None:
    event = event_data(event_id="evt-lineage-persisted")
    response = TestClient(app).post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": SECRET},
        json=event,
    )

    assert response.status_code == 200
    with SessionLocal() as session:
        attempt = session.scalar(
            select(RecoveryAttempt).where(RecoveryAttempt.event_id == "evt-lineage-persisted")
        )
        assert attempt is not None
        assert attempt.risk_score is not None
        assert attempt.risk_level == "HIGH"
        assert attempt.eligibility_result is True
        assert attempt.eligibility_reason
        assert attempt.decision_confidence == 0.7
        assert attempt.approval_required is False
        assert attempt.validation_status == "VALID"
        assert attempt.decision_diagnosis
        assert attempt.decision_reasoning
        assert attempt.policy_constraints


def test_missing_and_invalid_authentication_are_rejected() -> None:
    client = TestClient(app)
    payload = event_data()

    missing = client.post("/api/workflows/recovery", json=payload)
    invalid = client.post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": "wrong"},
        json=payload,
    )

    assert missing.status_code == 401
    assert invalid.status_code == 403
    assert "workflow-test-secret" not in missing.text + invalid.text


def test_n8n_workflow_uses_current_backend_contract() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / "workflows" / "reclaim-recovery-orchestration.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    text = workflow_path.read_text(encoding="utf-8")

    endpoint_calls = [
        node["parameters"]["url"]
        for node in workflow["nodes"]
        if node.get("type") == "n8n-nodes-base.httpRequest"
    ]

    assert any("/api/workflows/recovery" in url for url in endpoint_calls)
    assert "reclaim-demo-secret-2026" not in text
    assert "RECLAIM_WORKFLOW_SECRET" in text
    assert "RECLAIM_BACKEND_URL" in text
    assert "X-Reclaim-Workflow-Secret" in text


def test_invalid_payload_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": SECRET},
        json={"payment_id": "pay_workflow_test"},
    )

    assert response.status_code == 422


class MissingPaymentClient:
    def fetch_payment(self, payment_id: str) -> Any:
        raise RazorpayNotFoundError("Razorpay resource was not found.")


def test_unknown_payment_is_returned_as_not_found() -> None:
    workflow_service._payment_client = MissingPaymentClient()
    response = TestClient(app).post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": SECRET},
        json=event_data(payment=None),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "payment_not_found"


@pytest.mark.parametrize(
    ("event_id", "payment_overrides", "expected_action", "expected_status"),
    [
        ("evt-stop", {"status": "successful"}, "STOP", "terminal"),
        ("evt-retry", {"failure_reason": "network_error"}, "RETRY", "queued"),
        ("evt-link", {"failure_reason": "card_declined"}, "PAYMENT_LINK", "queued"),
        (
            "evt-reminder",
            {
                "failure_reason": "unknown",
                "status": "failed",
                "time_since_failure_hours": 30,
            },
            "REMINDER",
            "queued",
        ),
        ("evt-escalate", {"amount": 800_000}, "ESCALATE", "queued"),
    ],
)
def test_all_action_branches_are_dry_run(
    event_id: str,
    payment_overrides: dict[str, object],
    expected_action: str,
    expected_status: str,
) -> None:
    event = RecoveryEvent(
        **event_data(event_id=event_id, payment=payment_data(**payment_overrides))
    )
    service = RecoveryWorkflowService()

    result = service.process(event)

    assert result.action == expected_action
    assert result.result.mode == "dry_run"
    assert result.result.status == expected_status


def test_duplicate_event_returns_cached_result_without_reprocessing() -> None:
    event = RecoveryEvent(**event_data())
    service = RecoveryWorkflowService()

    first = service.process(event)
    duplicate = service.process(event)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.event_id == first.event_id
    assert duplicate.result == first.result


def test_provider_executor_is_used_for_payment_link_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str, str, str]] = []

    class PaymentLinkClient:
        def create_payment_link(self, amount: int, currency: str, reference_id: str, description: str) -> RazorpayPaymentLink:
            calls.append((amount, currency, reference_id, description))
            return RazorpayPaymentLink(
                id="plink_live_123",
                amount=amount,
                currency=currency,
                status="created",
                short_url="https://rzp.io/i/live123",
                reference_id=reference_id,
            )

    executor = RazorpayActionExecutor(PaymentLinkClient(), enabled=True)
    monkeypatch.setattr(
        "app.services.recovery_workflow.RazorpayActionExecutor.from_settings",
        lambda configured=None: executor,
    )

    event = RecoveryEvent(
        **event_data(
            event_id="evt-provider-link",
            payment=payment_data(amount=125_000, failure_reason="card_declined"),
        )
    )
    service = RecoveryWorkflowService()

    result = service.process(event)

    assert result.action == "PAYMENT_LINK"
    assert result.result.execution_mode == "provider"
    assert result.result.provider_called is True
    assert calls == [(125_000, "INR", "pay_workflow_test", "Recovery payment for pay_workflow_test")]
    assert "https://rzp.io/i/live123" in result.result.message


def test_internal_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(event: RecoveryEvent) -> Any:
        raise RuntimeError("internal detail with no secret")

    monkeypatch.setattr(workflow_service, "process", fail)
    response = TestClient(app).post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": SECRET},
        json=event_data(event_id="evt-internal"),
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "workflow_failed"
    assert "internal detail" not in response.text
    assert SECRET not in response.text


def test_event_payment_id_must_match_nested_payment() -> None:
    with pytest.raises(ValueError, match="payment_id must match"):
        RecoveryWorkflowService().process(
            RecoveryEvent(
                **event_data(
                    payment=PaymentRiskInput(**payment_data(payment_id="different-payment")),
                    customer=CustomerRiskContext(
                        customer_id="customer-1",
                        customer_age_days=100,
                        previous_successful_payments=1,
                        previous_failed_payments=0,
                        previous_recovery_attempts=0,
                        customer_lifetime_value=100_000,
                        average_previous_payment=100_000,
                        recent_payment_frequency=1,
                    ),
                )
            )
        )
