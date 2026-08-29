"""Public schemas for persisted recovery history."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RecoveryHistoryRecord(BaseModel):
    """Safe audit fields for one evaluated recovery attempt."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str | None
    payment_id: str
    action: str
    status: str
    amount: int
    attempt_number: int | None
    created_at: datetime
    completed_at: datetime | None
    execution_mode: str = "dry_run"
    provider_called: bool = False
    execution_succeeded: bool = True
    notification_generated: bool = False
    executed_at: datetime | None = None
    recovery_state: str | None = None
    state_reason: str | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    eligibility_result: bool | None = None
    eligibility_reason: str | None = None
    decision_confidence: float | None = None
    approval_required: bool | None = None
    validation_status: str | None = None
    policy_override_reason: str | None = None
    decision_diagnosis: str | None = None
    decision_reasoning: str | None = None
    policy_constraints: str | None = None