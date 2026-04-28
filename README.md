# Nirogidhara AI Command Center

AI Business Operating System for Ayurveda sales, CRM, AI calling, payments,
Delhivery delivery tracking, RTO control, AI agents, CEO AI, CAIO governance,
reward/penalty engine, and the human-call learning loop.

> Full vision: see *Nirogidhara AI Command Center — Master Blueprint v1.0*.

## Monorepo layout

```
nirogidhara-command/
  frontend/   # React 18 + Vite + TS + shadcn UI (19 pages)
  backend/    # Django 5 + DRF — 15 apps, implements the api.ts contract
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
# Backend (pytest, 275 tests)
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
- ✅ **Phase 3E** — Business configuration foundation: `apps.catalog` (ProductCategory / Product / ProductSKU + admin/director-managed CRUD) + discount policy with locked 10/20% bands (`apps/orders/discounts.py`) + ₹499 fixed advance (`apps/payments/policies.py`) + reward/penalty deterministic scoring (`apps/rewards/scoring.py`) capped at +100/-100 + approval matrix policy table (`apps/ai_governance/approval_matrix.py`) with read endpoint at `/api/ai/approval-matrix/` + WhatsApp sales/support design scaffold (`apps/crm/whatsapp_design.py` — design only, live integration is Phase 4+) + production infra targets (Postgres / Redis / Celery worker+beat / Channels / domain / SSL) documented in RUNBOOK.
- ✅ **Phase 4B** — Reward / Penalty Engine wiring (`apps/rewards/engine.py`) on top of the Phase 3E formula: AI-agents-only scoring with **CEO AI net accountability** for every delivered / RTO / cancelled order, idempotent `RewardPenaltyEvent` rows keyed by `unique_key`, agent leaderboard rollup, `/api/rewards/{events,summary,sweep}/` endpoints (admin/director only for events / summary / sweep), `python manage.py calculate_reward_penalties` (cron-friendly, supports `--order-id` and `--dry-run`), `apps.rewards.tasks.run_reward_penalty_sweep_task` (Celery eager-mode safe), Rewards page now shows agent-wise leaderboard + order-wise scoring events + sweep summary cards + Run Sweep button.
- ✅ **Phase 4C** — Approval Matrix Middleware enforcement (`apps/ai_governance/approval_engine.py`): `ApprovalRequest` + `ApprovalDecisionLog` models, `evaluate_action` / `enforce_or_queue` / `approve_request` / `reject_request` / `request_approval_for_agent_run`. 5 new admin/director endpoints under `/api/ai/approvals/...` and `/api/ai/agent-runs/{id}/request-approval/`. Live enforcement gating custom-amount payment links, prompt activation, and sandbox disable. CAIO never executes (refused at the bridge AND at the matrix evaluator). Governance page upgraded with an Approval queue table + Approve / Reject controls.

**Next:**

- ⏭ **Phase 4D** — Approved Action Execution Layer. Adds `POST /api/ai/approvals/{id}/execute/` over an allow-listed registry that maps each authorized matrix `action` key to a tested service-layer function. Hard stops locked: CAIO never executes, Claim Vault stays mandatory, no autonomous AI execution, **no ad-budget changes**, **no refunds**, **no live WhatsApp**, no silent complex writes (unmapped actions → HTTP 400 + `ai.approval.execution_skipped` audit), idempotent re-execute, director-only override on `director_override` actions. Plan in `docs/FUTURE_BACKEND_PLAN.md`.
- ⏭ **Phase 4A** — Real-time WebSockets (Django Channels pushing AuditEvent rows live).
- ⏭ **WhatsApp** — Live Business Cloud API sender (consent-gated, Claim-Vault-grounded). Phase 3E ships only the design scaffold.

Full roadmap with acceptance criteria: [`docs/FUTURE_BACKEND_PLAN.md`](docs/FUTURE_BACKEND_PLAN.md).
Detailed handoff: [`nd.md`](nd.md).

## Stack

**Frontend:** React 18, Vite, TypeScript, Tailwind, shadcn UI, React Router, Recharts, Vitest

**Backend:** Python 3.10+, Django 5.1, Django REST Framework, simplejwt, django-cors-headers, dj-database-url, razorpay, requests (lazy import for Delhivery / Vapi test/live), pytest

## License

Proprietary — Nirogidhara Private Limited. Internal use only.
