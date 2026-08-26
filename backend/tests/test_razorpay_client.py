"""Mocked tests for the Razorpay Test Mode integration."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_razorpay_client
from app.schemas import RazorpayCustomer
from app.services.razorpay_client import (
    RazorpayAuthenticationError,
    RazorpayClient,
    RazorpayInvalidRequestError,
    RazorpayMalformedResponseError,
    RazorpayNetworkError,
    RazorpayNotFoundError,
    RazorpayRateLimitError,
    RazorpayUpstreamError,
)

SECRET = "test-secret-that-must-not-leak"
PAYMENT = {
    "id": "pay_test_123",
    "order_id": "order_test_123",
    "amount": 199900,
    "currency": "INR",
    "status": "failed",
    "method": "card",
    "captured": False,
    "created_at": 1720000000,
    "error_code": "BAD_REQUEST_ERROR",
    "error_description": "The payment failed.",
}


def _client(transport: httpx.MockTransport) -> RazorpayClient:
    return RazorpayClient("test-key", SECRET, transport=transport)


def test_fetch_payment_normalizes_response_and_uses_basic_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payments/pay_test_123"
        assert request.headers["authorization"] == "Basic dGVzdC1rZXk6dGVzdC1zZWNyZXQtdGhhdC1tdXN0LW5vdC1sZWFr"
        return httpx.Response(200, json=PAYMENT)

    payment = _client(httpx.MockTransport(handler)).fetch_payment("pay_test_123")

    assert payment.id == "pay_test_123"
    assert payment.error is not None
    assert payment.error.code == "BAD_REQUEST_ERROR"
    assert payment.created_at is not None


def test_fetch_payments_normalizes_listing() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"items": [PAYMENT]}))

    payments = _client(transport).fetch_payments(count=1, skip=2)

    assert len(payments) == 1
    assert payments[0].amount == 199900


def test_create_payment_link_sends_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payment_links"
        assert request.content == (
            b'{"amount":199900,"currency":"INR","description":"Recover failed payment",'
            b'"customer":{"name":"Asha","email":"asha@example.com"}}'
        )
        return httpx.Response(
            200,
            json={
                "id": "plink_test_123",
                "amount": 199900,
                "currency": "INR",
                "status": "created",
                "short_url": "https://rzp.io/i/test",
                "description": "Recover failed payment",
                "customer": {"name": "Asha", "email": "asha@example.com"},
            },
        )

    link = _client(httpx.MockTransport(handler)).create_payment_link(
        amount=199900,
        description="Recover failed payment",
        customer=RazorpayCustomer(name="Asha", email="asha@example.com"),
    )

    assert link.id == "plink_test_123"
    assert link.short_url == "https://rzp.io/i/test"


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (401, RazorpayAuthenticationError),
        (400, RazorpayInvalidRequestError),
        (404, RazorpayNotFoundError),
        (429, RazorpayRateLimitError),
        (500, RazorpayUpstreamError),
    ],
)
def test_provider_errors_are_mapped(status_code: int, exception_type: type[Exception]) -> None:
    client = _client(httpx.MockTransport(lambda request: httpx.Response(status_code, json={"error": "noisy"})))

    with pytest.raises(exception_type) as raised:
        client.fetch_payment("pay_test_123")

    assert SECRET not in str(raised.value)


def test_timeout_and_network_failures_are_safe() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout", request=request)

    with pytest.raises(RazorpayNetworkError, match="timed out"):
        _client(httpx.MockTransport(timeout_handler)).fetch_payment("pay_test_123")

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with pytest.raises(RazorpayNetworkError, match="could not be completed"):
        _client(httpx.MockTransport(network_handler)).fetch_payment("pay_test_123")


def test_malformed_response_is_rejected_without_secret() -> None:
    client = _client(httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "failed"})))

    with pytest.raises(RazorpayMalformedResponseError) as raised:
        client.fetch_payment("pay_test_123")

    assert SECRET not in str(raised.value)


def test_payment_endpoint_returns_normalized_data_without_credentials() -> None:
    app.dependency_overrides[get_razorpay_client] = lambda: _client(
        httpx.MockTransport(lambda request: httpx.Response(200, json=PAYMENT))
    )
    try:
        response = TestClient(app).get("/api/integrations/razorpay/payments/pay_test_123")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["id"] == "pay_test_123"
    assert SECRET not in response.text