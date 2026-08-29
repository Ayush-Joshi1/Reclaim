"""Typed operational recovery summary response."""

from pydantic import BaseModel


class RecoverySummaryActivity(BaseModel):
    event_id: str | None
    payment_id: str
    action: str
    status: str
    execution_mode: str
    provider_called: bool
    execution_succeeded: bool
    notification_generated: bool
    executed_at: str | None


class RecoverySummary(BaseModel):
    total_evaluations: int
    total_successful_executions: int
    total_failed_executions: int
    total_dry_run_executions: int
    payments_analyzed: int = 0
    revenue_at_risk: int = 0
    total_revenue_at_risk: int = 0
    revenue_recovered: int | None = None
    total_recovered: int = 0
    recovery_rate: float = 0.0
    average_recovered_amount: float = 0.0
    interventions: int = 0
    intervention_rate: float = 0.0
    success_rate: float = 0.0
    recovered_count: int | None = None
    escalation_rate: float = 0.0
    stop_rate: float = 0.0
    action_counts: dict[str, int]
    stop_count: int
    escalate_count: int
    payment_link_count: int
    reminder_count: int
    retry_count: int
    recent_activity: list[RecoverySummaryActivity]