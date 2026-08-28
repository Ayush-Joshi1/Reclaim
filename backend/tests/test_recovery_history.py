"""Tests for persisted recovery evaluation history."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Payment, RecoveryAttempt
from app.services.recovery_workflow import workflow_service

SECRET = "history-test-secret"


@pytest.fixture(autouse=True)
def history_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret=SECRET),
    )
    workflow_service.clear_idempotency()


def history_event() -> dict[str, object]:
    payment_id = f"pay-history-{uuid4()}"
    failed_at = datetime.now(UTC) - timedelta(hours=2)
    return {
        "event_id": f"evt-history-{uuid4()}",
        "payment_id": payment_id,
        "event_type": "payment_failed",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "history-test",
        "recovery_attempt_count": 0,
        "payment": {
            "payment_id": payment_id,
            "amount": 125_000,
            "currency": "INR",
            "payment_method": "card",
            "status": "failed",
            "failure_reason": "insufficient_funds",
            "failed_at": failed_at.isoformat(),
            "time_since_failure_hours": 2,
        },
    }


def test_evaluation_persists_and_history_is_queryable() -> None:
    event = history_event()
    client = TestClient(app)
    headers = {"X-Reclaim-Workflow-Secret": SECRET}

    first = client.post("/api/workflows/recovery", headers=headers, json=event)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["duplicate"] is False

    with SessionLocal() as session:
        attempt = session.scalar(
            select(RecoveryAttempt).where(RecoveryAttempt.event_id == event["event_id"])
        )
        assert attempt is not None
        assert attempt.payment.razorpay_payment_id == event["payment_id"]
        assert attempt.action == first_body["action"]
        assert attempt.amount == 125_000
        assert attempt.attempt_number == 1
        assert attempt.created_at is not None
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttempt).where(
                RecoveryAttempt.event_id == event["event_id"]
            )
        ) == 1

    history = client.get(
        "/api/recovery/history", params={"payment_id": event["payment_id"], "limit": 10}
    )
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["event_id"] == event["event_id"]

    payment_history = client.get(f"/api/recovery/history/{event['payment_id']}")
    assert payment_history.status_code == 200
    assert payment_history.json()[0]["payment_id"] == event["payment_id"]

    duplicate = client.post("/api/workflows/recovery", headers=headers, json=event)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    with SessionLocal() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttempt).where(
                RecoveryAttempt.event_id == event["event_id"]
            )
        ) == 1

        attempt = session.scalar(
            select(RecoveryAttempt).where(RecoveryAttempt.event_id == event["event_id"])
        )
        assert attempt is not None
        payment = attempt.payment
        customer = payment.customer
        session.delete(attempt)
        session.delete(payment)
        session.delete(customer)
        session.commit()


def test_history_for_unknown_payment_is_empty() -> None:
    response = TestClient(app).get("/api/recovery/history/pay-does-not-exist")

    assert response.status_code == 200
    assert response.json() == []
