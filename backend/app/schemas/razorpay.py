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


class RazorpayCustomer(BaseModel):
    """Customer fields accepted from or returned by a payment link."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    email: str | None = None
    contact: str | None = None


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


class RazorpayPaymentLink(BaseModel):
    """The provider payment-link subset used by Reclaim."""

    model_config = ConfigDict(extra="forbid")

    id: str
    amount: int = Field(ge=0)
    currency: str
    status: str
    short_url: str | None = None
    description: str | None = None
    customer: RazorpayCustomer | None = None