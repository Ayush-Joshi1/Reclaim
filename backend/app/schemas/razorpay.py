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


class RazorpayPaymentLink(BaseModel):
    """Safe subset returned after creating a Payment Link."""

    model_config = ConfigDict(extra="forbid")

    id: str
    amount: int = Field(ge=0)
    currency: str
    status: str
    short_url: str
    reference_id: str | None = None


class RazorpayWebhookPaymentEntity(BaseModel):
    """The nested payment entity included in Razorpay webhook payloads."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    amount: int | None = None
    currency: str | None = None
    status: str | None = None
    method: str | None = None
    captured: bool | None = None
    order_id: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    created_at: datetime | None = None


class RazorpayWebhookPayment(BaseModel):
    """Envelope carrying the provider payment payload."""

    model_config = ConfigDict(extra="ignore")

    entity: RazorpayWebhookPaymentEntity


class RazorpayWebhookPaymentLinkEntity(BaseModel):
    """Nested payment-link entity included in a payment_link.paid webhook."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    amount: int | None = None
    currency: str | None = None
    status: str | None = None
    reference_id: str | None = None


class RazorpayWebhookPaymentLink(BaseModel):
    """Envelope carrying the provider payment-link payload."""

    model_config = ConfigDict(extra="ignore")

    entity: RazorpayWebhookPaymentLinkEntity


class RazorpayWebhookPayload(BaseModel):
    """Top-level event payload sent by Razorpay."""

    model_config = ConfigDict(extra="ignore")

    payment: RazorpayWebhookPayment
    payment_link: RazorpayWebhookPaymentLink | None = None


class RazorpayWebhookEvent(BaseModel):
    """A normalized Razorpay webhook event processed by Reclaim."""

    model_config = ConfigDict(extra="ignore")

    event: str
    payload: RazorpayWebhookPayload
    created_at: int | datetime | None = None