"""Authenticated entry points for provider-state reconciliation."""

from typing import Annotated

import hmac
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app import config
from app.services.recovery_reconciliation import RecoveryReconciliationService
from app.services.razorpay_client import RazorpayClientError

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


class ReconciliationRequest(BaseModel):
    """Select one payment/attempt or all eligible Payment Links."""

    attempt_id: str | None = Field(default=None, min_length=1, max_length=255)
    payment_id: str | None = Field(default=None, min_length=1, max_length=255)


@router.post("/run")
def run_reconciliation(
    request: ReconciliationRequest,
    workflow_secret: Annotated[str | None, Header(alias="X-Reclaim-Workflow-Secret")] = None,
) -> dict[str, object]:
    """Run authenticated one-record or batch provider synchronization."""
    expected_secret = config.settings.reclaim_workflow_secret
    if not expected_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "reconciliation_not_configured", "message": "Reconciliation authentication is not configured."})
    if workflow_secret is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "missing_workflow_secret", "message": "Workflow authentication is required."})
    if not hmac.compare_digest(workflow_secret, expected_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "invalid_workflow_secret", "message": "Workflow authentication failed."})
    if request.attempt_id and request.payment_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "ambiguous_reconciliation_target", "message": "Provide attempt_id, payment_id, or neither for batch reconciliation."})

    try:
        service = RecoveryReconciliationService(configured=config.settings)
        if request.attempt_id:
            results = [service.reconcile_attempt(request.attempt_id)]
        elif request.payment_id:
            results = service.reconcile_payment(request.payment_id)
        else:
            results = service.reconcile_eligible()
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "reconciliation_target_not_found", "message": str(error)}) from error
    except RazorpayClientError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "provider_unavailable", "message": str(error)}) from error

    return {"status": "completed", "results": [result.__dict__ for result in results]}
