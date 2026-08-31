# Reclaim

Reclaim is a merchant-focused failed-payment recovery workflow built around a deterministic risk engine, a safe decision-validation layer, and a dashboard for local evaluation and monitoring.

## Current repository status

This repository currently contains:

- a Python FastAPI backend in `backend/app`
- a Next.js dashboard in `frontend`
- PostgreSQL-backed persistence via SQLAlchemy models and database bootstrap code
- a deterministic payment-risk and recovery-decision engine
- a workflow-authenticated recovery endpoint for external orchestration
- a Razorpay adapter for read-only provider calls and optional provider action execution
- a synthetic evaluation pipeline and check-in artifacts under `docs/`
- workflow exports under `workflows/` for n8n import

This project is implemented and locally verifiable as a repository, but it does not include a repo-managed production deployment manifest or a verified live production deployment. The repository is a local/controlled environment project, not proof of live external business performance.

## What is implemented

### Backend

The backend is the source of truth for recovery policy, risk scoring, and validation. Key files include:

- `backend/app/main.py` – FastAPI app and health endpoints
- `backend/app/config.py` – environment-backed configuration loader
- `backend/app/database.py` – engine, session factory, and schema initialization
- `backend/app/services/revenue_risk.py` – deterministic risk scoring and eligibility logic
- `backend/app/services/recovery_decision.py` – LLM-response validation and policy enforcement
- `backend/app/services/razorpay_client.py` – Razorpay HTTP adapter with sanitized error handling
- `backend/app/services/recovery_workflow.py` – end-to-end workflow orchestration
- `backend/app/api/workflows.py` – authenticated workflow endpoint
- `backend/app/api/recovery.py` – recovery history and summary reads
- `backend/app/api/reconciliation.py` – reconciliation operations
- `backend/app/api/follow_up.py` – follow-up workflow operations
- `backend/app/api/integrations.py` – webhook and provider integration handling

### Frontend dashboard

The dashboard in `frontend` provides a local UI for:

- creating a failed-payment evaluation payload
- submitting it to the backend decision workflow
- viewing decision output and action results
- reading persisted recovery history
- viewing merchant KPI summaries

The key UI entry is `frontend/src/app/page.tsx`, and the API proxy routes live in:

- `frontend/src/app/api/recovery/route.ts`
- `frontend/src/app/api/recovery/summary/route.ts`

### Workflow integration

The repository includes workflow exports in `workflows/` that forward events to the backend through the authenticated recovery endpoint.

### Evaluation framework

The deterministic evaluation framework is implemented in:

- `backend/app/evaluation/run.py`

It generates a synthetic failed-payment dataset, runs the real Reclaim risk engine and decision logic, and calculates business/agent metrics. The current project artifacts are stored in:

- `docs/evaluation_results.json`
- `docs/evaluation_report.md`

## How the recovery flow works

The repository’s acting flow is:

1. A failed-payment event enters the backend or a workflow endpoint.
2. The event is validated against strict request schemas.
3. The system builds a risk context with payment, customer, and recovery history.
4. The deterministic Revenue Risk Engine scores recovery likelihood and eligibility.
5. A decision is generated and validated before it is accepted.
6. A safe action result is returned in dry-run mode by default.
7. Persisted outcomes are stored and surfaced in the dashboard history/summary views.

This is a controlled internal workflow, not a production autopilot. The repository uses dry-run semantics unless the relevant environment variables and execution flags are explicitly turned on.

## Environment and configuration

The repository reads settings from `backend/app/config.py` and the root `.env.example` file.

Required local setup includes:

- `DATABASE_URL` for PostgreSQL
- optional `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` for Razorpay calls
- optional `RAZORPAY_ACTIONS_ENABLED` to enable provider actions
- optional `RAZORPAY_TEST_MODE` for Test Mode behavior
- optional `RECLAIM_WORKFLOW_SECRET` for workflow auth
- optional LLM settings for a live OpenAI-compatible or Gemini-compatible provider

Important: the project does not commit secrets. The repo includes `.gitignore` exclusions for local `.env` files and the checked-in example file intentionally contains placeholders only.

## Local setup

### 1. Create a local environment file

From the repository root:

```bash
copy .env.example .env
```

Set at least:

```dotenv
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/reclaim
RECLAIM_WORKFLOW_SECRET=<workflow-secret>
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

### 2. Install backend dependencies

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. Initialize the database

```bash
cd backend
python -m app.init_db
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
```

### 5. Run the services

Backend:

```bash
cd backend
uvicorn app.main:app --reload --env-file ../.env
```

Frontend:

```bash
cd frontend
npm run dev
```

## API surface

The current FastAPI app exposes these endpoints:

- `GET /health`
- `GET /health/db`
- `POST /api/workflows/recovery`
- `GET /api/recovery/history`
- `GET /api/recovery/summary`
- `POST /api/reconciliation/run`
- `POST /api/recovery/follow-up`
- `GET /api/integrations/razorpay/payments/{payment_id}`

The workflow endpoint requires the `X-Reclaim-Workflow-Secret` header and compares it to the configured `RECLAIM_WORKFLOW_SECRET` value.

## Razorpay integration status

The repository includes a Razorpay adapter and normalization layer, but Razorpay execution is intentionally guarded until configuration is present and explicit execution is enabled.

The code does the following:

- validates credentials before creating a client
- reads provider responses into typed schemas
- sanitizes provider payloads before logging errors
- distinguishes authentication, invalid request, not-found, rate-limit, and upstream failures
- ignores unknown or extra provider fields in the payment-link model rather than rejecting the full payload

The project’s actual execution posture is safe-by-default: provider actions are not treated as automatic unless the app is explicitly configured to use them.

## Evaluation proof included in the repository

The repository contains an evaluation artifact generated from the current code. The latest dataset and metrics are recorded in `docs/evaluation_results.json` and summarized in `docs/evaluation_report.md`.

The captured metrics include:

- sample size: 500
- seed: 42
- total revenue at risk: 336501400
- total recovered: 39931200
- recovery rate: 11.87%
- successful recovery count: 188
- intervention count: 268
- success rate: 70.15%

This is proof of the implemented deterministic evaluation logic in the current repository. It is not proof of live external business performance.

## Local verification status

The repository includes local test and build verification artifacts from the current codebase:

- backend test suite results: `189 passed, 1 warning`
- frontend production build: successful `next build`

Those checks validate the repository’s current implementation and are local evidence only.

## What is not implemented as a repo-managed deployment

The repository does not include:

- a Dockerfile
- a docker-compose file
- a Render manifest
- a Heroku Procfile
- a GitHub Actions deployment workflow for production

The project therefore documents local execution and external service configuration rather than a managed production deployment in the repo itself.

## Security and secrets guidance

- Never commit `.env` files or live credentials
- Keep secrets in local environment configuration only
- Do not paste keys or tokens into documentation or issue reports
- The project intentionally keeps provider and workflow secrets outside source control

## Repository structure

```text
Reclaim/
├── backend/                     # FastAPI backend and service layer
│   ├── app/                     # application code
│   ├── tests/                  # backend test suite
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── pytest.ini
├── frontend/                   # Next.js dashboard
├── workflows/                  # n8n export files
├── docs/                       # evaluation, deployment, and project docs
├── data/                       # local data artifacts
├── .env.example                # environment example template
├── .gitignore                  # project ignores
├── README.md                   # repo overview
├── WORKFLOW_FIX_SUMMARY.md     # workflow-specific fix notes
├── fix_workflow.py             # workflow repair helper
└── .env                        # local environment file (not tracked)
```

## Final note

Reclaim in this repository is a working local system for deterministic recovery evaluation, workflow auth, provider integration boundaries, and dashboard monitoring. It is documented and verified at the repository level, but it is not a live production deployment claim or a business performance benchmark.
