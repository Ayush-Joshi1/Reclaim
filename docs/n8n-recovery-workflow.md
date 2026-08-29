# n8n Recovery Workflow

Task 5B adds an n8n Cloud orchestration boundary. n8n receives an event, forwards it to Reclaim, routes only on Reclaim's validated decision, and returns a dry-run result. Risk scoring, eligibility, limits, approval requirements, and decision validation remain in the backend.

## Configuration

Set these variables for the backend:

```text
DATABASE_URL=postgresql://...
RECLAIM_WORKFLOW_SECRET=use-a-local-shared-secret
```

Razorpay Test Mode variables remain those documented in [`razorpay-integration.md`](razorpay-integration.md). The workflow JSON contains no provider or database credentials.

## Import and configure n8n Cloud

1. Import [`workflows/reclaim-recovery-orchestration.json`](../workflows/reclaim-recovery-orchestration.json) from **Workflows** in n8n Cloud.
2. Set the **Reclaim Recovery Evaluation** URL base to a backend URL reachable from n8n by creating a workflow variable named `RECLAIM_BACKEND_URL` under **Settings > Variables** and keeping the HTTP Request node target at `={{ $vars.RECLAIM_BACKEND_URL }}/api/workflows/recovery`. The checked-in value is a placeholder and must be replaced in n8n Cloud.
3. Keep the existing n8n authentication configuration exactly as imported: **Authentication = Generic Credential Type**, **Generic Auth Type = Header Auth**, and the existing **Header Auth account**. Do not replace it with Basic Auth, Bearer, or another type.
4. In n8n Cloud, create a workflow variable named `RECLAIM_WORKFLOW_SECRET` under **Settings > Variables**, using the exact same value configured as the backend's `RECLAIM_WORKFLOW_SECRET`. The imported HTTP node reads it as `={{ $vars.RECLAIM_WORKFLOW_SECRET }}` and sends it in the `X-Reclaim-Workflow-Secret` header. Do not put the secret literally in the workflow JSON.
5. Activate the workflow and copy the generated webhook URL. If the backend is local, expose it to n8n only through a temporary authenticated development tunnel.
6. Keep the workflow inactive until the backend and secret have been configured.

The backend endpoint is:

```text
POST /api/workflows/recovery
```

Authentication uses:

```text
X-Reclaim-Workflow-Secret: <same value as RECLAIM_WORKFLOW_SECRET>
```

## Event payload

Required fields are `payment_id`, `event_type`, `timestamp`, and `source`. Use `event_id` for idempotency. For a synthetic dry-run, include normalized payment evidence and do not misrepresent a captured Razorpay payment:

```json
{
  "event_id": "evt_synthetic_failed_001",
  "payment_id": "synthetic-payment-001",
  "event_type": "payment_failed",
  "timestamp": "2026-08-26T00:00:00Z",
  "source": "n8n",
  "payment": {
    "payment_id": "synthetic-payment-001",
    "amount": 199900,
    "currency": "INR",
    "payment_method": "card",
    "status": "failed",
    "failure_reason": "network_error",
    "failed_at": "2026-08-25T22:00:00Z",
    "time_since_failure_hours": 2
  },
  "recovery_attempt_count": 0
}
```

If `payment` is omitted, Reclaim retrieves the payment through the existing Razorpay read-only adapter. A captured payment is normalized as successful and the deterministic validator returns `STOP`; it must not be presented as a failed payment.

n8n cannot submit merchant policy, risk scores, eligibility, or approval overrides. The backend constructs those values from its own policy and evidence.

## Decision routing

The **Route Validated Decision** switch uses the backend's `action` only:

- `RETRY`: queued dry-run request; no retry is sent.
- `PAYMENT_LINK`: queued dry-run request; no link is created or sent.
- `REMINDER`: queued dry-run notification request; no message is sent.
- `ESCALATE`: queued dry-run merchant-review event.
- `STOP`: terminal dry-run result; no external action.

The response includes flattened decision fields plus the existing validated `decision` object and a structured `result`.

## Errors and idempotency

Missing authentication returns `401`; an invalid secret returns `403`; missing backend workflow configuration returns `503`. Unknown Razorpay payments return `404`; provider failures return safe `502` or `503` responses. Invalid payloads return `422`, and unexpected workflow failures return a generic `500` response without stack traces or secrets.

The backend caches processed `event_id` values for the lifetime of the process and returns the prior result with `duplicate: true` for repeats. When `event_id` is omitted, a deterministic hash of the event payload is used. This is intentionally a basic Task 5B mechanism: it is not shared across multiple backend workers and is cleared on restart. Durable idempotency and audit persistence belong in a later task.

## Safe test procedure

1. Start the backend from `backend/`:

   ```bash
   uvicorn app.main:app --reload --env-file ../.env
   ```

2. Configure a local `RECLAIM_WORKFLOW_SECRET` in `.env` and the matching n8n header.
3. Send the synthetic payload above through the n8n webhook or directly to the Reclaim endpoint.
4. Confirm the returned `mode` is `dry_run` and that no Razorpay write request, notification, or payment operation occurs.
5. Repeat the same `event_id` and confirm `duplicate` is `true`.
6. Do not use `pay_TUJmhXqOMUqwiA` as a failed-payment fixture. It is a captured Test Mode payment and should demonstrate the backend's STOP behavior if retrieved.

Automated tests mock the provider boundary and do not make n8n or Razorpay network calls.

## Intentionally excluded

Task 5B does not implement webhooks from Razorpay, real retries, capture/refund operations, payment-link creation, email/SMS delivery, production durable idempotency, background workers, or frontend integration. Those remain future work.
