# Backend API Reference

Django REST Framework endpoints exposed by `backend/`. Every entry is consumed
by `frontend/src/services/api.ts`. Response shapes match the TypeScript
interfaces in `frontend/src/types/domain.ts`.

All paths are prefixed by `/api/`. JSON in, JSON out. CORS allows
`http://localhost:8080` by default.

## Health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/healthz/` | Liveness probe |

## Auth

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/auth/token/` | none | JWT login (`{username, password}`) |
| POST | `/api/auth/refresh/` | refresh token | Rotate access token |
| GET | `/api/auth/me/` | bearer access | Current user + role |
| GET | `/api/settings/` | none | Approval matrix + integration flags + kill-switch state |

## Dashboard

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/dashboard/metrics/` | `Record<string, DashboardMetric>` |
| GET | `/api/dashboard/activity/` | `ActivityEvent[]` (last 25 audit-ledger rows) |

## CRM

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/leads/` | `Lead[]` (now exposes optional `metaLeadgenId`, `metaPageId`, `metaFormId`, `metaAdId`, `metaCampaignId`, `sourceDetail` — all populated when ingested via the Meta webhook) |
| GET | `/api/leads/{id}/` | `Lead` |
| GET | `/api/customers/` | `Customer[]` |
| GET | `/api/customers/{id}/` | `Customer` |

## Orders

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/orders/` | `Order[]` |
| GET | `/api/orders/pipeline/` | `Order[]` (sorted by stage) |
| GET | `/api/confirmation/queue/` | `(Order & {hoursWaiting, addressConfidence, checklist})[]` |

## Calls

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/calls/` | `Call[]` (now exposes `provider`, `providerCallId`, `summary`, `recordingUrl`, `handoffFlags`) |
| GET | `/api/calls/active/` | `ActiveCall` (latest) |
| GET | `/api/calls/active/transcript/` | `CallTranscriptLine[]` |

## Payments / Shipments / RTO

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/payments/` | `Payment[]` |
| GET | `/api/shipments/` | `Shipment[]` (with `timeline`, `trackingUrl`, `riskFlag`) |
| GET | `/api/rto/risk/` | `(Order & {riskReasons, rescueStatus})[]` |

## Agents & AI Governance

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/agents/` | `Agent[]` |
| GET | `/api/agents/hierarchy/` | `{root, ceo, caio, departments}` |
| GET | `/api/ai/ceo-briefing/` | `CeoBriefing` (latest) |
| GET | `/api/ai/caio-audits/` | `CaioAudit[]` |
| GET | `/api/ai/agent-runs/` | `AgentRun[]` (Phase 3A — admin/director only) |
| GET | `/api/ai/agent-runs/{id}/` | `AgentRun` (admin/director only) |
| GET | `/api/ai/agent-runtime/status/` | `{phase, dryRunOnly, agents, lastRuns}` (Phase 3B — admin/director only) |
| GET | `/api/ai/scheduler/status/` | `{celeryConfigured, celeryEagerMode, redisConfigured, brokerUrl (redacted), timezone, morningSchedule, eveningSchedule, lastDailyBriefingRun, lastCaioSweepRun, aiProvider, primaryModel, fallbacks, lastCostUsd, lastFallbackUsed}` (Phase 3C — admin/director only) |
| GET | `/api/ai/sandbox/status/` | Sandbox singleton: `{isEnabled, note, updatedBy, updatedAt}` (Phase 3D — admin/director only) |
| GET | `/api/ai/prompt-versions/` (`?agent=`) | List prompt versions (Phase 3D — admin/director only) |
| GET | `/api/ai/prompt-versions/{id}/` | Single prompt version |
| GET | `/api/ai/budgets/` | Per-agent budgets with current daily/monthly spend decoration |

## Compliance / Rewards / Learning

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/compliance/claims/` | `Claim[]` (Approved Claim Vault) |
| GET | `/api/rewards/` | `RewardPenalty[]` |
| GET | `/api/learning/recordings/` | `LearningRecording[]` |

## Analytics

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/analytics/` | `{funnel, revenueTrend, stateRto, productPerformance, discountImpact}` |
| GET | `/api/analytics/funnel/` | `KPITrend[]` |
| GET | `/api/analytics/revenue-trend/` | `KPITrend[]` |
| GET | `/api/analytics/state-rto/` | `KPITrend[]` |
| GET | `/api/analytics/product-performance/` | `KPITrend[]` |

## Field naming

DRF serializers expose camelCase (e.g. `qualityScore`, `paymentLinkSent`,
`rtoRisk`) so the JSON matches the TS interfaces 1-to-1. DB columns stay
snake_case Python-side. The mapping lives in each app's `serializers.py`.

## Master Event Ledger

The `audit.AuditEvent` table is the source of truth for `/api/dashboard/activity/`.
Receivers in `apps/audit/signals.py` write rows on:

- `lead.created` — Lead row created (post-save signal)
- `lead.updated` — explicit, fired by service layer on PATCH
- `lead.assigned` — explicit, fired by service layer on POST `/leads/{id}/assign/`
- `customer.upserted` — explicit, on POST/PATCH customers
- `order.created` / `order.status_changed` — Order row created or stage changed (post-save signal)
- `confirmation.outcome` — explicit, on POST `/orders/{id}/confirm/`
- `payment.link_created` — explicit, on POST `/payments/links/`
- `payment.received` — Payment row saved with status=Paid (post-save signal)
- `shipment.created` — explicit, on POST `/shipments/`
- `shipment.status_changed` — Shipment row saved (post-save signal)
- `shipment.delivered` — explicit, on Delhivery webhook `delivered`
- `shipment.ndr` — explicit, on Delhivery webhook `ndr`
- `shipment.rto_initiated` / `shipment.rto_delivered` — explicit, on Delhivery webhook RTO events
- `rescue.attempted` / `rescue.updated` — explicit, on POST/PATCH `/rto/rescue/`
- `call.triggered` — explicit, on POST `/api/calls/trigger/`
- `call.started` / `call.completed` / `call.failed` — explicit, on Vapi webhook
- `call.transcript` — explicit, on Vapi `transcript.updated` / `transcript.final`
- `call.analysis` / `call.handoff_flagged` — explicit, on Vapi `analysis.completed` (handoff_flagged fires only when one of the 6 safety triggers is present)
- `lead.meta_ingested` — explicit, on Meta Lead Ads webhook delivery (created or refreshed)
- `ai.agent_run.created` / `ai.agent_run.completed` / `ai.agent_run.failed` — explicit, on POST `/api/ai/agent-runs/` (Phase 3A)
- `ai.ceo_brief.generated` — explicit, on CEO daily briefing run when the LLM returns usable content (Phase 3B)
- `ai.caio_sweep.completed` — explicit, on CAIO audit-sweep success (Phase 3B)
- `ai.agent_runtime.completed` / `ai.agent_runtime.failed` — explicit, on every per-agent runtime endpoint (Phase 3B)
- `ai.scheduler.daily_briefing.started` / `.completed` / `.failed` — explicit, on the Celery beat task wrapping CEO + CAIO sweeps (Phase 3C)
- `ai.provider.fallback_used` — explicit, when the dispatcher answered with a fallback provider after the primary failed (Phase 3C)
- `ai.cost_tracked` — explicit, on every successful AgentRun whose adapter reported token usage (Phase 3C)
- `ai.prompt_version.created` / `.activated` / `.rolled_back` — explicit, on PromptVersion CRUD + activate + rollback (Phase 3D)
- `ai.sandbox.enabled` / `.disabled` — explicit, on PATCH `/api/ai/sandbox/status/` (Phase 3D)
- `ai.budget.warning` / `.blocked` — explicit, when an agent's spend crosses the alert threshold or exceeds the configured cap (Phase 3D)

Phase 4+ will add: reward/penalty assigned, CAIO audit completed,
CEO approval recorded.

---

## Writes (Phase 2A)

All write endpoints require `Authorization: Bearer <jwt>` and a user role of
`operations`, `admin`, or `director`. Anonymous → 401, viewer/compliance → 403.

### CRM

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/leads/` | Create a lead |
| PATCH | `/api/leads/{id}/` | Update lead fields |
| POST | `/api/leads/{id}/assign/` | Assign a lead (`{ assignee }`) |
| POST | `/api/customers/` | Create a customer (upsert) |
| PATCH | `/api/customers/{id}/` | Update a customer |

### Orders & confirmation

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/orders/` | Punch a new order |
| POST | `/api/orders/{id}/transition/` | Move order to a new stage (validated by state machine) |
| POST | `/api/orders/{id}/move-to-confirmation/` | Convenience for `Order Punched → Confirmation Pending` |
| POST | `/api/orders/{id}/confirm/` | Record confirmation outcome (`confirmed` / `rescue_needed` / `cancelled`) |

#### State machine

```
New Lead              → Interested, Cancelled
Interested            → Payment Link Sent, Order Punched, Cancelled
Payment Link Sent     → Order Punched, Cancelled
Order Punched         → Confirmation Pending, Cancelled
Confirmation Pending  → Confirmed, Cancelled  (rescue_needed stays here)
Confirmed             → Dispatched, Cancelled
Dispatched            → Out for Delivery, RTO
Out for Delivery      → Delivered, RTO
Delivered             → terminal (reorder cycle in Phase 6)
RTO                   → terminal (reward/penalty in Phase 5)
Cancelled             → terminal
```

Invalid transitions return HTTP 400 with a `detail` message.

### Payments

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/payments/links/` | Mock payment link generator. Body: `{ orderId, amount, gateway, type }`. Returns `{ payment, paymentUrl }`. The Payment row starts in `Pending` status. |

### Shipments & RTO rescue

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/shipments/` | Create a Delhivery shipment. Body: `{ orderId }`. Routes through the three-mode adapter (`DELHIVERY_MODE=mock\|test\|live`). Mock mode generates `DLH<8 digits>` deterministically; test/live mode hits the real Delhivery API. Returns the `Shipment` row with `trackingUrl` populated. |
| POST | `/api/rto/rescue/` | Create a rescue attempt. Body: `{ orderId, channel, notes? }`. |
| PATCH | `/api/rto/rescue/{id}/` | Update outcome. Body: `{ outcome, notes? }`. Bubbles up to parent order's `rescue_status`. |

### Voice (Phase 2D)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/calls/trigger/` | Trigger an outbound Vapi voice call. Body: `{ leadId, purpose? }`. Routes through the three-mode adapter (`VAPI_MODE=mock\|test\|live`). Returns `{ callId, provider, status, leadId, providerCallId }`. |

### AI agent runs (Phase 3A — read-only / dry-run)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/ai/agent-runs/` | Trigger a dry-run agent analysis. Body: `{ agent: "ceo"\|"caio"\|"ads"\|"rto"\|"sales_growth"\|"marketing"\|"cfo"\|"compliance", input: {...}, dryRun?: true }`. Admin/director only. Phase 3A coerces `dryRun` to `true` server-side; the field is on the wire for forward-compat with Phase 5 approval-matrix execution. Routes through `apps/integrations/ai/<provider>.py` based on `AI_PROVIDER` (`disabled`/`openai`/`anthropic`/`grok`). When the provider is disabled or no key is configured the run is persisted with `status: "skipped"` — no LLM call. Every call is grounded in `apps.compliance.Claim` via the prompt builder; medical/product prompts with no approved-claim entries return `failed` rather than dispatching. CAIO can never execute business actions: payloads with intents like `execute`, `apply`, `create_order`, `transition`, etc. are rejected before any LLM dispatch. |
| GET | `/api/ai/agent-runs/` | List recent agent runs (admin/director only). |
| GET | `/api/ai/agent-runs/{id}/` | Single run detail (admin/director only). |

### AI agent runtime (Phase 3B — per-agent dispatch with pre-built DB slices)

Every endpoint is admin/director only and dry-run by construction. Each call dispatches the agent's read-only DB slice through `run_readonly_agent_analysis`; the underlying LLM never runs when `AI_PROVIDER=disabled` (every run is persisted as `skipped`). Each endpoint returns the persisted `AgentRun`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/agent-runtime/status/` | Snapshot — phase + dry-run flag + the last `AgentRun` per agent. |
| POST | `/api/ai/agent-runtime/ceo/daily-brief/` | Generate the daily CEO briefing. On `success` with usable output, refreshes the `CeoBriefing` row + writes `ai.ceo_brief.generated`. Skipped/failed runs leave the existing briefing untouched. |
| POST | `/api/ai/agent-runtime/caio/audit-sweep/` | CAIO audit/monitor sweep. Reads recent `AgentRun` rows + handoff flags + Claim Vault status. Never writes to business state — `services.CAIO_FORBIDDEN_INTENTS` blocks any execute/apply/create_* payload before the LLM is called. |
| POST | `/api/ai/agent-runtime/ads/analyze/` | Meta attribution + ad recommendations. Reads `Lead.meta_*` fields grouped by campaign / ad / form. |
| POST | `/api/ai/agent-runtime/rto/analyze/` | High-risk orders, NDR/RTO shipments, and rescue-attempt outcomes. Suggestions only. |
| POST | `/api/ai/agent-runtime/sales-growth/analyze/` | Call outcomes + order conversion + advance/discount ratios. |
| POST | `/api/ai/agent-runtime/cfo/analyze/` | Revenue + delivered/RTO + payment status. Reporting only. |
| POST | `/api/ai/agent-runtime/compliance/analyze/` | Claim Vault coverage + handoff flags + critical CAIO audits. Fails closed when the vault is empty (`ClaimVaultMissing` → `failed` AgentRun). |

Cron / Windows Task Scheduler can also call `python manage.py run_daily_ai_briefing` to fire the CEO + CAIO sweeps in one shot (`--skip-ceo` / `--skip-caio` to run just one).

### AI scheduler + cost tracking (Phase 3C)

Celery beat schedules the daily CEO briefing + CAIO sweep at **09:00 IST** (morning) and **18:00 IST** (evening). The dispatcher walks the provider chain in `AI_PROVIDER_FALLBACKS` (default: `openai → anthropic`); the first provider whose adapter returns `success` wins. Every AgentRun row stores `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`, `provider_attempts` (full attempt log), `fallback_used`, and `pricing_snapshot` (model-wise rates from `apps/integrations/ai/pricing.py` frozen at run time).

Local dev never needs Redis: `CELERY_TASK_ALWAYS_EAGER=true` (the default) makes `.delay()` run synchronously. To run the beat schedule for real:

```bash
docker compose -f docker-compose.dev.yml up -d redis
celery -A config worker -B --loglevel=info
```

Pricing fallback for `ClaimVaultMissing`: never. The prompt builder fails closed before any adapter is invoked, so a compliance refusal does not trigger a fallback to a different provider.

### AI governance — sandbox / prompt rollback / budget guards (Phase 3D)

All endpoints are admin/director only.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/sandbox/status/` | Read the global sandbox toggle. |
| PATCH | `/api/ai/sandbox/status/` | Body: `{ isEnabled, note? }`. Flips the singleton; writes `ai.sandbox.{enabled,disabled}`. While ON, successful AgentRuns NEVER refresh `CeoBriefing` or any other business-state row. |
| POST | `/api/ai/prompt-versions/` | Body: `{ agent, version, title?, systemPolicy?, rolePrompt?, instructionPayload?, metadata? }`. Creates a `draft` PromptVersion. The Approved Claim Vault block is always appended to every dispatched prompt — a PromptVersion CANNOT skip it. |
| POST | `/api/ai/prompt-versions/{id}/activate/` | Make this version the active one for its agent. The previous active version is auto-archived. |
| POST | `/api/ai/prompt-versions/{id}/rollback/` | Body: `{ reason }`. Re-activate this version and mark the prior active as `rolled_back` with the reason recorded. |
| POST | `/api/ai/budgets/` | Upsert by `agent`. Body: `{ agent, dailyBudgetUsd, monthlyBudgetUsd, isEnforced?, alertThresholdPct? }`. |
| PATCH | `/api/ai/budgets/{id}/` | Update an existing budget row. |

Behavior of the budget guard inside `run_readonly_agent_analysis`:

1. Compute the agent's daily + monthly spend from successful `AgentRun.cost_usd`.
2. If `is_enforced=True` AND spend exceeds the daily or monthly cap → write `ai.budget.blocked`, persist a `failed` AgentRun, and **never** call any adapter (no fallback either).
3. Else if spend ≥ `alert_threshold_pct`% of either cap → write `ai.budget.warning` and continue.
4. Snapshot of the budget check is stamped onto every `AgentRun.budget_snapshot`.

### Reward / Penalty Engine (Phase 4B)

The legacy `GET /api/rewards/` list endpoint stays public and now returns the agent-level rollup with Phase 4B fields (`agentId`, `agentType`, `rewardedOrders`, `penalizedOrders`, `lastCalculatedAt`) appended in camelCase. Three new endpoints power the per-order scoring view:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/rewards/` | Agent-level leaderboard (camelCase). Public read; backwards-compatible. |
| GET | `/api/rewards/events/` | Per-order, per-AI-agent scoring events. **Admin/director only.** Query params: `agent` (substring match on agent name), `orderId` (exact), `eventType` (`reward`/`penalty`/`mixed`), `limit` (default 200, max 1000). |
| GET | `/api/rewards/summary/` | Top-line totals + last sweep snapshot + agent leaderboard + missing-data warnings. **Admin/director only.** |
| POST | `/api/rewards/sweep/` | Trigger a sweep. **Admin/director only.** Body `{ startDate?, endDate?, orderId?, dryRun? }`. Returns `{ evaluatedOrders, createdEvents, updatedEvents, skippedOrders, totalReward, totalPenalty, netScore, dryRun, leaderboardUpdated, missingDataWarnings }`. |

**Locked rules** (Master Blueprint §10.2 + §26 + Prarit Apr 2026):
- AI-agents only — no human staff scoring.
- Eligible stages: `Delivered` (rewards), `RTO` + `Cancelled` (penalties); other stages skipped.
- **CEO AI net accountability** — every delivered order generates a CEO AI reward event mirroring the order's reward total; every RTO / cancelled order generates a CEO AI penalty event mirroring the order's penalty total. Always present, every sweep.
- **CAIO excluded** from business reward / penalty (audit-only).
- **Idempotent** — re-running a sweep updates rows in place via `unique_key = phase4b_engine:{order_id}:{agent_id}:{event_type}`.
- **Missing data is recorded, never invented** — `missing_data` JSON on every event; `missingDataWarnings` aggregated in the summary endpoint.

Cron / one-off:
- `python manage.py calculate_reward_penalties [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--order-id NRG-...] [--dry-run] [--rebuild-leaderboard]` — no Redis required.
- Celery task `apps.rewards.tasks.run_reward_penalty_sweep_task` runs the all-eligible sweep + leaderboard rebuild. Eager mode for dev / tests; production picks it up via the existing worker.

Audit kinds (Phase 4B):
- `ai.reward.calculated`, `ai.penalty.applied`, `ai.reward_penalty.sweep_started`, `ai.reward_penalty.sweep_completed`, `ai.reward_penalty.sweep_failed`, `ai.reward_penalty.leaderboard_updated`.

### Catalog (Phase 3E)

Reads stay public; writes are admin/director-only via `RoleBasedPermission` (anonymous → 401, viewer/operations → 403).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/catalog/categories/` | List all `ProductCategory` rows (camelCase: `id`, `name`, `slug`, `description`, `isActive`, `sortOrder`, `createdAt`, `updatedAt`). |
| POST/PUT/PATCH/DELETE | `/api/catalog/categories/[{id}/]` | Admin/director only. Each successful write fires `catalog.category.{created,updated}`. |
| GET | `/api/catalog/products/` | List products with nested `skus`. Camel: `id`, `categoryId`, `name`, `slug`, `description`, `defaultPriceInr`, `defaultQuantityLabel`, `productCostInr`, `defaultUsageInstructions`, `activeClaimProducts`, `isActive`, `metadata`, `createdAt`, `updatedAt`, `skus[]`. |
| GET | `/api/catalog/products/{id}/` | Single product detail. |
| POST/PUT/PATCH/DELETE | `/api/catalog/products/[{id}/]` | Admin/director only. Fires `catalog.product.{created,updated}`. |
| GET | `/api/catalog/skus/?productId={id}` | List SKUs (optionally filtered by `productId`). Camel: `id`, `productId`, `skuCode`, `title`, `quantityLabel`, `mrpInr`, `sellingPriceInr`, `productCostInr`, `stockQuantity`, `isActive`, `metadata`, `createdAt`, `updatedAt`. |
| POST/PUT/PATCH/DELETE | `/api/catalog/skus/[{id}/]` | Admin/director only. Fires `catalog.sku.{created,updated}`. |

### Approval matrix (Phase 3E — public read)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/approval-matrix/` | Returns the policy table from `apps.ai_governance.approval_matrix.APPROVAL_MATRIX`: `{ version, actions: [{ action, approver, mode, description }] }`. **Public read** — the data is policy, not secret. Phase 4C middleware enforces it. |

### Phase 3E — Business policy modules (no endpoints; service-layer policies)

These shape behaviour but expose no new HTTP endpoints. They are imported by services and (in Phase 4) the approval-matrix middleware:

- **Discount policy** (`apps/orders/discounts.py`): `validate_discount(discount_pct, actor_role, approval_context=None) → DiscountValidationResult`. Bands: 0–10% auto, 11–20% approval (CEO AI / admin / director), > 20% blocked unless `actor_role='director'` AND `approval_context['director_override']=True`. Director ceiling: 50%.
- **Advance payment policy** (`apps/payments/policies.py`): `FIXED_ADVANCE_AMOUNT_INR = 499`. `POST /api/payments/links/` with `type="Advance"` and no `amount` (or `amount=0`) defaults to ₹499. Other types still require an explicit positive amount.
- **Reward / penalty scoring** (`apps/rewards/scoring.py`): `calculate_order_reward_penalty(order, context=None) → OrderRewardPenaltyResult`. 7 reward components (max +100), 10 penalty components (max -100). Missing data is recorded explicitly — never invented. Phase 4B wires this into the engine.
- **WhatsApp design scaffold** (`apps/crm/whatsapp_design.py`): 9 supported message types, consent + admin-approval flags. NO live sender yet — Phase 4+ ships the actual integration.

### Webhooks (gateway → backend, public)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/webhooks/razorpay/` | Razorpay payment events (Phase 2B). HMAC-verified via `RAZORPAY_WEBHOOK_SECRET`; idempotent on `event.id`. |
| POST | `/api/webhooks/delhivery/` | Delhivery tracking events (Phase 2C). HMAC-verified via `DELHIVERY_WEBHOOK_SECRET` (`X-Delhivery-Signature`); idempotent on `event.id`. Status mapping: `pickup_scheduled` / `picked_up` / `in_transit` / `out_for_delivery` / `delivered` / `ndr` / `rto_initiated` / `rto_delivered`. NDR + RTO events bump parent order's `rto_risk` and write danger-tone `AuditEvent` rows. |
| POST | `/api/webhooks/vapi/` | Vapi voice events (Phase 2D). HMAC-verified via `VAPI_WEBHOOK_SECRET` (`X-Vapi-Signature`) when configured; signature is skipped when the secret is empty so dev/test fixtures stay simple. Idempotent on `event.id` via `calls.WebhookEvent`. Event types handled: `call.started` / `call.ended` / `transcript.updated` / `transcript.final` / `analysis.completed` / `call.failed`. `analysis.completed` records `handoff_flags` (medical_emergency, side_effect_complaint, very_angry_customer, human_requested, low_confidence, legal_or_refund_threat); the service falls back to keyword matching on the transcript when Vapi omits the explicit flags. |
| GET | `/api/webhooks/meta/leads/` | Meta Lead Ads subscription handshake (Phase 2E). Echoes `hub.challenge` only when `hub.mode == "subscribe"` and `hub.verify_token == META_VERIFY_TOKEN`; otherwise 403. |
| POST | `/api/webhooks/meta/leads/` | Meta Lead Ads delivery (Phase 2E). HMAC-verified via `META_WEBHOOK_SECRET` (or `META_APP_SECRET` as fallback) on `X-Hub-Signature-256` when configured. Idempotent on `leadgen_id` via `crm.MetaLeadEvent`. `META_MODE=mock` (default) parses the inbound body directly; `test`/`live` expand each `leadgen_id` via the Graph API (`v20.0` by default). Each accepted leadgen creates or refreshes a `Lead` and writes a `lead.meta_ingested` AuditEvent. |

### Permissions

`apps/accounts/permissions.py` exposes:

- `OPERATIONS_AND_UP` = `{director, admin, operations}`
- `COMPLIANCE_AND_UP` = `{director, admin, compliance}`
- `ADMIN_AND_UP` = `{director, admin}`
- `DIRECTOR_ONLY` = `{director}`

ViewSets opt in by setting `permission_classes = [RoleBasedPermission]` and
`allowed_write_roles = OPERATIONS_AND_UP`. Reads stay open via the global
default `IsAuthenticatedOrReadOnly`.

CAIO is intentionally absent from every role-set: it is an AI-agent identity,
not a user role, and per blueprint §6.3 must never execute business actions.
