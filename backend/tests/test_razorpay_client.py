"""Mocked tests for the Razorpay Test Mode integration."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, get_razorpay_client
from app.services.razorpay_client import (
    RazorpayAuthenticationError,
    RazorpayClient,
    RazorpayClientError,
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


def test_create_payment_link_uses_documented_endpoint_and_returns_safe_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/payment_links/"
        body = request.read().decode()
        assert '"amount":125000' in body
        assert '"reference_id":"pay_test_123"' in body
        return httpx.Response(
            200,
            json={
                "id": "plink_test_123",
                "amount": 125000,
                "currency": "INR",
                "status": "created",
                "short_url": "https://rzp.io/i/test123",
                "reference_id": "pay_test_123",
            },
        )

    link = _client(httpx.MockTransport(handler)).create_payment_link(
        amount=125000,
        currency="INR",
        reference_id="pay_test_123",
        description="Recovery payment",
    )

    assert link.id == "plink_test_123"
    assert link.short_url == "https://rzp.io/i/test123"


def test_get_payment_link_uses_documented_endpoint_and_returns_safe_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/payment_links/plink_test_123"
        return httpx.Response(
            200,
            json={
                "id": "plink_test_123",
                "amount": 125000,
                "currency": "INR",
                "status": "paid",
                "short_url": "https://rzp.io/i/test123",
                "reference_id": "pay_test_123",
            },
        )

    link = _client(httpx.MockTransport(handler)).get_payment_link("plink_test_123")

    assert link.id == "plink_test_123"
    assert link.status == "paid"


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
def test_payment_link_provider_errors_are_mapped(
    status_code: int, exception_type: type[Exception]
) -> None:
    client = _client(
        httpx.MockTransport(lambda request: httpx.Response(status_code, json={"error": "noisy"}))
    )

    with pytest.raises(exception_type):
        client.create_payment_link(125000, "INR", "pay_test_123", "Recovery payment")


def test_payment_link_malformed_response_is_rejected() -> None:
    client = _client(httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "plink_test"})))

    with pytest.raises(RazorpayMalformedResponseError) as raised:
        client.create_payment_link(125000, "INR", "pay_test_123", "Recovery payment")

    assert raised.value.status_code == 200
    assert raised.value.response_body == {"id": "plink_test"}
    assert raised.value.provider_code is None


def test_payment_link_malformed_response_preserves_status_and_provider_code() -> None:
    client = _client(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "error": {
                        "code": "BAD_REQUEST_ERROR",
                        "description": "bad request",
                        "customer": {"email": "test@example.com"},
                    },
                    "authorization": "Basic secret-key",
                },
            )
        )
    )

    with pytest.raises(RazorpayMalformedResponseError) as raised:
        client.create_payment_link(125000, "INR", "pay_test_123", "Recovery payment")

    assert raised.value.status_code == 200
    assert raised.value.provider_code == "BAD_REQUEST_ERROR"
    assert raised.value.response_body == {
        "error": {
            "code": "BAD_REQUEST_ERROR",
            "description": "bad request",
            "customer": {"id": "[REDACTED]"},
        },
        "authorization": "[REDACTED]",
    }
    assert "test@example.com" not in str(raised.value.response_body)
    assert "Basic secret-key" not in str(raised.value.response_body)


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


def test_missing_configuration_is_rejected() -> None:
    with pytest.raises(RazorpayAuthenticationError, match="not configured"):
        RazorpayClient.from_settings(
            Settings(database_url="postgresql://test", razorpay_key_id="", razorpay_key_secret="")
        )


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


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (RazorpayAuthenticationError("auth failed"), 502),
        (RazorpayNotFoundError("not found"), 404),
        (RazorpayUpstreamError("upstream failed"), 503),
        (RazorpayNetworkError("request timed out"), 503),
    ],
)
def test_payment_endpoint_translates_provider_failures(
    exception: RazorpayClientError, expected_status: int
) -> None:
    class FailingClient:
        def fetch_payment(self, payment_id: str) -> None:
            raise exception

    app.dependency_overrides[get_razorpay_client] = lambda: FailingClient()
    try:
        response = TestClient(app).get("/api/integrations/razorpay/payments/pay_test_123")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == expected_status
    assert SECRET not in response.text