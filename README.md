# Nirogidhara AI Command Center

AI Business Operating System for Ayurveda sales, CRM, AI calling, payments,
Delhivery delivery tracking, RTO control, AI agents, CEO AI, CAIO governance,
reward/penalty engine, and the human-call learning loop.

> Full vision: see *Nirogidhara AI Command Center — Master Blueprint v1.0*.

## Monorepo layout

```
nirogidhara-command/
  frontend/   # React 18 + Vite + TS + shadcn UI (21 pages)
  backend/    # Django 5 + DRF — 16 apps, implements the api.ts contract
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

## Production deploy — live at [`ai.nirogidhara.com`](https://ai.nirogidhara.com)

- **Live URL:** <https://ai.nirogidhara.com> · **Health:** <https://ai.nirogidhara.com/api/healthz/>
- **VPS folder:** `/opt/nirogidhara-command` on a Hostinger VPS (host port `18020 → 80`).
- **Stack:** isolated Docker Compose with 6 containers (`nirogidhara-db / -redis / -backend / -worker / -beat / -nginx`) — namespaced so it does not collide with Postzyo / OpenClaw on the same VPS.
- **TLS:** Let's Encrypt via Certbot, fronted by host Ubuntu Nginx.

Update an existing deploy:

```bash
ssh root@<vps>
cd /opt/nirogidhara-command
git pull origin main
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --pull never
```

Greenfield deploy + every operational command (DNS, TLS, smoke tests,
backups, troubleshooting — including the duplicate-index recovery for
the `calls.0002_phase2d_vapi_fields` migration): see
[`docs/DEPLOYMENT_VPS.md`](docs/DEPLOYMENT_VPS.md). The locked
production reference (URL / paths / commands / what stays mock-mode)
is also in [`nd.md`](nd.md) §17.

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
# Backend (pytest, 434 tests)
cd backend && python -m pytest -q

# Frontend (vitest, 13 tests)
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
- ✅ **Phase 4D** — Approved Action Execution Layer (`apps/ai_governance/approval_execution.py`): `ApprovalExecutionLog` model with one-executed-per-request constraint, `POST /api/ai/approvals/{id}/execute/` endpoint, **allow-listed registry of 3 handlers** (`payment.link.advance_499`, `payment.link.custom_amount`, `ai.prompt_version.activate`). Every other approved action returns HTTP 400 + `ai.approval.execution_skipped` audit. CAIO blocked at engine + bridge + execute layer; idempotent re-execute returns prior result; director-only override on `director_override`. Governance page now shows an Execution column + Execute button on approved rows.
- ✅ **Phase 4A** — Real-time AuditEvent WebSockets via Django Channels: `ws://<host>/ws/audit/events/` carries the **full stored `AuditEvent.payload`**, Dashboard "Live Activity" feed and Governance "Approval queue" auto-refresh on relevant audit kinds, existing polling endpoints (`/api/dashboard/activity/`, `/api/ai/approvals/`) remain as fallback. Frontend `services/realtime.ts` derives the WS origin from `VITE_API_BASE_URL` (or `VITE_WS_BASE_URL` override), reconnects with exponential backoff, deduplicates by id. Local dev defaults to the in-memory channel layer; production uses `CHANNEL_LAYER_BACKEND=redis` + `CHANNEL_REDIS_URL=redis://...:6379/2`.
- ✅ **Phase 4E** — Expanded Approved Execution Registry. Adds 3 new handlers: `discount.up_to_10`, `discount.11_to_20` (route through new `apps.orders.services.apply_order_discount`; only `Order.discount_pct` is mutated; validates via Phase 3E `validate_discount`), `ai.sandbox.disable` (Director-only via matrix `director_override`; idempotent on already-off). `discount.above_20` + ad-budget + refund + WhatsApp + production-live-mode-switch all remain unmapped → HTTP 400 + `ai.approval.execution_skipped`. CAIO blocked at engine + bridge + execute layer.
- ✅ **Phase 5A-0** (doc-only): WhatsApp compatibility audit of [`prarit0097/Whatsapp-sales-dashboard`](https://github.com/prarit0097/Whatsapp-sales-dashboard) → integration plan in [`docs/WHATSAPP_INTEGRATION_PLAN.md`](docs/WHATSAPP_INTEGRATION_PLAN.md). Locked: production target is Meta Cloud API (the reference repo's Meta Cloud provider is stubbed); Baileys is dev/demo only.
- ✅ **Phase 5A-1** (doc-only): **WhatsApp AI Chat Agent + Discount Rescue Policy Addendum** (sections S–GG of the integration plan). WhatsApp scope widens from "lifecycle reminder sender" to **inbound-first AI Chat Sales Agent + lifecycle messaging**. Locked: greeting rule (fixed Hindi UTILITY template), address collection in chat, category detection before product text, chat-to-call handoff, **AI never offers discount upfront** (rescue-only), **50% total-discount hard cap**.
- ✅ **Phase 5A** — WhatsApp Live Sender Foundation: new `apps.whatsapp` Django app (8 models — `WhatsAppConnection` / `Template` / `Consent` / `Conversation` / `Message` / `MessageAttachment` / `MessageStatusEvent` / `WebhookEvent` / `SendLog`), provider interface + 3 implementations (`mock` default for tests, `meta_cloud` Nirogidhara-built Graph client, `baileys_dev` dev-only stub that refuses to load when DEBUG=False), service layer (`queue_template_message` + `send_queued_message`) gating consent + approved template + Claim Vault + approval matrix + CAIO hard stop + idempotency, Celery task with `autoretry_for=ProviderError, retry_backoff, retry_jitter, max_retries=5`, signed webhook at `/api/webhooks/whatsapp/meta/` (HMAC-SHA256 + replay-window + provider-event-id idempotency + Meta GET handshake), 9 read + 4 write API endpoints under `/api/whatsapp/`, `python manage.py sync_whatsapp_templates` command, frontend Settings → WABA section + read-only `/whatsapp-templates` page + sidebar entry. Failed sends never mutate Order/Payment/Shipment. **50 new backend tests + 13 frontend tests all green.**
- ✅ **Phase 5B** — Inbound WhatsApp Inbox + Customer 360 Timeline. New `WhatsAppInternalNote` model + migration. Six new endpoints: `GET /api/whatsapp/inbox/` (conversations + counts + AI-suggestions-disabled placeholder), `PATCH /api/whatsapp/conversations/{id}/` (safe fields: status / assignedToId / tags / subject), `POST /api/whatsapp/conversations/{id}/mark-read/`, `GET + POST /api/whatsapp/conversations/{id}/notes/`, `POST /api/whatsapp/conversations/{id}/send-template/` (routes through Phase 5A `queue_template_message`), `GET /api/whatsapp/customers/{customer_id}/timeline/` (WhatsApp-only items). Six new audit kinds. Frontend ships a three-pane `/whatsapp-inbox` page (filter sidebar / conversation list / thread + internal notes + AI-disabled placeholder + manual template send modal) with live refresh via Phase 4A `connectAuditEvents` filtered on `whatsapp.*`, plus a Customer 360 WhatsApp tab. **AI auto-reply stays disabled.** Operations users can manually send approved templates; backend gates remain final. **33 new backend tests + 13 frontend tests all green.**

**Next:**

- ⏭ **Phase 5C–5F** — WhatsApp AI Chat Sales Agent with Claim-Vault-bound LLM + `learned_memory.py` ported wholesale (5C); chat-to-call handoff + lifecycle automation (5D); confirmation/delivery/RTO/reorder automation with rescue-discount flow + 50% cap enforcement in code (5E); approval-gated campaigns (5F).

Full roadmap with acceptance criteria: [`docs/FUTURE_BACKEND_PLAN.md`](docs/FUTURE_BACKEND_PLAN.md).
Detailed handoff: [`nd.md`](nd.md).

## Stack

**Frontend:** React 18, Vite, TypeScript, Tailwind, shadcn UI, React Router, Recharts, Vitest

**Backend:** Python 3.10+, Django 5.1, Django REST Framework, simplejwt, django-cors-headers, dj-database-url, razorpay, requests (lazy import for Delhivery / Vapi test/live), pytest

## License

Proprietary — Nirogidhara Private Limited. Internal use only.
