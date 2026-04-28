# Backend Roadmap (Phase 2+)

Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B + 3C + 3D + 3E + 4A + 4B + 4C + 4D are shipped (see `nd.md` §8 for the full checkpoint trail).
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
  WhatsApp / production live-mode-switch handlers. Those stay
  intentionally unmapped until the next phase.

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

## Phase 5 — Governance UI write paths

- Kill switch toggle endpoints (Section 12.1).
- Prompt rollback (already shipped in Phase 3D — frontend page exists).
- Reward/penalty leaderboard sweep UI on top of Phase 4B engine.
- Approval-matrix UI on top of Phase 4C middleware.

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
