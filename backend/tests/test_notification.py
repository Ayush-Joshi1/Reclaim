"""Tests for provider-independent dry-run notifications."""

from datetime import UTC

from app.schemas.notification import NotificationRequest
from app.services.notification import DryRunNotificationProvider, NotificationService


def request() -> NotificationRequest:
    return NotificationRequest(
        channel="email",
        recipient="customer@example.invalid",
        payment_id="pay-notification-test",
        action="REMINDER",
        message="A payment reminder would be sent.",
        event_id="evt-notification-test",
    )


def test_dry_run_notification_returns_safe_typed_result() -> None:
    result = DryRunNotificationProvider().send(request())

    assert result.success is True
    assert result.mode == "dry_run"
    assert result.channel == "email"
    assert result.payment_id == "pay-notification-test"
    assert result.recipient == "customer@example.invalid"
    assert result.provider_called is False
    assert result.created_at.tzinfo is UTC
    assert "secret" not in result.model_dump_json().lower()


def test_notification_policy_blocks_stop_like_conditions() -> None:
    service = NotificationService()

    assert service.send_reminder(
        payment_id="pay-1", recipient="customer-1", event_id="evt-1",
        eligible=False, requires_approval=False, duplicate=False,
        attempt_count=0, max_notifications=2,
    ) is None
    assert service.send_reminder(
        payment_id="pay-1", recipient="customer-1", event_id="evt-1",
        eligible=True, requires_approval=True, duplicate=False,
        attempt_count=0, max_notifications=2,
    ) is None
    assert service.send_reminder(
        payment_id="pay-1", recipient="customer-1", event_id="evt-1",
        eligible=True, requires_approval=False, duplicate=True,
        attempt_count=0, max_notifications=2,
    ) is None
    assert service.send_reminder(
        payment_id="pay-1", recipient="customer-1", event_id="evt-1",
        eligible=True, requires_approval=False, duplicate=False,
        attempt_count=2, max_notifications=2,
    ) is None


def test_notification_provider_failure_is_safe() -> None:
    class FailingProvider:
        def send(self, notification_request: NotificationRequest):
            raise RuntimeError("provider secret must not leak")

    result = NotificationService(FailingProvider()).send_reminder(
        payment_id="pay-1", recipient="customer-1", event_id="evt-1",
        eligible=True, requires_approval=False, duplicate=False,
        attempt_count=0, max_notifications=2,
    )

    assert result is not None
    assert result.success is False
    assert result.mode == "dry_run"
    assert "secret" not in result.model_dump_json().lower()
