"""Typed notification requests and safe provider results."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NotificationChannel = Literal["email", "sms", "whatsapp"]


class NotificationRequest(BaseModel):
    channel: NotificationChannel
    recipient: str
    payment_id: str
    action: Literal["REMINDER"]
    message: str = Field(min_length=1, max_length=2000)
    event_id: str


class NotificationResult(BaseModel):
    success: bool
    mode: Literal["dry_run"] = "dry_run"
    channel: NotificationChannel
    payment_id: str
    recipient: str
    message: str
    provider_called: bool = False
    created_at: datetime