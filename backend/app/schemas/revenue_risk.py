"""Typed inputs and outputs for deterministic revenue-risk evaluation."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MerchantPolicy(BaseModel):
    """Merchant-controlled limits used by the risk engine."""

    max_recovery_attempts: int = Field(default=2, ge=0)
    recovery_window_hours: int = Field(default=48, gt=0)
    auto_action_amount_limit: int = Field(default=500_000, ge=0)
    high_value_threshold: int = Field(default=2_500_000, ge=0)
    max_customer_notifications: int = Field(default=2, ge=0)


class PaymentRiskInput(BaseModel):
    """Failed-payment attributes relevant to recovery evaluation."""

    payment_id: str
    amount: int = Field(ge=0, description="Smallest currency unit, such as paise.")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_method: Literal["upi", "card", "netbanking", "wallet"]
    status: str = "failed"
    failure_reason: str | None = None
    failed_at: datetime
    time_since_failure_hours: int = Field(ge=0)

    @field_validator("failed_at")
    @classmethod
    def failed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject timestamps that do not carry timezone information."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("failed_at must be timezone-aware")
        return value


class CustomerRiskContext(BaseModel):
    """Customer and payment-history facts used by scoring rules."""

    customer_id: str
    customer_age_days: int = Field(ge=0)
    previous_successful_payments: int = Field(ge=0)
    previous_failed_payments: int = Field(ge=0)
    previous_recovery_attempts: int = Field(ge=0)
    customer_lifetime_value: int = Field(ge=0)
    average_previous_payment: int = Field(ge=0)
    recent_payment_frequency: int = Field(ge=0)


class RecoveryHistory(BaseModel):
    """Recovery activity tied to the payment under evaluation."""

    recovery_attempt_count: int = Field(ge=0)


class RevenueRiskResult(BaseModel):
    """Explainable output returned by the deterministic risk engine."""

    risk_score: int = Field(ge=0, le=100)
    revenue_at_risk: int = Field(ge=0)
    recovery_eligible: bool
    auto_action_eligible: bool
    requires_merchant_approval: bool
    should_stop: bool
    urgency: Literal["LOW", "MEDIUM", "HIGH"]
    risk_factors: list[str]
    eligibility_reasons: list[str]
