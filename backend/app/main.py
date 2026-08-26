"""FastAPI application entrypoint."""

import logging

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import DatabaseHealthResponse, ServiceHealthResponse
from app.schemas import RazorpayPayment
from app.services.razorpay_client import RazorpayClient, RazorpayClientError

logger = logging.getLogger(__name__)

app = FastAPI(title="Reclaim API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=ServiceHealthResponse)
def health_check() -> ServiceHealthResponse:
    """Return the API availability status."""
    return ServiceHealthResponse(status="ok", service=settings.app_name)


@app.get("/health/db", response_model=DatabaseHealthResponse)
def database_health_check(session: Session = Depends(get_db)) -> DatabaseHealthResponse:
    """Verify that the configured database accepts a lightweight query."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is unavailable.",
        ) from error

    return DatabaseHealthResponse(status="ok", database="connected")


def get_razorpay_client() -> RazorpayClient:
    """Build the provider adapter only when the integration is requested."""
    try:
        return RazorpayClient.from_settings()
    except RazorpayClientError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay integration is not configured.",
        ) from error


@app.get("/api/integrations/razorpay/payments/{payment_id}", response_model=RazorpayPayment)
def razorpay_payment(
    payment_id: str, client: RazorpayClient = Depends(get_razorpay_client)
) -> RazorpayPayment:
    """Return one normalized Razorpay payment without executing any payment."""
    try:
        return client.fetch_payment(payment_id)
    except RazorpayClientError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
