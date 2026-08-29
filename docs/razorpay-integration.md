# Razorpay Test Mode Integration

Reclaim's Razorpay integration is an isolated HTTP adapter. The client translates Razorpay responses into a small internal Pydantic model; recovery and database services do not depend on Razorpay response shapes. Task 5A only reads one payment at a time and does not execute payments or start recovery workflows.

## Environment variables

Set these in the backend process environment or in the local `.env` file:

```text
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
RAZORPAY_BASE_URL=https://api.razorpay.com/v1
```

Use Test Mode credentials from the Razorpay Dashboard. `RAZORPAY_BASE_URL` defaults to `https://api.razorpay.com/v1`. Never commit `.env` or put a key secret in logs, responses, tests, or documentation.

## Test Mode setup

1. Sign in to the Razorpay Dashboard and switch to **Test Mode**.
2. Generate or copy the Test Mode Key ID and Key Secret.
3. Put them in the local environment variables above.
4. Start the backend with the existing Uvicorn command.
5. Use a Test Mode payment ID when calling the read-only payment endpoint.

The internal endpoint is:

```text
GET /api/integrations/razorpay/payments/{payment_id}
```

It returns normalized fields such as `id`, `order_id`, `amount`, `currency`, `status`, `method`, `captured`, `error`, and `created_at`. It never returns credentials or the complete provider response.

## Client method

`RazorpayClient.fetch_payment(payment_id)` fetches one normalized payment. The client uses HTTP Basic Authentication, an explicit 10-second timeout, and no automatic retries.

## Payment Link reconciliation

Reclaim can reconcile Payment Links that it previously created through the authenticated
`POST /api/reconciliation/run` entry point. Send `attempt_id` or `payment_id` to target
one record, or an empty JSON object to reconcile all eligible links. Authenticate with
`X-Reclaim-Workflow-Secret`. Reconciliation only reads the provider state; it never
creates another Payment Link.

`RECONCILIATION_MAX_ATTEMPTS` bounds provider lookups. Active links remain pending,
paid links transition the associated payment and recovery attempt to `recovered`,
expired links transition the attempt to `failed`, and cancelled/closed links transition
it to `stopped`. Unknown provider states and provider errors are audited without
changing local financial state. A newer local terminal state is never downgraded by
stale provider data.

## Recovery follow-up loop

The authenticated `POST /api/recovery/follow-up` entry point processes one attempt,
one payment, or a bounded batch of pending Payment Link recoveries. It persists a
claim lease on the `RecoveryAttempt`, reconciles the existing link first, and only
re-enters the normal risk, decision, validation, and execution pipeline after an
expired or closed link when the existing recovery policy permits another attempt.

Active or unknown links remain waiting, recovered and stopped states are not retried,
and each new attempt receives a new event and attempt number. The endpoint is ready
for n8n or a scheduler, but this repository does not run a background scheduler by
itself; deployment must invoke the endpoint periodically.

The development database bootstrap applies these additive audit columns with
`create_tables()`. This repository does not contain a versioned migration system;
production deployments must apply the equivalent `RecoveryAttempt` schema changes
through the deployment's managed migration process before serving traffic.

## Error handling

Provider failures are converted to safe exceptions without including credentials:

- authentication failure
- invalid request
- resource not found
- rate limiting
- upstream 5xx failure
- timeout or other network failure
- malformed or unexpected response

The FastAPI payment endpoint exposes provider failures as safe HTTP errors. Missing credentials produce `503 Service Unavailable`; provider request failures produce `502 Bad Gateway`.

## Testing strategy

The test suite uses `httpx.MockTransport` for every Razorpay call. It verifies successful fetch, Basic Auth, endpoint construction, status-code mapping, timeout and network handling, malformed responses, missing configuration, endpoint normalization, and that the test secret cannot appear in errors or responses. The suite never contacts Razorpay.

## Recovery action mapping

The Day 3 action executor maps only `PAYMENT_LINK` to Razorpay's documented
`POST /v1/payment_links/` operation. It remains disabled unless both
`RAZORPAY_ACTIONS_ENABLED=true` and `RAZORPAY_TEST_MODE=true` are explicitly
configured. The executor passes amount, currency, a bounded reference ID, and
notifications/reminders disabled; it returns only the Payment Link ID and URL
through the safe action result message.

`RETRY` has no direct Razorpay REST operation for a failed payment, so it stays
dry-run. `REMINDER` is not mapped to a provider notification API, while
`ESCALATE` and `STOP` remain provider-independent. Capture and refund are not
part of this recovery flow and are not implemented.

Automated tests use mocked HTTP transports and never contact Razorpay. Live
Test Mode verification requires suitable test credentials and test data.

Run the focused tests from `backend/`:

```bash
python -m pytest tests/test_razorpay_client.py -q
```

## Manual verification

With Test Mode credentials configured, start the backend and call the read-only endpoint with a known Test Mode payment ID:

```bash
curl http://127.0.0.1:8000/api/integrations/razorpay/payments/pay_test_example
```

Confirm that the response contains normalized payment data and no secret. A valid Test Mode payment ID and credentials are required for this manual check. Automated verification remains mocked and does not require credentials.
