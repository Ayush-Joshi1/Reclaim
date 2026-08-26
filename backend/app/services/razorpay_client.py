"""Isolated, read-safe HTTP adapter for Razorpay Test Mode."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings, settings
from app.schemas.razorpay import RazorpayCustomer, RazorpayPayment, RazorpayPaymentLink


class RazorpayClientError(RuntimeError):
    """Base class for safe Razorpay integration failures."""


class RazorpayAuthenticationError(RazorpayClientError):
    """Razorpay rejected the configured credentials."""


class RazorpayInvalidRequestError(RazorpayClientError):
    """Razorpay rejected the request parameters."""


class RazorpayNotFoundError(RazorpayClientError):
    """The requested Razorpay resource does not exist."""


class RazorpayRateLimitError(RazorpayClientError):
    """Razorpay rate-limited the request."""


class RazorpayUpstreamError(RazorpayClientError):
    """Razorpay returned a server-side failure."""


class RazorpayNetworkError(RazorpayClientError):
    """The request could not reach Razorpay or timed out."""


class RazorpayMalformedResponseError(RazorpayClientError):
    """Razorpay returned a response outside the supported subset."""


class RazorpayClient:
    """Small synchronous Razorpay adapter with explicit request timeouts."""

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        base_url: str = "https://api.razorpay.com",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not key_id or not key_secret:
            raise RazorpayAuthenticationError("Razorpay credentials are not configured.")
        self._auth = (key_id, key_secret)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_settings(cls, configured: Settings = settings) -> "RazorpayClient":
        """Create a client from environment-backed application settings."""
        return cls(
            key_id=configured.razorpay_key_id,
            key_secret=configured.razorpay_key_secret,
            base_url=configured.razorpay_base_url,
        )

    def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        """Fetch and normalize one payment."""
        return self._parse_payment(self._request("GET", f"/v1/payments/{payment_id}"))

    def fetch_payments(
        self,
        *,
        count: int | None = None,
        skip: int | None = None,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> list[RazorpayPayment]:
        """Fetch and normalize a payment listing."""
        params = {
            key: value
            for key, value in {
                "count": count,
                "skip": skip,
                "from": from_timestamp,
                "to": to_timestamp,
            }.items()
            if value is not None
        }
        payload = self._request("GET", "/v1/payments", params=params)
        items = payload.get("items")
        if not isinstance(items, list):
            raise RazorpayMalformedResponseError("Razorpay returned an invalid payment list.")
        return [self._parse_payment(item) for item in items]

    def create_payment_link(
        self,
        *,
        amount: int,
        currency: str = "INR",
        description: str | None = None,
        customer: RazorpayCustomer | dict[str, str] | None = None,
    ) -> RazorpayPaymentLink:
        """Create and normalize a payment link; this method does not execute a payment."""
        payload: dict[str, Any] = {"amount": amount, "currency": currency}
        if description is not None:
            payload["description"] = description
        if customer is not None:
            payload["customer"] = (
                customer.model_dump(exclude_none=True)
                if isinstance(customer, RazorpayCustomer)
                else customer
            )
        return self._parse_payment_link(self._request("POST", "/v1/payment_links", json=payload))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            with httpx.Client(
                base_url=self._base_url,
                auth=self._auth,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            raise RazorpayNetworkError("Razorpay request timed out.") from error
        except httpx.RequestError as error:
            raise RazorpayNetworkError("Razorpay request could not be completed.") from error

        if response.status_code == 401:
            raise RazorpayAuthenticationError("Razorpay authentication failed.")
        if response.status_code == 400:
            raise RazorpayInvalidRequestError("Razorpay rejected the request.")
        if response.status_code == 404:
            raise RazorpayNotFoundError("Razorpay resource was not found.")
        if response.status_code == 429:
            raise RazorpayRateLimitError("Razorpay rate limit exceeded.")
        if response.status_code >= 500:
            raise RazorpayUpstreamError("Razorpay is temporarily unavailable.")
        if response.is_error:
            raise RazorpayClientError("Razorpay request failed.")
        try:
            payload = response.json()
        except ValueError as error:
            raise RazorpayMalformedResponseError("Razorpay returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise RazorpayMalformedResponseError("Razorpay returned an invalid object.")
        return payload

    @staticmethod
    def _parse_payment(payload: Any) -> RazorpayPayment:
        if not isinstance(payload, dict):
            raise RazorpayMalformedResponseError("Razorpay returned an invalid payment.")
        normalized = {key: payload.get(key) for key in RazorpayPayment.model_fields if key in payload}
        if isinstance(payload.get("created_at"), int):
            normalized["created_at"] = datetime.fromtimestamp(payload["created_at"], tz=UTC)
        error_fields = {
            field: payload.get(f"error_{field}")
            for field in ("code", "description", "source", "step", "reason")
            if payload.get(f"error_{field}") is not None
        }
        if error_fields:
            normalized["error"] = error_fields
        try:
            return RazorpayPayment.model_validate(normalized)
        except (TypeError, ValueError) as error:
            raise RazorpayMalformedResponseError("Razorpay returned an invalid payment.") from error

    @staticmethod
    def _parse_payment_link(payload: Any) -> RazorpayPaymentLink:
        if not isinstance(payload, dict):
            raise RazorpayMalformedResponseError("Razorpay returned an invalid payment link.")
        normalized = {key: payload.get(key) for key in RazorpayPaymentLink.model_fields if key in payload}
        try:
            return RazorpayPaymentLink.model_validate(normalized)
        except (TypeError, ValueError) as error:
            raise RazorpayMalformedResponseError("Razorpay returned an invalid payment link.") from error