"""Normalized schemas for the Razorpay resources used by Reclaim."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RazorpayErrorInfo(BaseModel):
    """Provider error details useful for recovery diagnostics."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = None
    description: str | None = None
    source: str | None = None
    step: str | None = None
    reason: str | None = None


class RazorpayPayment(BaseModel):
    """The provider payment subset used by Reclaim."""

    model_config = ConfigDict(extra="forbid")

    id: str
    order_id: str | None = None
    amount: int = Field(ge=0)
    currency: str
    status: str
    method: str | None = None
    captured: bool | None = None
    error: RazorpayErrorInfo | None = None
    created_at: datetime | None = None