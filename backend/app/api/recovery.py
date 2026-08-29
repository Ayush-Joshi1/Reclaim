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
            recovery_state=record.recovery_state,
            state_reason=record.state_reason,
            risk_score=record.risk_score,
            risk_level=record.risk_level,
            eligibility_result=record.eligibility_result,
            eligibility_reason=record.eligibility_reason,
            decision_confidence=record.decision_confidence,
            approval_required=record.approval_required,
            validation_status=record.validation_status,
            policy_override_reason=record.policy_override_reason,
            decision_diagnosis=record.decision_diagnosis,
            decision_reasoning=record.decision_reasoning,
            policy_constraints=record.policy_constraints,
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

    payment_rows = session.scalars(select(Payment)).all()
    failed_payment_amounts = [
        payment.amount for payment in payment_rows if (payment.status or "").lower() in {"failed", "payment_failed", "declined"}
    ]
    payments_analyzed = len({record.payment_id for record in records})
    total_evaluations = len(records)
    total_successful_executions = sum(record.execution_succeeded for record in records)
    total_failed_executions = sum(not record.execution_succeeded for record in records)
    revenue_at_risk = sum(failed_payment_amounts)
    successfully_recovered = [
        record for record in records
        if record.recovery_state == "recovered"
    ]
    revenue_recovered = sum(record.amount for record in successfully_recovered)
    recovered_count = len(successfully_recovered)
    interventions = total_evaluations
    recovery_rate = (recovered_count / total_evaluations * 100.0) if total_evaluations else 0.0
    intervention_rate = (interventions / payments_analyzed * 100.0) if payments_analyzed else 0.0
    success_rate = (recovered_count / total_evaluations * 100.0) if total_evaluations else 0.0
    escalation_rate = (action_counts["ESCALATE"] / total_evaluations * 100.0) if total_evaluations else 0.0
    stop_rate = (action_counts["STOP"] / total_evaluations * 100.0) if total_evaluations else 0.0
    average_recovered_amount = (revenue_recovered / recovered_count) if recovered_count else 0.0
    if recovered_count == 0:
        revenue_recovered = 0
        recovered_count = 0
        average_recovered_amount = 0.0

    return RecoverySummary(
        total_evaluations=total_evaluations,
        total_successful_executions=total_successful_executions,
        total_failed_executions=total_failed_executions,
        total_dry_run_executions=sum(record.execution_mode == "dry_run" for record in records),
        payments_analyzed=payments_analyzed,
        revenue_at_risk=revenue_at_risk,
        total_revenue_at_risk=revenue_at_risk,
        revenue_recovered=revenue_recovered,
        total_recovered=revenue_recovered if revenue_recovered is not None else 0,
        recovery_rate=round(recovery_rate, 2),
        average_recovered_amount=round(average_recovered_amount, 2),
        interventions=interventions,
        intervention_rate=round(intervention_rate, 2),
        success_rate=round(success_rate, 2),
        recovered_count=recovered_count,
        escalation_rate=round(escalation_rate, 2),
        stop_rate=round(stop_rate, 2),
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