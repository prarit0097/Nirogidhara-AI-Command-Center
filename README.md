# Nirogidhara AI Command Center

AI Business Operating System for Ayurveda sales, CRM, AI calling, payments,
Delhivery delivery tracking, RTO control, AI agents, CEO AI, CAIO governance,
reward/penalty engine, and the human-call learning loop.

> Full vision: see [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md) — Master Blueprint v2.0 (the v1.0 PDF is historical reference only).

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
# Backend migration drift gate — MUST report "No changes detected"
cd backend && python manage.py makemigrations --check --dry-run

# Backend (pytest, 656 tests)
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
- ✅ **Phase 5F-Gate Hardening Hotfix** — post-live-pass diagnostics layer. The live one-number gate passed (`nrg_greeting_intro` outbound `WAM-100003` delivered to phone, inbound `WAM-100004` "Namaste webhook test" stored after the WABA `subscribed_apps` empty-list issue was fixed via `POST` + override-callback). Three gaps closed: (1) the duplicate-idempotency unique-constraint crash now returns clean JSON with `duplicateIdempotencyKey=true` + `existingMessageId` + `alreadyQueued`/`alreadySent` + a new `whatsapp.meta_test.duplicate_idempotency` audit row; (2) `--check-webhook-config` now also runs `GET /{WABA}/subscribed_apps` and reports `wabaSubscriptionActive` / `wabaSubscribedAppCount` + a new `whatsapp.meta_test.webhook_subscription_checked` audit row; (3) new strictly-read-only `python manage.py inspect_whatsapp_live_test --phone +91XXXXXXXXXX --json` surfaces customer / consent / conversation / latest messages / webhook envelopes / status events / WABA subscription / latest `whatsapp.*` audit rows + a typed `nextAction`. Never sends, never mutates DB, never prints tokens. **13 new backend tests; 656 backend + 13 frontend, all green.** Phase 5F remains LOCKED until the inspector reports `gate_hardened_ready_for_limited_ai_auto_reply_plan` on a real VPS run.
- ✅ **Phase 5F-Gate** — Limited Live Meta WhatsApp One-Number Test harness. New `apps.whatsapp.meta_one_number_test` module + `python manage.py run_meta_one_number_test` command verify real Meta Cloud sends against exactly one approved test number. Hard stops stacked: provider must be `meta_cloud`, `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`, destination must be in `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`, template must be APPROVED + active + UTILITY/AUTHENTICATION (MARKETING tier refused), every automation flag must remain off. Default `--dry-run`; `--send` is required for a real dispatch and refuses on any amber gate. Eight new audit kinds (`whatsapp.meta_test.{started,config_ok,config_failed,blocked_number,template_missing,sent,failed,completed}`); audit payloads NEVER carry tokens. **24 new backend tests; 643 backend + 13 frontend, all green.** Phase 5F (broadcasts / campaigns) remains LOCKED until this gate passes live.
- ✅ **Phase 5E-Smoke-Fix-3** — False-positive safety classification fix. New `apps.whatsapp.safety_validation.validate_safety_flags(inbound_text, safety_flags)` runs server-side just before `_safety_block` and downgrades any `sideEffectComplaint` / `medicalEmergency` / `legalThreat` flag whose vocabulary is absent from the inbound text (English + Hindi + Hinglish keyword sets). Real safety phrases (`medicine khane ke baad ulta asar`, `chest pain`, `consumer forum`) stay flagged exactly as the LLM said; the corrector never promotes false→true and never touches `angryCustomer` / `claimVaultUsed`. New audit kind `whatsapp.ai.safety_downgraded` makes every correction observable. The LLM prompt now carries an explicit `SAFETY FLAG DISCIPLINE` block listing required vocabulary per flag. **28 new backend tests; 619 backend + 13 frontend, all green.** VPS rebuild required so the new orchestrator + prompt land in the container.
- ✅ **Phase 5E-Smoke-Fix-2** — OpenAI Chat Completions token-parameter hotfix. Modern Chat models (gpt-4o, gpt-5, o1, o3, …) reject the legacy `max_tokens` parameter; adapter now always sends `max_completion_tokens` via the new testable `build_request_kwargs()` helper. **10 new backend tests; 591 backend + 13 frontend, all green.** VPS rebuild required so the new adapter code lands in the container.
- ✅ **Phase 5E-Smoke-Fix** — OpenAI SDK (`openai>=1.0,<2.0`) added to `backend/requirements.txt` so the AI provider chain has a real SDK to import on every deploy. Smoke harness `ai-reply` scenario now reports `openaiAttempted` / `openaiSucceeded` / `providerPassed` / `safeFailure` — a safe-failure (adapter raised but customer send stayed blocked) no longer reports `overallPassed=true` so operators can't miss a broken provider integration. Pre-seeds an outbound on the smoke conversation so the greeting fast-path no longer bypasses LLM dispatch. **6 new backend tests; 579 backend + 13 frontend, all green.** VPS rebuild required after the requirements.txt change.
- ✅ **Phase 5E-Smoke** — Controlled Mock + OpenAI Smoke Testing Harness. New `apps.whatsapp.smoke_harness` + `python manage.py run_controlled_ai_smoke_test --scenario {ai-reply|claim-vault|rescue-discount|vapi-handoff|reorder-day20|all}` exercise the AI orchestrator, Claim Vault gates, 50% cumulative discount cap, Vapi handoff, and Day-20 reorder without sending any real customer message. Defaults are SAFE (dry-run + mock-WhatsApp + mock-Vapi + OpenAI off). Refuses real Meta provider outright. Four new audit kinds (`system.smoke_test.{started,completed,failed,warning}`). `--json` flag for CI / log scraping. **23 new backend tests; 573 backend + 13 frontend, all green.**
- ✅ **Phase 5E-Hotfix-2** — Strengthen demo Claim Vault seed coverage. Adds four universal safe usage-guidance phrases (use as directed on the label / hydration + balanced diet / consult doctor for serious cases / discontinue on adverse reaction) merged into every demo entry; widens `USAGE_HINT_KEYWORDS` so the coverage detector matches the new phrasing. Bumps the demo marker to `version="demo-v2"`; `--reset-demo` upgrades demo-v1 rows. All 8 categories now report `risk=demo_ok` (not `weak`). Real admin / doctor-approved rows are still never overwritten. Production still needs real doctor-approved final claims before full live rollout; automation flags remain OFF.
- ✅ **Phase 5E-Hotfix** — Sync Phase 5D / 5E migration index names. Two new `RenameIndex` migrations (`apps/orders/migrations/0004_rename_orders_disc_*` + `apps/whatsapp/migrations/0004_rename_whatsapp_wh_*`) bring the hand-rolled Phase 5D / 5E index names in line with Django's auto-suffix names. Pure metadata renames; no schema rewrite. Release checklist now includes `python manage.py makemigrations --check --dry-run` so this drift never lands again.
- ✅ **Phase 5E** — Rescue Discount Flow + Day-20 Reorder + Default Claim Vault Seeds. New `apps.orders.rescue_discount` is the single source of truth for AI rescue discount math: cumulative 50% absolute hard cap across all stages, per-stage ladder (confirmation 5/10/15, delivery 5/10, RTO 10/15/20 + high-risk step-up, reorder 5), and automatic CEO AI / admin escalation via two new matrix rows when an offer is over the auto band or over the cap. Every offer (offered / accepted / rejected / blocked / skipped / `needs_ceo_review`) writes an append-only `DiscountOfferLog` row + 6 new `discount.offer.*` audit kinds. Customer acceptance applies via `apps.orders.services.apply_order_discount` only. Lifecycle service routes confirmation / delivery / RTO refusals + Day-20 reorder through Phase 5A's `queue_template_message` (consent + Claim Vault + matrix + CAIO + idempotency unchanged) and emits dedicated `whatsapp.lifecycle.rescue_discount_{queued,sent}` + `whatsapp.lifecycle.reorder_day20_{queued,sent}` audits. Day-20 reorder sweep covers delivered orders 20–27 days old via `python manage.py run_reorder_day20_sweep` + Celery `run_reorder_day20_sweep_task`. New `python manage.py seed_default_claims [--reset-demo]` sows conservative non-cure / non-guarantee Claim Vault rows for the eight current categories; demo rows are flagged `version="demo-v1"` and surface in coverage as `risk=demo_ok` with a "replace before live rollout" note. Five new endpoints (`/api/orders/{id}/discount-offers/`, `/rescue/`, `/{id}/{accept,reject}/`, `/api/whatsapp/reorder/day20/{status,run}/`). Four new env vars (all default safe). Frontend adds a Rescue Discount cap card to the AI panel + new TS types + six new api methods. Hard stops still: never above 50% cumulative; never on reorder upfront; CAIO never originates offers; no shipment from chat / no campaigns / no refunds / no ad-budget execution. **38 new backend tests, 13 frontend tests, all green (536 backend total).**
- ✅ **Phase 5D** — Chat-to-Call Handoff + Lifecycle Automation. New `apps.whatsapp.call_handoff.trigger_vapi_call_from_whatsapp` is the single entry that may dial Vapi from a WhatsApp conversation; goes through the existing `apps.calls.services.trigger_call_for_lead` Vapi service path (never the adapter). Idempotent on `(conversation, inbound_message, reason)` via the new `WhatsAppHandoffToCall` model. Safety reasons (medical_emergency / side_effect_complaint / legal_threat) record a `skipped` row and never auto-dial — a doctor / admin picks up the call manually. Operator manual trigger at `POST /api/whatsapp/conversations/{id}/handoff-to-call/` (operations+). AI-booked orders move directly into the confirmation queue (`book_order_from_decision` → `move_to_confirmation`); failure flips `confirmationMoveFailed=true` in metadata but never loses the order. New `apps.whatsapp.lifecycle` + `apps.whatsapp.signals` route Order/Payment/Shipment `post_save` events into approved templates (`whatsapp.confirmation_reminder`, `whatsapp.payment_reminder`, `whatsapp.delivery_reminder`, `whatsapp.usage_explanation`, `whatsapp.rto_rescue`) through Phase 5A's `queue_template_message`; idempotent on `lifecycle:{action}:{type}:{id}:{event}`. New Claim Vault coverage audit: `apps.compliance.coverage`, `python manage.py check_claim_vault_coverage`, and admin-only `GET /api/compliance/claim-coverage/`. Three new endpoints (handoff-to-call, handoffs list, lifecycle-events list). Eleven new audit kinds. Four new env vars (all default safe — handoff/lifecycle OFF, limited-test-mode ON). Frontend adds a "Call customer" button to the AI panel + `WhatsAppHandoffToCall` / `WhatsAppLifecycleEvent` / `ClaimVaultCoverageReport` types + four new api methods. Hard stops: no shipment from chat, no campaigns, no refunds, no ad-budget execution. **29 new backend tests, all green (498 total). 13 frontend tests, all green.**
- ✅ **Phase 5C** — WhatsApp AI Chat Sales Agent. New `apps.whatsapp.ai_orchestration` runs on every inbound: language detection (Hindi / Hinglish / English), locked Hindi greeting via approved UTILITY template, OpenAI dispatch through the existing `apps.integrations.ai.dispatch` chain, strict JSON schema validator, Claim Vault grounding, blocked-phrase filter, discount discipline (no upfront / 2–3 push minimum / 50% total cap), order booking via `apps.orders.services.create_order` + ₹499 advance link via `apps.payments.services.create_payment_link`, and auto-send rate gates. Six new endpoints under `/api/whatsapp/ai/...` and per-conversation `ai-mode / run-ai / ai-runs / handoff / resume-ai`. 18 new audit kinds. Frontend ships an AI Chat Agent panel inside the inbox (mode toggle / language + category pill / confidence / Run AI / Handoff / Resume) + AI Auto badge on AI-generated messages. Auto-reply defaults to OFF (`WHATSAPP_AI_AUTO_REPLY_ENABLED=false`); ops flips it true after verification. Hard stops still in force: no medical-emergency replies, no freeform claims, no CAIO send, no shipment from chat. **35 new backend tests + 13 frontend tests, all green.**
- ✅ **Phase 5B** — Inbound WhatsApp Inbox + Customer 360 Timeline. New `WhatsAppInternalNote` model + migration. Six new endpoints: `GET /api/whatsapp/inbox/` (conversations + counts + AI-suggestions-disabled placeholder), `PATCH /api/whatsapp/conversations/{id}/` (safe fields: status / assignedToId / tags / subject), `POST /api/whatsapp/conversations/{id}/mark-read/`, `GET + POST /api/whatsapp/conversations/{id}/notes/`, `POST /api/whatsapp/conversations/{id}/send-template/` (routes through Phase 5A `queue_template_message`), `GET /api/whatsapp/customers/{customer_id}/timeline/` (WhatsApp-only items). Six new audit kinds. Frontend ships a three-pane `/whatsapp-inbox` page (filter sidebar / conversation list / thread + internal notes + AI-disabled placeholder + manual template send modal) with live refresh via Phase 4A `connectAuditEvents` filtered on `whatsapp.*`, plus a Customer 360 WhatsApp tab. **AI auto-reply stays disabled.** Operations users can manually send approved templates; backend gates remain final. **33 new backend tests + 13 frontend tests all green.**

**Next:**

- ⏭ **Phase 5F** — Director-approved broadcast / sales campaigns (gated, MARKETING template tier).
- ⏭ **Phase 6** — Recording / QA / learning loop pipeline (speech-to-text → compliance review → CAIO audit → sandbox test → live promotion).

## Documentation index

| File | What it is |
| --- | --- |
| [`nd.md`](nd.md) | Operational handoff and **single source of truth** for the project state. Read this first. |
| [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md) | **Master Blueprint v2.0** — current strategic blueprint (supersedes the v1.0 PDF, which is historical only). |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Local dev / run commands. |
| [`docs/DEPLOYMENT_VPS.md`](docs/DEPLOYMENT_VPS.md) | Production deployment runbook (`/opt/nirogidhara-command`). |
| [`docs/BACKEND_API.md`](docs/BACKEND_API.md) | Endpoint reference. |
| [`docs/FRONTEND_AUDIT.md`](docs/FRONTEND_AUDIT.md) | Frontend page status + open improvements. |
| [`docs/FUTURE_BACKEND_PLAN.md`](docs/FUTURE_BACKEND_PLAN.md) | Phased roadmap with acceptance criteria. |
| [`docs/WHATSAPP_INTEGRATION_PLAN.md`](docs/WHATSAPP_INTEGRATION_PLAN.md) | WhatsApp + AI Chat Sales Agent design plan. |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | AI agent guardrails (read on every session). |

Full roadmap with acceptance criteria: [`docs/FUTURE_BACKEND_PLAN.md`](docs/FUTURE_BACKEND_PLAN.md).
Detailed handoff: [`nd.md`](nd.md).
Strategic blueprint: [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md).

## Stack

**Frontend:** React 18, Vite, TypeScript, Tailwind, shadcn UI, React Router, Recharts, Vitest

**Backend:** Python 3.10+, Django 5.1, Django REST Framework, simplejwt, django-cors-headers, dj-database-url, razorpay, requests (lazy import for Delhivery / Vapi test/live), pytest

## License

Proprietary — Nirogidhara Private Limited. Internal use only.
