# Backend Roadmap (Phase 2+)

Phase 1 ships a working Django + DRF backend with all 25 read endpoints
matching the frontend service-layer contract. Real integrations, AI agent
reasoning, and the full governance UI live in the phases below — ordered per
blueprint Section 25 (`CRM → Workflow → Integrations → Voice AI → Agents →
Governance → Learning → Reward/Penalty → Growth → SaaS`).

Each phase is shippable on its own. None of it is required to keep the
frontend working today (the mock-fallback in `services/api.ts` keeps every
page rendering even if the backend is offline).

## Phase 2 — Integrations & Write Operations

| Item | Notes |
| --- | --- |
| Razorpay payment links | Need merchant account + webhook secret. New endpoint `POST /api/payments/links/`. |
| PayU payment links | Same shape as Razorpay; gateway flag selects provider. |
| Delhivery AWB creation + tracking webhook | `POST /api/shipments/` and `/api/webhooks/delhivery/`. |
| Vapi voice AI trigger + transcript ingest | `POST /api/calls/trigger/`. Webhook receives transcript & saves `ActiveCall` + `CallTranscriptLine`. |
| Meta Lead Ads webhook ingest | `POST /api/webhooks/meta/leads/`. Idempotent — same lead ID skips. |
| WhatsApp Business consent + outbound | Optional, blueprint Section 24 lists this as a clarification. |
| Audit signals for: payment events, shipment events, reward assigned, prompt updated | Already partially wired; expand. |

Add `Authorization` checks on writes (`IsAuthenticated`).

## Phase 3 — AI Agents (LLM-powered)

The CEO/CAIO/department agents currently return seeded structured insights.
Phase 3 replaces those with real LLM calls.

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
