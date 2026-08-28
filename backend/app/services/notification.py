"""Provider-independent customer communication boundary."""

from datetime import UTC, datetime
from typing import Protocol

from app.schemas.notification import NotificationRequest, NotificationResult


class NotificationProvider(Protocol):
    def send(self, request: NotificationRequest) -> NotificationResult:
        """Produce or send a notification through a provider."""


class DryRunNotificationProvider:
    """Deterministic provider that never sends a customer message."""

    def send(self, request: NotificationRequest) -> NotificationResult:
        return NotificationResult(
            success=True,
            channel=request.channel,
            payment_id=request.payment_id,
            recipient=request.recipient,
            message=request.message,
            created_at=datetime.now(UTC),
        )


class NotificationService:
    """Apply communication safety rules before delegating to a provider."""

    def __init__(self, provider: NotificationProvider | None = None) -> None:
        self._provider = provider or DryRunNotificationProvider()

    def send_reminder(
        self,
        *,
        payment_id: str,
        recipient: str,
        event_id: str,
        eligible: bool,
        requires_approval: bool,
        duplicate: bool,
        attempt_count: int,
        max_notifications: int,
    ) -> NotificationResult | None:
        if (
            duplicate
            or not eligible
            or requires_approval
            or attempt_count >= max_notifications
        ):
            return None
        try:
            return self._provider.send(
                NotificationRequest(
                    channel="email",
                    recipient=recipient,
                    payment_id=payment_id,
                    action="REMINDER",
                    message=f"A payment reminder would be sent for {payment_id}.",
                    event_id=event_id,
                )
            )
        except Exception:
            return NotificationResult(
                success=False,
                channel="email",
                payment_id=payment_id,
                recipient=recipient,
                message="Notification provider failed; no customer message was sent.",
                created_at=datetime.now(UTC),
            )