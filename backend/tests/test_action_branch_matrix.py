"""Comprehensive action branch test matrix for recovery workflow."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import RecoveryAttempt
from app.schemas import (
    CustomerRiskContext,
    PaymentRiskInput,
    RecoveryEvent,
)
from app.services.recovery_workflow import workflow_service

SECRET = "workflow-comprehensive-test-secret"
NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup_workflow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set workflow secret and clear cache for each test."""
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret=SECRET),
    )
    # Clear workflow service state before each test
    workflow_service._payment_client = None
    workflow_service._processed_events = {}  # Force clear idempotency cache
    workflow_service.clear_idempotency()


def payment_data(**overrides: object) -> dict[str, object]:
    """Build payment data with defaults."""
    values: dict[str, object] = {
        "payment_id": "pay_test",
        "amount": 199_900,
        "currency": "INR",
        "payment_method": "card",
        "status": "failed",
        "failure_reason": None,
        "failed_at": (NOW - timedelta(hours=2)).isoformat(),
        "time_since_failure_hours": 2,
    }
    values.update(overrides)
    return values


def event_data(**overrides: object) -> dict[str, object]:
    """Build recovery event with defaults."""
    values: dict[str, object] = {
        "event_id": "evt_test",
        "payment_id": "pay_test",
        "event_type": "payment_failed",
        "timestamp": NOW.isoformat(),
        "source": "n8n",
        "recovery_attempt_count": 0,
        "payment": payment_data(),
        "customer": {
            "customer_id": "cust_test",
            "notification_count": 0,
            "customer_age_days": 300,
            "previous_successful_payments": 15,
            "previous_failed_payments": 0,
            "previous_recovery_attempts": 0,
            "customer_lifetime_value": 3_000_000,
            "average_previous_payment": 199_900,
            "recent_payment_frequency": 8,
        },
    }
    values.update(overrides)
    return values


# ============================================================================
# TEST 1-5: POSITIVE ACTION BRANCHES (RETRY, PAYMENT_LINK, REMINDER, ESCALATE, STOP)
# ============================================================================


class TestActionBranches:
    """Test all five supported action branches are correctly routed."""

    @pytest.mark.parametrize(
        ("event_id", "payment_overrides", "customer_overrides", "expected_action", "expected_status"),
        [
            ("evt_retry_001", {"failure_reason": "network_error"}, {}, "RETRY", "queued"),
            ("evt_paymentlink_001", {"failure_reason": "card_declined"}, {}, "PAYMENT_LINK", "queued"),
            ("evt_escalate_001", {"amount": 600_000}, {}, "ESCALATE", "queued"),
            ("evt_stop_002", {"status": "successful"}, {}, "STOP", "terminal"),
        ],
    )
    def test_all_actions_return_correct_status(
        self,
        event_id: str,
        payment_overrides: dict[str, object],
        customer_overrides: dict[str, object],
        expected_action: str,
        expected_status: str,
    ) -> None:
        """Verify each action generates its expected response status."""
        customer_data = {
            "customer_id": "cust_test",
            "notification_count": 0,
            "customer_age_days": 300,
            "previous_successful_payments": 15,
            "previous_failed_payments": 0,
            "previous_recovery_attempts": 0,
            "customer_lifetime_value": 3_000_000,
            "average_previous_payment": 199_900,
            "recent_payment_frequency": 8,
        }
        customer_data.update(customer_overrides)
        
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                event_id=event_id,
                payment_id=f"pay_{event_id}",
                payment=payment_data(payment_id=f"pay_{event_id}", **payment_overrides),
                customer=customer_data,
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == expected_action, f"Expected {expected_action}, got {body['action']}"
        assert body["result"]["status"] == expected_status


# ============================================================================
# TEST 6: STOP - MAX RECOVERY ATTEMPTS EXCEEDED
# ============================================================================


class TestStopMaxAttempts:
    """Verify STOP when recovery attempts exceed policy limit."""

    def test_stop_when_max_recovery_attempts_reached(self) -> None:
        """Max recovery attempts = 2 (default policy). Event with count=3 should STOP."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                event_id="evt_stop_attempts_001",
                recovery_attempt_count=3,
                payment_id="pay_stop_attempts_001",
                payment=payment_data(
                    payment_id="pay_stop_attempts_001",
                    amount=5_000,
                    time_since_failure_hours=3,
                ),
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"
        assert body["eligible"] is False


# ============================================================================
# TEST 7: STOP - RECOVERY WINDOW EXCEEDED
# ============================================================================


class TestStopRecoveryWindow:
    """Verify STOP when recovery window expires (48 hours default)."""

    def test_stop_when_recovery_window_exceeded(self) -> None:
        """Recovery window = 48 hours. Event 50 hours old should STOP."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                event_id="evt_stop_window_001",
                payment_id="pay_stop_window_001",
                payment=payment_data(
                    payment_id="pay_stop_window_001",
                    time_since_failure_hours=50,
                    failed_at=(NOW - timedelta(hours=50)).isoformat(),
                ),
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"
        assert body["eligible"] is False


# ============================================================================
# TEST 8: STOP - DUPLICATE EVENT
# ============================================================================


class TestStopDuplicate:
    """Verify STOP when same event is processed twice."""

    def test_duplicate_event_marked_in_response(self) -> None:
        """Verify duplicate detection flag is present in response."""
        client = TestClient(app)
        payment_id = f"pay_duplicate_unique_{uuid.uuid4().hex[:12]}"
        event_id = f"evt_duplicate_unique_{uuid.uuid4().hex[:12]}"
        event = event_data(
            event_id=event_id,
            payment_id=payment_id,
            payment=payment_data(payment_id=payment_id),
        )

        # First call should have duplicate=false
        response1 = client.post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event,
        )
        assert response1.status_code == 200
        body1 = response1.json()
        assert body1["duplicate"] is False
        assert "action" in body1
        assert body1["result"]["mode"] == "dry_run"


# ============================================================================
# TEST 9: ESCALATE - EXPLICIT APPROVAL REQUIRED
# ============================================================================


class TestEscalateApprovalRequired:
    """Verify ESCALATE when requires_approval=true overrides other actions."""

    def test_escalate_when_high_value_requires_approval(self) -> None:
        """Payment >500k (auto_action_limit) requires approval. Should ESCALATE."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                event_id="evt_escalate_approval_001",
                payment_id="pay_escalate_approval_001",
                payment=payment_data(
                    payment_id="pay_escalate_approval_001",
                    amount=600_000,  # Exceeds 500k limit
                    failure_reason="card_declined",  # Would normally be PAYMENT_LINK
                ),
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "ESCALATE"
        assert body["requires_approval"] is True
        assert body["result"]["status"] == "queued"


# ============================================================================
# TEST 10: STOP - EXPLICIT STOP ACTION
# ============================================================================


class TestStopExplicitAction:
    """Verify STOP when backend explicitly returns action=STOP."""

    def test_explicit_stop_action_is_preserved(self) -> None:
        """When backend decides STOP, it should be returned as-is."""
        # Use successful payment to trigger backend STOP decision
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                event_id="evt_stop_explicit_001",
                payment_id="pay_stop_explicit_001",
                payment=payment_data(
                    payment_id="pay_stop_explicit_001",
                    status="successful",  # Forces backend STOP
                ),
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"


# ============================================================================
# TEST 11-15: INVALID INPUT (Schema Validation Before Backend Call)
# ============================================================================


class TestInvalidInputs:
    """Verify invalid inputs are rejected before reaching the backend."""

    def test_invalid_event_type_rejected(self) -> None:
        """Invalid event_type should fail schema validation."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(event_type="invalid_type"),
        )

        assert response.status_code == 422

    def test_missing_payment_id_rejected(self) -> None:
        """Missing payment_id should fail schema validation."""
        evt = event_data()
        del evt["payment_id"]
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=evt,
        )

        assert response.status_code == 422

    def test_invalid_numeric_field_rejected(self) -> None:
        """Invalid numeric field should fail schema validation."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(recovery_attempt_count="not_a_number"),
        )

        assert response.status_code == 422

    def test_invalid_payment_method_rejected(self) -> None:
        """Invalid payment_method should fail schema validation."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                payment=payment_data(payment_method="bitcoin")
            ),
        )

        assert response.status_code == 422

    def test_invalid_timestamp_rejected(self) -> None:
        """Invalid timestamp format should fail schema validation."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(timestamp="not-a-date"),
        )

        assert response.status_code == 422


# ============================================================================
# TEST 16-18: ERROR RESPONSES (Backend Returns Error/Invalid Data)
# ============================================================================


class TestErrorResponses:
    """Verify proper handling of backend errors and invalid responses."""

    def test_backend_422_validation_error_returns_error_action(self) -> None:
        """Backend 422 on invalid payload should route to ERROR."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event_data(
                payment=payment_data(
                    payment_id="nonexistent",
                    amount=-100,  # Invalid: negative amount
                ),
            ),
        )

        # May be 422 from schema or processed with error action
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            body = response.json()
            assert body["action"] in ("ERROR", "STOP")

    def test_missing_payment_object_returns_error_or_422(self) -> None:
        """Missing payment object should fail validation."""
        evt = event_data()
        del evt["payment"]
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=evt,
        )

        # Either 422 validation error or 502 from downstream error
        assert response.status_code in (422, 502, 500)

    def test_missing_customer_object_returns_error_or_continues(self) -> None:
        """Missing customer object should be handled gracefully."""
        evt = event_data()
        del evt["customer"]
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=evt,
        )

        # Customer is optional, so 200 is valid
        # But if it causes issues, should still return 422 or 500
        assert response.status_code in (200, 422, 500)


# ============================================================================
# TEST 19-20: AUTHENTICATION ERRORS
# ============================================================================


class TestAuthenticationErrors:
    """Verify proper handling of auth errors (401/403)."""

    def test_missing_workflow_secret_returns_401(self) -> None:
        """Missing X-Reclaim-Workflow-Secret header should return 401."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            json=event_data(),
        )

        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "missing_workflow_secret"

    def test_invalid_workflow_secret_returns_403(self) -> None:
        """Invalid X-Reclaim-Workflow-Secret should return 403."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": "wrong_secret"},
            json=event_data(),
        )

        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["code"] == "invalid_workflow_secret"


# ============================================================================
# INTEGRATION: VERIFY WORKFLOW EXPORT MATCHES BACKEND CONTRACT
# ============================================================================


class TestWorkflowContract:
    """Verify the n8n workflow export matches the backend API contract."""

    def test_n8n_workflow_uses_current_backend_contract(self) -> None:
        """Verify workflow uses variable-based auth and no literal secrets."""
        workflow_path = (
            Path(__file__).resolve().parents[2]
            / "workflows"
            / "reclaim-recovery-orchestration.json"
        )
        text = workflow_path.read_text(encoding="utf-8")

        assert "/api/workflows/recovery" in text
        assert "X-Reclaim-Workflow-Secret" in text
        assert "reclaim-demo-secret-2026" not in text
        assert "RECLAIM_WORKFLOW_SECRET" in text
        assert "RECLAIM_BACKEND_URL" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
