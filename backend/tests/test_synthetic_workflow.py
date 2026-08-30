"""Process representative records from the checked-in synthetic dataset."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.config import Settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Payment, RecoveryAttempt
from app.schemas import CustomerRiskContext, PaymentRiskInput, RecoveryEvent
from app.services.action_executor import DryRunActionExecutor
from app.services.recovery_workflow import workflow_service

SECRET = "synthetic-workflow-test-secret"
DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "sample_payments.json"
EXPECTED_ACTIONS = (
    "PAYMENT_LINK",
    "PAYMENT_LINK",
    "REMINDER",
    "ESCALATE",
    "STOP",
    "ESCALATE",
    "ESCALATE",
    "REMINDER",
    "ESCALATE",
    "STOP",
    "RETRY",
)


def _selected_records() -> list[dict[str, object]]:
    records = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    selected: list[dict[str, object]] = []
    seen_scenarios: set[str] = set()
    for record in records:
        scenario_type = str(record["scenario_type"])
        if scenario_type not in seen_scenarios:
            selected.append(record)
            seen_scenarios.add(scenario_type)
        if len(selected) == 10:
            break
    selected.append(
        next(
            record
            for record in records
            if record["failure_reason"] in {"network_error", "timeout", "bank_error"}
            and int(record["amount"]) <= 500_000
        )
    )
    return selected


def _event_from_record(record: dict[str, object], index: int) -> RecoveryEvent:
    payment_id = str(record["payment_id"])
    failed_at = datetime.fromisoformat(str(record["failed_at"]))
    timestamp = failed_at + timedelta(hours=int(record["time_since_failure_hours"]))
    payment = PaymentRiskInput(
        **{field: record[field] for field in PaymentRiskInput.model_fields}
    )
    customer = CustomerRiskContext(
        **{field: record[field] for field in CustomerRiskContext.model_fields}
    )
    return RecoveryEvent(
        event_id=f"synthetic-{index}-{payment_id}",
        payment_id=payment_id,
        event_type="payment_failed",
        timestamp=timestamp,
        source="synthetic-dataset",
        payment=payment,
        customer=customer,
        recovery_attempt_count=int(record["recovery_attempt_count"]),
    )


def _cleanup_records(event_ids: list[str], payment_ids: list[str]) -> None:
    with SessionLocal() as session:
        attempts = session.scalars(
            select(RecoveryAttempt).where(RecoveryAttempt.event_id.in_(event_ids))
        ).all()
        for attempt in attempts:
            session.delete(attempt)
        session.flush()

        payments = session.scalars(
            select(Payment).where(Payment.razorpay_payment_id.in_(payment_ids))
        ).all()
        customer_ids = {payment.customer_id for payment in payments}
        for payment in payments:
            session.delete(payment)
        session.flush()

        customers = session.scalars(
            select(Customer).where(Customer.id.in_(customer_ids))
        ).all()
        for customer in customers:
            session.delete(customer)
        session.commit()


@pytest.fixture(autouse=True)
def synthetic_workflow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    records = _selected_records()
    events = [_event_from_record(record, index) for index, record in enumerate(records)]
    event_ids = [event.event_id for event in events if event.event_id is not None]
    payment_ids = [event.payment_id for event in events]
    _cleanup_records(event_ids, payment_ids)
    monkeypatch.setattr(
        config,
        "settings",
        Settings(database_url="postgresql://test", reclaim_workflow_secret=SECRET),
    )
    monkeypatch.setattr(workflow_service, "_action_executor", DryRunActionExecutor())
    workflow_service._payment_client = None
    workflow_service.clear_idempotency()
    yield
    workflow_service.clear_idempotency()
    _cleanup_records(event_ids, payment_ids)


def test_sample_dataset_records_process_through_recovery_route() -> None:
    records = _selected_records()
    client = TestClient(app)
    first_event: RecoveryEvent | None = None

    for index, (record, expected_action) in enumerate(zip(records, EXPECTED_ACTIONS)):
        event = _event_from_record(record, index)
        if first_event is None:
            first_event = event
        response = client.post(
            "/api/workflows/recovery",
            headers={"X-Reclaim-Workflow-Secret": SECRET},
            json=event.model_dump(mode="json"),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["duplicate"] is False
        assert body["event_id"] == event.event_id
        assert body["payment_id"] == event.payment_id
        assert body["risk_score"] >= 0
        assert body["action"] == expected_action
        assert body["validation_status"] in {"VALID", "OVERRIDDEN"}
        assert body["result"]["mode"] == "dry_run"
        assert body["result"]["execution_mode"] == "dry_run"
        assert body["result"]["provider_called"] is False
        assert body["result"]["execution_succeeded"] is True

        with SessionLocal() as session:
            attempt = session.scalar(
                select(RecoveryAttempt).where(RecoveryAttempt.event_id == event.event_id)
            )
            assert attempt is not None
            assert attempt.action == expected_action
            assert attempt.payment.razorpay_payment_id == event.payment_id
            assert attempt.execution_mode == "dry_run"
            assert attempt.provider_called is False
            assert attempt.execution_succeeded is True

    assert first_event is not None
    duplicate = client.post(
        "/api/workflows/recovery",
        headers={"X-Reclaim-Workflow-Secret": SECRET},
        json=first_event.model_dump(mode="json"),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
