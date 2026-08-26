"""Strict schemas for LLM recovery recommendations and guarded results."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.revenue_risk import (
    CustomerRiskContext,
    MerchantPolicy,
    PaymentRiskInput,
    RecoveryHistory,
)

AllowedRecoveryAction = Literal["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"]
DecisionPriority = Literal["LOW", "MEDIUM", "HIGH"]
ValidationStatus = Literal["VALID", "OVERRIDDEN", "FAILED"]


class RecoveryRiskContext(BaseModel):
    """Deterministic risk output supplied as evidence to the LLM."""

    model_config = ConfigDict(extra="forbid")

    risk_score: int = Field(ge=0, le=100)
    revenue_at_risk: int = Field(ge=0)
    recovery_eligible: bool
    auto_action_eligible: bool
    requires_approval: bool
    urgency: DecisionPriority
    risk_factors: list[str]
    eligibility_reasons: list[str]


class RecoveryContext(BaseModel):
    """Complete evidence package used for an LLM recovery recommendation."""

    model_config = ConfigDict(extra="forbid")

    payment: PaymentRiskInput
    customer: CustomerRiskContext
    recovery_history: RecoveryHistory
    risk: RecoveryRiskContext
    merchant_policy: MerchantPolicy


class RecoveryDecision(BaseModel):
    """Strict, constrained recommendation returned by an LLM provider."""

    model_config = ConfigDict(extra="forbid")

    action: AllowedRecoveryAction
    diagnosis: str = Field(min_length=1, max_length=400)
    reasoning: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    priority: DecisionPriority
    policy_constraints: list[str] = Field(default_factory=list)
    expected_outcome: str = Field(min_length=1, max_length=400)


class ValidatedRecoveryDecision(RecoveryDecision):
    """A recommendation enriched with immutable policy-validation audit details."""

    payment_id: str
    risk_score: int = Field(ge=0, le=100)
    recovery_eligible: bool
    validation_status: ValidationStatus
    validation_notes: list[str]
    decided_at: datetime
