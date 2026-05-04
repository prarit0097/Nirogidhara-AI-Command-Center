# Backend Roadmap (Phase 2+)

## Current SaaS runtime gate status

Phase 6G Controlled Runtime Routing Dry Run + AI Provider Routing is
**FULL PASS**. Phase 6H Live Audit Gate, Phase 6I Single Internal Live
Gate Simulation, Phase 6J Single Internal Provider Test Plan, Phase 6K-A
Single Internal Razorpay Test-Mode Execution Gate, Phase 6K-B (one-shot
real Razorpay test-mode execution on the VPS — `pex_8f309650e9644cfaae4418f9`
→ `order_Sks3KPf0vntKhf`, ₹1.00, rolled back), Phase 6L Razorpay Test
Execution Audit Review + Webhook Readiness Plan, Phase 6M-0 MCP Gateway
Foundation (dormant), and Phase 6M Razorpay Webhook Handler (test-mode,
dormant by default) all ✅ shipped. Default live execution remains blocked
(`dryRun=true`, `liveExecutionAllowed=false`,
`externalCallWillBeMade=false`, `externalCallWasMade=false`,
`providerCallAttempted=false` everywhere except the recorded Phase 6K-B
artefact), runtime providers still use env/config, the global kill switch
remains active, `MCP_ENABLED=false`, and
`RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false`.

**Phase 6O Razorpay Sandbox Status Mapping + Manual Review is FULL
PASS (sandbox-review-only).** New `RazorpaySandboxStatusReview` model
+ migration `payments.0005_phase6o_razorpay_sandbox_status_review`,
service module + 6 management commands + 7 admin/auth-protected DRF
endpoints + `/saas-admin` section + 8 audit kinds + new env flag
`RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED` (default `False`). Approving
a review only flips its `status` to `approved_for_future_phase6p`;
no business-table mutation in Phase 6O. **Next backend phase: Phase
6P — Controlled internal paid-status mutation test** (implementation-only
synthetic `Order` / `Payment` status flip, behind a NEW env flag
distinct from `RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED`, gated by an
approved Phase 6O review + Director sign-off). Do **not** enable any
sandbox env flag in production until Phase 6P implementation lands
and passes its own acceptance criteria.

Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B + 3C + 3D + 3E + 4A + 4B + 4C + 4D + 4E are shipped (see `nd.md` §8 for the full checkpoint trail).
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

## ✅ Phase 3C — Celery scheduler + cost tracking + fallback (DONE)

Shipped via `feat: add ai scheduler and cost tracking`.

- **Celery app** at `backend/config/celery.py`. Local dev uses
  `CELERY_TASK_ALWAYS_EAGER=true` (the default) so tasks run synchronously
  without Redis. Production cron runs `celery -A config worker -B`.
- **Beat schedule** fires `apps.ai_governance.tasks.run_daily_ai_briefing_task`
  at **09:00 IST** (morning) and **18:00 IST** (evening). Hours / minutes
  are env-driven so ops can shift them without code changes.
- **Local Redis dev** via `docker-compose.dev.yml` (Redis 7 alpine on
  6379). VPS Redis is **never** used in development.
- **Model-wise pricing table** at
  `backend/apps/integrations/ai/pricing.py` covering OpenAI gpt-5.x /
  gpt-4.1 family + Anthropic Claude Sonnet / Opus 4.5+. `cost_usd` is
  computed per-run via `Decimal` math; the rate sheet used at the time
  of the call is stored on every AgentRun in `pricing_snapshot`.
- **Provider fallback** in `apps/integrations/ai/dispatch.py`. The
  dispatcher walks `AI_PROVIDER_FALLBACKS` (default: `openai → anthropic`)
  left → right. ClaimVaultMissing **never** triggers a fallback — it
  fails closed before any adapter is invoked. `provider_attempts`
  records every attempt (provider / model / status / error / latency /
  tokens / cost). `fallback_used=True` whenever a non-first provider
  answered.
- **AgentRun model** extended (migration `0003_agentrun_cost_tracking`)
  with `prompt_tokens`, `completion_tokens`, `total_tokens`,
  `provider_attempts`, `fallback_used`, `pricing_snapshot`.
- **OpenAI + Anthropic adapters** extract token usage (including
  cached-input / cache-creation / cache-read variants) and compute
  `cost_usd` via the pricing table.
- **`GET /api/ai/scheduler/status/`** (admin/director only) returns the
  Celery / Redis / schedule / fallback / last-cost snapshot. Broker
  credentials are redacted before the response leaves the server.
- **5 new audit kinds**: `ai.scheduler.daily_briefing.started` /
  `.completed` / `.failed`, `ai.provider.fallback_used`, `ai.cost_tracked`.
- **Frontend Scheduler Status page** at `/ai-scheduler` (under "AI Layer"
  in the sidebar). Premium Ayurveda + AI SaaS theme. Pure read; no
  business logic; never receives a provider API key.
- 17 new pytest tests cover Celery eager mode, beat schedule env-var
  parsing, scheduler-status perms (admin allowed; viewer / operations /
  anonymous blocked), broker URL credential redaction, disabled-provider
  no-network path, cost tracking persistence, OpenAI + Anthropic
  pricing math (including cached-input / cache-write / cache-read),
  fallback triggered when OpenAI fails, no fallback when first provider
  succeeds, ClaimVaultMissing not-triggering-fallback, and CAIO hard-stop
  surviving the dispatcher refactor.

## ✅ Phase 3D — Sandbox + prompt rollback + budget guards (DONE)

Shipped via `feat: add ai sandbox prompt rollback and budget guards`.

- **PromptVersion model** — versioned prompt content per agent. DB-level
  partial-unique constraint enforces "one active per agent". The prompt
  builder (`apps.ai_governance.prompting.build_messages`) accepts an
  optional active version and overrides ``system_policy`` / ``role_prompt``
  with its content. The Claim Vault block is **always** appended on top —
  a PromptVersion CANNOT skip it.
- **AgentBudget model** — per-agent daily + monthly USD caps with
  `is_enforced` flag and `alert_threshold_pct`. Spend is computed by
  summing successful `AgentRun.cost_usd` for the agent over the period.
- **SandboxState singleton** — DB-backed toggle seeded from
  `settings.AI_SANDBOX_MODE`. While enabled, successful CEO runs do NOT
  refresh the live `CeoBriefing` row. CAIO is read-only regardless.
- **AgentRun** extended with `sandbox_mode`, `prompt_version_ref` FK,
  `budget_status`, `budget_snapshot` (migration `0004`).
- **Budget guard** in `run_readonly_agent_analysis` runs BEFORE prompt
  building and dispatch:
  1. Block when daily / monthly cap is exceeded → `failed` AgentRun +
     `ai.budget.blocked` audit. **Never triggers provider fallback.**
  2. Warning at `alert_threshold_pct` → `ai.budget.warning` audit; run
     still proceeds.
- **9 new endpoints** under `/api/ai/{sandbox,prompt-versions,budgets}/*`
  — admin/director only. Sandbox + activate + rollback all write
  audit-ledger rows.
- **7 new audit kinds**: `ai.prompt_version.{created,activated,rolled_back}`,
  `ai.sandbox.{enabled,disabled}`, `ai.budget.{warning,blocked}`.
- **Frontend Governance page** at `/ai-governance` (under "AI Layer")
  — sandbox toggle, per-agent prompt-version list with activate /
  rollback buttons, per-agent budget editor with live spend display.
  Premium Ayurveda + AI SaaS theme. Pure read/write through `api.ts`;
  no business logic; never receives provider keys.
- 15 new pytest tests cover PromptVersion CRUD + activation flip +
  rollback, sandbox-mode CeoBriefing skip, active prompt version
  injection (with Claim Vault still appended), budget block path
  (no fallback), budget warning path, ClaimVaultMissing still failing
  closed, CAIO still hard-stopped, and admin/viewer permission gates
  on every new endpoint.

## ✅ Phase 3E — Business Configuration Foundation (DONE)

Shipped via `feat: add business configuration foundation`.

- **`apps.catalog`** Django app: `ProductCategory`, `Product`, `ProductSKU` +
  Django admin (with SKU inline) + `/api/catalog/` read+write endpoints.
  Reads public; writes admin/director only. Each write fires an audit
  event (`catalog.{category,product,sku}.{created,updated}`).
- **Discount policy** at `apps/orders/discounts.py`. `validate_discount`
  encodes the locked bands: 0–10% auto, 11–20% requires CEO AI / admin /
  director approval, > 20% blocked unless director override. Director
  ceiling 50%. Negative / over-100 / unknown role → blocked.
- **Advance payment policy** at `apps/payments/policies.py`:
  `FIXED_ADVANCE_AMOUNT_INR = 499`. The `Advance` payment-link path now
  defaults to ₹499 when the caller omits `amount`.
- **Reward / Penalty scoring** at `apps/rewards/scoring.py`:
  `calculate_order_reward_penalty(order, context=None)` returns a
  capped (+100 / -100) deterministic result. Missing data is recorded
  explicitly, never invented.
- **Approval matrix** at `apps/ai_governance/approval_matrix.py`. 22-row
  policy table with read endpoint at `GET /api/ai/approval-matrix/`.
- **WhatsApp design scaffold** at `apps/crm/whatsapp_design.py` — 9
  message types, consent + admin-approval flags, audit kinds. No live
  integration in Phase 3E; Phase 4+ wires the actual sender.
- 12 new audit kinds + 29 new pytest tests covering catalog camelCase
  + admin/operations/viewer gating + audit firing + discount bands +
  ₹499 default + reward/penalty caps + approval matrix shape +
  WhatsApp scaffold contracts + compliance hard stops still hold.

**Compliance:** Phase 3E is policy + config only. CAIO is still
read-only, the Approved Claim Vault still gates every medical AI call,
no live messaging or order writes are executed by the Phase 3E modules.

## Phase 4 — Real-time + reward / penalty + approval middleware

### ✅ Phase 4A — Real-time AuditEvent WebSockets (DONE)

Shipped via `feat: add realtime audit event websockets`.

- `requirements.txt` adds `channels`, `channels_redis`, and `daphne`.
  `INSTALLED_APPS` lists `daphne` first and `channels` after the
  third-party DRF block.
- `config/asgi.py` rewired as a `ProtocolTypeRouter`: HTTP through the
  standard Django ASGI app; WebSocket through a `URLRouter` mounted
  from `config/routing.py` (which mounts `apps.audit.routing`).
- `apps/audit/realtime.py` — `serialize_event(event)` returns the
  camelCase shape the frontend `ActivityEvent` type expects and
  carries the **full stored `AuditEvent.payload`** verbatim.
  `latest_events()` returns the freshest 25 rows for the connect
  snapshot. `publish_audit_event(event)` schedules a fan-out via
  `transaction.on_commit` and swallows every Channels failure so a
  missing Redis cannot cascade into a service-layer write failure.
- `apps/audit/consumers.py` — `AuditEventConsumer` (an
  `AsyncJsonWebsocketConsumer`). On connect: optional `?token=<jwt>`
  validation via simplejwt, group join on `audit_events`, initial
  `{ type: "audit.snapshot", events: [...] }` frame. On each broadcast:
  `{ type: "audit.event", event: ... }`. `ping` → `pong`. Read-only.
- `apps/audit/routing.py` mounts the consumer at `/ws/audit/events/`.
- `apps/audit/signals.py` adds a `post_save(sender=AuditEvent)`
  receiver that fans newly-created rows out to the WebSocket group
  via `publish_audit_event`. Updates are intentionally not streamed.
- New env vars in `backend/.env.example`: `CHANNEL_LAYER_BACKEND`
  (default `memory` for tests / dev) and `CHANNEL_REDIS_URL`
  (default `redis://localhost:6379/2` — index 2 reserved for
  Channels; Celery still uses 0/1). Production sets
  `CHANNEL_LAYER_BACKEND=redis`.
- Frontend `services/realtime.ts` — `buildWebSocketUrl(path?, opts?)`
  + `connectAuditEvents(opts)` with snapshot replace + per-event
  prepend dedupe + exponential reconnect + status callback
  (`connecting | live | reconnecting | offline`). Never throws.
- Dashboard `Index.tsx` — opens the socket on mount, replaces the
  initial polling-fetched activity list with the snapshot, prepends
  new events with id-deduplication, caps the list at 25 rows.
  "Live Activity" header shows a tone-mapped status pill.
- Governance `Governance.tsx` — opens the same socket, calls
  `refresh()` whenever a frame's `kind` starts with `ai.approval.`,
  `ai.agent_run.approval_requested`, `ai.prompt_version.`,
  `ai.sandbox.`, or `ai.budget.`. The Approval queue header shows
  the same realtime status pill.
- Existing HTTP polling endpoints (`/api/dashboard/activity/`,
  `/api/ai/approvals/`) remain as fallback and stay green in tests.
- 8 new pytest tests cover serializer shape (full payload included),
  `latest_events()`, publisher resilience to a broken channel layer,
  `AuditEvent.objects.create` not breaking when the layer raises,
  consumer connect + snapshot, broadcast forwarding, ping/pong, and
  `GET /api/dashboard/activity/` still working.
- 5 new vitest cases cover `buildWebSocketUrl` for `http→ws`,
  `https→wss + /api stripping`, `VITE_WS_BASE_URL` override,
  empty-base fallback, and `?token=…` appending.

### ✅ Phase 4D — Approved Action Execution Layer (DONE)

Shipped via `feat: add approved action execution layer`. Phase 4C added
approval gating without execution; Phase 4D adds the safe, explicit
execution paths over a strict allow-listed registry.

**Goal (delivered)**: turn an approved `ApprovalRequest` into the
underlying business write through a tested service path, with no
autonomous / silent execution and a strong CAIO + Claim Vault hard
stop.

**Surface shipped:**

- `POST /api/ai/approvals/{id}/execute/` — admin/director only;
  director-only when policy mode is `director_override`. Body:
  `{ payloadOverride?, note? }`. Response:
  `{ approvalRequestId, action, executionStatus, executedAt,
  executedBy, result, errorMessage, message, alreadyExecuted }`.
- **Decision: separate model.** Added `ApprovalExecutionLog`
  (FK to `ApprovalRequest`) with status `executed` / `failed` /
  `skipped` and a partial unique constraint enforcing **one
  `executed` row per request** (idempotency).
  `ApprovalRequestSerializer` carries `latestExecutionStatus`,
  `latestExecutionAt`, `latestExecutionResult`,
  `latestExecutionError`, `executionLogs[]`.
- **Allow-listed initial registry** (everything else returns HTTP
  400 + `ai.approval.execution_skipped`):
  - `payment.link.advance_499` → `apps.payments.services.create_payment_link`
    (amount **always** resolved to `FIXED_ADVANCE_AMOUNT_INR`).
  - `payment.link.custom_amount` → same service, requires `amount > 0`.
  - `ai.prompt_version.activate` →
    `apps.ai_governance.prompt_versions.activate_prompt_version`,
    idempotent on already-active.
- **Phase 4D first pass intentionally LEAVES UNMAPPED**:
  `discount.up_to_10`, `discount.11_to_20`, `discount.above_20`,
  `ai.sandbox.disable`, `ad.budget_change`, `payment.refund`,
  every `whatsapp.*`, every `complaint.*`, and
  `ai.production.live_mode_switch`. They stay approval-only until a
  later phase wires them with explicit tests.
- Audit kinds: `ai.approval.executed`, `ai.approval.execution_failed`,
  `ai.approval.execution_skipped`.

**Hard stops (locked, do NOT relax):**

1. **CAIO can never trigger execution.** Refused at the engine AND at
   the bridge — Phase 4D adds a third refusal at the execute endpoint.
2. **Claim Vault remains mandatory** — no medical / claim-bound action
   may execute without an Approved Claim Vault grounding.
3. **No autonomous AI execution.** The execute endpoint always requires
   an approved `ApprovalRequest`; AgentRuns can only request approval,
   never execute.
4. **No ad budget changes** in Phase 4D — `ad.budget_change` stays in
   `director_override` mode and the registry intentionally leaves it
   unmapped (will 400 on execute even if approved).
5. **No refunds** in Phase 4D — `payment.refund` stays in
   `human_escalation` mode and is intentionally unmapped.
6. **No live WhatsApp** in Phase 4D — design scaffold only.
7. **No silent complex business writes.** The registry is an
   allow-list; an approved action whose key is NOT in the registry
   responds with HTTP 400 and writes `ai.approval.execution_skipped`.
8. **Director-only override** stays enforced for any `director_override`
   action even at the execute endpoint.
9. **Idempotency** — re-executing an already-executed approval returns
   the prior result; never re-runs the underlying write.
10. **Existing tests must stay green** (currently 275 backend + 8
    frontend).

**Frontend shipped (Phase 4D):**

- New "Execution" column in the Governance page Approval queue table
  showing the latest execution status pill + relative time +
  error/skip reason.
- "Execute" button on rows whose `status ∈ {approved, auto_approved}`
  AND `latestExecutionStatus !== "executed"` — admin/director only on
  the API; the button is a UX affordance, not an authorization
  mechanism.
- TypeScript types `ApprovalExecutionLog`, `ApprovalExecutionStatus`,
  `ExecuteApprovalPayload`, `ExecuteApprovalResponse`.
- `api.executeApprovalRequest(id, payload?)` with deterministic mock
  fallback.
- No business logic in React.

**What Phase 4D explicitly did NOT do:**

- Did not replace the existing service layer. Every write still flows
  through `apps/<app>/services.py`.
- Did not introduce automation that turns approval queues into
  background drainers. Execution stays an explicit operator action.
- Did not wire discount / sandbox-disable / ad-budget / refund /
  WhatsApp / production live-mode-switch handlers. Phase 4E (below)
  later wired discount + sandbox-disable; ad-budget / refund / WhatsApp
  / production live-mode-switch / discount.above_20 stay unmapped.

### ✅ Phase 4E — Expanded Approved Execution Registry (DONE)

Shipped via `feat: expand approved action execution registry`.

- Three new handlers added to `apps/ai_governance/approval_execution.py`:
  - `discount.up_to_10` (band 0–10%) — accepts ApprovalRequest status
    `approved` OR `auto_approved` (the matrix lets this band auto-approve).
  - `discount.11_to_20` (band 11–20%) — same approve / auto_approve gate.
    Auto_approved is trusted only because the backend approval_engine
    puts it there; frontend / AI cannot fake the status.
  - `ai.sandbox.disable` — flips the SandboxState singleton off via the
    existing `apps.ai_governance.sandbox.set_sandbox_enabled` helper.
    **Director-only** via matrix `director_override`. Idempotent on
    already-off (returns `alreadyDisabled=true`, no audit fire).
- New service `apps.orders.services.apply_order_discount` — validates
  via the locked Phase 3E `validate_discount` policy, mutates ONLY
  `Order.discount_pct`, writes a `discount.applied` audit row, returns
  a structured result. New `DiscountValidationError` exception bubbles
  policy refusals to the handler.
- New audit kind `discount.applied` registered in `ICON_BY_KIND`.
- Band-edge guards in the handler (belt-and-braces on top of policy):
  `discount.up_to_10` rejects pct > 10; `discount.11_to_20` rejects
  pct ≤ 10 OR > 20; both reject negative + missing. Missing `orderId`
  → ExecutionRefused; unknown order → 404.
- `ai.sandbox.disable` requires `note` OR `overrideReason` in the
  proposed payload (or via `approval.reason` / `decision_note`);
  otherwise refuses.
- Phase 4D pre-checks unchanged — idempotency, CAIO refusal, role
  gate (admin/director; director-only on `director_override`),
  status gate (must be `approved` or `auto_approved`), unknown action
  → skipped + 400.
- 31 new pytest tests cover discount.up_to_10 happy + edge paths;
  discount.11_to_20 happy + every band-edge refusal; discount.above_20
  stays unmapped → 400 + skipped + order untouched; idempotency on
  discount; discount-only side-effect scope (only `discount_pct`
  changes); audit firing on discount + sandbox paths; sandbox.disable
  Director-only + idempotent + note required; CAIO blocked on both
  surfaces; remaining-unmapped parametric on the 4 still-blocked
  actions; HTTP endpoint smoke tests.
- Phase 4D `tests/test_phase4d.py` parametrized "unmapped" lists were
  trimmed by 2 (the now-mapped `discount.11_to_20` and
  `ai.sandbox.disable`), keeping the rest of the regression intact.

**What Phase 4E explicitly did NOT do:**

- Did not wire `discount.above_20` execution. Even when approved (e.g.
  director_override path), execute → 400 + skipped audit.
- Did not wire `ad.budget_change`, `payment.refund`, `whatsapp.*`, or
  `ai.production.live_mode_switch` execution.
- Did not change role rules. Director-only on `director_override` is
  inherited from Phase 4D `_check_role`.
- Did not introduce frontend-side discount or sandbox logic. The
  Governance page Execute button + execution-status column from
  Phase 4D continue to render the result of any registered handler.

**39 new pytest tests** (`tests/test_phase4d.py`) cover idempotency,
non-approved status refusals (pending / rejected / blocked / escalated /
expired all → 409), CAIO requested_by_agent + metadata refusals,
advance_499 happy path with amount = ₹499, advance_499 ignoring
tampered amount, advance_499 missing orderId, custom_amount happy path,
custom_amount pending → 409, custom_amount zero / negative / missing
amount, prompt activation happy path + idempotent on already-active +
Claim Vault preserved, 4 admin-eligible unmapped actions → skipped,
2 director_override unmapped actions → skipped, audit emission on
each path, full endpoint role gating, 404 / 409 / alreadyExecuted
responses, director_override blocking admin at execute, and
`latestExecutionStatus` surfacing in the approval list response.

### ✅ Phase 4B — Reward / Penalty Engine wiring (DONE)

Shipped via `feat: add reward penalty engine`.

- New `RewardPenaltyEvent` model (per-order, per-AI-agent) with
  `unique_key` for idempotency. `RewardPenalty` rollup row gets
  Phase 4B columns (`agent_id`, `agent_type`, `rewarded_orders`,
  `penalized_orders`, `last_calculated_at`).
- `apps/rewards/engine.py` wires the Phase 3E pure formula
  (`apps.rewards.scoring.calculate_order_reward_penalty`) into per-order
  attribution across the 10 in-scope AI agents (CEO AI, Ads, Marketing,
  Sales Growth, Calling AI, Confirmation AI, RTO, Customer Success, Data
  Quality, Compliance). Helpers: `build_reward_context`, `calculate_for_order`,
  `calculate_for_delivered_orders`, `calculate_for_failed_orders`,
  `calculate_for_all_eligible_orders`, `rebuild_agent_leaderboard`.
- **Locked rule**: every RTO / cancelled order generates a CEO AI net
  accountability **penalty** event; every delivered order generates a
  CEO AI **reward** event. CAIO is excluded from business scoring.
- 3 new endpoints under `/api/rewards/`: `GET events/`, `GET summary/`,
  `POST sweep/` — admin/director only. Existing `GET /api/rewards/`
  remains public and backwards-compatible.
- Management command `python manage.py calculate_reward_penalties`
  with `--start-date`, `--end-date`, `--order-id`, `--dry-run`,
  `--rebuild-leaderboard` flags. No Redis required.
- Celery task `apps.rewards.tasks.run_reward_penalty_sweep_task`
  (eager-mode safe).
- 6 new audit kinds: `ai.reward.calculated`, `ai.penalty.applied`,
  `ai.reward_penalty.sweep_started` / `.sweep_completed` /
  `.sweep_failed` / `.leaderboard_updated`.
- Frontend Rewards page upgraded with agent-wise leaderboard, order-wise
  scoring events table, sweep summary cards, and a Run Sweep button.
- 25 new pytest tests cover idempotency, CEO AI accountability rules,
  CAIO exclusion, missing-data preservation, reward / penalty caps,
  audit firing, dry-run no-persistence, management command, Celery
  task in eager mode, and full role-gating across the new endpoints.

### ✅ Phase 4C — Approval Matrix Middleware enforcement (DONE)

Shipped via `feat: add approval matrix middleware`.

- Two new models in `apps.ai_governance`: `ApprovalRequest` (id, action,
  mode, approver, status, requested_by, target, proposed_payload,
  policy_snapshot, decision fields, metadata) and `ApprovalDecisionLog`
  (one row per status transition with note + decided_by). Migration
  `0005_phase4c_approval_matrix`.
- `apps/ai_governance/approval_engine.py` — pure `evaluate_action` +
  persisted `enforce_or_queue` / `create_approval_request` /
  `mark_auto_approved` / `approve_request` / `reject_request` /
  `request_approval_for_agent_run`. Modes: `auto`, `auto_with_consent`,
  `approval_required`, `director_override`, `human_escalation` —
  unknown mode / action fail closed. CAIO actor blocked at the
  evaluator AND at the AgentRun bridge.
- 5 new admin/director endpoints under `/api/ai/`:
  list / detail / approve / reject / evaluate + AgentRun
  `request-approval/`.
- Live enforcement wired into 3 high-value paths today:
  `payment.link.{advance_499,custom_amount}`, `ai.prompt_version.activate`,
  `ai.sandbox.disable`. Other workflows stay auto per matrix.
- 8 new audit kinds (`ai.approval.*` + `ai.agent_run.approval_requested`).
- Frontend Governance page upgraded with an Approval queue table
  (Action / Mode / Approver / Target / Status / Proposed payload preview /
  Approve + Reject controls + decision-note input).
- 31 new pytest tests cover every matrix mode, persistence + policy
  snapshot, approve / reject transitions, director-only override,
  AgentRun bridge happy path + all rejection paths, full role-gating
  on every endpoint, and live enforcement smoke for payment-link
  custom-amount + sandbox-disable.

**Locked decisions:** approval `approve_request` does NOT silently
execute the underlying business write; the existing tested service
path still owns the write. Phase 4D will add explicit safe execution
paths action-by-action.

## Phase 5 — WhatsApp + Governance UI write paths

### ✅ Phase 5A-0 — WhatsApp compatibility audit (DONE, doc-only)

Shipped via `docs: add whatsapp integration audit and phase 5a plan`.
Audit of [`prarit0097/Whatsapp-sales-dashboard`](https://github.com/prarit0097/Whatsapp-sales-dashboard) at SHA `273b57a3`. Every backend module, frontend page, and Node service file mapped to a `reuse / adapt / replace / avoid` decision. Locked decisions (Production Meta Cloud only; Baileys dev/demo only; Claim Vault + consent + approval matrix gates server-side; CAIO blocked end-to-end). Full integration plan with Sections A-R, model specs, provider interface, allowed message types, audit kinds, env vars, test plan, and migration sequence lives in **`docs/WHATSAPP_INTEGRATION_PLAN.md`**. **Zero runtime code changes.**

### ✅ Phase 5A-1 — WhatsApp AI Chat Agent + Discount Rescue Policy Addendum (DONE, doc-only)

Shipped via `docs: add whatsapp ai chat agent and discount rescue policy`.
Locked addendum (sections S–GG) to `docs/WHATSAPP_INTEGRATION_PLAN.md`. **Zero runtime code changes.** Key product direction shifts:

- **WhatsApp module direction widened** from "lifecycle reminder sender" to "**inbound-first AI Chat Sales Agent + lifecycle messaging**" mirroring the AI Calling Agent's business objective (greet → category detection → Claim-Vault-grounded explanation → objection handling → address collection → order booking → payment-link handoff → confirmation / delivery / RTO / reorder lifecycle → chat-to-call handoff).
- **Greeting rule locked.** Generic intro → fixed Hindi UTILITY template ("*Namaskar, Nirogidhara Ayurvedic Sanstha mai aapka swagat hai. Bataye mai aapki kya help kar sakta/sakti hu?*"). No freestyle on first reply.
- **First-phase mode = `auto-reply` with guardrails.** "Auto-reply" means the AI replies without operator click — it does NOT bypass the matrix, Claim Vault, or approval engine. Every send still flows through `enforce_or_queue` first; CAIO never sends; sandbox stamps live; budgets gate.
- **Address collection** in chat is stateful per `WhatsAppConversation.metadata.address_collection` with required fields and Delhivery pincode validation. Failure → handoff.
- **Category detection (locked):** before any product-specific text, the agent must identify a `apps.catalog.ProductCategory` slug; the category-detection prompt is itself a Meta UTILITY template (not freestyle); product explanation thereafter must use `apps.compliance.Claim.approved` only.
- **Chat-to-call handoff triggers (locked):** explicit call request, low confidence on two consecutive turns, address / payment / pincode clarification failure, six existing handoff flags (medical / side-effect / very-angry / human-requested / low-confidence / legal-or-refund), high-risk RTO rescue.
- **Discount discipline (THE locked Prarit rule):** **AI never offers a discount upfront.** Lead with standard ₹3000/30-capsule price; do not mention discount unless customer asks; on first ask, handle the underlying objection (value / trust / benefit / brand / doctor / ingredients / lifestyle); only after 2–3 customer pushes may the AI offer a discount within Phase 3E `validate_discount` bands. **Refusal-based rescue is the only proactive offer path** — eligible at three stages: A) order-booking refusal (Sales/Chat/Call), B) confirmation refusal (Confirmation AI), C) delivery / RTO refusal (Delivery / RTO AI).
- **50% total discount hard cap (LOCKED).** Across all stages combined, the total discount on a single order must NEVER exceed 50%. Examples: 20+20+10=50% allowed; 20+20+20=60% blocked. Scope: every AI workflow that can offer a discount (Chat / Calling / Confirmation / RTO / Customer Success / any future). Enforcement (Phase 5C/5D code work) layers a new `validate_total_discount_cap(order, additional_pct)` check on top of the existing `validate_discount` policy, in front of `apply_order_discount` in the Phase 4D execute layer; over-cap requests convert to a director-only `discount.above_50_director_override` `ApprovalRequest` row.
- **Discount audit fields locked** (Phase 5C/5D `DiscountOfferLog` table): customer / order / conversation / agent / channel / stage / trigger / current+proposed+final pct / cap-check / policy band / approval state / estimated profit impact / Reward-Penalty signal / `AuditEvent` id.
- **Future model + API planning notes** (NOT implemented in 5A-1 or 5A): `WhatsAppAIReplySuggestion`, `WhatsAppChatAgentRun`, `WhatsAppHandoffToCall`, `WhatsAppConversationOutcome`, `WhatsAppEscalation`, `WhatsAppLearningCandidate`, `DiscountOfferLog`. Future endpoints `POST /api/whatsapp/conversations/{id}/ai-reply/`, `POST /handoff-to-call/`, `POST /orders/draft-from-chat/`, `POST /discount-offers/`, `GET /timeline/`.
- **Learning loop scope (locked):** may improve tone / timing / objection handling / closing style / discount-offer timing / handoff timing / category-question phrasing / address-collection wording. **Must NOT create** new medical claims, product promises, cure statements, side-effect advice, refund/legal commitments, new outbound templates, or discount offers above the per-stage band or the 50% cap.

**Phase 5A implementation must read §S–§DD of the integration plan** before designing models / provider / service contracts — `WhatsAppConversation.metadata.address_collection` needs a home; `WhatsAppMessage` must carry context for the Chat Agent path; the provider interface must serve both lifecycle templates (5A) and AI-driven chat (5C); the discount audit table is anticipated by the model name space.

### ✅ Phase 5A — WhatsApp Live Sender Foundation (DONE)

Implemented per `docs/WHATSAPP_INTEGRATION_PLAN.md` §C / §D / §E / §O:

- ✅ New `apps.whatsapp` Django app added to `INSTALLED_APPS`. 8 models: `WhatsAppConnection`, `WhatsAppTemplate`, `WhatsAppConsent`, `WhatsAppConversation`, `WhatsAppMessage`, `WhatsAppMessageAttachment`, `WhatsAppMessageStatusEvent`, `WhatsAppWebhookEvent`, `WhatsAppSendLog`. Migration `0001_initial`.
- ✅ Provider interface in `apps/whatsapp/integrations/whatsapp/base.py` with `ProviderSendResult`, `ProviderWebhookEvent`, `ProviderStatusResult`, `ProviderHealth` dataclasses + `ProviderError` exception.
- ✅ `MockProvider` (default for tests / dev) — deterministic `wamid.MOCK_<idempotency_key>`, no network.
- ✅ Real `MetaCloudProvider` (Nirogidhara-built — the reference repo's was stubbed): `send_template_message` posting to `https://graph.facebook.com/{version}/{phone_number_id}/messages`, lazy `requests` import, `verify_webhook` HMAC-SHA256 against `META_WA_APP_SECRET` (or `WHATSAPP_WEBHOOK_SECRET`) + replay-window check, `parse_webhook_event` for Meta's `entry[].changes[].value.{messages,statuses}` shape, `get_message_status` (informational), `health_check` against `GET /v20.0/{phone_number_id}`.
- ✅ `BaileysDevProvider` dev-only stub — refuses to load when `DEBUG=False` AND `WHATSAPP_DEV_PROVIDER_ENABLED!=true`. Has no production transport.
- ✅ Service layer `apps.whatsapp.services` — `queue_template_message` runs the full safety stack (no consent → block; opt-out → block; template not approved/inactive → block; Claim Vault required + no row → block; CAIO actor → block; `enforce_or_queue` matrix gate; idempotency key dedupe). `send_queued_message` drives the queued row through the provider once and writes a `WhatsAppSendLog`. **Failed sends never mutate Order/Payment/Shipment.**
- ✅ Celery task `apps.whatsapp.tasks.send_whatsapp_message` with `bind=True, autoretry_for=(ProviderError,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True, max_retries=5`. Idempotent on entry.
- ✅ Webhook receiver at `/api/webhooks/whatsapp/meta/` (GET handshake + signed POST). HMAC-verified, replay-window-checked, idempotent on `WhatsAppWebhookEvent.provider_event_id`. Failed-signature attempts are still persisted as `processing_status=rejected` for audit visibility.
- ✅ Consent enforcement in `apps.whatsapp.consent` — `has_whatsapp_consent`, `grant_whatsapp_consent`, `revoke_whatsapp_consent`, `record_opt_out` (cancels queued sends), `detect_opt_out_keyword` matches `STOP / UNSUBSCRIBE / BAND KARO / BAND / CANCEL` (case-insensitive substring).
- ✅ Claim Vault enforcement: `claim_vault_required=True` templates must match a `apps.compliance.Claim` row whose `approved` list is non-empty for the customer's `product_interest`.
- ✅ Approval matrix integration — 9 new entries: `whatsapp.payment_reminder` (auto_with_consent), `whatsapp.confirmation_reminder` (auto_with_consent), `whatsapp.delivery_reminder` (auto_with_consent), `whatsapp.rto_rescue` (auto_with_consent), `whatsapp.usage_explanation` (approval_required by compliance), `whatsapp.reorder_reminder` (auto_with_consent), `whatsapp.support_complaint_ack` (auto_with_consent), `whatsapp.greeting` (auto_with_consent), plus the existing `whatsapp.broadcast_or_campaign` (approval_required) and `whatsapp.support_handover_to_human` (human_escalation).
- ✅ 18 new audit kinds in `apps/audit/signals.py` ICON_BY_KIND. Phase 4A WebSocket fanout picks them up automatically.
- ✅ 13 API endpoints under `/api/whatsapp/` (provider/status, connections, templates list / sync, conversations + messages, send-template, retry, consent get/patch). Permissions split: admin-only for sync + provider status; operations+ for send + consent patch + retry; viewer+ for reads.
- ✅ `python manage.py sync_whatsapp_templates` command — seeds 8 default templates when run with no flags; accepts `--from-file <meta-payload.json>` for real WABA syncs.
- ✅ Frontend: types under `frontend/src/types/domain.ts`, API methods under `frontend/src/services/api.ts` (with mock-fallback), Settings → WABA section, read-only `/whatsapp-templates` page, sidebar entry.
- ✅ **50 new backend tests + 13 frontend tests, all green.** Total backend: 401.

**Out of scope for Phase 5A (deferred to 5B/5C/5D/5E/5F):** WhatsApp AI Chat Sales Agent (Phase 5C), inbound auto-reply, chat-to-call handoff, Order booking from chat, lifecycle automation triggers, rescue discount, broadcast/campaigns. Phase 5A is the safe foundation — no AI freestyle, no automatic outbound on lifecycle events, manual operator-triggered sends only.

### ✅ Phase 5B — Inbound Inbox + Customer 360 timeline (DONE)

Implemented per Prarit's locked decisions (manual-only inbox, AI suggestions placeholder defaults to disabled, separate Customer 360 WhatsApp tab — no unified timeline yet):

- ✅ New `WhatsAppInternalNote` model + migration `0002_whatsappinternalnote`. Notes carry `conversation FK / author FK (User) / body / metadata` and timestamps. Notes are NEVER sent to the customer — only the operator-side audit trail.
- ✅ Six new endpoints: `GET /api/whatsapp/inbox/`, `PATCH /api/whatsapp/conversations/{id}/` (safe fields only — `status / assignedToId / tags / subject`), `POST /api/whatsapp/conversations/{id}/mark-read/`, `GET + POST /api/whatsapp/conversations/{id}/notes/`, `POST /api/whatsapp/conversations/{id}/send-template/` (routes through Phase 5A's `queue_template_message`), `GET /api/whatsapp/customers/{customer_id}/timeline/` (WhatsApp-only items).
- ✅ Six new audit kinds wired into `apps/audit/signals.py` ICON_BY_KIND: `whatsapp.conversation.opened/updated/assigned/read`, `whatsapp.internal_note.created`, `whatsapp.template.manual_send_requested`. Phase 4A WebSocket fanout picks them up automatically.
- ✅ Conversation list filters extended (`?unread=true`, `?assignedTo=`, `?q=`).
- ✅ Conversation serializer extended with `customerName / customerPhone / assignedToUsername`. Message serializer extended with `templateName`.
- ✅ Frontend three-pane `/whatsapp-inbox` page (filters / conversation list / thread + internal notes + AI-suggestions-disabled placeholder + manual template send modal). Live refresh via Phase 4A `connectAuditEvents` filtered on `whatsapp.*` — no new WebSocket channel.
- ✅ Customer 360 WhatsApp tab (separate from Calls/Orders/Payments/Delivery/Consent tabs — Prarit explicitly avoided a unified timeline). Loads `getCustomerWhatsAppTimeline` and renders messages + notes + AI-disabled placeholder + Open in Inbox link.
- ✅ AI auto-reply stays disabled. Operations users can only send approved templates; backend gates (consent + approved-template + Claim Vault + approval matrix + CAIO + idempotency) remain final.
- ✅ 33 new pytest cases in `backend/tests/test_phase5b.py`. Existing 401 backend tests stay green; total 434.

**Out of scope for Phase 5B (deferred to 5C/5D/5E/5F):** AI Chat Agent, inbound auto-reply, chat-to-call handoff, order booking from chat, rescue discount automation, escalation automation, campaigns, freeform outbound text.

### ✅ Phase 5B-Deploy — Production Docker scaffold (DONE)

Pure deployment scaffold. **No business logic changed; 434 backend + 13
frontend tests stay green.**

- ✅ `docker-compose.prod.yml` — project `nirogidhara-command`, six isolated containers (`nirogidhara-db` Postgres 16-alpine, `nirogidhara-redis` Redis 7-alpine AOF, `nirogidhara-backend` Daphne ASGI :8000, `nirogidhara-worker` Celery worker concurrency=1, `nirogidhara-beat` Celery beat, `nirogidhara-nginx` Vite SPA + reverse proxy). Host port `18020:80` to avoid colliding with Postzyo / OpenClaw on the same VPS.
- ✅ `backend/Dockerfile` — Python 3.11 slim + tini + libpq + non-root uid 10001. Same image runs backend / worker / beat; the runtime command comes from compose.
- ✅ `deploy/backend/entrypoint.sh` — role-aware. Daphne role waits for Postgres + Redis, runs `migrate --noinput` and `collectstatic --noinput`, then `exec`s the supplied command. Worker / beat skip migrate (backend container owns schema) but still wait for DB + Redis.
- ✅ `frontend/Dockerfile` — multi-stage node 20 → nginx 1.27 alpine. Build context = repo root so the runtime stage can read `deploy/nginx/nirogidhara.conf`. Bakes `VITE_API_BASE_URL=/api` + empty `VITE_WS_BASE_URL` so production stays same-origin.
- ✅ `deploy/nginx/nirogidhara.conf` — serves SPA from `/usr/share/nginx/html`, proxies `/api/` + `/admin/` + `/ws/` to `backend:8000` (with WebSocket upgrade headers + Forwarded-* + X-Real-IP), gzip + 25 MB upload cap, hashed-asset caching + `index.html` no-cache.
- ✅ `.env.production.example` — covers every env var read by `backend/config/settings.py`. Mock-mode defaults locked; `AI_PROVIDER=disabled`. Production callback URLs (Razorpay, Vapi) point at `https://ai.nirogidhara.com/...` placeholders.
- ✅ `backend/config/settings.py` — `CSRF_TRUSTED_ORIGINS` is now env-driven (defaults to the dev CORS origins when unset). Same pattern as the existing `CORS_ALLOWED_ORIGINS`.
- ✅ `backend/requirements.txt` — adds `psycopg[binary]` (Postgres driver) and `requests` (used lazily by Vapi / Delhivery / Meta Cloud / WhatsApp adapters).
- ✅ `.gitignore` extended: `.env.production`, `*.pem / *.key / *.crt`, `certbot/`, `deploy/secrets/`. Allow-list keeps `.env.production.example` tracked.
- ✅ `.dockerignore` (repo root + backend) — keeps secrets, sqlite, dev artifacts, git history out of every image.
- ✅ `docs/DEPLOYMENT_VPS.md` — end-to-end runbook: prerequisites, clone into `/opt/nirogidhara-command`, env stamping, first boot, migrate + createsuperuser + sync_whatsapp_templates, smoke tests, DNS A-record, host Nginx + Certbot **or** Hostinger Traefik, daily logs / restart / update / Postgres backup commands, security checklist, shared-VPS resource-safety notes, and an explicit "intentionally NOT here" list (Phase 5C+).

**Locked safety:**

- Project / network / container / volume / host-port names are all namespaced (`nirogidhara-*`) so the new stack cannot accidentally touch Postzyo or OpenClaw.
- `.env.production` is gitignored. The repo carries only the `*.example`.
- Worker concurrency starts at 1; bump only after `docker stats` confirms headroom.
- All integration adapters keep their three-mode (mock / test / live) dispatch. The first deploy ships every adapter in `mock` so a misconfiguration cannot send a live customer message.

### ✅ Phase 5C — WhatsApp AI Chat Sales Agent (DONE)

Shipped per Phase 5A-1 addendum + Prarit's locked Phase 5C decisions (auto mode, locked greeting template, multilingual replies, order booking from chat, no shipment). Tests: 35 new pytest cases; 469 backend + 13 frontend, all green.

- ✅ `apps/whatsapp/ai_orchestration.py` — `run_whatsapp_ai_agent` end-to-end pipeline (idempotency → language detection → greeting fast-path → AI provider gate → Claim Vault context → prompt build → dispatch → JSON validation → safety + discount + rate gates → freeform send / order booking / handoff). Fail-closed when `AI_PROVIDER=disabled` / `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` / Claim Vault missing.
- ✅ `apps/whatsapp/language.py` — deterministic Hindi/Hinglish/English heuristic + persistence helper.
- ✅ `apps/whatsapp/ai_schema.py` — strict JSON schema + `BLOCKED_CLAIM_PHRASES` defence in depth.
- ✅ `apps/whatsapp/discount_policy.py` — wraps Phase 3E `validate_discount` with the never-upfront rule (`MIN_OBJECTION_TURNS_BEFORE_OFFER=2`), refusal-rescue unlock, and the locked 50% total cap (`validate_total_discount_cap`).
- ✅ `apps/whatsapp/order_booking.py` — `book_order_from_decision` validates address completeness + discount cap, calls `apps.orders.services.create_order` (existing service path), optionally creates ₹499 advance link via `apps.payments.services.create_payment_link`. Never touches `apps.shipments`.
- ✅ `apps/whatsapp/services.py` adds `send_freeform_text_message` (TEXT messages) — gated identically to `queue_template_message` (consent + CAIO refusal + idempotency).
- ✅ `apps/whatsapp/tasks.py` adds `run_whatsapp_ai_agent_for_conversation` Celery task. Inbound webhook fires it on commit (eager-mode safe).
- ✅ Six new HTTP endpoints under `/api/whatsapp/ai/*` and per-conversation `ai-mode / run-ai / ai-runs / handoff / resume-ai`. Viewer read-only; operations+ for writes.
- ✅ 18 new audit kinds wired into `apps/audit/signals.ICON_BY_KIND`.
- ✅ Frontend `AiAgentPanel` inside `WhatsAppInbox.tsx` + AI Auto badge on AI-generated message bubbles + Customer 360 status pill update.
- ✅ Settings: `WHATSAPP_AI_AUTO_REPLY_ENABLED` (off by default), `WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.75`, `WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR=10`, `WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY=30`. Documented in both `.env.example` and `.env.production.example`.

**Out of scope (still deferred):** `learned_memory.py` port, `WhatsAppAIReplySuggestion` / `WhatsAppChatAgentRun` separate tables, chat-to-call handoff (Phase 5D), lifecycle automation (Phase 5D), confirmation / delivery / RTO / reorder rescue automation (Phase 5E), campaigns (Phase 5F).

### ✅ Phase 5D — Chat-to-Call Handoff + Lifecycle Automation (DONE)

Shipped per Prarit's locked Phase 5D decisions (direct Vapi handoff, AI-booked → confirmation queue, mock + OpenAI test then limited live Meta rollout, Claim Vault coverage check). Tests: 29 new pytest cases; **498 backend + 13 frontend, all green.**

- ✅ `apps.whatsapp.call_handoff.trigger_vapi_call_from_whatsapp` is the SINGLE entry that may dial Vapi from WhatsApp; routes through existing `apps.calls.services.trigger_call_for_lead`. New `WhatsAppHandoffToCall` model is idempotent on `(conversation, inbound_message, reason)`. `whatsapp.handoff.call_requested / call_triggered / call_failed / call_skipped / call_skipped_duplicate` audits.
- ✅ Phase 5C orchestrator opportunistically routes safe handoff reasons to Vapi when `WHATSAPP_CALL_HANDOFF_ENABLED=true`. Safety reasons (medical_emergency / side_effect_complaint / legal_threat / refund_threat) record a `skipped` row for human/doctor pickup.
- ✅ Operator manual trigger at `POST /api/whatsapp/conversations/{id}/handoff-to-call/` (operations+); CAIO never reaches the view (no auth path).
- ✅ AI-booked orders move directly into the confirmation queue: `book_order_from_decision` calls `apps.orders.services.move_to_confirmation` post-create, audits `whatsapp.ai.order_moved_to_confirmation`. Failure flips `confirmationMoveFailed=true` metadata flag — order is never lost.
- ✅ Lifecycle service `apps.whatsapp.lifecycle.queue_lifecycle_message` + `apps.whatsapp.signals` listen on Order/Payment/Shipment `post_save` and route to approved templates (`whatsapp.confirmation_reminder`, `whatsapp.payment_reminder`, `whatsapp.delivery_reminder`, `whatsapp.usage_explanation`, `whatsapp.rto_rescue`). Idempotent on `lifecycle:{action}:{type}:{id}:{event}`. `whatsapp.lifecycle.queued / sent / blocked / skipped_duplicate / failed` audits. `usage_explanation` template fails closed when Phase 5D Claim Vault coverage shows `missing` / `weak`.
- ✅ Claim Vault coverage audit: `apps.compliance.coverage` + `python manage.py check_claim_vault_coverage` (exits 1 on missing) + admin-only `GET /api/compliance/claim-coverage/`.
- ✅ Three new endpoints (`POST /api/whatsapp/conversations/{id}/handoff-to-call/`, `GET /api/whatsapp/conversations/{id}/handoffs/`, `GET /api/whatsapp/lifecycle-events/`).
- ✅ Four new env vars (all default safe): `WHATSAPP_CALL_HANDOFF_ENABLED=false`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false`, `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`, `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS=`.
- ✅ Frontend: "Call customer" button on AI Chat panel; new `WhatsAppHandoffToCall` / `WhatsAppLifecycleEvent` / `ClaimVaultCoverageReport` types; new `triggerWhatsAppConversationCall / getWhatsAppConversationHandoffs / getWhatsAppLifecycleEvents / getClaimVaultCoverage` api methods.

**Out of scope (deferred to 5E):** confirmation / delivery / RTO refusal-based rescue discount flow, `DiscountOfferLog` table, `validate_total_discount_cap` enforcement before `apply_order_discount`, `discount.above_50_director_override` matrix row, `WhatsAppConversationOutcome` / `WhatsAppEscalation` finalisation tables, reverse handoff (AI Calling Agent → WhatsApp template), `learned_memory.py` port. Campaigns remain Phase 5F.

### ✅ Phase 5E — Rescue Discount Flow + Day-20 Reorder + Default Claim Vault Seeds (DONE)

Shipped per Prarit's locked Phase 5E decisions (cumulative 50% cap, RTO auto-rescue, Day-20 reorder cadence, demo Claim Vault seed). Tests: 38 new pytest cases; **536 backend + 13 frontend, all green.**

- ✅ `apps.orders.rescue_discount` is the single source of truth for AI rescue discount math: `get_current_total_discount_pct`, `get_discount_cap_remaining`, `validate_total_discount_cap`, `cap_status`, `calculate_rescue_discount_offer`, `create_rescue_discount_offer`, `accept_rescue_discount_offer`, `reject_rescue_discount_offer`. Cumulative cap = **50% absolute hard cap** across confirmation / delivery / RTO / reorder.
- ✅ Per-stage rescue ladder (confirmation 5/10/15, delivery 5/10, RTO 10/15/20 with high-risk step-up, reorder 5). Conservative-first; clamps to `cap_remaining` automatically.
- ✅ `apps.orders.DiscountOfferLog` model — append-only log of every offer (offered / accepted / rejected / blocked / skipped / `needs_ceo_review`). New audit kinds: `discount.offer.{created,sent,accepted,rejected,blocked,needs_ceo_review}`.
- ✅ Two new matrix rows (`discount.rescue.ceo_review` for AI-stuck / over-band cases, `discount.above_safe_auto_band` for >20% director override) — over-cap / over-band offers automatically mint `ApprovalRequest` rows via `enforce_or_queue`.
- ✅ Customer acceptance applies via `apps.orders.services.apply_order_discount` only (no module mutates `Order.discount_pct` directly). Cap is re-validated at accept time; over-cap flips status to `needs_ceo_review` instead of writing.
- ✅ Phase 5C orchestrator now also writes a `DiscountOfferLog` row whenever the WhatsApp AI proposes a discount, regardless of outcome — orders / analytics see the offer in one canonical place.
- ✅ Lifecycle service grew four triggers — `whatsapp.confirmation_rescue_discount`, `whatsapp.delivery_rescue_discount`, `whatsapp.rto_rescue_discount`, `whatsapp.reorder_day20_reminder` — all `auto_with_consent` in the matrix; consent + Claim Vault + matrix + CAIO + idempotency stays in force on every send. Dedicated audit kinds: `whatsapp.lifecycle.rescue_discount_{queued,sent}`, `whatsapp.lifecycle.reorder_day20_{queued,sent}`.
- ✅ Day-20 reorder sweep: `apps.whatsapp.reorder.run_day20_reorder_sweep` covers delivered orders 20–27 days old, idempotent on `lifecycle:whatsapp.reorder_day20_reminder:order:{id}:day20`. New management command (`python manage.py run_reorder_day20_sweep [--dry-run] [--json]`) + Celery task (`apps.whatsapp.tasks.run_reorder_day20_sweep_task`).
- ✅ Default Claim Vault seed: `python manage.py seed_default_claims [--reset-demo] [--json]`. Idempotent; covers Weight Management / Blood Purification / Men Wellness / Women Wellness / Immunity / Lungs Detox / Body Detox / Joint Care; demo rows flagged `version="demo-v1"` and surfaced in coverage as `risk=demo_ok` with a "replace before live rollout" note. Real admin-added rows are NEVER overwritten. Audit kind: `compliance.default_claims.seeded`.
- ✅ Five new endpoints (`/api/orders/{id}/discount-offers/{,rescue/,{offer_id}/{accept,reject}/}`, `/api/whatsapp/reorder/day20/{status,run}/`).
- ✅ Four new env vars (all default safe): `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`, `DEFAULT_CLAIMS_SEED_DEMO_ONLY`.
- ✅ Frontend: Rescue Discount cap card on the AI Chat panel + new TS types (`DiscountOffer`, `DiscountOfferListResponse`, `CreateRescueOfferPayload`, `ReorderDay20StatusResponse`, `ReorderDay20RunResponse`) + six new `api` methods.

**Out of scope (still deferred):** `WhatsAppConversationOutcome` + `WhatsAppEscalation` finalisation tables, reverse handoff (AI Calling Agent → WhatsApp template), `learned_memory.py` port. Campaigns remain Phase 5F.

### ✅ Phase 5F-Gate — Approved Customer Pilot Readiness + SaaS Guardrails (DONE)

This gate prepares a tiny approved customer pilot without enabling broad
rollout. It keeps `WHATSAPP_AI_AUTO_REPLY_ENABLED=false`,
`WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`, campaigns/broadcast locked,
and call handoff / lifecycle / rescue / RTO / reorder OFF. The prior
4-hour soak was accelerated, not full-duration, so this phase is
read-only/prep plus monitoring only.

- ✅ New `WhatsAppPilotCohortMember` model references `crm.Customer` and
  stores masked phone/suffix, status, consent verification, source,
  approver, daily cap, notes, and metadata.
- ✅ New `apps.whatsapp.pilot.get_whatsapp_pilot_readiness_summary()`
  validates safe live posture, consent, allow-list membership, daily
  caps, recent non-allowed sends, mutation counts, and dashboard
  availability.
- ✅ Three commands: `inspect_whatsapp_customer_pilot --json`
  (read-only), `prepare_whatsapp_customer_pilot_member --phone ...`
  (creates/reuses Customer + pilot member only; pending if consent is
  missing; audit `whatsapp.pilot.member_prepared`), and
  `pause_whatsapp_customer_pilot_member --phone ...` (audit-only pause).
- ✅ New admin-only read endpoints:
  `/api/v1/whatsapp/monitoring/pilot/` and
  `/api/v1/whatsapp/monitoring/overview/` with masked phones only.
- ✅ `/whatsapp-monitoring` adds a read-only "Approved Customer Pilot
  Readiness" section with counts, blockers, `nextAction`, daily caps,
  and a masked member table. No send / enable / approve / pause buttons.
- ✅ SaaS guardrail audit is documented without forcing a multi-tenant
  migration into this single-tenant production release.

SaaS gaps intentionally deferred to Phase 7:

- No Organization / tenant model.
- No Branch model.
- No middleware-enforced tenant queryset scoping.
- No per-tenant feature flags.
- No per-tenant WhatsApp provider/settings record.
- No `AuditEvent` org/branch context fields.
- User roles exist today, but are global rather than tenant-scoped.

### Phase 5F — Campaign system (gated, later)

- Director-approved broadcast campaigns.
- Meta MARKETING template tier required.
- Per-campaign rate limit + dry-run + audit.
- Frontend: a Campaigns page for Director + Admin only.

### Phase 5 — Governance UI write paths (interleaved)

- Kill switch toggle endpoints (Section 12.1).
- Prompt rollback (already shipped in Phase 3D — frontend page exists).
- Reward/penalty leaderboard sweep UI on top of Phase 4B engine.
- Approval-matrix UI on top of Phase 4C middleware.

## Phase 6 — Learning loop

- Recording upload → speech-to-text → speaker separation pipeline.
- QA scoring → Compliance review → CAIO audit workflow tables.
- Sandbox test infrastructure.
- Approved learning → playbook version update.

## Phase 6A — SaaS Foundation Safe Migration ✅ shipped

What landed:

- `apps.saas` app with five tables: `Organization`, `Branch`,
  `OrganizationMembership`, `OrganizationFeatureFlag`,
  `OrganizationSetting` (rows flagged `is_sensitive=True` are
  filtered out of every public-API selector).
- Read-only selectors (`get_default_organization`,
  `get_user_organizations`, `is_feature_enabled`,
  `get_non_sensitive_settings`, …).
- Idempotent `ensure_default_organization` management command that
  seeds `Nirogidhara Private Limited` (code `nirogidhara`) + `Main
  Branch` (code `main`) and attaches existing users with sane
  default org-level roles.
- Three read-only DRF endpoints under `/api/v1/saas/`
  (`current-organization`, `my-organizations`, `feature-flags`).
- Read-only `OrgBadge` in the frontend topbar.
- One new audit kind: `saas.default_organization.ensured`.

Hard rules preserved:

- No existing model got an `organization` FK in this migration.
- No request middleware filters existing endpoints by organization.
- Customer / Order / Payment / Shipment / WhatsApp data stays
  un-tenant-scoped.
- WhatsApp env flags untouched.
- No real provider credentials migrated into `OrganizationSetting`.

## SaaS gaps still pending (driving Phase 6B+ scope)

| Gap | Phase | Notes |
| --- | --- | --- |
| Add `organization` FK to `Customer / Lead / Order / Payment / Shipment / WhatsAppMessage / WhatsAppConversation` and backfill the default org for all existing rows | **6B** | Must ship a backfill management command first; only after full backfill can foreign keys go non-nullable. |
| Org-scoped API filtering (every queryset filters on the request's active org) and a request middleware that resolves the active org from JWT claims | **6C** | Default org backstop required so any request without org context still returns the existing single-tenant view. |
| Per-org WhatsApp settings (provider, allow-list, auto-reply flag, lifecycle / call handoff / rescue / RTO / reorder flags) | **6D** | Currently global via env vars. Phase 6D moves them into `OrganizationSetting` with `is_sensitive=True` for credentials. |
| Per-org Meta Cloud credentials (access token, phone number id, business account id, verify token, app secret) | **6D** | Encrypted at rest before they land in `OrganizationSetting`; never returned by the public API. |
| Per-org Razorpay / PayU / Delhivery / Vapi credentials | **6D** | Same encryption + filtering rules as Meta. |
| Audit `organization` + `branch` context on every `AuditEvent` row | **6C** | Add nullable FKs first, then backfill. Helps multi-tenant audit dashboards. |
| Tenant data isolation tests (one org's data never leaks into another's API responses) | **6C / 6D** | Comprehensive cross-tenant integration suite. |
| Billing + subscription plan tables (`Plan`, `Subscription`, `BillingPeriod`, `Invoice`) | **6E** | Plus a public Stripe / Razorpay subscription webhook. |
| Tenant admin onboarding (organization create / branch create / member invite endpoints + UI) | **6E** | Phase 6A is read-only; Phase 6E ships the writes. |
| SaaS admin panel UI (org switcher, plan upgrade flow, member admin) | **6E** | Frontend `/saas-admin` page. |

## Phase 6B — Default Org Data Backfill ✅ shipped

What landed:

- Nullable `organization` (and `branch` where applicable) FKs added
  to 14 business-state models: `crm.Lead`, `crm.Customer`,
  `orders.Order`, `orders.DiscountOfferLog`, `payments.Payment`,
  `shipments.Shipment`, `calls.Call`, `whatsapp.WhatsAppConsent`,
  `whatsapp.WhatsAppConversation`, `whatsapp.WhatsAppMessage`,
  `whatsapp.WhatsAppLifecycleEvent`, `whatsapp.WhatsAppHandoffToCall`,
  `whatsapp.WhatsAppPilotCohortMember`, `audit.AuditEvent`.
- Idempotent `backfill_default_organization_data` management command
  (dry-run default; `--apply` writes; never overwrites existing
  assignments). Emits
  `saas.default_org_backfill.{started,completed,failed}` audits.
- `inspect_default_organization_coverage` management command + the
  `apps.saas.coverage.compute_default_organization_coverage`
  selector are the single source of truth.
- `GET /api/v1/saas/data-coverage/` endpoint mirrors the inspector.
- Read-only `SaasCoverageCard` on the dashboard.

Hard rules preserved:

- `globalTenantFilteringEnabled` stays `False` for this whole phase.
- FKs stay nullable.
- No middleware scopes existing endpoints per tenant yet.
- No queryset filtering on tenant.
- WhatsApp env flags untouched.

## Phase 6C — Org-Scoped API Filtering Plan ✅ shipped

What landed:

- `apps.saas.context` module — seven resolvers
  (`get_default_organization`, `get_user_active_organization`,
  `resolve_request_organization`, `user_has_org_access`, etc.) and
  four queryset helpers (`filter_queryset_by_organization`,
  `scoped_queryset_for_user`, `scoped_queryset_for_request`,
  `attach_default_org_filter_if_model_supports_org`).
- `apps.audit.signals.write_event` upgraded to auto-attach the
  active organization (explicit param > request > user > default-org
  fallback). Backwards-compatible.
- `apps.saas.readiness.compute_org_scoped_api_readiness` selector +
  `inspect_org_scoped_api_readiness` management command +
  `GET /api/v1/saas/org-scope-readiness/` API.
- Read-only `OrgScopeReadinessCard` on the dashboard.
- Two-org leak proofs in tests for Customer, Order,
  WhatsAppConversation.

Hard rules preserved:

- `globalTenantFilteringEnabled` stays `False` — no blanket
  queryset-filtering middleware yet (Phase 6E).
- FKs stay nullable.
- Superusers still see across tenants for diagnostics.
- Models without an `organization` field are returned unchanged by
  the helpers.
- WhatsApp env flags untouched.

## Phase 6D — Org-Aware Write Path Assignment ✅ shipped

What landed:

- `apps.saas.write_context` module with six pure helpers that resolve
  + apply org/branch context (`resolve_write_organization`,
  `resolve_write_branch`, `apply_org_branch`,
  `get_parent_org_branch`, `assign_org_branch_from_parent`,
  `assign_org_branch_from_first_parent`).
- `apps.saas.signals.auto_assign_org_branch` pre_save receiver wired
  via `SaasConfig.ready` to 13 business-state models. Fires only on
  create + when FK is NULL. Walks parent chain, falls back to default.
- `apps.saas.write_readiness.compute_org_write_path_readiness`
  selector + `inspect_org_write_path_readiness` management command +
  `GET /api/v1/saas/write-path-readiness/` API.
- Read-only `WritePathReadinessCard` on the dashboard.
- Cross-tenant write-leak proof in tests.

Hard rules preserved:

- Signal NEVER overwrites explicit assignments.
- Signal NEVER fires on bulk `QuerySet.update()` (backfill path).
- Signal NEVER crashes a save (silent on errors).
- FKs stay nullable.
- `globalTenantFilteringEnabled` stays `False` (Phase 6E).
- Business-state status logic untouched.
- WhatsApp env flags untouched.

## Phase 6E — SaaS Admin + Integration Settings Foundation ✅ shipped

What landed:

- `OrganizationIntegrationSetting` stores per-org provider readiness for
  WhatsApp Meta, Razorpay, PayU, Delhivery, Vapi, OpenAI, and `other`.
- Only non-sensitive `config` and `ENV:` / `VAULT:` `secret_refs` are allowed.
  Raw secret values are rejected and never returned by APIs.
- `apps.saas.integration_settings` masks secret refs and computes provider
  readiness. Runtime providers still use env/config exactly as before.
- Admin-protected APIs expose SaaS overview, organizations, integration
  settings, integration readiness, org-scope readiness, and write-path
  readiness. Safe integration-setting create/update is audit logged, but does
  not activate any provider or call external APIs.
- Frontend `/saas-admin` renders organization overview, org/write readiness,
  integration readiness, safety locks, and SaaS audit events with no send,
  enable, campaign, or provider-activation buttons.
- `inspect_saas_admin_readiness --json` and
  `inspect_org_integration_settings --json` provide deploy diagnostics.

Hard rules preserved:

- Phase 6D org-aware write assignment is **FULL PASS**.
- Runtime providers still read env/config; per-org runtime provider routing is
  deferred to **Phase 6F Per-Org Runtime Integration Routing Plan**.
- `globalTenantFilteringEnabled` stays `False`; no blanket tenant middleware.
- Organization/branch FKs stay nullable.
- WhatsApp flags remain untouched/off; campaigns/broadcast/lifecycle/call/
  rescue/RTO/reorder remain locked.

## Phase 6F — Per-Org Runtime Integration Routing Plan ✅ shipped

What landed:

- `apps.saas.integration_runtime` resolver layer with secret-ref
  helpers, per-provider preview, and combined `safeToStartPhase6G`
  composition. Live runtime is unchanged (`runtimeSource="env_config"`
  always, `runtimeUsesPerOrgSettings=False` always).
- `inspect_runtime_integration_routing` management command +
  `GET /api/v1/saas/runtime-routing-readiness/` admin-only API.
- Idempotent `seed_default_org_integration_refs` command — writes
  ENV: secret refs only (no raw values), defaults to dry-run, emits
  `saas.integration_refs.seeded` audit rows on apply.
- SaaS Admin Panel "Runtime Integration Routing Preview" section
  with six provider rows and a clear "Per-org runtime routing is
  not active" banner.

Hard rules preserved:

- Raw secret values NEVER stored, logged, or returned.
- ENV: refs return PRESENCE only (boolean); VAULT: refs return
  `planned/not_configured`.
- No external provider calls; no live runtime switch.
- WhatsApp env flags untouched; broad-automation flags remain
  LOCKED OFF; campaigns / broadcast remain LOCKED.

## Phase 6G — Controlled Runtime Routing Dry Run + AI Provider Routing ✅ shipped

What landed: 14-operation `apps.saas.runtime_operations` taxonomy, NVIDIA-primary AI routing table (with OpenAI + Anthropic Claude fallbacks), `apps.saas.runtime_dry_run` composer, three read-only management commands + one operator-only `smoke_test_ai_provider_routes` (the only path that may issue a tiny live AI request), three admin-only DRF endpoints, and `/saas-admin` "Controlled Runtime Routing Dry Run" + "AI Provider Routing Preview" sections. Hard invariant `validate_dry_run_has_no_side_effects` asserts every dry-run output keeps `dryRun=true`, `externalCallWillBeMade=false`. Raw NVIDIA / OpenAI / Anthropic / Razorpay / Meta / Vapi keys never appear in any output.

## Phase 6H — Controlled Runtime Routing Live Audit Gate ✅ shipped

What landed: `apps.saas.live_gate_policy` (every operation `allowedInPhase6H=false`), `RuntimeLiveGatePolicySnapshot` / `RuntimeLiveExecutionRequest` / `RuntimeKillSwitch` models (default global kill switch enabled), `apps.saas.live_gate` audit-only decision recorder, `/api/v1/saas/runtime-live-gate/...` admin APIs, and `/saas-admin` "Controlled Runtime Live Audit Gate" section. Approval in Phase 6H is audit-only — never executes a provider call.

## Phase 6I — Single Internal Live Gate Simulation ✅ shipped

What landed: `RuntimeLiveGateSimulation` model, simulation-only service, six management commands (prepare / request-approval / approve / reject / run / rollback), `/api/v1/saas/runtime-live-gate/simulations/` admin APIs, and `/saas-admin` "Single Internal Live Gate Simulation" section. Hard invariant: every simulation response keeps `dryRun=true`, `externalCallWillBeMade=false`, `externalCallWasMade=false`, `providerCallAttempted=false`.

## Phase 6J — Single Internal Provider Test Plan ✅ shipped

What landed: `apps.saas.provider_test_plan_policy` (seven plan policies registered; only **target** is `razorpay.create_order`), `RuntimeProviderTestPlan` model, six strictly-read-only / plan-only management commands, seven admin-only DRF endpoints under `/api/v1/saas/provider-test-plans/`, and `/saas-admin` "Single Internal Provider Test Plan" section. Razorpay synthetic payload locked: `{amount: 100, currency: "INR", receipt: "phase6j_internal_test_plan_<plan_id>"}`. Asserted by `assert_provider_test_plan_has_no_side_effects`. Approval ONLY unlocks a future Phase 6K execution gate; never enables a provider call in Phase 6J.

## Phase 6K-A — Single Internal Razorpay Test-Mode Execution Gate ✅ shipped (code/gate/readiness only)

What landed: `apps.saas.provider_execution_policy` (one Phase 6K target — `razorpay.create_order` against a Razorpay TEST key — with `amount_paise=100`, `real_money=False`, `api_execution_allowed=False` (CLI-only), `frontend_execution_allowed=False`, `max_executions_per_approved_plan=1`), `RuntimeProviderExecutionAttempt` model, Phase-6K-only `apps.saas.razorpay_test_execution` adapter (separate from the Phase 2B production payment-link client), five management commands (`execute_single_razorpay_test_order` is the ONLY one that may dispatch — refuses unless approved Phase 6J plan + `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=true` + `--confirm-test-execution` + `RAZORPAY_KEY_ID` starts with `rzp_test` + no prior successful execution), and five admin-only DRF endpoints (intentionally **no** `POST execute` endpoint).

## Phase 6K-B — Manual VPS one-shot real Razorpay test-mode execution ✅ shipped

Immutable artefact: `execution_id=pex_8f309650e9644cfaae4418f9` → `provider_object_id=order_Sks3KPf0vntKhf`, `amount_paise=100`, `currency=INR`. **No payment link, no capture, no notification, no business mutation.** `rollback_status=completed`. `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED` flipped back to `false` immediately after the run. The only real provider-side write the platform has ever made.

## Phase 6L — Razorpay Test Execution Audit Review + Webhook Readiness Plan ✅ shipped

What landed: `apps.saas.razorpay_audit_review` ships `review_razorpay_test_execution_audit(execution_id)` (replays the 10 Phase 6K invariants + scans every linked AuditEvent for raw-key leak), `inspect_razorpay_webhook_readiness()` (env presence-only — masked Razorpay key id + webhook secret presence boolean), `plan_razorpay_webhook_readiness()` (canonical webhook policy doc with HMAC-SHA256 + 300-second replay window + 9-event allowlist + 9-event denylist + 13-key sensitive-payload scrub list + `businessMutationPolicy` all-False). Three read-only management commands + three auth-required DRF endpoints under `/api/v1/saas/razorpay/`. Phase 6L never calls Razorpay, never returns the raw provider response (whitelisted summary only).

## Phase 6M-0 — MCP Gateway Foundation + AI Connector Readiness ✅ shipped (dormant)

What landed: `apps.mcp_gateway` Django app with six models (`McpClientApp`, `McpAccessPolicy`, `McpToolDefinition`, `McpResourceDefinition`, `McpPromptDefinition`, `McpToolInvocationLog`), 13-name forbidden-tool list, `MCP_ENABLED=false` / `MCP_READ_ONLY_MODE=true` / `MCP_WRITE_TOOLS_ENABLED=false` / `MCP_PROVIDER_TOOLS_ENABLED=false` defaults, admin-only readiness APIs under `/api/v1/mcp/`, idempotent registry seed command, PII / raw-secret detection helpers (`detect_raw_secret`, `detect_full_pii` with `\b\d{10,}\b` word-boundary digit match to avoid timestamp false positives), and `/saas-admin` "MCP Gateway Readiness" dormant section.

## Phase 6M — Razorpay Webhook Handler Implementation (test-mode, dormant by default) ✅ shipped

What landed: `apps.payments.razorpay_webhooks.process_razorpay_webhook` ships HMAC-SHA256 signature verification over the raw body in constant time, 300-second replay window validation, idempotency on `X-Razorpay-Event-Id`, 9-event allowlist + 9-event denylist, 13-key sensitive-payload scrub list, `assert_no_business_mutation` invariant, and a safe-summary persistence path on `RazorpayWebhookEvent`. New `POST /api/webhooks/razorpay/test/` endpoint (separate from the Phase 2B production `/api/webhooks/razorpay/`). Four read-only / planning management commands. Four auth-required DRF readiness/list/detail/simulate APIs under `/api/v1/saas/razorpay/webhook-...`. `/saas-admin` adds "Razorpay Webhook Handler (Test Mode)" section. 9 new audit kinds (`razorpay.webhook.*`).

Hard rules preserved:

- Dormant by default — `RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false`,
  `RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED=false`,
  `RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED=false`,
  `RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD=false`.
- Order / Payment / Shipment / DiscountOfferLog / Customer never
  mutated (asserted in tests via `assert_no_business_mutation`).
- No customer notification ever sent.
- Production webhook secret is **never** consumed by this handler.

## Phase 6N — Razorpay Webhook Business-Mutation Sandbox Plan ✅ shipped (planning-only / readiness-only)

What landed: new `apps.saas.razorpay_business_mutation_plan` ships seven
pure functions (`get_razorpay_business_mutation_sandbox_plan`,
`inspect_razorpay_business_mutation_sandbox_readiness`,
`build_razorpay_event_status_mapping_plan`,
`build_synthetic_order_eligibility_policy`,
`build_phase6n_manual_review_checklist`,
`build_phase6n_rollback_plan`,
`validate_phase6n_no_mutation_invariants`). Nine Razorpay events mapped
(`payment_link.paid`, `payment.captured`, `payment.failed`,
`payment.authorized`, `order.paid`, `payment_link.cancelled`,
`payment_link.expired`, `refund.created`, `refund.processed`); every row
carries `mutationAllowedInPhase6N=False`,
`customerNotificationAllowed=False`, `shipmentEffectAllowed=False`,
`discountEffectAllowed=False`, `idempotencyRequired=True`,
`rollbackRequired=True`. Synthetic-order eligibility policy + 8-item
manual review checklist + 7-step rollback plan + locked safety
invariants. Two read-only management commands
(`inspect_razorpay_business_mutation_sandbox_plan`,
`inspect_razorpay_business_mutation_sandbox_readiness`). Two
admin/auth-protected GET endpoints under `/api/v1/saas/razorpay/`
(POST/PATCH/DELETE return 405). `/saas-admin` adds a "Razorpay Business
Mutation Sandbox Plan" read-only section. **No DB migration. No env
flag flipped. No provider call. No business mutation. No customer
notification.** 35 new backend tests + 2 new frontend tests; 1318
backend / 50 frontend, all green.

Hard rules preserved:

- Phase 6M handler stays dormant
  (`RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false`,
  `RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED=false`,
  `RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED=false`,
  `RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD=false`).
- Order / Payment / Shipment / DiscountOfferLog / Customer never
  mutated by Phase 6N code paths (asserted with before/after counts +
  mock-spies on the Razorpay client / WhatsApp send / Vapi trigger).
- `RuntimeKillSwitch` remains enabled.
- Raw secrets / planted PII never appear in any Phase 6N output (asserted in tests with planted env values + planted Customer rows).

## Phase 6O — Razorpay Sandbox Status Mapping + Manual Review ✅ shipped (sandbox-review-only)

What landed: new `apps.payments.RazorpaySandboxStatusReview` model
(migration `payments.0005_phase6o_razorpay_sandbox_status_review` —
new table only, no existing-row schema drift). New
`apps.payments.razorpay_sandbox_status_mapping` service module ships
10 functions covering the full review lifecycle (mapping + readiness
+ eligibility + preview + prepare + approve + reject + archive +
invariant-violation assertion + summary). Six management commands
(`inspect_razorpay_sandbox_status_mapping_readiness`,
`preview_razorpay_sandbox_status_mapping`,
`prepare_razorpay_sandbox_status_review`,
`approve_razorpay_sandbox_status_review`,
`reject_razorpay_sandbox_status_review`,
`archive_razorpay_sandbox_status_review`). Seven admin/auth-protected
DRF endpoints under `/api/v1/saas/razorpay/sandbox-status-...`.
Eight new audit kinds. New env flag
`RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED` (default `False`) gates
`prepare`. `/saas-admin` adds a "Razorpay Sandbox Status Mapping +
Manual Review" section with **only** "Approve Review Only" /
"Reject Review" / "Archive Review" buttons.

Hard rules preserved (asserted in 29 new pytest cases):

- Approving a review flips its `status` to
  `approved_for_future_phase6p` only — `Order` / `Payment` /
  `Shipment` / `DiscountOfferLog` / `Customer` are NEVER touched
  (asserted with before/after counts).
- No Razorpay client / WhatsApp send / Vapi trigger invocation
  (asserted with mock spies).
- `mutationAllowedInPhase6O=False` on every event-mapping row and
  every persisted review.
- Output never carries planted secrets (`RAZORPAY_KEY_*`,
  `RAZORPAY_WEBHOOK_SECRET`) or planted PII (Customer phone / name).
- Endpoints admin/auth gated; POST/PATCH/DELETE on read endpoints
  return 405.
- Production `.env.production` is not edited.

## Phase 6P — Controlled internal paid-status mutation test (Planned · Not started)

Implementation-only synthetic `Order.status` / `Payment.status` flip,
behind a NEW env flag distinct from
`RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED`. Phase 6P must:

1. Introduce the new env flag (default off) — suggested name
   `RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED`.
2. Refuse to mutate unless: (a) source `RazorpaySandboxStatusReview.status
   == approved_for_future_phase6p`, (b) the linked
   `RazorpayWebhookEvent` is synthetic-eligible per Phase 6O policy,
   (c) the new env flag is `True`, (d) a Director sign-off
   `AuditEvent` exists for the review id, (e) the synthetic-order
   resolver accepts only `phase6j_internal_test_plan_*` /
   `phase6n_sandbox_synthetic_*` prefixes.
3. Add audit kinds `razorpay.sandbox_paid_status.{applied,blocked,rolled_back}`.
4. Provide a CLI rollback command that restores the synthetic row to
   pre-mutation state.

Acceptance criteria for the Phase 6P implementation:

- Every Phase 6N + 6O safety invariant stays true on real (non-synthetic)
  rows;
- The new sandbox env flag stays `False` in `.env.production`;
- `business_mutation_was_made` / `customer_notification_sent` stay
  `False` on every real `RazorpayWebhookEvent` and every
  `RazorpaySandboxStatusReview` row.

## Recommended future phases

- **Phase 6B — Default-org data backfill.** ✅ shipped — see above.
- **Phase 6C — Org-scoped API filtering.** Tenant middleware + queryset filtering across every existing endpoint. Cross-tenant integration tests assert isolation. Make `organization` FK non-nullable. Add `organization` + `branch` context to `AuditEvent`.
- **Phase 6D — Per-org integration settings.** Move WhatsApp / Meta / Razorpay / PayU / Delhivery / Vapi credentials into encrypted `OrganizationSetting` rows. Per-org WhatsApp automation flags. Per-org Claim Vault.
- **Phase 6E — SaaS admin panel.** Org create / member invite / plan upgrade endpoints + UI. Billing + subscription tables. Public Stripe / Razorpay subscription webhooks.

## Phase 7 — Multi-tenant SaaS (legacy roadmap entry — superseded by Phase 6A–E above)

- Tenant model + middleware that scopes every queryset.
- Per-tenant settings, integrations, claim vault.
- Billing.

## Out of scope forever (or until explicitly requested)

- Implementing the full reward formula in JS / pushing it to the frontend.
- Mobile push notifications.
- E2E Playwright suite (the prototype phase doesn't need it).
