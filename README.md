# Nirogidhara AI Command Center

AI Business Operating System for Ayurveda sales, CRM, AI calling, payments,
Delhivery delivery tracking, RTO control, AI agents, CEO AI, CAIO governance,
reward/penalty engine, and the human-call learning loop.

> Full vision: see *Nirogidhara AI Command Center — Master Blueprint v1.0*.

## Monorepo layout

```
nirogidhara-command/
  frontend/   # React 18 + Vite + TS + shadcn UI (current Lovable app)
  backend/    # Django 5 + DRF — implements the api.ts contract
  docs/       # RUNBOOK, BACKEND_API, FRONTEND_AUDIT, FUTURE_BACKEND_PLAN
```

## Quickstart

```bash
# 1. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                  # cp on macOS/Linux
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py runserver 0.0.0.0:8000

# 2. Frontend (new terminal)
cd frontend
npm install
copy .env.example .env                  # cp on macOS/Linux
npm run dev
```

Open [http://localhost:8080](http://localhost:8080) — the dashboard now reads
real data from Django. Stop the backend and the frontend transparently falls
back to the deterministic mock fixtures in
`frontend/src/services/mockData.ts`.

Full setup detail in [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Architecture rule

The frontend never holds business logic. It calls the API service layer
(`frontend/src/services/api.ts`); every function in that layer maps 1-to-1 to
a Django REST endpoint documented in [`docs/BACKEND_API.md`](docs/BACKEND_API.md).

```
┌────────────┐    /api/...      ┌─────────────────┐
│  React UI  │  ─────────────▶  │   Django + DRF  │
└────────────┘   (JSON, JWT)    └─────────────────┘
       │                              │
       └──── mock fallback ───────────┘
            (offline-safe dev)
```

## Tests

```bash
# Backend (pytest, 190 tests)
cd backend && python -m pytest -q

# Frontend (vitest, 8 tests)
cd frontend && npm test
```

## Phase scope

**Done:**

- ✅ **Phase 1** — 14 Django apps, 25 read endpoints, JWT auth, CORS, Master Event Ledger via signals, seed command (42 leads, 60 orders, 18 calls, 19 agents, etc.), frontend wired with mock fallback.
- ✅ **Phase 2A** — 14 write endpoints, role-based permissions (`apps/accounts/permissions.py`), order workflow state machine (`apps/orders/services.py`), service-layer pattern across CRM / orders / payments / shipments.
- ✅ **Phase 2B** — Razorpay payment-link integration with mock / test / live modes (`apps/payments/integrations/razorpay_client.py`) and HMAC-verified, idempotent webhook receiver at `/api/webhooks/razorpay/`.
- ✅ **Phase 2C** — Delhivery courier integration with the same three-mode adapter (`apps/shipments/integrations/delhivery_client.py`) and an HMAC-verified, idempotent tracking webhook at `/api/webhooks/delhivery/` (handles delivered / NDR / RTO transitions and bumps order risk accordingly).
- ✅ **Phase 2D** — Vapi voice trigger (`POST /api/calls/trigger/`) + transcript ingest webhook (`/api/webhooks/vapi/`) with the same three-mode adapter (`apps/calls/integrations/vapi_client.py`). Persists transcripts, post-call summaries, and handoff flags (medical / side-effect / angry / human-requested / low-confidence / legal-threat).
- ✅ **Phase 2E** — Meta Lead Ads ingest with `GET /api/webhooks/meta/leads/` (subscription handshake) + `POST /api/webhooks/meta/leads/` (signed delivery). Three-mode adapter (`apps/crm/integrations/meta_client.py`) with mock-mode default, leadgen_id idempotency, and Lead refresh-not-duplicate semantics.
- ✅ **Phase 3A** — AgentRun foundation + AI provider adapters (`apps/integrations/ai/`). Approved-Claim-Vault-grounded prompt builder, CAIO hard stop, admin/director-only `POST /api/ai/agent-runs/` (always dry-run in Phase 3A). Disabled / no-key path returns `skipped` AgentRuns without any network call.
- ✅ **Phase 3B** — Per-agent runtime services for CEO / CAIO / Ads / RTO / Sales Growth / CFO / Compliance. 8 new admin-only `/api/ai/agent-runtime/*` endpoints, CEO success refreshes the `CeoBriefing` row, management command `run_daily_ai_briefing` for cron / Windows Task Scheduler.
- ✅ **Phase 3C** — Celery beat scheduler firing CEO + CAIO at 09:00 + 18:00 IST (`apps/ai_governance/tasks.py`), provider fallback chain (OpenAI → Anthropic) in `apps/integrations/ai/dispatch.py`, model-wise USD cost tracking via `apps/integrations/ai/pricing.py`, frontend Scheduler Status page at `/ai-scheduler`. Local dev runs in Celery eager mode; `docker-compose.dev.yml` brings up Redis only when you want the real beat schedule.
- ✅ **Phase 3D** — AI sandbox toggle + versioned prompts (one-click rollback) + per-agent USD budget guards (warning + block, never triggers fallback) + frontend Governance page at `/ai-governance`. PromptVersion content cannot bypass the Approved Claim Vault.

**Next:**

- ⏭ **Phase 4** — Real-time WebSockets + reward / penalty engine + approval-matrix middleware that finally turns dry-run AgentRun suggestions into business writes.

Full roadmap with acceptance criteria: [`docs/FUTURE_BACKEND_PLAN.md`](docs/FUTURE_BACKEND_PLAN.md).
Detailed handoff: [`nd.md`](nd.md).

## Stack

**Frontend:** React 18, Vite, TypeScript, Tailwind, shadcn UI, React Router, Recharts, Vitest

**Backend:** Python 3.10+, Django 5.1, Django REST Framework, simplejwt, django-cors-headers, dj-database-url, razorpay, requests (lazy import for Delhivery / Vapi test/live), pytest

## License

Proprietary — Nirogidhara Private Limited. Internal use only.
