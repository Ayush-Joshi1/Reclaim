"""Safe action-execution boundary for validated recovery decisions."""

import logging
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from app.schemas.recovery_decision import ValidatedRecoveryDecision
from app.schemas.workflow import RecoveryActionResult
from app.config import Settings, settings
from app.services.razorpay_client import RazorpayClient, RazorpayClientError
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)


def convert_inr_to_paise(amount_inr: int | float | Decimal) -> int:
    """
    Safely convert INR amount to paise (smallest currency unit) for Razorpay.

    Razorpay API expects amounts in the smallest unit: paise for INR.
    1 INR = 100 paise

    Args:
        amount_inr: Amount in INR (normal representation, e.g., 121 for Ã¢â€šÂ¹121.00)

    Returns:
        Amount in paise as integer (e.g., 12100 for Ã¢â€šÂ¹121.00)

    Examples:
        121 -> 12100 (Ã¢â€šÂ¹121.00)
        121.50 -> 12150 (Ã¢â€šÂ¹121.50)
        999.99 -> 99999 (Ã¢â€šÂ¹999.99)
    """
    amount_decimal = Decimal(str(amount_inr))
    amount_paise_decimal = amount_decimal * Decimal("100")
    amount_paise = int(
        amount_paise_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return amount_paise


class ActionExecutor(Protocol):
    """Provider boundary for future recovery action adapters."""

    def execute(
        self,
        decision: ValidatedRecoveryDecision,
        *,
        duplicate: bool = False,
        amount: int | None = None,
        currency: str = "INR",
        event_id: str | None = None,
        recipient: str | None = None,
        recovery_attempt_count: int = 0,
        max_customer_notifications: int = 0,
    ) -> RecoveryActionResult:
        """Return an action result without bypassing policy validation."""


class DryRunActionExecutor:
    """Return safe action intents without calling external providers."""

    def __init__(self, notification_service: NotificationService | None = None) -> None:
        self._notifications = notification_service or NotificationService()

    def execute(
        self,
        decision: ValidatedRecoveryDecision,
        *,
        duplicate: bool = False,
        amount: int | None = None,
        currency: str = "INR",
        event_id: str | None = None,
        recipient: str | None = None,
        recovery_attempt_count: int = 0,
        max_customer_notifications: int = 0,
    ) -> RecoveryActionResult:
        notification = None
        if decision.action == "REMINDER":
            notification = self._notifications.send_reminder(
                payment_id=decision.payment_id,
                recipient=recipient or decision.payment_id,
                event_id=event_id or "unidentified-event",
                eligible=decision.recovery_eligible,
                requires_approval=decision.requires_approval,
                duplicate=duplicate,
                attempt_count=recovery_attempt_count,
                max_notifications=max_customer_notifications,
            )
        if duplicate:
            message = "Duplicate recovery event; no external action was performed."
        elif decision.action == "STOP":
            message = "Recovery is stopped; no external action was requested."
        elif not decision.recovery_eligible:
            message = "Recovery is ineligible; no external action was performed."
        elif decision.requires_approval:
            message = "Merchant approval is required; no external action was performed."
        elif decision.action == "REMINDER" and notification is None:
            message = "Reminder was blocked by recovery policy; no notification was sent."
        elif decision.action == "REMINDER" and not notification.success:
            message = notification.message
        else:
            message = {
                "RETRY": "A payment retry would be requested; no payment operation was performed.",
                "PAYMENT_LINK": "A payment link would be requested; no link was created or sent.",
                "REMINDER": "A customer reminder would be requested; no notification was sent.",
                "ESCALATE": "Merchant escalation would be requested for review.",
            }[decision.action]
        return RecoveryActionResult(
            payment_id=decision.payment_id,
            action=decision.action,
            status="terminal" if decision.action == "STOP" else "queued",
            message=message,
            event_id=event_id,
            executed_at=datetime.now(UTC),
            execution_succeeded=notification.success if notification is not None else True,
            notification_generated=notification is not None and notification.success,
        )


class RazorpayActionExecutor:
    """Opt-in Test Mode adapter for the one supported provider action."""

    def __init__(self, client: RazorpayClient | None, enabled: bool = False) -> None:
        self._client = client
        self._enabled = enabled
        self._dry_run = DryRunActionExecutor()

    def execute(
        self,
        decision: ValidatedRecoveryDecision,
        *,
        duplicate: bool = False,
        amount: int | None = None,
        currency: str = "INR",
        event_id: str | None = None,
        recipient: str | None = None,
        recovery_attempt_count: int = 0,
        max_customer_notifications: int = 0,
    ) -> RecoveryActionResult:
        if duplicate or decision.action in {"RETRY", "REMINDER", "ESCALATE", "STOP"}:
            return self._dry_run.execute(
                decision,
                duplicate=duplicate,
                event_id=event_id,
                recipient=recipient,
                recovery_attempt_count=recovery_attempt_count,
                max_customer_notifications=max_customer_notifications,
            )
        if not decision.recovery_eligible or decision.requires_approval:
            return self._dry_run.execute(decision, event_id=event_id)
        if not self._enabled or self._client is None or amount is None:
            return self._dry_run.execute(decision, event_id=event_id)
        if decision.validation_status not in {"VALID", "OVERRIDDEN"}:
            return self._dry_run.execute(decision, event_id=event_id)
        try:
            # Convert INR amount to paise for Razorpay API
            amount_paise = convert_inr_to_paise(amount)
            link = self._client.create_payment_link(
                amount=amount_paise,
                currency=currency,
                reference_id=decision.payment_id[:40],
                description=f"Recovery payment for {decision.payment_id}",
            )
        except RazorpayClientError as error:
            logger.warning(
                "Razorpay provider failure: %s | status_code=%s | provider_code=%s | response=%s",
                type(error).__name__,
                error.status_code,
                error.provider_code,
                error.response_body,
            )
            return RecoveryActionResult(
                payment_id=decision.payment_id,
                action="PAYMENT_LINK",
                status="terminal",
                message="Payment Link provider failed; no further action was performed.",
                execution_mode="provider",
                provider_called=True,
                execution_succeeded=False,
                event_id=event_id,
                executed_at=datetime.now(UTC),
            )
        return RecoveryActionResult(
            payment_id=decision.payment_id,
            action="PAYMENT_LINK",
            status="queued",
            message=f"Payment Link created in the configured Razorpay environment: {link.short_url}",
            payment_link=link.short_url,  # Structured URL for frontend
            execution_mode="provider",
            provider_called=True,
            provider_payment_link_id=link.id,
            provider_reference_id=decision.payment_id[:40],
            event_id=event_id,
            executed_at=datetime.now(UTC),
        )

    @classmethod
    def from_settings(cls, configured: Settings = settings) -> "RazorpayActionExecutor":
        """Build an executor that is disabled unless explicitly enabled."""
        if not configured.razorpay_actions_enabled or not configured.razorpay_test_mode:
            return cls(client=None, enabled=False)
        try:
            return cls(RazorpayClient.from_settings(configured), enabled=True)
        except RazorpayClientError:
            return cls(client=None, enabled=True)
