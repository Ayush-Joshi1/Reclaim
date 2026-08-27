"""Authenticated endpoints for external workflow orchestration."""

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app import config
from app.schemas.workflow import RecoveryEvent, RecoveryWorkflowResponse
from app.services.recovery_workflow import workflow_service
from app.services.razorpay_client import (
    RazorpayAuthenticationError,
    RazorpayClientError,
    RazorpayNetworkError,
    RazorpayNotFoundError,
    RazorpayUpstreamError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("/recovery", response_model=RecoveryWorkflowResponse)
def recovery_workflow(
    event: RecoveryEvent,
    workflow_secret: Annotated[str | None, Header(alias="X-Reclaim-Workflow-Secret")] = None,
) -> RecoveryWorkflowResponse:
    """Evaluate a recovery event and return a safe dry-run action request."""
    expected_secret = config.settings.reclaim_workflow_secret
    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "workflow_not_configured", "message": "Workflow authentication is not configured."},
        )
    if workflow_secret is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_workflow_secret", "message": "Workflow authentication is required."},
        )
    if not hmac.compare_digest(workflow_secret, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "invalid_workflow_secret", "message": "Workflow authentication failed."},
        )

    try:
        return workflow_service.process(event)
    except RazorpayNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "payment_not_found", "message": str(error)},
        ) from error
    except RazorpayAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "provider_authentication_failed", "message": str(error)},
        ) from error
    except (RazorpayNetworkError, RazorpayUpstreamError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "provider_unavailable", "message": str(error)},
        ) from error
    except RazorpayClientError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "provider_request_failed", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_recovery_event", "message": str(error)},
        ) from error
    except Exception as error:
        logger.exception("Recovery workflow failed for payment_id=%s", event.payment_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "workflow_failed", "message": "Recovery workflow could not be completed."},
        ) from error
