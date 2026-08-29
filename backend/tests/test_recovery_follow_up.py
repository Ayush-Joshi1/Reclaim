"""Tests for persistent autonomous recovery follow-ups."""

from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Payment, RecoveryAttempt
from app.schemas import MerchantPolicy
from app.schemas.razorpay import RazorpayPaymentLink
from app.services.recovery_follow_up import RecoveryFollowUpService
from app.services.recovery_reconciliation import RecoveryReconciliationService
from app.services.razorpay_client import RazorpayNetworkError


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with SessionLocal() as session:
        session.execute(text("TRUNCATE TABLE recovery_attempts, payments, customers RESTART IDENTITY CASCADE"))
        session.commit()


class LinkClient:
    def __init__(self, status: str = "active", error: Exception | None = None) -> None:
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
            reference_id="pay-follow-up",
        )


def make_attempt() -> str:
    payment_id = f"pay-follow-up-{uuid4()}"
    with SessionLocal() as session:
        customer = Customer(name="Follow-up Customer", email=f"{payment_id}@example.invalid")
        payment = Payment(
            razorpay_payment_id=payment_id,
            customer=customer,
            amount=125_000,
            currency="INR",
            status="failed",
            recovery_state="action_pending",
            failure_reason="card_declined",
        )
        session.add(payment)
        session.flush()
        attempt = RecoveryAttempt(
            payment=payment,
            event_id=f"evt-follow-up-{uuid4()}",
            attempt_number=1,
            execution_mode="provider",
            provider_called=True,
            execution_succeeded=True,
            action="PAYMENT_LINK",
            status="queued",
            recovery_state="action_pending",
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
        session.expunge(attempt)
        return attempt


def reconciler(client: LinkClient, policy: MerchantPolicy | None = None) -> RecoveryReconciliationService:
    return RecoveryReconciliationService(
        client=client,
        configured=Settings(database_url="postgresql://test"),
        policy=policy,
    )


def test_active_link_waits_without_creating_another_link() -> None:
    attempt_id = make_attempt()
    client = LinkClient("active")
    service = RecoveryFollowUpService(
        reconciler=reconciler(client),
        configured=Settings(database_url="postgresql://test"),
    )

    result = service.process_attempt(attempt_id)

    assert result.status == "waiting"
    assert load_attempt(attempt_id).follow_up_status == "waiting"
    assert client.calls and len(client.calls) == 1


def test_paid_link_becomes_recovered_without_follow_up_execution() -> None:
    attempt_id = make_attempt()
    client = LinkClient("paid")
    workflow = SimpleNamespace(process=lambda event: pytest.fail("workflow must not run after payment") )
    service = RecoveryFollowUpService(
        reconciler=reconciler(client),
        workflow=workflow,
        configured=Settings(database_url="postgresql://test"),
    )

    result = service.process_attempt(attempt_id)

    assert result.status == "recovered"
    assert load_attempt(attempt_id).follow_up_status == "recovered"


class RetryWorkflow:
    def __init__(self) -> None:
        self.events = []

    def process(self, event):
        self.events.append(event)
        with SessionLocal() as session:
            payment = session.scalar(select(Payment).where(Payment.razorpay_payment_id == event.payment_id))
            assert payment is not None
            attempt = RecoveryAttempt(
                payment=payment,
                event_id=event.event_id,
                attempt_number=event.recovery_attempt_count + 1,
                execution_mode="provider",
                provider_called=True,
                execution_succeeded=True,
                action="PAYMENT_LINK",
                status="queued",
                recovery_state="action_pending",
                provider_payment_link_id="plink-new-follow-up",
                provider_reference_id=event.payment_id,
                amount=payment.amount,
            )
            session.add(attempt)
            session.commit()
        return SimpleNamespace(result=SimpleNamespace(message="new validated recovery action created"))


def test_expired_link_reenters_existing_workflow_with_new_attempt() -> None:
    attempt_id = make_attempt()
    workflow = RetryWorkflow()
    service = RecoveryFollowUpService(
        reconciler=reconciler(LinkClient("expired")),
        workflow=workflow,
        configured=Settings(database_url="postgresql://test"),
        policy=MerchantPolicy(max_recovery_attempts=2),
    )

    result = service.process_attempt(attempt_id)

    assert result.status == "retried"
    assert result.new_attempt_id is not None
    assert len(workflow.events) == 1
    with SessionLocal() as session:
        attempts = session.scalars(select(RecoveryAttempt).order_by(RecoveryAttempt.attempt_number)).all()
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert attempts[0].follow_up_status == "superseded"


def test_retry_limit_stops_expired_recovery() -> None:
    attempt_id = make_attempt()
    service = RecoveryFollowUpService(
        reconciler=reconciler(LinkClient("expired")),
        configured=Settings(database_url="postgresql://test"),
        policy=MerchantPolicy(max_recovery_attempts=1),
    )

    result = service.process_attempt(attempt_id)

    assert result.status == "stopped"
    attempt = load_attempt(attempt_id)
    assert attempt.recovery_state == "stopped"
    assert attempt.payment.recovery_state == "stopped" if attempt.payment else True


def test_provider_failure_waits_and_does_not_blindly_retry() -> None:
    attempt_id = make_attempt()
    workflow = SimpleNamespace(process=lambda event: pytest.fail("workflow must not run after provider failure"))
    service = RecoveryFollowUpService(
        reconciler=reconciler(LinkClient(error=RazorpayNetworkError("timeout"))),
        workflow=workflow,
        configured=Settings(database_url="postgresql://test"),
    )

    result = service.process_attempt(attempt_id)

    assert result.status == "waiting"
    assert load_attempt(attempt_id).recovery_state == "action_pending"


def test_concurrent_workers_are_serialized_by_persistent_claim() -> None:
    attempt_id = make_attempt()
    entered_provider = Event()
    release_provider = Event()

    class BlockingClient(LinkClient):
        def get_payment_link(self, payment_link_id: str) -> RazorpayPaymentLink:
            entered_provider.set()
            release_provider.wait(timeout=5)
            return super().get_payment_link(payment_link_id)

    client = BlockingClient("active")
    service = RecoveryFollowUpService(
        reconciler=reconciler(client),
        configured=Settings(database_url="postgresql://test", follow_up_lease_seconds=300),
    )
    results = []

    first = Thread(target=lambda: results.append(service.process_attempt(attempt_id)))
    first.start()
    assert entered_provider.wait(timeout=5)
    second = Thread(target=lambda: results.append(service.process_attempt(attempt_id)))
    second.start()
    second.join(timeout=5)
    release_provider.set()
    first.join(timeout=5)

    assert sorted(result.status for result in results) == ["skipped", "waiting"]
    assert len(client.calls) == 1


def test_follow_up_api_rejects_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret="follow-up-secret"),
    )

    response = TestClient(app).post("/api/recovery/follow-up", json={})

    assert response.status_code == 401
    assert "follow-up-secret" not in response.text


def test_follow_up_api_returns_bounded_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret="follow-up-secret"),
    )
    class StubFollowUpService:
        def __init__(self, **kwargs: object) -> None:
            pass

        def process_pending(self, limit: int) -> SimpleNamespace:
            return SimpleNamespace(
                processed_count=1,
                recovered_count=1,
                retried_count=0,
                stopped_count=0,
                skipped_count=0,
                failure_count=0,
                results=[],
            )

    monkeypatch.setattr("app.api.follow_up.RecoveryFollowUpService", StubFollowUpService)

    response = TestClient(app).post(
        "/api/recovery/follow-up",
        headers={"X-Reclaim-Workflow-Secret": "follow-up-secret"},
        json={"limit": 10},
    )

    assert response.status_code == 200
    assert response.json()["processed_count"] == 1
    assert response.json()["recovered_count"] == 1
