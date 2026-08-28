"""Read-only recovery history endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Payment, RecoveryAttempt
from app.schemas.recovery_history import RecoveryHistoryRecord
from app.schemas.recovery_summary import RecoverySummary, RecoverySummaryActivity

router = APIRouter(prefix="/api/recovery", tags=["recovery-history"])


@router.get("/history", response_model=list[RecoveryHistoryRecord])
def recovery_history(
    payment_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Session = Depends(get_db),
) -> list[RecoveryHistoryRecord]:
    """Return recent persisted recovery evaluations, optionally for one payment."""
    statement = (
        select(RecoveryAttempt)
        .join(Payment)
        .order_by(desc(RecoveryAttempt.created_at))
        .limit(limit)
    )
    if payment_id is not None:
        statement = statement.where(Payment.razorpay_payment_id == payment_id)
    records = session.scalars(statement).all()
    return [
        RecoveryHistoryRecord(
            event_id=record.event_id,
            payment_id=record.payment.razorpay_payment_id or str(record.payment_id),
            action=record.action,
            status=record.status,
            amount=record.amount,
            attempt_number=record.attempt_number,
            created_at=record.created_at,
            completed_at=record.completed_at,
            execution_mode=record.execution_mode,
            provider_called=record.provider_called,
            execution_succeeded=record.execution_succeeded,
            notification_generated=record.notification_generated,
            executed_at=record.executed_at,
        )
        for record in records
    ]


@router.get("/history/{payment_id}", response_model=list[RecoveryHistoryRecord])
def payment_recovery_history(
    payment_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Session = Depends(get_db),
) -> list[RecoveryHistoryRecord]:
    """Return recent persisted evaluations for one payment identifier."""
    return recovery_history(payment_id=payment_id, limit=limit, session=session)


@router.get("/summary", response_model=RecoverySummary)
def recovery_summary(session: Session = Depends(get_db)) -> RecoverySummary:
    """Return deterministic operational metrics from persisted recovery attempts."""
    records = session.scalars(
        select(RecoveryAttempt).order_by(desc(RecoveryAttempt.created_at))
    ).all()
    action_counts = {action: 0 for action in ("RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP")}
    for record in records:
        action_counts[record.action] = action_counts.get(record.action, 0) + 1
    return RecoverySummary(
        total_evaluations=len(records),
        total_successful_executions=sum(record.execution_succeeded for record in records),
        total_failed_executions=sum(not record.execution_succeeded for record in records),
        total_dry_run_executions=sum(record.execution_mode == "dry_run" for record in records),
        action_counts=action_counts,
        stop_count=action_counts["STOP"],
        escalate_count=action_counts["ESCALATE"],
        payment_link_count=action_counts["PAYMENT_LINK"],
        reminder_count=action_counts["REMINDER"],
        retry_count=action_counts["RETRY"],
        recent_activity=[
            RecoverySummaryActivity(
                event_id=record.event_id,
                payment_id=record.payment.razorpay_payment_id or str(record.payment_id),
                action=record.action,
                status=record.status,
                execution_mode=record.execution_mode,
                provider_called=record.provider_called,
                execution_succeeded=record.execution_succeeded,
                notification_generated=record.notification_generated,
                executed_at=record.executed_at.isoformat() if record.executed_at else None,
            )
            for record in records[:10]
        ],
    )