# Reclaim Deployment Guide

## 1. System Overview

Reclaim is a Python + FastAPI backend plus a Next.js dashboard, with an n8n workflow export used as an external orchestration boundary.

The current repository proves the following architecture:

- Backend: FastAPI application in [backend/app](../backend/app)
- Frontend: Next.js app in [frontend](../frontend)
- Workflow orchestration: n8n JSON exports in [workflows](../workflows)
- Persistence: PostgreSQL via SQLAlchemy models and [backend/app/database.py](../backend/app/database.py)
- External provider integration: Razorpay adapter in [backend/app/services/razorpay_client.py](../backend/app/services/razorpay_client.py)
- LLM adapter: OpenAI-compatible / Gemini-compatible client in [backend/app/services/llm_client.py](../backend/app/services/llm_client.py)
- Recovery engine: deterministic policy + validation in [backend/app/services](../backend/app/services)

The backend is the source of truth for recovery policy, risk evaluation, decision validation, and provider execution boundaries. The frontend is a dashboard that reads persisted recovery data and submits evaluation requests to the backend. n8n is used to forward recovery events to the backend, but the workflow is imported/exported and not auto-activated by the repository itself.

## 2. Repository Structure

```text
Reclaim/
├── backend/                     # FastAPI API and services
│   ├── app/
│   │   ├── api/                 # workflow, recovery, reconciliation, follow-up endpoints
│   │   ├── config.py            # environment-driven settings
│   │   ├── database.py          # DB engine and schema bootstrap
│   │   ├── init_db.py          # create_tables entrypoint
│   │   ├── main.py              # FastAPI app and health routes
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # request/response models
│   │   └── services/            # LLM, Razorpay, risk, workflow logic
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   └── tests/
├── frontend/                   # Next.js dashboard
│   ├── src/
│   ├── package.json
│   ├── next.config.ts
│   └── .env example usage via NEXT_PUBLIC_BACKEND_URL
├── workflows/                  # n8n JSON exports
│   ├── reclaim-recovery-orchestration.json
│   ├── reclaim_autonomous_followup_scheduler.json
│   └── README.md
├── docs/                       # project docs
├── data/
├── .env.example
├── .gitignore
├── README.md
├── WORKFLOW_FIX_SUMMARY.md
└── fix_workflow.py
```

## 3. Prerequisites

Required locally:

- Python environment for the backend
- PostgreSQL instance reachable from `DATABASE_URL`
- Node.js + npm for the frontend
- Access to a Razorpay Test Mode account for provider checks
- n8n environment for importing the workflow JSON

This repository does not contain a Dockerfile, docker-compose file, Render manifest, or Procfile. Deployment is therefore repository-driven only through local execution, environment configuration, and external service setup.

## 4. Environment Variables

The actual environment variables used by the project are loaded from [backend/app/config.py](../backend/app/config.py) and the example file [.env.example](../.env.example).

### Backend variables

| Name | Purpose | Required | Placeholder |
| --- | --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | Yes | `postgresql://<user>:<password>@<host>:5432/<db>` |
| `RAZORPAY_KEY_ID` | Razorpay API key ID | No for local dry-run; required for live provider calls | `<RAZORPAY_KEY_ID>` |
| `RAZORPAY_KEY_SECRET` | Razorpay secret | No for local dry-run; required for live provider calls | `<RAZORPAY_KEY_SECRET>` |
| `RAZORPAY_BASE_URL` | Razorpay base URL | No | `https://api.razorpay.com/v1` |
| `RAZORPAY_ACTIONS_ENABLED` | Enables provider action execution path | No | `false` |
| `RAZORPAY_TEST_MODE` | Switches app behavior to Test Mode semantics | No | `true` |
| `RAZORPAY_WEBHOOK_SECRET` | Signature validation for webhook endpoints | No | `<RAZORPAY_WEBHOOK_SECRET>` |
| `RECLAIM_WORKFLOW_SECRET` | Shared secret for workflow-to-backend auth | Yes when workflow endpoint is used | `<WORKFLOW_SECRET>` |
| `RECOVERY_LLM_API_KEY` | API key for OpenAI-compatible / Gemini-compatible model | No for fake mode | `<LLM_API_KEY>` |
| `RECOVERY_LLM_MODEL` | LLM model name | No for fake mode | `<MODEL_NAME>` |
| `RECOVERY_LLM_BASE_URL` | LLM base URL | No | `https://api.openai.com/v1` |
| `RECONCILIATION_MAX_ATTEMPTS` | Reconciliation retry cap | No | `3` |
| `FOLLOW_UP_LEASE_SECONDS` | Follow-up lease duration | No | `300` |

### Frontend variables

| Name | Purpose | Required | Placeholder |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_BACKEND_URL` | Backend base URL used by dashboard API routes | Recommended | `http://localhost:8000` |
| `RECLAIM_WORKFLOW_SECRET` | Server-only proxy secret used by Next.js API route | Only if the frontend proxies workflow calls | `<WORKFLOW_SECRET>` |

The frontend route files in [frontend/src/app/api/recovery/route.ts](../frontend/src/app/api/recovery/route.ts) and [frontend/src/app/api/recovery/summary/route.ts](../frontend/src/app/api/recovery/summary/route.ts) read `NEXT_PUBLIC_BACKEND_URL` and use the backend base URL.

### n8n variables

The workflow export in [workflows/reclaim-recovery-orchestration.json](../workflows/reclaim-recovery-orchestration.json) expects n8n workflow variables:

- `RECLAIM_BACKEND_URL`
- `RECLAIM_WORKFLOW_SECRET`

The workflow uses the header:

```text
X-Reclaim-Workflow-Secret: <same value as RECLAIM_WORKFLOW_SECRET>
```

The checked-in JSON does not contain the live secret itself; it uses `={{ $vars.RECLAIM_WORKFLOW_SECRET }}`.

## 5. Local Backend Setup

Use the actual repo paths and commands:

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Create a local environment file at the repo root or in `backend/` depending on your shell setup. The project loads environment variables via [backend/app/config.py](../backend/app/config.py), and the app entrypoint is [backend/app/main.py](../backend/app/main.py).

Safe example:

```bash
cd Reclaim
copy .env.example .env
```

Then set the values, for example:

```text
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/reclaim
RAZORPAY_KEY_ID=<RAZORPAY_KEY_ID>
RAZORPAY_KEY_SECRET=<RAZORPAY_KEY_SECRET>
RAZORPAY_TEST_MODE=true
RAZORPAY_ACTIONS_ENABLED=false
RECLAIM_WORKFLOW_SECRET=<WORKFLOW_SECRET>
RECOVERY_LLM_API_KEY=<LLM_API_KEY>
RECOVERY_LLM_MODEL=<MODEL_NAME>
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

Create tables:

```bash
cd backend
python -m app.init_db
```

Run the backend:

```bash
cd backend
uvicorn app.main:app --reload --env-file ../.env
```

The app exposes:

- `GET /health`
- `GET /health/db`
- `POST /api/workflows/recovery`
- `GET /api/recovery/history`
- `GET /api/recovery/summary`
- `POST /api/reconciliation/run`
- `POST /api/recovery/follow-up`
- `GET /api/integrations/razorpay/payments/{payment_id}`

## 6. Local Frontend Setup

Use the actual frontend app:

```bash
cd frontend
npm install
```

Set the backend URL for local development, for example:

```text
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

Run locally:

```bash
cd frontend
npm run dev
```

Production build check:

```bash
cd frontend
npm run build
```

The frontend has server-side API proxies under [frontend/src/app/api](../frontend/src/app/api) and reads the backend through `NEXT_PUBLIC_BACKEND_URL`.

## 7. Backend Deployment

The repository does not include a deployment manifest such as `render.yaml`, `Dockerfile`, `docker-compose.yml`, or `Procfile`.

The project does include a live backend URL in the local `.env` used for a Render deployment, and a scheduler workflow references a deployed backend endpoint, but the repository itself does not manage the deployment. In other words:

- repository-managed deployment: not present
- external deployment platform: likely Render, as inferred from the configured URL and workflow JSON references
- repo validation: local backend and frontend are fully testable, but live deployment state must be confirmed in the environment itself

If deploying to a host provider, use the same backend commands and environment variables listed above. Do not copy secret values into documentation or source control.

## 8. Frontend Deployment

The repo does not include a Vercel config or build manifest for a specific frontend hosting platform. The frontend is a standard Next.js app and can be deployed to any provider that supports `npm run build` + `next start` or equivalent serverless deployment of Next.js.

What is proven by the repo:

- `next.config.ts` is present and minimal;
- `frontend/package.json` defines `next build` and `next start`;
- `NEXT_PUBLIC_BACKEND_URL` is the required runtime variable.

What is not proven by the repo:

- the actual frontend host provider
- the exact deployment domain
- any live production deployment status

## 9. n8n Workflow Setup

The actual workflow export is [workflows/reclaim-recovery-orchestration.json](../workflows/reclaim-recovery-orchestration.json).

### Import steps

1. Open n8n and import the workflow JSON.
2. Create workflow variables:
   - `RECLAIM_BACKEND_URL`
   - `RECLAIM_WORKFLOW_SECRET`
3. Keep the HTTP Request node configured to call:

```text
{{ $vars.RECLAIM_BACKEND_URL }}/api/workflows/recovery
```

4. Keep the header 

```text
X-Reclaim-Workflow-Secret
```

as a value sourced from `={{ $vars.RECLAIM_WORKFLOW_SECRET }}`.

5. Activate the workflow only after the backend is reachable and the secret matches the backend configuration.

### Workflow behavior

The workflow:

- validates the incoming event,
- forwards it to the backend at `POST /api/workflows/recovery`,
- uses the backend’s validated action to route execution,
- returns the backend response as dry-run results,
- does not create payment links, send notifications, or change payment state independently.

The follow-up scheduler export is [workflows/reclaim_autonomous_followup_scheduler.json](../workflows/reclaim_autonomous_followup_scheduler.json). It targets a deployed `/api/recovery/follow-up` endpoint and must be configured separately in n8n or a scheduler.

## 10. Razorpay Test Mode Setup

The actual integration logic lives in [backend/app/services/razorpay_client.py](../backend/app/services/razorpay_client.py) and the relevant API route is [backend/app/main.py](../backend/app/main.py).

### Variables

```text
RAZORPAY_KEY_ID=<RAZORPAY_KEY_ID>
RAZORPAY_KEY_SECRET=<RAZORPAY_KEY_SECRET>
RAZORPAY_BASE_URL=https://api.razorpay.com/v1
RAZORPAY_TEST_MODE=true
RAZORPAY_ACTIONS_ENABLED=false
```

### Safe verification flow

1. Use Razorpay Test Mode credentials in the backend environment.
2. Start the backend locally with the correct environment variables.
3. Use a known valid Razorpay Test Mode payment ID with the read-only endpoint:

```bash
curl http://127.0.0.1:8000/api/integrations/razorpay/payments/<PAYMENT_ID>
```

4. Confirm the response includes normalized fields and not secrets.
5. For the recovery workflow, send a valid payload to `POST /api/workflows/recovery` with the shared secret header.

Important distinction:

- `LIVE / PRODUCTION`: requires real production credentials and environment; not represented in this repo as a deployable config
- `RAZORPAY TEST MODE`: is the safe, repository-supported verification path and should be used for local or staging checks

## 11. End-to-End Verification

Use this order:

1. Start PostgreSQL.
2. Configure the backend environment variables.
3. Run `python -m app.init_db`.
4. Start the backend with `uvicorn app.main:app --reload --env-file ../.env`.
5. Confirm `GET /health` returns `200`.
6. Confirm `GET /health/db` returns `200` when the database is reachable.
7. Start the frontend with `npm run dev`.
8. Confirm the dashboard loads and reads recovery history and summary endpoints.
9. Import the n8n workflow and configure `RECLAIM_BACKEND_URL` and `RECLAIM_WORKFLOW_SECRET`.
10. Submit a valid recovery event to the workflow endpoint.
11. Confirm the backend returns a validated decision and persisted audit data.
12. Verify the dashboard displays the recovery history/summary.

## 12. Deployment Verification Checklist

Repository-verified:

- [x] Repository cloned
- [x] Backend dependencies installed from [backend/requirements.txt](../backend/requirements.txt)
- [x] Backend environment configured using [.env.example](../.env.example)
- [x] Backend tests pass in the current repo
- [x] Frontend build passes in the current repo
- [x] n8n workflow export exists in [workflows/reclaim-recovery-orchestration.json](../workflows/reclaim-recovery-orchestration.json)
- [x] Required workflow variables are documented and match the backend contract
- [x] Razorpay client contract is implemented and test-covered

Manually verified only when performed in the environment:

- [ ] PostgreSQL database is provisioned and reachable
- [ ] Backend is started on the target host
- [ ] Frontend is deployed and served
- [ ] n8n workflow is imported and activated
- [ ] Workflow secret matches backend configuration
- [ ] Razorpay Test Mode credentials are configured
- [ ] Recovery event is submitted through the live endpoint
- [ ] Dashboard reflects a live event

Still requiring deployment verification:

- [ ] live production deployment status
- [ ] production endpoint reachability
- [ ] real live provider execution in a non-test environment
- [ ] managed hosting configuration beyond local repo validation

## 13. Troubleshooting

### 1) Razorpay Payment Link response schema rejection

Symptom:
- Valid Razorpay responses are rejected as invalid due to extra provider fields.

Likely cause:
- Strict Pydantic validation with extra-forbid rejected unknown data from the upstream provider.

Verification:
- Check [backend/tests/test_razorpay_client.py](../backend/tests/test_razorpay_client.py) and the schema in [backend/app/schemas/razorpay.py](../backend/app/schemas/razorpay.py).

Fix:
- Ignore non-essential provider fields rather than rejecting them.

### 2) Workflow JSON UTF-8 BOM

Symptom:
- `json.loads` raises `JSONDecodeError: Unexpected UTF-8 BOM`.

Likely cause:
- BOM at the beginning of the exported n8n JSON file.

Verification:
- The failing tests are in [backend/tests/test_action_matrix_comprehensive.py](../backend/tests/test_action_matrix_comprehensive.py) and [backend/tests/test_recovery_workflow.py](../backend/tests/test_recovery_workflow.py).

Fix:
- Strip the BOM before parsing or save the workflow file without a BOM.

### 3) Gemini/OpenAI-compatible response extra content

Symptom:
- Structured provider responses include extra text or metadata that is not a pure JSON object.

Likely cause:
- The provider returns wrapped content such as fenced JSON, Google metadata, or mixed text.

Verification:
- [backend/app/services/llm_client.py](../backend/app/services/llm_client.py) contains defensive parsing to extract JSON from provider text and ignore surrounding non-JSON content.

Fix:
- Use the safe parser to strip fenced wrappers and extract the JSON payload before validation.

## 14. Security Notes

Repository security status:

- [.gitignore](../.gitignore) excludes `.env` and `.env.*` files from git tracking.
- [.env.example](../.env.example) is tracked and safe to reference.
- Local `.env` files may exist outside git but must not be committed.
- No hardcoded production credentials are documented in the repository files reviewed for this task.
- The workflow JSON references a generic header credential name but does not embed a secret value.

Important:

- Do not copy `.env` values into docs or source control.
- Rotate any real secret if it was exposed to a shared environment or commit history.
- Treat all local `.env` files as privileged configuration.

## 15. Current Deployment Status

### Verified in repository

The following are proven by the actual repo and recent verification runs:

- Backend configuration points to environment-driven settings via [backend/app/config.py](../backend/app/config.py)
- API endpoints and auth are implemented in [backend/app/api](../backend/app/api)
- PostgreSQL schema bootstrap is implemented in [backend/app/database.py](../backend/app/database.py)
- n8n workflow export exists at [workflows/reclaim-recovery-orchestration.json](../workflows/reclaim-recovery-orchestration.json)
- Frontend build passes with `npm run build`
- Backend tests pass in the current repo

### Verified live

No repository-managed deployment manifest proves a current live deployment state. A deployed backend URL may be present in a non-tracked local `.env` and a scheduler workflow may reference a hosted backend, but the repository alone does not prove current live service health or external uptime.

### Requires manual deployment/configuration

- Provision PostgreSQL and configure `DATABASE_URL`
- Provision or import the n8n workflow and set `RECLAIM_BACKEND_URL`
- Create the corresponding workflow secret in n8n and backend
- Configure Razorpay Test Mode credentials in the deployment environment
- Deploy the backend and frontend to the target host
- Verify health and workflow delivery in the actual environment

## 16. Important Commands

Backend tests:

```bash
cd backend
python -m pytest -q
```

Backend health check:

```bash
curl http://127.0.0.1:8000/health
```

Database health check:

```bash
curl http://127.0.0.1:8000/health/db
```

Workflow endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/recovery \
  -H "Content-Type: application/json" \
  -H "X-Reclaim-Workflow-Secret: <WORKFLOW_SECRET>" \
  -d '{"payment_id":"pay_test_example","event_type":"payment_failed","timestamp":"2026-08-31T00:00:00Z","source":"n8n","recovery_attempt_count":0}'
```

Razorpay payment lookup:

```bash
curl http://127.0.0.1:8000/api/integrations/razorpay/payments/<PAYMENT_ID>
```

Frontend build:

```bash
cd frontend
npm run build
```

## 17. Safe Deployment Guidance

Do this in order:

1. Clone the repo and inspect the tracked files.
2. Set up PostgreSQL and the backend environment.
3. Install backend dependencies.
4. Run app initialization.
5. Start the backend.
6. Set the frontend `NEXT_PUBLIC_BACKEND_URL`.
7. Build the frontend.
8. Configure the n8n workflow variables.
9. Activate the workflow only after secret matching is complete.
10. Use Razorpay Test Mode credentials for verification.
11. Record results in the deployment environment instead of in repo files.

Do not assume production status because a repo file or local environment exists. The repository proves the structure and local validation path; live deployment status must be proven in the target environment.
