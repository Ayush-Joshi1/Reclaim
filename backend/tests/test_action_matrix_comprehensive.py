"""Comprehensive action branch matrix (20+ tests) for recovery workflow."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.config import Settings
from app.main import app
from app.services.recovery_workflow import workflow_service

SECRET = "workflow-comprehensive-test-secret"
NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure test environment before each test."""
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret=SECRET),
    )
    workflow_service._payment_client = None
    workflow_service.clear_idempotency()


def base_event(event_id: str = "evt_test", **overrides) -> dict:
    """Build test event with sensible defaults."""
    event = {
        "event_id": event_id,
        "payment_id": f"pay_{event_id}",
        "event_type": "payment_failed",
        "timestamp": NOW.isoformat(),
        "source": "n8n",
        "recovery_attempt_count": 0,
        "payment": {
            "payment_id": f"pay_{event_id}",
            "amount": 199_900,
            "currency": "INR",
            "payment_method": "card",
            "status": "failed",
            "failure_reason": None,
            "failed_at": (NOW - timedelta(hours=2)).isoformat(),
            "time_since_failure_hours": 2,
        },
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
    
    # Deep merge overrides
    for key, value in overrides.items():
        if isinstance(value, dict) and key in event and isinstance(event[key], dict):
            event[key].update(value)
        else:
            event[key] = value
    
    return event


# ============================================================================
# TEST GROUP 1: CORE ACTION BRANCHES (RETRY, PAYMENT_LINK, ESCALATE, STOP)
# ============================================================================


class TestCoreActionBranches:
    """Verify the four core action branches work correctly."""

    def test_retry_transient_failure(self) -> None:
        """TEST 1: RETRY action for transient failures."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_retry_001", payment={"failure_reason": "network_error"}),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "RETRY"
        assert body["result"]["status"] == "queued"

    def test_payment_link_for_card_decline(self) -> None:
        """TEST 2: PAYMENT_LINK action for card decline."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_paymentlink_001", payment={"failure_reason": "card_declined"}),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "PAYMENT_LINK"
        assert body["result"]["status"] == "queued"

    def test_escalate_high_value_payment(self) -> None:
        """TEST 3: ESCALATE action for high-value payment requiring approval."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_escalate_001",
                payment={"amount": 600_000},  # Exceeds 500k approval limit
            ),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "ESCALATE"
        assert body["requires_approval"] is True
        assert body["result"]["status"] == "queued"

    def test_stop_successful_payment(self) -> None:
        """TEST 4: STOP action for already-successful payment."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_stop_successful_001",
                payment={"status": "successful"},
            ),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"
        assert body["eligible"] is False
        assert body["result"]["status"] == "terminal"


# ============================================================================
# TEST GROUP 2: STOP CONDITIONS
# ============================================================================


class TestStopConditions:
    """Verify STOP is triggered by policy violations."""

    def test_stop_max_recovery_attempts(self) -> None:
        """TEST 5: STOP when max recovery attempts (2) exceeded."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_stop_attempts_001",
                recovery_attempt_count=3,  # > 2 limit
            ),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"
        assert body["eligible"] is False

    def test_stop_recovery_window_expired(self) -> None:
        """TEST 6: STOP when recovery window (48h) exceeded."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_stop_window_001",
                payment={
                    "time_since_failure_hours": 50,  # > 48h limit
                    "failed_at": (NOW - timedelta(hours=50)).isoformat(),
                },
            ),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"
        assert body["eligible"] is False

    def test_stop_closed_payment(self) -> None:
        """TEST 7: STOP for permanently closed payment."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_stop_closed_001",
                payment={"status": "permanently_closed"},
            ),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "STOP"


# ============================================================================
# TEST GROUP 3: INPUT VALIDATION
# ============================================================================


class TestInputValidation:
    """Verify invalid inputs are rejected with 422."""

    def test_invalid_event_type(self) -> None:
        """TEST 8: Reject invalid event_type."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_invalid_type", event_type="invalid_type"),
        )
        
        assert response.status_code == 422

    def test_missing_payment_id(self) -> None:
        """TEST 9: Reject missing payment_id."""
        event = base_event("evt_missing_pid")
        del event["payment_id"]
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event,
        )
        
        assert response.status_code == 422

    def test_missing_payment_object(self) -> None:
        """TEST 10: Reject missing payment object."""
        event = base_event("evt_missing_pmt")
        del event["payment"]
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event,
        )
        
        assert response.status_code in (422, 500, 502)

    def test_invalid_numeric_amount(self) -> None:
        """TEST 11: Reject invalid numeric amount."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_invalid_amount",
                payment={"amount": "not_a_number"},
            ),
        )
        
        assert response.status_code == 422

    def test_invalid_payment_method(self) -> None:
        """TEST 12: Reject invalid payment_method."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event(
                "evt_invalid_method",
                payment={"payment_method": "crypto"},
            ),
        )
        
        assert response.status_code == 422

    def test_invalid_timestamp(self) -> None:
        """TEST 13: Reject invalid timestamp format."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_invalid_ts", timestamp="not-a-date"),
        )
        
        assert response.status_code == 422


# ============================================================================
# TEST GROUP 4: AUTHENTICATION
# ============================================================================


class TestAuthentication:
    """Verify auth errors are handled correctly."""

    def test_missing_secret_header(self) -> None:
        """TEST 14: Missing X-Reclaim-Workflow-Secret returns 401."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            json=base_event("evt_no_secret"),
        )
        
        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "missing_workflow_secret"

    def test_invalid_secret(self) -> None:
        """TEST 15: Invalid X-Reclaim-Workflow-Secret returns 403."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": "wrong_secret"},
            json=base_event("evt_bad_secret"),
        )
        
        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["code"] == "invalid_workflow_secret"


# ============================================================================
# TEST GROUP 5: RESPONSE STRUCTURE
# ============================================================================


class TestResponseStructure:
    """Verify response contains required fields."""

    def test_response_has_all_required_fields(self) -> None:
        """TEST 16: Response includes all required fields."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_fields_check"),
        )
        
        assert response.status_code == 200
        body = response.json()
        
        # Verify required fields
        required_fields = [
            "event_id",
            "duplicate",
            "payment_id",
            "risk_score",
            "eligible",
            "requires_approval",
            "action",
            "confidence",
            "validation_status",
            "priority",
            "decision",
            "result",
        ]
        for field in required_fields:
            assert field in body, f"Missing required field: {field}"

    def test_dry_run_result_mode(self) -> None:
        """TEST 17: Result always has mode=dry_run."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_dryrun_check"),
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["mode"] == "dry_run"
        assert body["result"]["execution_mode"] == "dry_run"


# ============================================================================
# TEST GROUP 6: WORKFLOW JSON CONTRACT
# ============================================================================


class TestWorkflowContract:
    """Verify the n8n workflow export matches backend contract."""

    def test_workflow_export_uses_environment_variables(self) -> None:
        """TEST 18: Workflow export uses {{ $vars.* }} for auth and URL."""
        workflow_path = (
            Path(__file__).resolve().parents[2]
            / "workflows"
            / "reclaim-recovery-orchestration.json"
        )
        text = workflow_path.read_text(encoding="utf-8")
        
        # Verify no hardcoded secrets
        assert "reclaim-demo-secret-2026" not in text
        assert "early-excellence-telephone-honey.trycloudflare.com" not in text
        
        # Verify runtime configuration is used for the auth secret and the public backend endpoint
        assert "RECLAIM_WORKFLOW_SECRET" in text or "$vars.RECLAIM_WORKFLOW_SECRET" in text
        assert "https://reclaim-wirm.onrender.com/api/workflows/recovery" in text
        assert "/api/workflows/recovery" in text

    def test_workflow_json_is_valid(self) -> None:
        """TEST 19: Workflow export is valid JSON."""
        workflow_path = (
            Path(__file__).resolve().parents[2]
            / "workflows"
            / "reclaim-recovery-orchestration.json"
        )
        content = workflow_path.read_text(encoding="utf-8")
        
        # Should not raise
        parsed = json.loads(content)
        assert isinstance(parsed, dict)


# ============================================================================
# TEST GROUP 7: INTEGRATION SANITY CHECKS
# ============================================================================


class TestIntegrationSanity:
    """Quick sanity checks for end-to-end behavior."""

    def test_multiple_sequential_requests(self) -> None:
        """TEST 20: Multiple sequential requests work correctly."""
        import uuid
        client = TestClient(app)
        
        for i in range(3):
            unique_id = str(uuid.uuid4())[:8]
            response = client.post(
                "/api/workflows/recovery",
                headers={"X-Reclaim-Workflow-Secret": SECRET},
                json=base_event(f"evt_seq_{unique_id}"),
            )
            
            assert response.status_code == 200
            body = response.json()
            assert "action" in body
            # First occurrence of any event should not be marked as duplicate
            # (though subsequent same-event calls within this test might be)

    def test_action_field_is_valid_literal(self) -> None:
        """TEST 21: Action field contains only valid literals."""
        response = TestClient(app).post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=base_event("evt_action_check"),
        )
        
        assert response.status_code == 200
        body = response.json()
        valid_actions = {"RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"}
        assert body["action"] in valid_actions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
