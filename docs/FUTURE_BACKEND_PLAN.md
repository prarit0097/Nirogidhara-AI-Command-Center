# Backend Roadmap (Phase 2+)

Phase 1 + 2A + 2B are shipped (see `nd.md` §8 for the full checkpoint trail).
Phase 3 env scaffolding is in place. Real AI-agent reasoning, the rest of the
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

## ⏭ Phase 2C — Delhivery Courier API + Tracking Webhook (NEXT)

| Item | Notes |
| --- | --- |
| Delhivery client adapter | New `apps/shipments/integrations/delhivery_client.py` mirroring the Razorpay three-mode dispatch (`DELHIVERY_MODE=mock|test|live`). |
| Real AWB creation | Replace `_mint_awb()` mock in `apps/shipments/services.create_mock_shipment` with a real Delhivery `POST /api/cmu/create.json` call when mode is test/live. |
| Tracking webhook | New `POST /api/webhooks/delhivery/` — verify Delhivery's `token` header (or HMAC if available), update Shipment status + parent Order. Idempotent via `WebhookEvent` table (already exists). |
| Status events to handle | Manifested → Pickup Scheduled → In Transit → Out for Delivery → Delivered → RTO Initiated → RTO Delivered. |
| Tests | Mock + test-mode adapter, webhook OFD/Delivered/RTO, idempotency, invalid token. ~10 tests. |

Acceptance: setting `DELHIVERY_MODE=test` and providing the API token must
let the same `POST /api/shipments/` flow create a real AWB in Delhivery's
sandbox without any view code change.

## Phase 2D — Vapi Voice Trigger + Transcript Ingest

- `POST /api/calls/trigger/` — kicks off an outbound Vapi call for a lead.
- `POST /api/webhooks/vapi/` — receives the transcript + objection detection
  output and persists `Call` + `ActiveCall` + `CallTranscriptLine` rows.
- HMAC verification on the webhook.

## Phase 2E — Meta Lead Ads Webhook

- `POST /api/webhooks/meta/leads/` — ingest leads from Meta forms.
- Idempotent on Meta's `leadgen_id`.
- Maps form fields to the `Lead` model.

## Phase 2 — Other gateways (slot when needed)

| Item | Notes |
| --- | --- |
| PayU payment links | Same shape as Razorpay; `gateway` flag in `PaymentLinkSerializer` already accepts it — only the adapter is missing. |
| WhatsApp Business outbound + consent | Blueprint §24 lists this as a clarification — design first, build later. |

## Phase 3 — AI Agents (LLM-powered)

**Env scaffolding is already in place** (`apps/_ai_config.py` exposes
`current_config()` reading `AI_PROVIDER` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` /
`GROK_API_KEY`). Today the CEO/CAIO/department agents return seeded
structured insights; Phase 3 replaces those with real LLM calls dispatched
through provider adapters.

- Add per-provider adapters under `apps/integrations/ai/`:
  `openai.py`, `anthropic.py`, `grok.py`. Each follows the Razorpay
  pattern (lazy SDK import, `enabled` short-circuit when key empty).
- Add an `AgentRun` model (`agent`, `prompt_version`, `input_payload`,
  `output_payload`, `status`, `latency_ms`, `cost_usd`).
- Hook a service per agent: `services/agents/ceo.py`, `services/agents/caio.py`,
  etc. Each takes the relevant DB slice and returns the same dataclass shapes
  the seed currently produces.
- Background scheduler (Celery beat) regenerates the daily CEO briefing.
- Approved Claim Vault is the single source of truth for medical claims —
  every LLM call must include the relevant Claim entries in its prompt.

Sandbox mode and prompt versioning (Section 12.2) live here too.

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
