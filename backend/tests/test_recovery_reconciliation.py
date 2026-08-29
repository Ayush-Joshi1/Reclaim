"""Tests for safe Razorpay Payment Link reconciliation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload
from fastapi.testclient import TestClient

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Payment, RecoveryAttempt
from app.schemas.razorpay import RazorpayPaymentLink
from app.services.recovery_reconciliation import RecoveryReconciliationService
from app.services.razorpay_client import RazorpayNetworkError, RazorpayUpstreamError


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with SessionLocal() as session:
        session.execute(text("TRUNCATE TABLE recovery_attempts, payments, customers RESTART IDENTITY CASCADE"))
        session.commit()


class FakePaymentLinkClient:
    def __init__(self, status: str = "created", error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls: list[str] = []

    def get_payment_link(self, payment_link_id: str) -> RazorpayPaymentLink:
        self.calls.append(payment_link_id)
        if self.error:
            raise self.error
        return RazorpayPaymentLink(
            id=payment_link_id,
            amount=125_000,
            currency="INR",
            status=self.status,
            short_url="https://rzp.io/i/test",
            reference_id="pay-reconcile-test",
        )


def make_attempt(state: str = "action_pending") -> str:
    payment_id = f"pay-reconcile-{uuid4()}"
    with SessionLocal() as session:
        customer = Customer(name="Reconciliation Customer", email=f"{payment_id}@example.invalid")
        payment = Payment(
            razorpay_payment_id=payment_id,
            customer=customer,
            amount=125_000,
            currency="INR",
            status="failed",
            recovery_state=state,
            failure_reason="card_declined",
        )
        session.add(payment)
        session.flush()
        attempt = RecoveryAttempt(
            payment=payment,
            event_id=f"evt-reconcile-{uuid4()}",
            attempt_number=1,
            execution_mode="provider",
            provider_called=True,
            execution_succeeded=True,
            action="PAYMENT_LINK",
            status="queued",
            recovery_state=state,
            state_reason="Payment link created.",
            provider_payment_link_id=f"plink-{uuid4()}",
            provider_reference_id=payment_id,
            amount=125_000,
        )
        session.add(attempt)
        session.commit()
        return str(attempt.id)


def load_attempt(attempt_id: str) -> RecoveryAttempt:
    with SessionLocal() as session:
        attempt = session.scalar(
            select(RecoveryAttempt)
            .options(joinedload(RecoveryAttempt.payment))
            .where(RecoveryAttempt.id == attempt_id)
        )
        assert attempt is not None
        return attempt


def service(client: FakePaymentLinkClient, max_attempts: int = 3) -> RecoveryReconciliationService:
    return RecoveryReconciliationService(
        client=client,
        configured=Settings(database_url="postgresql://test", reconciliation_max_attempts=max_attempts),
    )


def test_active_link_remains_pending_and_is_audited() -> None:
    attempt_id = make_attempt()
    client = FakePaymentLinkClient("active")

    result = service(client).reconcile_attempt(attempt_id)
    attempt = load_attempt(attempt_id)

    assert result.status == "unchanged"
    assert result.provider_state == "active"
    assert attempt.recovery_state == "action_pending"
    assert attempt.reconciliation_provider_state == "active"
    assert attempt.reconciliation_resulting_state == "action_pending"
    assert attempt.reconciliation_attempts == 1


def test_paid_link_recovers_payment_without_webhook() -> None:
    attempt_id = make_attempt()
    client = FakePaymentLinkClient("paid")

    result = service(client).reconcile_attempt(attempt_id)
    attempt = load_attempt(attempt_id)

    assert result.status == "recovered"
    assert attempt.recovery_state == "recovered"
    assert attempt.payment.recovery_state == "recovered"
    assert attempt.payment.status == "successful"
    assert attempt.completed_at is not None


def test_expired_and_cancelled_links_stop_further_recovery() -> None:
    for provider_status, expected_state in (("expired", "failed"), ("cancelled", "stopped"), ("closed", "stopped")):
        attempt_id = make_attempt()
        result = service(FakePaymentLinkClient(provider_status)).reconcile_attempt(attempt_id)
        attempt = load_attempt(attempt_id)

        assert result.status == expected_state
        assert attempt.recovery_state == expected_state
        assert attempt.reconciliation_resulting_state == expected_state


def test_unknown_provider_state_does_not_change_local_state() -> None:
    attempt_id = make_attempt()

    result = service(FakePaymentLinkClient("pending")).reconcile_attempt(attempt_id)
    attempt = load_attempt(attempt_id)

    assert result.status == "unknown_state"
    assert attempt.recovery_state == "action_pending"
    assert attempt.reconciliation_reason is not None


@pytest.mark.parametrize("error", [RazorpayNetworkError("timeout"), RazorpayUpstreamError("upstream")])
def test_provider_failures_are_recorded_without_recovery(error: Exception) -> None:
    attempt_id = make_attempt()
    client = FakePaymentLinkClient(error=error)

    result = service(client).reconcile_attempt(attempt_id)
    attempt = load_attempt(attempt_id)

    assert result.status == "failed"
    assert attempt.recovery_state == "action_pending"
    assert attempt.reconciliation_status == "failed"
    assert attempt.reconciliation_attempts == 1


def test_recovered_state_is_protected_from_stale_created_response() -> None:
    attempt_id = make_attempt("recovered")
    with SessionLocal() as session:
        attempt = session.scalar(select(RecoveryAttempt).where(RecoveryAttempt.id == attempt_id))
        assert attempt is not None
        attempt.payment.status = "successful"
        attempt.payment.recovery_state = "recovered"
        session.commit()

    client = FakePaymentLinkClient("created")
    result = service(client).reconcile_attempt(attempt_id)

    assert result.status == "skipped"
    assert load_attempt(attempt_id).recovery_state == "recovered"
    assert client.calls == []


def test_duplicate_paid_reconciliation_is_idempotent() -> None:
    attempt_id = make_attempt()
    client = FakePaymentLinkClient("paid")
    reconciler = service(client)

    first = reconciler.reconcile_attempt(attempt_id)
    second = reconciler.reconcile_attempt(attempt_id)

    assert first.status == "recovered"
    assert second.status == "skipped"
    assert client.calls == [load_attempt(attempt_id).provider_payment_link_id]


def test_reconciliation_limit_prevents_unbounded_provider_calls() -> None:
    attempt_id = make_attempt()
    client = FakePaymentLinkClient(error=RazorpayNetworkError("timeout"))
    reconciler = service(client, max_attempts=1)

    first = reconciler.reconcile_attempt(attempt_id)
    second = reconciler.reconcile_attempt(attempt_id)

    assert first.status == "failed"
    assert second.status == "skipped"
    assert len(client.calls) == 1


def test_old_payment_link_is_not_eligible() -> None:
    attempt_id = make_attempt()
    with SessionLocal() as session:
        attempt = session.scalar(select(RecoveryAttempt).where(RecoveryAttempt.id == attempt_id))
        assert attempt is not None
        attempt.created_at = datetime.now(UTC) - timedelta(hours=49)
        session.commit()

    client = FakePaymentLinkClient("paid")
    result = service(client).reconcile_attempt(attempt_id)

    assert result.status == "skipped"
    assert client.calls == []


def test_reconciliation_api_requires_workflow_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret="reconcile-secret"),
    )

    response = TestClient(app).post("/api/reconciliation/run", json={})

    assert response.status_code == 401
    assert "reconcile-secret" not in response.text
