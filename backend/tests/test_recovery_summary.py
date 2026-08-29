"""Tests for persisted recovery operational summaries."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Customer, Payment, RecoveryAttempt


def test_summary_counts_persisted_execution_metadata() -> None:
    suffix = str(uuid4())
    with SessionLocal() as session:
        customer = Customer(name=f"Summary {suffix}", email=f"{suffix}@example.invalid")
        payment = Payment(
            razorpay_payment_id=f"pay-summary-{suffix}",
            customer=customer,
            amount=1000,
            currency="INR",
            status="failed",
        )
        session.add_all([
            RecoveryAttempt(
                payment=payment, event_id=f"evt-summary-{suffix}", attempt_number=1,
                action="REMINDER", status="queued", amount=1000,
                execution_mode="dry_run", provider_called=False,
                execution_succeeded=True, notification_generated=True,
            ),
            RecoveryAttempt(
                payment=payment, event_id=f"evt-summary-stop-{suffix}", attempt_number=1,
                action="STOP", status="terminal", amount=1000,
                execution_mode="dry_run", provider_called=False,
                execution_succeeded=True, notification_generated=False,
            ),
        ])
        session.commit()

    try:
        response = TestClient(app).get("/api/recovery/summary")
        assert response.status_code == 200
        summary = response.json()
        assert summary["total_evaluations"] >= 2
        assert summary["total_dry_run_executions"] >= 2
        assert summary["reminder_count"] >= 1
        assert summary["stop_count"] >= 1
        assert isinstance(summary["revenue_at_risk"], int)
        assert isinstance(summary["recovery_rate"], (int, float))
        assert isinstance(summary["payments_analyzed"], int)
        assert isinstance(summary["interventions"], int)
        assert summary["revenue_recovered"] is None or isinstance(summary["revenue_recovered"], int)
        assert summary["recovered_count"] is None or isinstance(summary["recovered_count"], int)
        assert any(
            activity["event_id"] == f"evt-summary-{suffix}"
            and activity["notification_generated"] is True
            for activity in summary["recent_activity"]
        )
    finally:
        with SessionLocal() as session:
            attempts = session.scalars(
                select(RecoveryAttempt).where(RecoveryAttempt.event_id.in_([
                    f"evt-summary-{suffix}", f"evt-summary-stop-{suffix}"
                ]))
            ).all()
            payment = attempts[0].payment
            customer = payment.customer
            for attempt in attempts:
                session.delete(attempt)
            session.delete(payment)
            session.delete(customer)
            session.commit()


def test_summary_empty_activity_shape_is_valid() -> None:
    response = TestClient(app).get("/api/recovery/summary")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["total_evaluations"], int)
    assert isinstance(body["revenue_at_risk"], int)
    assert isinstance(body["recovery_rate"], (int, float))
    assert isinstance(body["action_counts"], dict)
    assert isinstance(body["recent_activity"], list)


def test_summary_counts_only_persisted_recovered_states_as_revenue() -> None:
    suffix = str(uuid4())
    with SessionLocal() as session:
        customer = Customer(name=f"Recovered {suffix}", email=f"{suffix}@example.invalid")
        payment = Payment(
            razorpay_payment_id=f"pay-recovered-{suffix}",
            customer=customer,
            amount=9000,
            currency="INR",
            status="successful",
            recovery_state="recovered",
        )
        session.add_all([
            RecoveryAttempt(
                payment=payment, event_id=f"evt-recovered-{suffix}", attempt_number=1,
                action="PAYMENT_LINK", status="queued", amount=9000,
                execution_mode="provider", provider_called=True,
                execution_succeeded=True, recovery_state="recovered",
            ),
            RecoveryAttempt(
                payment=payment, event_id=f"evt-pending-{suffix}", attempt_number=2,
                action="PAYMENT_LINK", status="queued", amount=9000,
                execution_mode="provider", provider_called=True,
                execution_succeeded=True, recovery_state="action_pending",
            ),
            RecoveryAttempt(
                payment=payment, event_id=f"evt-stopped-{suffix}", attempt_number=3,
                action="STOP", status="terminal", amount=9000,
                execution_mode="dry_run", provider_called=False,
                execution_succeeded=True, recovery_state="stopped",
            ),
        ])
        session.commit()

    try:
        response = TestClient(app).get("/api/recovery/summary")
        assert response.status_code == 200
        summary = response.json()
        assert summary["revenue_recovered"] == 9000
        assert summary["recovered_count"] == 1
    finally:
        with SessionLocal() as session:
            attempts = session.scalars(
                select(RecoveryAttempt).where(RecoveryAttempt.event_id.in_([
                    f"evt-recovered-{suffix}", f"evt-pending-{suffix}", f"evt-stopped-{suffix}"
                ]))
            ).all()
            payment = attempts[0].payment
            customer = payment.customer
            for attempt in attempts:
                session.delete(attempt)
            session.delete(payment)
            session.delete(customer)
            session.commit()
