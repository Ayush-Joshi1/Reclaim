"""Tests for Razorpay webhook ingestion and payment-state synchronization."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Payment, ProviderWebhookReceipt, RecoveryAttempt

SECRET = "webhook-test-secret"
NOW = datetime(2026, 8, 27, tzinfo=UTC)


@pytest.fixture(autouse=True)
def webhook_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        Settings(
            database_url="postgresql://test",
            reclaim_workflow_secret="workflow-secret",
            razorpay_webhook_secret=SECRET,
        ),
    )

    with SessionLocal() as session:
        session.execute(text("TRUNCATE TABLE provider_webhook_receipts, recovery_attempts, payments, customers RESTART IDENTITY CASCADE"))
        session.commit()


def signed_body(secret: str, payload: dict[str, object]) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, signature


def test_valid_signature_and_supported_event_updates_payment_state() -> None:
    payment_id = f"pay_webhook_{uuid4()}"
    customer = Customer(name="Webhook Customer", email=f"{payment_id}@example.invalid")
    with SessionLocal() as session:
        session.add(customer)
        session.flush()
        payment = Payment(
            razorpay_payment_id=payment_id,
            customer_id=customer.id,
            amount=125_000,
            currency="INR",
            status="authorized",
            failure_reason=None,
        )
        session.add(payment)
        session.commit()

    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 125_000,
                    "currency": "INR",
                    "status": "failed",
                    "error_code": "payment_failed",
                    "error_description": "Card declined",
                }
            }
        },
        "created_at": int(NOW.timestamp()),
    }
    raw, signature = signed_body(SECRET, payload)

    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["payment_id"] == payment_id

    with SessionLocal() as session:
        updated = session.scalar(select(Payment).where(Payment.razorpay_payment_id == payment_id))
        assert updated is not None
        assert updated.status == "failed"
        assert updated.customer_id == customer.id

        receipt = session.scalar(
            select(ProviderWebhookReceipt).where(
                ProviderWebhookReceipt.provider == "razorpay",
                ProviderWebhookReceipt.provider_event_id == "payment.failed:pay_webhook_" + payment_id.split("pay_webhook_")[-1],
            )
        )
        assert receipt is not None


def test_payment_link_paid_event_marks_related_recovery_successful() -> None:
    original_payment_id = f"pay_original_{uuid4()}"
    payment_link_id = f"plink_paid_{uuid4()}"
    event_id = f"evt-link-paid-{uuid4()}"
    customer = Customer(name="Recovery Customer", email=f"{original_payment_id}@example.invalid")
    with SessionLocal() as session:
        session.add(customer)
        session.flush()
        payment = Payment(
            razorpay_payment_id=original_payment_id,
            customer_id=customer.id,
            amount=125_000,
            currency="INR",
            status="failed",
            failure_reason="card_declined",
        )
        session.add(payment)
        session.flush()
        attempt = RecoveryAttempt(
            payment_id=payment.id,
            event_id=event_id,
            attempt_number=1,
            execution_mode="provider",
            provider_called=True,
            execution_succeeded=True,
            notification_generated=False,
            action="PAYMENT_LINK",
            status="queued",
            recovery_state="action_pending",
            state_reason="Payment link created.",
            amount=125_000,
            provider_payment_link_id=payment_link_id,
            provider_reference_id=original_payment_id,
        )
        session.add(attempt)
        session.commit()

    payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment": {"entity": {"id": "pay_link_paid_123", "amount": 125_000, "currency": "INR", "status": "paid"}},
            "payment_link": {"entity": {"id": payment_link_id, "reference_id": original_payment_id, "amount": 125_000, "currency": "INR", "status": "paid"}},
        },
        "created_at": int(NOW.timestamp()),
    }
    raw, signature = signed_body(SECRET, payload)

    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    with SessionLocal() as session:
        payment = session.scalar(select(Payment).where(Payment.razorpay_payment_id == original_payment_id))
        assert payment is not None
        assert payment.status == "successful"
        assert payment.recovery_state == "recovered"

        attempt = session.scalar(select(RecoveryAttempt).where(RecoveryAttempt.event_id == event_id))
        assert attempt is not None
        assert attempt.recovery_state == "recovered"
        assert attempt.execution_succeeded is True
        assert attempt.provider_payment_id == "pay_link_paid_123"
        assert attempt.provider_payment_link_id == payment_link_id
        assert attempt.completed_at is not None


def test_unknown_payment_link_does_not_modify_unrelated_payments() -> None:
    payment_id = f"pay_other_{uuid4()}"
    payment_link_id = f"plink_missing_{uuid4()}"
    customer = Customer(name="Other Customer", email=f"{payment_id}@example.invalid")
    with SessionLocal() as session:
        session.add(customer)
        session.flush()
        payment = Payment(
            razorpay_payment_id=payment_id,
            customer_id=customer.id,
            amount=99_000,
            currency="INR",
            status="failed",
            failure_reason="bank_error",
        )
        session.add(payment)
        session.commit()

    payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment": {"entity": {"id": "pay_unknown_link_payment", "amount": 99_000, "currency": "INR", "status": "paid"}},
            "payment_link": {"entity": {"id": payment_link_id, "reference_id": "not-a-known-payment", "amount": 99_000, "currency": "INR", "status": "paid"}},
        },
        "created_at": int(NOW.timestamp()),
    }
    raw, signature = signed_body(SECRET, payload)

    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert response.status_code == 404
    assert response.json()["status"] == "unknown_payment_link"

    with SessionLocal() as session:
        payment = session.scalar(select(Payment).where(Payment.razorpay_payment_id == payment_id))
        assert payment is not None
        assert payment.status == "failed"
        assert payment.recovery_state != "recovered"


def test_invalid_signature_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": "bad-signature"},
        content=b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_bad"}}}}',
    )

    assert response.status_code == 403


def test_missing_signature_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        content=b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_bad"}}}}',
    )

    assert response.status_code == 401


def test_malformed_json_is_rejected() -> None:
    raw = b'{"event": '
    signature = hmac.new(SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert response.status_code == 400


def test_unsupported_event_is_ignored_safely() -> None:
    payload = {
        "event": "payment.refunded",
        "payload": {"payment": {"entity": {"id": "pay_unsupported"}}},
        "created_at": int(NOW.timestamp()),
    }
    raw, signature = signed_body(SECRET, payload)

    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert response.status_code == 202
    assert response.json()["status"] == "ignored"


def test_duplicate_webhook_does_not_create_duplicate_records() -> None:
    payment_id = f"pay_duplicate_{uuid4()}"
    payload = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": payment_id, "amount": 200_000, "currency": "INR", "status": "captured"}}},
        "created_at": int((NOW - timedelta(minutes=1)).timestamp()),
    }
    raw, signature = signed_body(SECRET, payload)

    client = TestClient(app)
    first = client.post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )
    second = client.post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "duplicate"

    with SessionLocal() as session:
        assert session.scalar(select(Payment).where(Payment.razorpay_payment_id == payment_id)) is not None
        assert session.scalar(
            select
            (
                __import__("sqlalchemy").func.count()
            )
            .select_from(Payment)
            .where(Payment.razorpay_payment_id == payment_id)
        ) == 1

        assert session.scalar(
            select
            (
                __import__("sqlalchemy").func.count()
            )
            .select_from(ProviderWebhookReceipt)
            .where(
                ProviderWebhookReceipt.provider == "razorpay",
                ProviderWebhookReceipt.provider_event_id == "payment.captured:" + payment_id,
            )
        ) == 1


def test_unknown_payment_is_created_safely() -> None:
    payment_id = f"pay_unknown_{uuid4()}"
    payload = {
        "event": "payment.authorized",
        "payload": {"payment": {"entity": {"id": payment_id, "amount": 150_000, "currency": "INR", "status": "authorized"}}},
        "created_at": int(NOW.timestamp()),
    }
    raw, signature = signed_body(SECRET, payload)

    response = TestClient(app).post(
        "/api/integrations/razorpay/webhook",
        headers={"X-Razorpay-Signature": signature},
        content=raw,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    with SessionLocal() as session:
        record = session.scalar(select(Payment).where(Payment.razorpay_payment_id == payment_id))
        assert record is not None
        assert record.status == "authorized"
        assert record.customer is not None
