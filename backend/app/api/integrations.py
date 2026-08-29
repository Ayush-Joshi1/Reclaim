"""Razorpay integration endpoints for read-only lookup and webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.models import Customer, Payment, ProviderWebhookReceipt, RecoveryAttempt
from app.schemas.razorpay import RazorpayWebhookEvent

router = APIRouter(prefix="/api/integrations/razorpay", tags=["razorpay"])

SUPPORTED_PROVIDER_EVENTS: dict[str, str] = {
    "payment.failed": "failed",
    "payment.authorized": "authorized",
    "payment.captured": "captured",
    "payment_link.paid": "successful",
}


def _receipt_key(event_type: str, payment_id: str) -> str:
    return f"{event_type}:{payment_id}"


def _record_receipt(
    session: Session,
    *,
    event_type: str,
    payment_id: str,
    processed: bool,
) -> ProviderWebhookReceipt:
    receipt = ProviderWebhookReceipt(
        provider="razorpay",
        provider_event_id=_receipt_key(event_type, payment_id),
        event_type=event_type,
        processed=processed,
        processed_at=None if not processed else datetime.now(UTC),
    )
    session.add(receipt)
    return receipt


def _payload_payment_entity(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None

    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="python")

    if not isinstance(payload, dict):
        return None

    payment = payload.get("payment")
    if hasattr(payment, "model_dump"):
        payment = payment.model_dump(mode="python")

    if not isinstance(payment, dict):
        return None

    entity = payment.get("entity")
    if hasattr(entity, "model_dump"):
        entity = entity.model_dump(mode="python")

    if not isinstance(entity, dict):
        return None

    return entity


def _payload_payment_link_entity(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None

    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="python")

    if not isinstance(payload, dict):
        return None

    payment_link = payload.get("payment_link")
    if hasattr(payment_link, "model_dump"):
        payment_link = payment_link.model_dump(mode="python")

    if not isinstance(payment_link, dict):
        return None

    entity = payment_link.get("entity")
    if hasattr(entity, "model_dump"):
        entity = entity.model_dump(mode="python")

    if not isinstance(entity, dict):
        return None

    return entity


@router.post("/webhook")
async def razorpay_webhook(request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Verify and process Razorpay webhook events without triggering real recovery actions."""
    secret = config.settings.razorpay_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "webhook_secret_not_configured",
                "message": "Razorpay webhook secret is not configured.",
            },
        )

    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    if signature is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "missing_webhook_signature",
                "message": "X-Razorpay-Signature header is required.",
            },
        )

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invalid_webhook_signature",
                "message": "Webhook signature verification failed.",
            },
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "malformed_webhook_payload",
                "message": "Webhook payload is not valid JSON.",
            },
        ) from error

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "malformed_webhook_payload",
                "message": "Webhook payload must be a JSON object.",
            },
        )

    try:
        event = RazorpayWebhookEvent.model_validate(payload)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_webhook_payload",
                "message": "Webhook payload does not match the expected schema.",
            },
        ) from error

    payment_entity = _payload_payment_entity(event.payload)
    payment_link_entity = _payload_payment_link_entity(event.payload)
    payment_id = str(payment_entity.get("id")) if payment_entity and payment_entity.get("id") is not None else ""
    payment_link_id = (
        str(payment_link_entity.get("id"))
        if payment_link_entity and payment_link_entity.get("id") is not None
        else ""
    )
    event_type = event.event

    if not payment_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_webhook_payload",
                "message": "Webhook payment identifier is missing.",
            },
        )

    provider_event_id = _receipt_key(
        event_type,
        payment_link_id if event_type == "payment_link.paid" and payment_link_id else payment_id,
    )
    existing_receipt = session.scalar(
        select(ProviderWebhookReceipt).where(
            ProviderWebhookReceipt.provider == "razorpay",
            ProviderWebhookReceipt.provider_event_id == provider_event_id,
        )
    )
    normalized_status = SUPPORTED_PROVIDER_EVENTS.get(event_type)

    if existing_receipt is not None and normalized_status is not None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "duplicate",
                "payment_id": payment_id,
                "event_type": event_type,
                "duplicate": True,
            },
        )

    if normalized_status is None:
        if existing_receipt is not None:
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "ignored",
                    "payment_id": payment_id,
                    "event_type": event_type,
                    "duplicate": False,
                },
            )
        receipt = _record_receipt(
            session,
            event_type=event_type,
            payment_id=payment_id,
            processed=False,
        )
        session.add(receipt)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "ignored",
                    "payment_id": payment_id,
                    "event_type": event_type,
                    "duplicate": False,
                },
            )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "ignored",
                "payment_id": payment_id,
                "event_type": event_type,
                "duplicate": False,
            },
        )

    if event_type == "payment_link.paid":
        link_reference_id = (
            str(payment_link_entity.get("reference_id"))
            if payment_link_entity and payment_link_entity.get("reference_id") is not None
            else None
        )
        related_payment = None
        if link_reference_id:
            related_payment = session.scalar(
                select(Payment).where(Payment.razorpay_payment_id == link_reference_id)
            )
        if related_payment is None:
            receipt = _record_receipt(
                session,
                event_type=event_type,
                payment_id=payment_id,
                processed=False,
            )
            session.add(receipt)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "unknown_payment_link",
                    "payment_id": payment_id,
                    "event_type": event_type,
                    "duplicate": False,
                },
            )

        attempt = session.scalar(
            select(RecoveryAttempt)
            .where(RecoveryAttempt.payment_id == related_payment.id)
            .order_by(desc(RecoveryAttempt.created_at))
        )
        if attempt is None:
            receipt = _record_receipt(
                session,
                event_type=event_type,
                payment_id=payment_id,
                processed=False,
            )
            session.add(receipt)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "unknown_payment_link",
                    "payment_id": payment_id,
                    "event_type": event_type,
                    "duplicate": False,
                },
            )

        if attempt.recovery_state in {"recovered", "stopped", "duplicate", "ignored"}:
            receipt = _record_receipt(
                session,
                event_type=event_type,
                payment_id=payment_id,
                processed=True,
            )
            session.add(receipt)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
            return {
                "status": "already_recovered" if attempt.recovery_state == "recovered" else "state_protected",
                "payment_id": related_payment.razorpay_payment_id,
                "event_type": event_type,
                "normalized_status": normalized_status,
                "duplicate": False,
            }

        related_payment.status = normalized_status
        related_payment.recovery_state = "recovered"
        related_payment.state_updated_at = datetime.now(UTC)
        related_payment.failure_reason = None

        attempt.provider_payment_id = payment_id
        attempt.provider_payment_link_id = payment_link_id or attempt.provider_payment_link_id
        attempt.provider_reference_id = link_reference_id or attempt.provider_reference_id
        attempt.execution_succeeded = True
        attempt.recovery_state = "recovered"
        attempt.status = "queued"
        attempt.state_reason = "Payment link payment confirmation received from Razorpay."
        attempt.completed_at = datetime.now(UTC)

        receipt = _record_receipt(
            session,
            event_type=event_type,
            payment_id=payment_id,
            processed=True,
        )
        session.add(receipt)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return {
                "status": "duplicate",
                "payment_id": related_payment.razorpay_payment_id,
                "event_type": event_type,
                "duplicate": True,
            }

        return {
            "status": "processed",
            "payment_id": related_payment.razorpay_payment_id,
            "event_type": event_type,
            "normalized_status": normalized_status,
            "duplicate": False,
            "recovery_state": "recovered",
        }

    payment = session.scalar(select(Payment).where(Payment.razorpay_payment_id == payment_id))
    if payment is None:
        customer = Customer(
            name=f"Webhook customer {payment_id}",
            email=f"{payment_id}@reclaim.invalid",
        )
        session.add(customer)
        session.flush()
        payment = Payment(
            razorpay_payment_id=payment_id,
            customer_id=customer.id,
            amount=int(payment_entity.get("amount") or 0),
            currency=str(payment_entity.get("currency") or "INR").upper(),
            status=normalized_status,
            failure_reason=(
                str(payment_entity.get("error_description"))
                if payment_entity.get("error_description") is not None
                else None
            ),
        )
        session.add(payment)
    else:
        if payment.recovery_state in {"recovered", "stopped"} and normalized_status != "successful":
            receipt = _record_receipt(
                session,
                event_type=event_type,
                payment_id=payment_id,
                processed=True,
            )
            session.add(receipt)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return {
                    "status": "duplicate",
                    "payment_id": payment_id,
                    "event_type": event_type,
                    "duplicate": True,
                }
            return {
                "status": "state_protected",
                "payment_id": payment_id,
                "event_type": event_type,
                "normalized_status": normalized_status,
                "duplicate": False,
            }
        payment.status = normalized_status
        if payment_entity.get("amount") is not None:
            payment.amount = int(payment_entity["amount"])
        if payment_entity.get("currency") is not None:
            payment.currency = str(payment_entity["currency"]).upper()
        if event_type == "payment.failed" and payment_entity.get("error_description") is not None:
            payment.failure_reason = str(payment_entity.get("error_description"))
        elif event_type != "payment.failed":
            payment.failure_reason = None

    receipt = _record_receipt(
        session,
        event_type=event_type,
        payment_id=payment_id,
        processed=True,
    )
    session.add(receipt)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return {
            "status": "duplicate",
            "payment_id": payment_id,
            "event_type": event_type,
            "duplicate": True,
        }

    return {
        "status": "processed",
        "payment_id": payment_id,
        "event_type": event_type,
        "normalized_status": normalized_status,
        "duplicate": False,
    }
