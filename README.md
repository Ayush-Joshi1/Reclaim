# Reclaim

An autonomous revenue recovery platform for merchants, being built for the Razorpay AI Buildathon (Track 03: AI Revenue Recovery).

**Current status:** Day 1 foundation.

## Planned tech stack

- Frontend: Next.js, TypeScript, App Router, Tailwind CSS, ESLint
- Backend: Python, FastAPI, Uvicorn, SQLAlchemy 2.x, PostgreSQL
- Future (not yet implemented): n8n, automatic recovery, and an AI agent

## Repository structure

```text
reclaim/
├── frontend/     # Next.js dashboard
├── backend/      # FastAPI service
├── workflows/    # Future n8n workflows
├── data/         # Future synthetic payment data
└── docs/         # Architecture and technical documentation
```

## Local setup

1. Install PostgreSQL and create a local database:

   ```sql
   CREATE USER recoverai WITH PASSWORD 'localdev';
   CREATE DATABASE reclaim OWNER recoverai;
   ```

2. Copy `.env.example` to `.env`, then export its `DATABASE_URL` in your shell. For local development it can be:

   ```text
   postgresql://recoverai:localdev@localhost:5432/reclaim
   ```

   `DATABASE_URL` is required; the backend will not start without it.

3. Create the initial local tables:

   ```bash
   cd backend
   python -m app.init_db
   ```

4. Install frontend dependencies with `cd frontend` followed by `npm install`.
5. Create and activate a Python virtual environment, then install backend dependencies with `pip install -r backend/requirements.txt`.

## Run locally

Frontend:

```bash
cd frontend
npm run dev
```

Backend:

```bash
cd backend
uvicorn app.main:app --reload --env-file ../.env
```

The backend health check is available at `GET http://127.0.0.1:8000/health`. Verify the PostgreSQL connection at `GET http://127.0.0.1:8000/health/db`; it returns `503 Service Unavailable` if PostgreSQL cannot be reached.

## Synthetic payment data and revenue risk engine

Generate a reproducible JSON dataset (defaults: 500 records, seed `42`):

```bash
cd backend
python -m app.services.synthetic_data --count 500 --seed 42 --output ../data/sample_payments.json
```

The deterministic Revenue Risk Engine is a backend service only; it takes typed payment, customer-history, recovery-history, and merchant-policy inputs. Its named rules and eligibility behavior are documented in [`docs/revenue-risk-engine.md`](docs/revenue-risk-engine.md).

## AI recovery decision engine

Run a local decision demonstration without any external LLM call:

```bash
cd backend
python -m app.cli.recovery_decision --index 0 --fake
```

For a live, OpenAI-compatible provider call, set `RECOVERY_LLM_API_KEY`, `RECOVERY_LLM_MODEL`, and optionally `RECOVERY_LLM_BASE_URL`. The provider only returns a recommendation; the deterministic validator still enforces policy and no payment or workflow is executed. The versioned system prompt is at [`docs/prompts/recovery-agent.md`](docs/prompts/recovery-agent.md).

## Environment variables

`.env.example` documents `DATABASE_URL` and the Razorpay Test Mode integration variables. Never commit `.env` or real credentials. See [`docs/razorpay-integration.md`](docs/razorpay-integration.md) for setup and verification.
