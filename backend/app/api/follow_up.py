"""Authenticated entry point for persistent recovery follow-ups."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app import config
from app.services.recovery_follow_up import RecoveryFollowUpService
from app.services.razorpay_client import RazorpayClientError

router = APIRouter(prefix="/api/recovery", tags=["recovery-follow-up"])


class FollowUpRequest(BaseModel):
    """Select one attempt, one payment, or a bounded batch."""

    attempt_id: str | None = Field(default=None, min_length=1, max_length=255)
    payment_id: str | None = Field(default=None, min_length=1, max_length=255)
    limit: int = Field(default=20, ge=1, le=100)


@router.post("/follow-up")
def recovery_follow_up(
    request: FollowUpRequest,
    workflow_secret: Annotated[str | None, Header(alias="X-Reclaim-Workflow-Secret")] = None,
) -> dict[str, object]:
    """Process authenticated pending recovery follow-ups."""
    expected_secret = config.settings.reclaim_workflow_secret
    if not expected_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "follow_up_not_configured", "message": "Follow-up authentication is not configured."})
    if workflow_secret is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "missing_workflow_secret", "message": "Workflow authentication is required."})
    if not hmac.compare_digest(workflow_secret, expected_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "invalid_workflow_secret", "message": "Workflow authentication failed."})
    if request.attempt_id and request.payment_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "ambiguous_follow_up_target", "message": "Provide attempt_id, payment_id, or neither for batch processing."})

    try:
        service = RecoveryFollowUpService(configured=config.settings)
        if request.attempt_id:
            result = service.process_attempt(request.attempt_id)
            summary = {
                "processed_count": int(result.status != "skipped"),
                "recovered_count": int(result.status == "recovered"),
                "retried_count": int(result.status == "retried"),
                "stopped_count": int(result.status == "stopped"),
                "skipped_count": int(result.status == "skipped"),
                "failure_count": int(result.status == "failed"),
                "results": [result.__dict__],
            }
        elif request.payment_id:
            results = service.process_payment(request.payment_id)
            summary = _summary(results)
        else:
            batch = service.process_pending(request.limit)
            summary = batch.__dict__
            summary["results"] = [result.__dict__ for result in batch.results]
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "follow_up_target_not_found", "message": str(error)}) from error
    except RazorpayClientError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "provider_unavailable", "message": str(error)}) from error

    return {"status": "completed", **summary}


def _summary(results: list[object]) -> dict[str, object]:
    return {
        "processed_count": sum(getattr(result, "status") != "skipped" for result in results),
        "recovered_count": sum(getattr(result, "status") == "recovered" for result in results),
        "retried_count": sum(getattr(result, "status") == "retried" for result in results),
        "stopped_count": sum(getattr(result, "status") == "stopped" for result in results),
        "skipped_count": sum(getattr(result, "status") == "skipped" for result in results),
        "failure_count": sum(getattr(result, "status") == "failed" for result in results),
        "results": [result.__dict__ for result in results],
    }
