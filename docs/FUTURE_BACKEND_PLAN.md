# Backend Roadmap (Phase 2+)

Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B are shipped (see `nd.md` §8 for the full checkpoint trail).
Phase 3 env scaffolding is in place. Real AI-agent reasoning, the remaining
gateway integrations, and the full governance UI live in the phases below —
ordered per blueprint Section 25 (`CRM → Workflow → Integrations → Voice AI →
Agents → Governance → Learning → Reward/Penalty → Growth → SaaS`).

Each phase is shippable on its own. None of it is required to keep the
frontend working today (the mock-fallback in `services/api.ts` keeps every
page rendering even if the backend is offline).

## ✅ Phase 2A — Core Write APIs + Workflow State Machine (DONE)

Shipped in commit `82f1a60`. 13 write endpoints (lead create/update/assign,
customer upsert, order create/transition/move-to-confirmation/confirm, mock
shipment, RTO rescue create/update). Role-based permissions
(`apps/accounts/permissions.py`) — anonymous → 401, viewer → 403, ops/admin/
director → allowed. Order state machine in `apps/orders/services.py`. Service-
layer pattern across CRM / orders / payments / shipments. 18 new pytest tests.

## ✅ Phase 2B — Razorpay Payment Links (DONE)

Shipped in commit `82f1a60`. Three-mode adapter
(`apps/payments/integrations/razorpay_client.py`): `mock` (default, no
network), `test` (Razorpay sandbox), `live` (production). HMAC-verified,
idempotent webhook receiver at `/api/webhooks/razorpay/` handling
`payment_link.paid`, `partially_paid`, `cancelled`, `expired`,
`payment.failed`, `refund.processed`. 13 new pytest tests covering all event
flows + signature verification.

## ✅ Phase 2C — Delhivery Courier API + Tracking Webhook (DONE)

Shipped via `feat: add delhivery shipment integration adapter`.
Three-mode adapter (`apps/shipments/integrations/delhivery_client.py`):
`mock` (default, deterministic `DLH<8 digits>` AWB, no network), `test`
(Delhivery staging), `live` (production). The `_create_via_sdk` path lazy-
imports `requests` so mock dev works without the dependency. HMAC-verified,
idempotent webhook receiver at `/api/webhooks/delhivery/` (`X-Delhivery-
Signature`) handling `pickup_scheduled`, `picked_up`, `in_transit`,
`out_for_delivery`, `delivered`, `ndr`, `rto_initiated`, `rto_delivered`.
NDR / RTO transitions bump `Order.rto_risk` to High and write danger-tone
audit rows. 13 new pytest tests covering all event flows + signature
verification. Reuses `payments.WebhookEvent` for cross-gateway idempotency
(its `gateway` field accepts arbitrary strings).

## ✅ Phase 2D — Vapi Voice Trigger + Transcript Ingest (DONE)

Shipped via `feat: add vapi call trigger and transcript ingest`.
Three-mode adapter (`apps/calls/integrations/vapi_client.py`): `mock`
(default, deterministic provider call id, no network), `test` (Vapi
staging), `live` (production). Lazy `requests` import keeps mock dev
free of the dependency. New endpoint `POST /api/calls/trigger/` returns
`{ callId, provider, status, leadId, providerCallId }`. HMAC-verified
(when `VAPI_WEBHOOK_SECRET` is set), idempotent webhook receiver at
`/api/webhooks/vapi/` handling `call.started`, `call.ended`,
`transcript.updated`, `transcript.final`, `analysis.completed`,
`call.failed`. Six handoff flags (medical_emergency,
side_effect_complaint, very_angry_customer, human_requested,
low_confidence, legal_or_refund_threat) are persisted on `Call.handoff_flags`
with a keyword fallback when Vapi omits the explicit flag list. Per-call
transcripts are stored on `CallTranscriptLine.call` (the legacy FK was
renamed to `active_call` to keep the live console intact). 14 new pytest
tests cover mock + test-mode adapter, auth/role gating, every webhook
event, idempotency, signature verification, audit firing.

**Compliance**: Vapi adapter passes only metadata in the call payload;
medical text is configured server-side in Vapi's dashboard. Any future
prompt-builder MUST pull from `apps.compliance.Claim` only.

## ✅ Phase 2E — Meta Lead Ads Webhook (DONE)

Shipped via `feat: add meta lead ads webhook`. Three-mode adapter
(`apps/crm/integrations/meta_client.py`): `mock` (default — parses the
inbound webhook body directly, no network), `test` (Graph API
expansion of each `leadgen_id`), `live` (production). The `_fetch_lead_via_graph`
path lazy-imports `requests` so mock dev works without the dependency.

`GET /api/webhooks/meta/leads/` answers Meta's subscription handshake when
`hub.mode == "subscribe"` and `hub.verify_token == META_VERIFY_TOKEN`.
`POST /api/webhooks/meta/leads/` verifies `X-Hub-Signature-256` against
`META_WEBHOOK_SECRET` (falls back to `META_APP_SECRET`); empty secret →
signature check skipped so dev fixtures stay simple. Each delivered lead
upserts a `Lead` row and writes a `lead.meta_ingested` AuditEvent.
Idempotency uses `crm.MetaLeadEvent` (PK = `leadgen_id`); duplicate
deliveries return 200 with `action: duplicate` and never duplicate the
Lead. Existing leads with the same `leadgen_id` are refreshed in place.

`Lead` model gains `meta_leadgen_id`, `meta_page_id`, `meta_form_id`,
`meta_ad_id`, `meta_campaign_id`, `source_detail`, `raw_source_payload`
(migration `0002_phase2e_meta_fields`). Frontend `Lead` type widened with
those same fields, all optional.

13 new pytest tests cover GET handshake (pass / wrong token / unset
token), POST mock create, idempotency, signature verification (good /
bad / missing / app-secret fallback), AuditEvent firing, test-mode
Graph API expansion (patched), refresh-not-duplicate, signature helper
round-trip, empty payload.

## Phase 2 — Other gateways (slot when needed)

| Item | Notes |
| --- | --- |
| PayU payment links | Same shape as Razorpay; `gateway` flag in `PaymentLinkSerializer` already accepts it — only the adapter is missing. |
| Delhivery test-mode credentials | Code path is wired; just needs a real test API token + a pickup location registered with Delhivery to flip `DELHIVERY_MODE=test`. |
| Meta test-mode credentials | Code path is wired; just needs a real Meta app + page access token to flip `META_MODE=test`. |
| WhatsApp Business outbound + consent | Blueprint §24 lists this as a clarification — design first, build later. |

## ✅ Phase 3A — AgentRun foundation + provider adapters (DONE)

Shipped via `feat: add agent run foundation`.

- `AgentRun` model (`apps/ai_governance/models.py`) — id, agent, prompt_version,
  input/output payload, status (pending/success/failed/skipped), provider,
  model, latency_ms, cost_usd, error_message, dry_run, triggered_by,
  created_at, completed_at. Migration `0002_agentrun`.
- Provider adapters under `apps/integrations/ai/`:
  `base.py` (Adapter Protocol, AdapterResult dataclass, `skipped_result`),
  `openai_client.py`, `anthropic_client.py`, `grok_client.py` (Grok reuses the
  OpenAI SDK pointed at `https://api.x.ai/v1`). All adapters lazy-import
  their SDK and short-circuit with `skipped` when `config.enabled` is False.
  `dispatch.py` is the single seam the agent service calls.
- Prompt builder (`apps/ai_governance/prompting.py`) assembles a fixed
  system policy block, agent role block, Approved Claim Vault grounding,
  and the JSON-coerced input payload. `ClaimVaultMissing` is raised when a
  medical/product run has no approved claims — the call site logs a
  `failed` AgentRun rather than dispatching a hallucinated answer.
- Services (`apps/ai_governance/services.py`): `create_agent_run`,
  `complete_agent_run`, `fail_agent_run`, and the high-level
  `run_readonly_agent_analysis` which builds prompt → dispatches → persists.
  CAIO is hard-stopped: payloads carrying `execute`, `apply`, `create_order`,
  `transition` (etc.) are refused before any LLM call.
- New endpoint `POST /api/ai/agent-runs/` (admin/director only). Phase 3A
  always coerces `dryRun` to `true` — non-dry-run requests fail with a row
  pointing at the Phase 5 approval-matrix milestone.
- `GET /api/ai/agent-runs/` and `/{id}/` are admin/director-only audit reads.
- `audit.signals.ICON_BY_KIND` extended with `ai.agent_run.created`,
  `ai.agent_run.completed`, `ai.agent_run.failed`.
- Frontend `AgentRun` type + `api.listAgentRuns()` / `getAgentRun()` /
  `createAgentRun()` (offline-safe optimistic stub returns a `skipped`
  draft so dev never crashes when the backend is offline).
- 25 new pytest tests cover provider routing (disabled/openai/anthropic/grok
  with patched adapters — real SDKs never imported), auth/role gating,
  CAIO no-execute, prompt-builder Claim Vault enforcement, audit firing,
  and the dry-run guard.

## ✅ Phase 3B — Per-agent runtime services (DONE)

Shipped via `feat: add per-agent runtime services`.

- Per-agent service modules under `apps/ai_governance/services/agents/`:
  `ceo.py`, `caio.py`, `ads.py`, `rto.py`, `sales_growth.py`, `cfo.py`,
  `compliance.py`. Each exposes `build_input_payload()` (safe DB read)
  and `run(triggered_by="")` that dispatches through
  `run_readonly_agent_analysis`. None of them write to business state —
  the only side effects are `AgentRun` rows + audit ledger entries +
  `CeoBriefing` refresh on the CEO success path.
- 8 new endpoints under `/api/ai/agent-runtime/*` (admin/director only):
  status snapshot + 7 POST routes (one per agent). Every call returns
  the persisted `AgentRun`.
- Management command `python manage.py run_daily_ai_briefing` calls the
  CEO + CAIO sweeps in one shot (`--skip-ceo` / `--skip-caio` flags).
  No Redis / Celery dependency — wire to cron or Windows Task Scheduler
  directly. Phase 3C upgrades to a Celery beat schedule once Redis is
  available in the ops environment.
- 4 new audit kinds: `ai.ceo_brief.generated`, `ai.caio_sweep.completed`,
  `ai.agent_runtime.completed`, `ai.agent_runtime.failed`.
- Frontend `AgentRuntimeStatus` type + `api.getAgentRuntimeStatus()` and
  one method per agent runtime endpoint with offline-safe optimistic stubs.
- 26 new pytest tests cover each agent's payload shape, the success path
  for CEO refreshing the CeoBriefing row, the skipped path leaving it
  unchanged, the compliance fail-closed when the vault is empty, the
  permission gates (anonymous / viewer / operations all blocked, admin
  / director allowed), the status endpoint, the management command (with
  `--skip-caio` variant), and the audit-event firing.

## Phase 3C — Background scheduler + cost tracking (NEXT)

- Celery beat schedule that fires the management command once a day.
- Per-provider cost tracking (token usage → USD) populating
  `AgentRun.cost_usd`.
- Provider fall-back chains (e.g. OpenAI → Anthropic on rate-limit).
- Sandbox mode toggle (Section 12.2) and prompt version rollback (12.3).

## Phase 4 — Real-Time

- Django Channels + WebSockets to push `AuditEvent` rows to subscribed
  dashboards.
- Replace polling on the dashboard's activity feed.
- Frontend already polls via React Query — adding push is purely additive.

## Phase 5 — Governance UI write paths

- Kill switch toggle endpoints (Section 12.1).
- Prompt rollback (Section 12.3).
- Reward/penalty engine — actually compute Section 10.2 from event ledger.
- Approval matrix enforcement — middleware that blocks risky actions until
  CEO AI / Prarit approves.

## Phase 6 — Learning loop

- Recording upload → speech-to-text → speaker separation pipeline.
- QA scoring → Compliance review → CAIO audit workflow tables.
- Sandbox test infrastructure.
- Approved learning → playbook version update.

## Phase 7 — Multi-tenant SaaS

- Tenant model + middleware that scopes every queryset.
- Per-tenant settings, integrations, claim vault.
- Billing.

## Out of scope forever (or until explicitly requested)

- Implementing the full reward formula in JS / pushing it to the frontend.
- Mobile push notifications.
- E2E Playwright suite (the prototype phase doesn't need it).
