"""Strict request and response schemas for n8n recovery orchestration."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.recovery_decision import ValidatedRecoveryDecision
from app.schemas.revenue_risk import CustomerRiskContext, PaymentRiskInput


class RecoveryEvent(BaseModel):
    """An authenticated event submitted by an external workflow orchestrator."""

    model_config = ConfigDict(extra="forbid")

    event_id: str | None = Field(default=None, min_length=1, max_length=255)
    payment_id: str = Field(min_length=1, max_length=255)
    event_type: Literal["payment_failed", "recovery_requested"]
    timestamp: datetime
    source: str = Field(min_length=1, max_length=100)
    payment: PaymentRiskInput | None = None
    customer: CustomerRiskContext | None = None
    recovery_attempt_count: int = Field(default=0, ge=0)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Require an unambiguous event time for risk evaluation."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class RecoveryActionResult(BaseModel):
    """The safe dry-run result routed by n8n."""

    model_config = ConfigDict(extra="forbid")

    payment_id: str
    action: Literal["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"]
    mode: Literal["dry_run"] = "dry_run"
    status: Literal["queued", "terminal"]
    message: str


class RecoveryWorkflowResponse(BaseModel):
    """Predictable decision and dry-run result returned to n8n."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    duplicate: bool = False
    payment_id: str
    risk_score: int = Field(ge=0, le=100)
    eligible: bool
    requires_approval: bool
    action: Literal["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"]
    confidence: float = Field(ge=0.0, le=1.0)
    validation_status: Literal["VALID", "OVERRIDDEN", "FAILED"]
    priority: Literal["LOW", "MEDIUM", "HIGH"]
    decision: ValidatedRecoveryDecision
    result: RecoveryActionResult

    @classmethod
    def from_decision(
        cls,
        event_id: str,
        decision: ValidatedRecoveryDecision,
        result: RecoveryActionResult,
        *,
        duplicate: bool = False,
    ) -> "RecoveryWorkflowResponse":
        """Flatten key decision fields while retaining the existing validated decision."""
        return cls(
            event_id=event_id,
            duplicate=duplicate,
            payment_id=decision.payment_id,
            risk_score=decision.risk_score,
            eligible=decision.recovery_eligible,
            requires_approval=decision.requires_approval,
            action=decision.action,
            confidence=decision.confidence,
            validation_status=decision.validation_status,
            priority=decision.priority,
            decision=decision,
            result=result,
        )
