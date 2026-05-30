# Phase 16A — Business MVP Gap Audit

> **Phase 16B follow-up status (2026-05-27):** **Phase 16B — Customer Lifecycle UI Backbone is PRODUCTION VERIFIED at commit `00c3295` after Hotfix-2, and is CLOSED.** Verification: backend Phase 16B suite 30/30, `manage.py check` clean, `makemigrations --check` clean, `GET /api/healthz/` OK, browser validation passed (lead creation, phone-only duplicate blocking, `S.N.` column, Customer 360 layout, Orders responsive pipeline, safety shell unchanged). Hotfix-1 (`8c0c6b9`) was superseded by Hotfix-2 (`00c3295`), which delivered **phone-only lead uniqueness** (same email + different phone allowed; same normalized phone blocked) and the **Orders Pipeline responsive wrapped layout** (no horizontal-scroll dependency). **Phase 16C — Director Daily Briefing + Team Roles UI has since SHIPPED and is PRODUCTION VERIFIED + CLOSED at commit `687ef41`** (see the Phase 16C follow-up note below), mitigating the Director-briefing-UI + team-roles-UI launch blockers. The current next planned work is **Phase 16E — Payment / Logistics Integration Hardening** (NOT started; separate Director directive required). Six of the audit's launch-blocker items are now resolved or substantially mitigated:
>
> - **P0 #1 Confirmation queue UI not wired** → **RESOLVED.** Buttons now call `POST /api/orders/{id}/confirm/` with real loading / success / error states.
> - **P0 #2 Customer 360 Calls / Orders / Payments / Delivery tabs empty** → **RESOLVED.** New `GET /api/customers/{id}/timeline/` endpoint hydrates all four tabs.
> - **P0 #9 Lead consent fields missing on Lead model** → **RESOLVED.** Migration `crm.0004_phase16b_lead_consent_fields` adds `consent_call` / `consent_whatsapp` / `consent_marketing` (default False).
> - **P1 #11 Lead duplicate detection** → **RESOLVED (phone-only per Hotfix-2 `00c3295`).** `apps.crm.services.create_lead` raises `LeadDuplicateError` on a **normalized-phone** match only; endpoint returns HTTP 409 "Duplicate phone blocked — existing lead found." with `{duplicate, field: "phone", existingLeadId}`. Same email + different phone is allowed; email is metadata, NOT a uniqueness key.
> - **P1 #12 Order kanban detail sheet has no action buttons** → **RESOLVED for safe internal transitions.** Detail sheet exposes NEW_LEAD → INTERESTED → PAYMENT_LINK_SENT → ORDER_PUNCHED → CONFIRMATION_PENDING via existing `transition_order` service. Dispatched / Delivered / RTO deliberately not exposed.
> - **P1 #15 No "Create Order" UI** → **PARTIALLY MITIGATED** by the new "Create Lead" form (lead creation works from UI; order creation from UI is still Phase 16C+ scope).
>
> **Phase 16C follow-up status (2026-05-28):** **Phase 16C — Director Daily Briefing + Team Roles UI SHIPPED** (internal-only / review-only; no provider call, no AI generation, Phase 15 safety shell untouched). It resolves/mitigates two of the audit's open blockers:
> - **P0 #5 Director Daily Briefing approval UI missing → RESOLVED (review-only).** New `/director-briefing` page reads the latest snapshot status + records an internal-only Director review/decision via `POST /api/v1/director-ops/briefing-reviews/`. It does NOT generate an AI briefing or execute any business action.
> - **P0 #7 No UI for org-role assignment → RESOLVED (internal labels).** New `/team-roles` page lists users and assigns one of 8 internal operational-role labels via `POST /api/v1/director-ops/team-roles/assign/` (director/admin-gated). Labels grant no provider access and activate no automation.
>
> **Phase 16E follow-up status (2026-05-30):** **Phase 16E — Payment / Logistics Integration Hardening is PRODUCTION VERIFIED + CLOSED at `36395f6`** (internal/read-only — no live provider call, Phase 15 safety shell untouched). New app `apps.integration_hardening` adds a read-only Payment & Logistics readiness surface (`/operations/payment-logistics`) for Razorpay / PayU (unavailable, no adapter/dependency) / Delhivery, and **hardened `ShipmentViewSet.create()`** so the HTTP endpoint can no longer book a live production Delhivery AWB (live → HTTP 409 "Director live gate required"). This resolves the P0 #3 `ShipmentCreateView` hardcoded-mock ambiguity and locks live provider actions behind a future Director gate. **Phase 16D — Uploaded Customer Data Campaigns + Calling Lifecycle is PRODUCTION VERIFIED + CLOSED at `c0be74a`** (internal-only; closed the offline/old-data → order gap).
>
> **Items still open after Phase 16E (carried to Phase 16F / 16G):**
>
> - P0 #3 `ShipmentCreateView` hardcoded to `create_mock_shipment()` — **RESOLVED by Phase 16E** (explicit mode dispatch; live HTTP booking blocked without a Director gate).
> - P0 #4 Phase 7E-Live-B / 7G-Live / 8F all **NOT approved** — live activation remains future and requires explicit written Director directives (live-gate phases).
> - P0 #6 No UI for human calling agent — **PARTIALLY MITIGATED** by Phase 16D Imported Campaigns queue (manual outcome recording + create-order); a full agent console is deferred to Phase 16G if scope desired.
> - P0 #8 Production Claim Vault seed is demo-v2 — deferred (Phase 16F+).
> - P0 #10 RTO Rescue buttons toast-only — deferred (Phase 16F+).
>
> **The original audit body below is preserved verbatim as the canonical reference.** Phase 15 safety shell remains FROZEN at code commit `eefd8b3`.
>
> For Phase 16B implementation details see [`nd.md`](../nd.md) §0 head + the Phase 16B entry in §8.

---

> **Status:** SHIPPED — docs-only / read-only audit.
> **Phase 15 safety shell remains FROZEN at code commit `eefd8b3`.** This audit does **NOT** modify any backend code, frontend code, migration, env file, Celery beat schedule, runtime state, business state, or safety state. Phase 16A is a planning-only gap audit; the implementation phases it recommends (Phase 16B and beyond) require **separate explicit Director directives** before any code change.

---

## 1. Executive summary

**Director question:** *Is the Nirogidhara AI Command Center ready for an internal business MVP today?*

**Answer: READY ONLY FOR SAFETY / GOVERNANCE / READ-ONLY OBSERVABILITY. NOT READY FOR REAL BUSINESS OPERATIONS.**

The repo today is a **complete read-only Director command center on top of a complete read-only data-model and governance stack**. Specifically:

- **What is fully operational right now:** Phase 9A–9F deterministic Tier-2 AI agents producing daily snapshots; Phase 11A–11D transcript ingestion + call quality scoring + CAIO audit + Director-gated learning loop; Phase 12A–12D AI calling campaign gate, outcome classifier, post-call WhatsApp follow-up queue, and Tier-4 read-only performance dashboard; Phase 14D–F + Phase 15A–L safety shell chrome (AI Kill Switch UI, Sandbox Mode UI, Rollback System, Rollback History modal, Sidebar Director Briefing badge, Audit Timeline page, Topbar Safety Pill, Safety Diagnostics Panel + Detail Drawer, Session Expiry UX, Manual Refresh button); Phase 4A real-time `AuditEvent` WebSocket; Phase 6A SaaS multi-tenancy scaffold; full data models for Lead / Customer / Order / Payment / Shipment / WhatsApp / Call / RewardPenaltyEvent / Claim / LearningProposal / AgentRun / PromptVersion / ApprovalRequest / RuntimeKillSwitch / SandboxState; all six Provider adapters (Razorpay / PayU enum-only / Delhivery / Vapi / Meta Cloud / OpenAI–Anthropic–NVIDIA) with `mock` defaults locked in `.env.production.example`.
- **What is NOT operational for real customer business:** **Almost every customer-facing action button.** Phase 7E-Live-B (real customer WhatsApp send) — **NOT approved**. Phase 7G-Live (real customer Delhivery dispatch) — **NOT approved**. Phase 8F (real customer payment → order mutation) — **NOT staged** (Reading 1 ran 2026-05-14, rolled back same hour). Phase 12A AI calling campaign execute — gated behind `AI_CALLING_ENABLED=false`, never run live. All broad WhatsApp automation flags (`WHATSAPP_AI_AUTO_REPLY_ENABLED`, `WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`) default `false`. MCP gateway disabled. Confirmation queue action buttons (Confirmed / Rescue needed / Cancelled) are **toast-only** with no API call. RTO Rescue / Convinced buttons are **toast-only**. Leads page "New Lead" / "Import" buttons are **toast-only**. There is **no UI for a human calling agent** to see their assigned leads, dial, record outcome, reschedule callback, or escalate — the system is AI-calling-only by design. There is **no UI to assign users to organisation roles** — Lead.assignee is a string CharField, not a User FK. There is **no Director Daily Briefing approval workflow** (Phase 14A `nd.md §1.5` 16-question briefing + 1-click approval + mobile-first PWA) — only a read-only briefing display. PayU adapter is **MISSING** (only an enum value). Payment 10C link refresh is **CLI-only**. Shipment creation is hardcoded to `create_mock_shipment()` in `apps/shipments/views.py` — never routes through the real Delhivery adapter from the API surface.

**Verdict:** the codebase is **safety-foundation-complete** (Phase 15M freeze) and **observability-complete** (read-only dashboards across every business domain) but **not yet a business-execution platform**. To run an internal pilot that actually books an order, takes a payment, dispatches a shipment, or sends a WhatsApp to a customer, the Director must (a) flip specific env flags, (b) authorise specific Phase 7-8 gates via separate Director directives, AND (c) commission a focused Phase 16B implementation phase to wire frontend action buttons to the existing backend service entrypoints.

**The recommended next step is NOT to start any implementation phase yet.** It is for the Director to review this audit, answer the §9 yes/no decisions, and then commission a narrow Phase 16B with explicit scope. Skipping this step risks repeating the Phase 15 polish-loop pattern — building chrome on top of an already-frozen foundation instead of advancing the business backbone.

---

## 2. Current production baseline

| Field | Value |
| --- | --- |
| **Operational baseline** | Phase 15M — Foundation Release Freeze (post-Phase-15 chrome) |
| **Safety shell frozen code commit** | `eefd8b3` (`feat: phase 15l add safety diagnostics manual refresh`) |
| **Docs / sign-off commit chain** | `8fc77d6` (sign-off pack) → `c75697f` (Hotfix-1) → `c85a32e` (Hotfix-2 semantics) → `966c246` (Hotfix-2 docs-index) → `aa0852a` (Final Docs Reconciliation) → `fb8408c` (Final grep-cleanup) → **this commit** (Phase 16A audit) |
| **HEAD = origin/main at audit start** | `fb8408cc8840acd083a3846cc0bcb73a4ee895f9` |
| **Production URL** | <https://ai.nirogidhara.com> |
| **Production health endpoint** | `GET /api/healthz/` → `{"status":"ok","service":"nirogidhara-backend"}` (verified via Director's local check) |
| **AI state** | **AI Paused** (`RuntimeKillSwitch.enabled=True` — kill switch active; daily Celery sweeps refuse with `*.daily_run.blocked`) |
| **Sandbox state** | **OFF** (`SandboxState.is_enabled=False`) |
| **CEO Director Briefing** | typically **STALE** in current production state (daily sweep not running on the VPS by default) |
| **Phase 7E-Live-B real customer WhatsApp send** | **NOT approved** |
| **Phase 7G-Live real customer Delhivery dispatch** | **NOT approved** |
| **Phase 8F real customer payment → order mutation** | **Not staged for next run.** Reading 1 ran 2026-05-14, rolled back same hour. |
| **Phase 12A AI calling campaign execute** | **Never run live.** `AI_CALLING_ENABLED=false`. |
| **Broad WhatsApp automation flags** | all `false` |
| **MCP gateway (`MCP_ENABLED`)** | `false` |
| **Backend test baseline** | 2200+ tests passing on local SQLite (Test Hygiene Hotfix-1 pins integration modes to mock) |
| **Frontend test baseline** | **275 / 275 passed** (post-Phase-15L) |
| **`makemigrations --check --dry-run`** | clean |
| **`manage.py check`** | clean |

---

## 3. Audit method

This audit is **read-only**:

- **No backend code modified.** No `models.py` / `views.py` / `serializers.py` / `urls.py` / `services.py` / `tasks.py` / `webhooks.py` / `integrations/*.py` touched.
- **No frontend code modified.** No `App.tsx` / pages / components / hooks / context / services / types touched.
- **No migration created** (`makemigrations --check --dry-run` = `No changes detected`).
- **No env file edited** — `.env.production.example` and the VPS `.env.production` unchanged.
- **No Celery beat schedule edited.**
- **No database mutation.** No `Order` / `Payment` / `Customer` / `Lead` / `Shipment` / `DiscountOfferLog` / `WhatsAppMessage` / `Call` / `RewardPenaltyEvent` / `Claim` / `LearningProposal` / `AgentRun` / `PromptVersion` / `ApprovalRequest` / `RuntimeKillSwitch` / `SandboxState` / `CeoOrchestrationSnapshot` / `CaioAuditSnapshot` row written or mutated.
- **No provider call.** Razorpay / PayU / Delhivery / Vapi / Meta Cloud / OpenAI / Anthropic / NVIDIA — none called.
- **No safety-state change.** Kill switch and sandbox state untouched.

**Discovery commands run (all read-only):**

- `git fetch origin --prune` + `git log --oneline -10` + `git rev-parse HEAD origin/main` + `git status --short` → confirmed HEAD = origin/main = `fb8408cc8`.
- `ls backend/apps/` → 26 Django apps enumerated.
- `ls frontend/src/pages/` → 27 pages enumerated.
- `cat backend/config/urls.py` → 35 URL include lines mapped.
- `grep -n "to=\"/" frontend/src/components/layout/Sidebar.tsx` → 25 sidebar nav items mapped.
- `grep -c "^  [a-z]" frontend/src/services/api.ts` → **249 api.ts methods**.
- `cat .env.production.example` → provider mode flags + safety env catalogue.
- **6 parallel Explore agents** dispatched, each producing concrete file/line evidence for one business domain pair:
  1. Lead capture + Customer CRM (`apps/crm` + `Leads.tsx` + `Customers.tsx`)
  2. Order / Payment / Shipment business flow (`apps/orders` + `apps/payments` + `apps/shipments` + `Orders.tsx` + `Confirmation.tsx` + `Payments.tsx` + `PendingPayments.tsx` + `Delivery.tsx` + `Rto.tsx`)
  3. WhatsApp full surface (`apps/whatsapp` 8+ models + 3 providers + `WhatsAppInbox.tsx` + `WhatsAppTemplates.tsx` + `WhatsAppMonitoring.tsx`)
  4. Calls / Voice / AI calling (`apps/calls` Phase 2D + 11A-D + 12A-D + `Calling.tsx` + `CallingDashboard.tsx`)
  5. AI agents + governance + safety (`apps/agents` 9A-9F + `apps/ai_governance` + `apps/caio` + `apps/learning` + `apps/compliance` + `apps/rewards` + frozen Phase 15 chrome)
  6. Roles + dashboards + DevOps + tests + cross-cutting (`apps/accounts` + `apps/saas` + `apps/dashboards` + `apps/analytics` + `apps/audit` + `Index.tsx` + `Analytics.tsx` + `docker-compose.prod.yml` + `docs/DEPLOYMENT_VPS.md` + `backend/tests/` + `frontend/src/test/`)

All agent findings were cross-checked against `nd.md` head-of-file truth state (Phase 15M sign-off pack, production posture, env flag locks).

---

## 4. Business MVP area matrix

Status definitions used throughout:

- **READY** = usable today for internal pilot with real data and acceptable risk.
- **PARTIAL** = core pieces exist but one or more required pieces missing.
- **STUB** = UI / model / mock exists but not real workflow-ready.
- **MISSING** = not implemented.
- **BLOCKED** = requires Director decision / credentials / external approval / production env change.

Launch-impact ranking: **P0** = cannot pilot without this; **P1** = pilot possible but risky; **P2** = improvement; **P3** = later.

| # | Business Area | Status | Current evidence | What works today | What is missing | Launch impact | Recommended next phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Lead intake — Meta Lead Ads webhook** | **READY** | `apps/crm/webhooks.py:70-103` + `apps/crm/services.py:181-262` (`ingest_meta_lead`) + `apps/crm/integrations/meta_client.py:116-249` + `MetaLeadEvent` idempotency log | HMAC-SHA256 verify, three payload shapes handled, dedup on `leadgen_id`, fires `lead.meta_ingested` audit | None for ingestion path itself | P2 (it works) | — |
| 2 | **Lead intake — manual entry UI** | **STUB** | `frontend/src/pages/Leads.tsx:36-37` ("New Lead" + "Import" buttons are toast-only) | Read-only table + filters | No create-lead form, no CSV/Sheets import path | P1 | 16B |
| 3 | **Lead assignment to agent** | **PARTIAL** | `Lead.assignee` is `CharField` (not FK to User), `assign_lead` service exists, no UI dropdown | API path `/api/leads/{id}/assign/` works | No user→agent dropdown in UI; assignee is free-text; no team/roster concept | P1 | 16B |
| 4 | **Lead duplicate detection** | **PARTIAL** | Only `meta_leadgen_id` dedup; no phone/email dedup logic in `services.create_lead` | Meta-side duplicates blocked | Hand-raised + Sheet-imported + WhatsApp-inbound duplicates not detected | P1 | 16B |
| 5 | **Lead consent fields** | **MISSING** | `Lead` model has no consent fields; only `Customer` has `consent_call/whatsapp/marketing` | Customer-level consent works | Cannot record consent state at Lead stage (before Customer conversion) | P1 | 16B |
| 6 | **Customer 360 timeline** | **PARTIAL** | `Customers.tsx:55-194` renders 7 tabs | Overview / WhatsApp tab (live) / Consent table all work | Calls tab is hardcoded mock (line 139-149); Orders / Payments / Delivery tabs empty (line 152-154); Reorder tab placeholder; no PII masking on phone in profile header (line 87) | P0 | 16B |
| 7 | **Order lifecycle backbone** | **READY** | `apps/orders/models.py` Order with 10-stage enum + state machine in `services.py:35-51` (ALLOWED_TRANSITIONS) + `apply_order_discount` + `move_to_confirmation` + `record_confirmation_outcome` | Full state machine enforced, audit-logged, 50% discount cap | None at model layer | P0 (foundation) | — |
| 8 | **Orders Kanban UI** | **PARTIAL** | `Orders.tsx` 10-column kanban, read-only | Renders all 10 stages | No action buttons on detail sheet — cannot transition stages from UI | P1 | 16B |
| 9 | **Confirmation queue UI** | **STUB** | `Confirmation.tsx` — buttons present (Confirmed / Rescue / Cancelled) but call `toast.success()` only, NO API call | Visual queue + checklist | Action buttons fire toast only; no backend persistence; no API to `record_confirmation_outcome` from UI | P0 | 16B |
| 10 | **Razorpay payment link generation** | **READY** (test/mock) | `apps/payments/integrations/razorpay_client.py` 3 modes + `Payments.tsx:28-68` "Generate link" button calls `api.createPaymentLink()` | Works in mock + test mode | Live mode never used in production (Razorpay test keys in `.env.production` per nd.md) | P0 (foundation) | — |
| 11 | **Razorpay webhook** | **READY** | `apps/payments/webhooks.py` HMAC-SHA256 verify + `WebhookEvent` idempotency + status mapping + Phase 6M test-mode handler at `/api/webhooks/razorpay/test/` | Works for inbound test events | — | P2 | — |
| 12 | **PayU adapter** | **MISSING** | `Payment.Gateway.PAYU = "PayU"` enum present (`apps/payments/models.py:18`); no `payu_client.py`; no webhook handler | — | Entire adapter missing | P2 (Razorpay primary) | 16D (if needed) |
| 13 | **Payment status mutation safety** | **READY** | Phase 6Q–6T audit gates + Phase 8A–F controlled-mutation gates + Phase 10C payment link refresh gate (CLI-only) | All gates are CLI-only governance with locked-False safety booleans | None — by design CLI-only | P2 | — |
| 14 | **Phase 10C payment link refresh from UI** | **MISSING** | CLI-only currently | CLI works | No web form to request/approve a link refresh | P2 | 16D |
| 15 | **Phase 7E-Live-B real customer WhatsApp send** | **BLOCKED** | Full code shipped + CLI-only execute path | All gates wired; defaults locked | Director directive + `PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=true` env flip + structured UTC window required | P0 (for any pilot send) | 16E |
| 16 | **Phase 7G-Live real customer Delhivery dispatch** | **BLOCKED** | Full code shipped + CLI-only execute path | All gates wired; defaults locked | Director directive + `PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=true` env flip | P0 (for any pilot dispatch) | 16D |
| 17 | **Phase 8F real customer payment → order mutation** | **BLOCKED** | Reading 1 ran 2026-05-14, rolled back same hour | Mechanism proven | No Reading 2 staged. Each future run needs fresh Director directive. | P1 | 16D |
| 18 | **Shipment creation from API** | **PARTIAL** | `apps/shipments/views.py:31-40` `ShipmentCreateView` calls `services.create_mock_shipment()` — hardcoded to mock | Mock path works | API does NOT route through `create_shipment()` with real Delhivery adapter even when `DELHIVERY_MODE=live` | P0 | 16D |
| 19 | **Delivery / Tracking UI** | **STUB** | `Delivery.tsx` — read-only table + 5-step timeline | Renders shipment list | No action buttons; no AWB creation UI; no Phase 7G surface | P1 | 16D |
| 20 | **RTO Rescue UI** | **STUB** | `Rto.tsx:62-63` "Rescue" + "Convinced" buttons fire toast only, NO API call | Visual RTO board | No backend wiring on rescue actions; `RescueAttempt` model exists but unreachable from UI | P0 | 16D |
| 21 | **Delhivery tracking webhook** | **READY** | `apps/shipments/webhooks.py` HMAC-SHA256 verify + idempotency + status mapping (NDR / RTO / Delivered) | Works for inbound test events | — | P2 | — |
| 22 | **WhatsApp template send (manual operator)** | **READY** | `apps/whatsapp/services.py:316-599` `queue_template_message` + 5F-Gate final-send guard + `WhatsAppInbox.tsx` send-template modal | Works in mock; meta_cloud path gated by allow-list | Live customer send requires Phase 7E-Live-B Director directive | P0 (foundation) | — |
| 23 | **WhatsApp AI auto-reply** | **PARTIAL** | `apps/whatsapp/ai_orchestration.py:143-668` + deterministic grounded fallback (lines 1316-1495) | All safety gates + Claim Vault + discount discipline + 50% cap | `WHATSAPP_AI_AUTO_REPLY_ENABLED=false`; confidence threshold default 0.75 blocks auto-send when flag off | P1 | 16E |
| 24 | **WhatsApp lifecycle automation (confirmation / delivery / RTO / reorder reminders)** | **PARTIAL** | `apps/whatsapp/lifecycle.py:44-58` LIFECYCLE_TRIGGERS map + signal receivers in `signals.py` | Idempotent dispatch; all signals fire | All 6 automation flags default `false`; no template lands on a real customer phone | P1 | 16E |
| 25 | **WhatsApp call handoff** | **READY** | `apps/whatsapp/call_handoff.py:92-297` `trigger_vapi_call_from_whatsapp` + safe/non-auto reason split | Code complete | `WHATSAPP_CALL_HANDOFF_ENABLED=false`; safety reasons (medical / side effect / legal) deliberately do NOT auto-call | P2 | 16F |
| 26 | **WhatsApp Inbox UI** | **READY** | `WhatsAppInbox.tsx` 1019 lines — three-pane inbox + AI suggestions panel + internal notes + manual template send modal | Fully functional read+manual-send | Manual send still gated by approval matrix + limited-test-mode + allow-list | P0 (foundation) | — |
| 27 | **WhatsApp Monitoring dashboard** | **READY** | `WhatsAppMonitoring.tsx` 803 lines | Provider health, template sync, automation flag display — all read-only | None | P2 | — |
| 28 | **Vapi adapter (mock / test / live)** | **READY** | `apps/calls/integrations/vapi_client.py` all 3 modes + webhook signature verify | All modes work | Live requires `VAPI_MODE=live` + `VAPI_API_KEY` + `VAPI_ASSISTANT_ID` + `VAPI_PHONE_NUMBER_ID` | P0 (foundation) | — |
| 29 | **Vapi webhook (call.started / .ended / transcript.updated / .final / analysis.completed / call.failed)** | **READY** | `apps/calls/webhooks.py` + `apps/calls/services.py:381-388` handlers | Handoff flag detection, sentiment, transcript persistence | — | P2 | — |
| 30 | **Phase 11A transcript ingestion (Vapi REST pull)** | **READY** | `apps/calls/transcript_ingestion.py` + daily Celery task 23:00 IST | Backlog tracking + denormalized `transcript_line_count` | — | P2 | — |
| 31 | **Phase 11B call quality scorer (deterministic 5-dim)** | **READY** | `apps/calls/quality_scorer.py:1-643` + daily Celery task 23:30 IST | Composite + 7 flags emitted | V1 deterministic; LLM scorer is V2 work | P2 | — |
| 32 | **Phase 11C CAIO audit** | **READY** | `apps/caio/` + daily Celery task **14:00 IST** (confirmed in `backend/config/celery.py` beat schedule) | Severity GREEN/AMBER/RED + 30-day window + audit events | — | P2 | — |
| 33 | **Phase 11D learning loop (Director-gated)** | **READY** | `apps/learning/` + `LearningProposals.tsx` | Director approve / reject / implement / cancel; CAIO auto-creates proposals on RED audit | — | P2 | — |
| 34 | **Phase 12A AI Calling Campaign Gate** | **BLOCKED** | `apps/calls/ai_calling_gate.py:1-922` + Phase 12D dashboard | All gates wired; CLI happy-path test passes | `AI_CALLING_ENABLED=false`; needs Director UTC window + Vapi live credentials; never run live | P0 (for AI calling pilot) | 16F |
| 35 | **Phase 12B outcome classifier** | **READY** | `apps/calls/outcome_classifier.py` + daily Celery task 07:00 IST | Hinglish-aware deterministic V1, recommendations-only | None | P2 | — |
| 36 | **Phase 12C post-call WhatsApp follow-up queue** | **READY** | `apps/calls/post_call_followup.py` + daily Celery task 08:30 IST | Queues draft Phase 7E-Live-B gates; never auto-sends | None | P2 | — |
| 37 | **Phase 12D Calling Performance Dashboard** | **READY** | `CallingDashboard.tsx` 707 lines | 4 sections all read-only; CLI reference block | None | P2 | — |
| 38 | **Human calling agent UI (assigned leads / dial / outcome form / callback / escalation)** | **MISSING** | No "My Leads" dashboard, no manual call trigger button, no outcome form, no callback scheduling, no escalation routing | — | The system is **AI-calling-only** by design; if Director wants humans to make calls and record outcomes from the platform, this is net-new work | P0 (if human-calling pilot desired) | 16C |
| 39 | **AI Kill Switch UI** (Phase 14D) | **READY** | `KillSwitchModal.tsx` + `/api/v1/saas/runtime-live-gate/kill-switch/` | Confirmation modal + expected phrase + audit | None | P0 (foundation) | — |
| 40 | **Sandbox Mode UI** (Phase 14E) | **READY** | Settings card + `/api/ai/sandbox/status/` | Toggle works | None | P2 | — |
| 41 | **Rollback System UI** (Phase 14F + 15A) | **READY** | `RollbackSystemModal.tsx` + `RollbackHistoryModal.tsx` | Director can roll back a prompt version with audit | None | P2 | — |
| 42 | **Audit Timeline page** (Phase 15C) | **READY** | `AuditTimeline.tsx` + `/api/v1/audit/timeline/` + 70-key allow-list slice + 200-char truncation | Read-only filtered audit feed | None | P2 | — |
| 43 | **Sidebar Director Briefing badge** (Phase 15B) | **READY** | Sidebar + `/api/v1/ceo-orchestration/snapshots/sidebar-status/` | Status pill (READY / STALE / CRIT / MISSING) | Briefing typically **STALE** in production (daily sweep not running) | P2 | — |
| 44 | **Topbar Safety Pill + Sync indicator** (Phase 15D-H) | **READY** | Topbar + shared `SafetyStateProvider` + WebSocket auto-refresh | Live state across all tabs | None | P2 | — |
| 45 | **Safety Diagnostics Panel + Detail Drawer + Manual Refresh** (Phase 15I-L) | **READY** | Settings page diagnostics | All read-only | None | P2 | — |
| 46 | **Session Expiry UX** (Phase 15K) | **READY** | `AuthExpiredError` + deduped global toast + `SessionExpiredBanner` on `/login` | One clean session-expired toast | None | P2 | — |
| 47 | **CEO Director Briefing page** (`/ceo-ai`) | **PARTIAL** | Reads CeoOrchestrationSnapshot | Read-only display of headline + summary + recommendations | **No approval workflow UI** — the Phase 14A `nd.md §1.5` "16-question briefing + 1-click approval + mobile-first PWA" is NOT implemented | P0 (Director's primary intended workflow) | 16C |
| 48 | **CAIO Audit Center** (`/caio`) | **READY** | `Caio.tsx` | Severity grid + "Send to CEO AI" + critical alert button | CAIO never executes — by design | P2 | — |
| 49 | **AI Agents Center** (`/agents`) | **READY** | All 6 Tier-2 agents (9A-9F) | Daily snapshots visible | None | P2 | — |
| 50 | **AI Scheduler + Cost** (`/ai-scheduler`) | **READY** | Phase 3C scheduler + USD pricing | Cost ledger visible | None | P2 | — |
| 51 | **AI Governance** (`/ai-governance`) | **READY** | Phase 3D versions + Phase 4C matrix + Phase 4D execution log | All three surfaces read-only | None | P2 | — |
| 52 | **Reward / Penalty** (`/rewards`) | **READY** | `RewardPenaltyEvent` + engine + Celery task + `Rewards.tsx` leaderboard | Event-level scoring works | Reward calculation runs only when sweep is triggered; visibility depends on data | P2 | — |
| 53 | **Claim Vault** (`/claims`) | **READY** | `Claim` model + `Claims.tsx` + Phase 5D coverage command | Per-product approved/disallowed + doctor/compliance status | Current seed is **demo-v2**; production rollout requires real doctor-approved claims | P0 (for any real customer message) | 16E |
| 54 | **Command Center home** (`/`) | **READY** | `Index.tsx` 452 lines | 12+ KPIs, 7-day trends, funnel, agent health, live activity feed (WebSocket fallback to polling) | None | P0 (foundation) | — |
| 55 | **Analytics page** (`/analytics`) | **READY** | `Analytics.tsx` 91 lines | Funnel, revenue, RTO by region, discount impact, product table | None | P2 | — |
| 56 | **SaaS Admin page** (`/saas-admin`) | **READY** | Phase 6E-onwards read-only control panel | Org overview + 60+ Phase 6-8 gate sections, all read-only | Internal-consumption Director admin view | P2 | — |
| 57 | **Roles & permissions** | **PARTIAL** | `User.role` enum (5 values) + `RoleBasedPermission` DRF class + Phase 6A `OrganizationMembership` (separate org-role enum) | API-level enforcement works | **No UI to assign users to organisation roles**; calling-agent / confirmation-team / warehouse / delivery / QA / finance teams have **no role definitions** beyond the 5 generic User roles | P0 (multi-user pilot needs this) | 16C |
| 58 | **Org multi-tenancy (Phase 6A scaffold)** | **READY** | `Organization` + `Branch` + `OrganizationMembership` + `OrganizationFeatureFlag` + `OrganizationSetting` | Default `nirogidhara` org seeded; nullable FKs on 14 business models | No production tenant-isolation enforcement (global tenant filtering still disabled) | P2 | — |
| 59 | **Audit trail** | **READY** | `AuditEvent` + Phase 4A WebSocket + Phase 15C Audit Timeline page + sanitised payloads | Live event feed + filterable history | None | P0 (foundation) | — |
| 60 | **Production Docker stack** | **READY** | `docker-compose.prod.yml` 6 containers + healthcheck + Nginx + Postgres 16 + Redis 7 | All services up | None | P0 (foundation) | — |
| 61 | **Backup / restore** | **MISSING** | `docs/DEPLOYMENT_VPS.md` has setup walkthrough but no explicit DB backup/restore runbook | — | No documented backup procedure (Postgres dump + offsite); no documented restore drill | P1 | 16C |
| 62 | **Centralized logging** | **MISSING** | `docker compose logs` only | Per-container tail works | No log aggregation (no Datadog / Loki / ELK); no error alerting | P1 | 16C |
| 63 | **Daily Celery beat schedule** | **READY** | `backend/config/celery.py` — **13 daily IST entries** (07:00 outcome classifier → 23:30 quality scoring) | All Phase 9–12 agents on schedule | None for code; but on the production VPS the schedule may not be running (CEO Briefing typically STALE in production) | P1 | 16C |
| 64 | **Phase 4A pytest test-DB teardown warning** | **ACCEPTED** | Documented in Phase 15M sign-off pack §8 | Non-blocking | — | P3 | — |
| 65 | **Test coverage** | **READY** | Backend 2200+ passing, Frontend 275 / 275 passing | All green | No coverage % report generated | P2 | — |

---

## 5. End-to-end workflow audit

The audit's most important question: **can a real customer be acquired, converted, paid, dispatched, and followed up entirely through this platform today?**

| # | Workflow step | Implemented? | Backend evidence | Frontend evidence | Gap | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **Lead captured** (Meta ads / direct call / Sheet) | **PARTIAL** | Meta webhook **READY**; call-lead path requires manual Lead creation | Read-only Leads page; "New Lead" + "Import" toast-only | No UI create-form; no Sheet importer | P1 |
| 2 | **Lead assigned to agent** | **PARTIAL** | `assign_lead` API works | No UI dropdown | Assignee is free-text string; no team roster | P1 |
| 3 | **Agent calls customer** | **BLOCKED** for AI / **MISSING** for human | Vapi adapter + `trigger_call_for_lead` work | No "My Leads" page; no dial button | AI: `AI_CALLING_ENABLED=false`. Human: no UI exists at all. | P0 |
| 4 | **Problem / disease captured** | **PARTIAL** | Customer model has `disease_category` / `lifestyle_notes` / `objections` | Visible on Customer 360 read-only | No edit form on Customer 360 page | P1 |
| 5 | **Product / medicine recommended (via approved Claim Vault)** | **READY** | `apps/compliance/Claim` + `apps/whatsapp/ai_orchestration` + 5F-Gate Claim Vault grounding | Claims page read-only display | Production rollout needs **real doctor-approved claims**, not demo seed | P0 |
| 6 | **Discount / advance payment** | **PARTIAL** | `apply_order_discount` + 50% cap + Phase 3E `validate_discount` + Phase 5E `evaluate_whatsapp_discount` | No UI to apply a discount mid-call | Backend complete; UI missing | P1 |
| 7 | **Order created** | **PARTIAL** | `apps/orders/services.py create_order` works; Phase 5C `book_order_from_decision` works for WhatsApp AI | No manual "Create Order" UI; Orders page is read-only kanban | UI gap | P1 |
| 8 | **Confirmation team verifies (name / address / product / amount / intent)** | **STUB** | `record_confirmation_outcome` service works | `Confirmation.tsx` buttons fire toast, NO API call | **Highest-priority UI gap** | P0 |
| 9 | **Payment / advance tracked** | **PARTIAL** | Razorpay webhook + Payment model | Payments page read-only + "Generate link" works in mock | Live Razorpay collection NOT approved (Phase 7E-Live-B / 8F) | P0 |
| 10 | **Order dispatched to Delhivery** | **BLOCKED** | Delhivery adapter works in mock/test; Phase 7G-Live gate ready | `ShipmentCreateView` hardcoded to `create_mock_shipment` — never routes to real adapter from API | Phase 7G-Live Director directive + env flip required AND view rewrite | P0 |
| 11 | **Delivery follow-up (out-for-delivery reminder)** | **PARTIAL** | Phase 5D `_on_shipment_saved` signal + lifecycle dispatch | Signals fire, but `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false` blocks send | Director directive + env flip | P1 |
| 12 | **Delivered / RTO update** | **READY** | Delhivery webhook + status mapping (delivered / ndr / rto) | Delivery + RTO pages read-only | None for status update | P2 |
| 13 | **Reorder follow-up (Day-20)** | **PARTIAL** | Phase 5E reorder sweep + Celery task | `WHATSAPP_REORDER_DAY20_ENABLED=false` | Director directive + env flip | P2 |

**Summary:** **3 of 13 steps are end-to-end automatable today** (Meta lead ingest, claim recommendation, delivered/RTO status update). The other 10 require either a UI gap fix, an env flag flip, a Director directive for a Phase 7-8 gate, or human-team workflow definition.

---

## 6. Launch blockers

### P0 — Cannot pilot without this

1. **Confirmation queue UI buttons must call the backend.** `Confirmation.tsx` Confirmed / Rescue / Cancelled fire `toast.success()` only — no API call. The backend `record_confirmation_outcome` service exists and is fully wired; this is purely a frontend wiring gap.
2. **Customer 360 Calls / Orders / Payments / Delivery tabs are empty.** The Customer 360 page (`Customers.tsx`) renders the WhatsApp tab live but the other four tabs are empty placeholders. Director cannot review a customer's full history.
3. **Shipment creation API hardcoded to mock.** `apps/shipments/views.py:31-40` `ShipmentCreateView` calls `services.create_mock_shipment()` — never routes through the real Delhivery adapter even when `DELHIVERY_MODE=live`. Means even after Phase 7G-Live Director directive, the API surface won't actually call Delhivery.
4. **Phase 7E-Live-B / 7G-Live / 8F all NOT approved.** Without a Director directive + env flag flip + structured UTC window for each, no real customer WhatsApp send / shipment / payment-confirmation can happen.
5. **Director Daily Briefing approval UI missing.** `nd.md §1.5` Phase 14A founder operating model promises a 16-question daily briefing with 1-click approval. The `/ceo-ai` page shows the briefing read-only but has no approval workflow — Director cannot act on the briefing from inside the app.
6. **No UI for a human calling agent.** Lead-assignment, "My Leads" queue, dial button, outcome form, callback scheduling, escalation routing — all missing. The system is AI-calling-only by design. If the Director wants humans to make calls and capture outcomes from the platform, this is net-new work.
7. **No UI to assign users to organisation roles.** Calling-agent / confirmation-team / warehouse / delivery / QA / finance team definitions don't exist beyond the 5 generic User roles. `OrganizationMembership` table exists but has no admin UI.
8. **Production Claim Vault seed is demo-v2.** Real doctor-approved claims for the 8 product categories must be loaded before any real customer message goes out (the AI orchestrator hard-blocks ungrounded sends, so this is a true blocker, not a soft warning).
9. **Lead consent fields missing on Lead model.** Cannot record consent state at the Lead stage; only at Customer conversion. P0 for compliance / DND posture.
10. **RTO Rescue buttons are toast-only.** `Rto.tsx` "Rescue" / "Convinced" fire toast — no `RescueAttempt` row created. RTO recovery is the highest-leverage business lever in Ayurveda D2C; this gap zero-impacts a key revenue motion.

### P1 — Pilot possible but risky

11. **Lead duplicate detection only on Meta leadgen_id.** Phone / email / WhatsApp inbound duplicates not detected — risks double-calling.
12. **Order kanban detail sheet has no action buttons.** Director / agent cannot transition stages from UI; backend `transition_order` works.
13. **No backup / restore runbook.** `docs/DEPLOYMENT_VPS.md` has setup walkthrough but no documented Postgres dump procedure, no restore drill.
14. **No centralized logging / alerting.** `docker compose logs` only.
15. **No "Create Order" UI.** Orders are minted from WhatsApp AI booking flow (`book_order_from_decision`) only.
16. **No manual discount-application UI.** Backend cap-validation works; no agent-facing form.
17. **WhatsApp lifecycle automation flags all locked off.** Once `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=true`, confirmation / delivery / RTO / reorder reminders flow automatically — but the Claim Vault must be production-ready first.
18. **Customer-360 PII not masked.** Full phone displayed in profile header — risks if non-Director users gain access.

### P2 — Improvement

19. PayU adapter missing (Razorpay primary; PayU is contingency).
20. Phase 10C payment link refresh is CLI-only (no UI).
21. Phase 14A Director Daily Briefing mobile-first PWA mode unbuilt.
22. Coverage % report not generated for tests.
23. Daily Celery beat may not be running on the production VPS (Briefing typically STALE).

### P3 — Later

24. Phase 4A pytest test-DB teardown warning (accepted; documented).
25. SaaS multi-tenant global queryset filtering not blanket-enabled.

---

## 7. Recommended Phase 16 roadmap

The roadmap below proposes a **business-backbone-first** order. Each phase is independent of the next — the Director can stop at any phase and ship a meaningful subset. **Each phase requires a separate Director directive to start.** Phase 16A produces this audit and stops here.

### Phase 16B — Customer Lifecycle UI Backbone (highest priority MVP scope)

**Goal:** make the existing data models actionable from the UI for the Director and her future agent team. **Backend mostly already exists; this phase wires the frontend.**

Scope (one narrow ticket per piece, in priority order):

1. **Confirmation queue action buttons wire-up** — `Confirmation.tsx` Confirmed / Rescue / Cancelled buttons call `api.recordConfirmationOutcome` → `apps.orders.services.record_confirmation_outcome`. Resolves P0 #1.
2. **Customer 360 tabs hydration** — load Calls / Orders / Payments / Delivery rows from existing GET endpoints into the four empty tabs. Resolves P0 #2.
3. **Order kanban detail sheet action buttons** — allow stage transitions via `transition_order` API. Resolves P1 #12.
4. **Manual Create Lead form** + **Lead Import CSV** — replace the two toast-only buttons in `Leads.tsx`. Resolves P1 #15-equivalent.
5. **Lead duplicate-detection service** — extend `services.create_lead` with duplicate detection. Resolves P1 #11. *(Implemented PHONE-ONLY in Hotfix-2 `00c3295` — normalized phone is the uniqueness key; email is metadata only.)*
6. **Lead consent fields** — migration to add `consent_call` / `consent_whatsapp` / `consent_marketing` to `Lead` model (mirror `Customer`). Resolves P1 #9.

Phase 16B is **entirely additive** to the Phase 15 chrome — does NOT modify any frozen safety surface.

### Phase 16C — Director Daily Briefing + Team Roles UI

**Goal:** implement the Phase 14A `nd.md §1.5` Director Operating Model promise.

1. **Director Daily Briefing approval workflow** on `/ceo-ai`. 16-question structured briefing pulled from `CeoOrchestrationSnapshot` + per-question 1-click approve / defer / reject buttons backed by Phase 4C `ApprovalRequest`. Resolves P0 #5.
2. **Team role management UI on `/saas-admin`** — extend `OrganizationMembership` to cover calling-agent / confirmation-team / warehouse / delivery / QA / finance roles + invite-user form. Resolves P0 #7.
3. **Audit log of who-did-what on `/operations/audit-timeline`** — already shipped (Phase 15C); confirm filters cover the new role events.
4. **Backup / restore runbook** in `docs/DEPLOYMENT_VPS.md`. Resolves P1 #13.
5. **Centralised logging** — Loki or Datadog wiring + structured backend log format. Resolves P1 #14.

### Phase 16E — Payment / Logistics Integration Hardening

**Goal:** make the existing Razorpay + Delhivery gates actually run live, safely.

1. **`ShipmentCreateView` real-adapter routing** — replace `create_mock_shipment` with mode-aware dispatch. Resolves P0 #3.
2. **Phase 7G-Live real customer Delhivery dispatch** — Director directive + env flip + structured UTC window + first internal smoke. Resolves P0 #4 (partial).
3. **Phase 8F Reading 2 staging** — fresh Director directive required. Resolves P1 #17.
4. **Phase 10C payment link refresh UI** — admin-facing web form on `/saas-admin`. Resolves P2 #20.
5. **RTO Rescue UI wiring** — `Rto.tsx` buttons call `services.create_rescue_attempt` + lifecycle template. Resolves P0 #10.

### Phase 16E — WhatsApp Business Workflow Activation

**Goal:** turn the existing lifecycle automation from `false` to gradual rollout.

1. **Production Claim Vault rollout** — load real doctor-approved claims for all 8 product categories; archive demo-v2 rows. Resolves P0 #8.
2. **Phase 7E-Live-B real customer WhatsApp send** — Director directive + env flip + structured UTC window + per-recipient allow-list expansion. Resolves P0 #4 (partial).
3. **Limited `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` rollout** — confidence threshold tuning + soak test + monitoring dashboard already exists. Resolves P1 #17-equivalent.
4. **Gradual lifecycle flag flips**: confirmation_reminder → payment_reminder → delivery_reminder → rto_rescue → reorder_day20 — one flag per week with soak monitoring.

### Phase 16F — AI Calling Pilot

**Goal:** run the first real AI outbound calling campaign.

1. **`AI_CALLING_ENABLED=true`** + Vapi live credentials + Director-issued 30-min UTC window + first 10-lead campaign. Resolves P0 #6 (AI side).
2. **Vapi monitoring dashboard polish** — existing `CallingDashboard.tsx` (Phase 12D) extended with real-time per-call status.
3. **Director-review queue for Phase 12B outcome classifier suggestions** + 1-click apply via Phase 4C approval.

### Phase 16G — Human Calling Agent UI (if scope desired)

**Goal:** support humans making calls from the platform (currently AI-calling-only).

1. **"My Leads" agent dashboard** — assignee-filtered Lead queue.
2. **Manual call trigger UI** — click-to-call via PSTN (not Vapi) for human agents.
3. **Outcome form** — explicit Connected / Callback / Not Interested / Wrong Number / etc.
4. **Callback scheduler** — Lead.callback_at field + queue UI.
5. **Escalation routing** — handoff to a senior agent role.

**Recommendation:** start with Phase 16B (customer lifecycle UI backbone) because it produces the most usable value per coding-hour and unblocks every downstream phase. Stop after each phase, validate against this audit, and only commission the next phase when the previous one is signed off.

---

## 8. What NOT to build yet

The biggest risk for Phase 16A → 16B handoff is repeating the Phase 15 polish loop — adding shiny but non-critical surfaces while leaving the business backbone gaps untouched. **Explicitly defer the following until the Phase 16B backbone is sound:**

1. **More Phase 15 safety UI polish.** No new diagnostics rows, no new sync states, no new badge tones. Phase 15M freeze rules apply.
2. **Advanced reward / penalty automation execution.** Phase 4B scoring is already running deterministically; do not wire an "auto-disable underperforming agent" workflow until the human-team UI exists (Phase 16C).
3. **Broad WhatsApp automation flag flips.** Do NOT flip all six lifecycle flags simultaneously. Roll out one flag per week with monitoring (Phase 16E).
4. **Production AI calling rollout.** Phase 12A is gated behind `AI_CALLING_ENABLED=false` for a reason — without a confirmation queue that actually persists outcomes (Phase 16B #1), AI calls produce data the operator cannot act on.
5. **Automated courier dispatch.** Phase 7G-Live first, then `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=true` for delivery reminders. Do NOT enable automated AWB creation from order signals.
6. **Phase 4A pytest test-DB teardown warning fix.** Accepted as non-blocking; do not retry-loop or sleep around it.
7. **Coverage % reports.** Test count tracking is already in `nd.md`; coverage % adds infra cost without unblocking a customer flow.
8. **PayU adapter.** Razorpay is the primary path; PayU is contingency. Skip until Razorpay live rollout proves stable.
9. **SaaS multi-tenant global queryset filtering blanket enable.** Phase 6A scaffold is sufficient for a single-tenant pilot.
10. **MCP gateway tool execution.** `MCP_ENABLED=false`; foundation only. Do not enable for at least 6 months.

---

## 9. Director decisions needed

Before commissioning Phase 16B, the Director needs to answer these yes/no questions:

1. **Which product / disease journey first?** Weight management, blood purification, men's wellness, immunity, lungs detox, body detox, or joint care?
2. **Which team uses the system first?** Director only, or Director + 1-2 internal staff?
3. **How many internal pilot users?** 1, 2, 3, or 5?
4. **WhatsApp allowed-list size?** Stay at the current internal cohort (2-3 numbers) or expand to a 10-15 internal+staff cohort?
5. **Payment pilot mode?** Stay in Razorpay test mode for Phase 16B, or commission a Phase 16D Razorpay live rollout?
6. **Delhivery pilot scope?** No real AWBs in 16B; or commission a Phase 16D Phase 7G-Live single-shipment Reading?
7. **AI calling — disabled or internal test only?** Stay disabled for 16B/C/D; enable in 16F with explicit directive.
8. **Data import path from old CRM / Sheets?** What is the source of existing customer data — Google Sheets, Excel, an old CRM, paper records? Phase 16B needs to know to design the import surface.
9. **Is human calling in scope?** If yes, Phase 16G needs to be planned; if no, the AI-only design stays.
10. **Production environment safety changes?** Director must explicitly approve flipping `RAZORPAY_MODE` from `test` to `live`, flipping `DELHIVERY_MODE` from `mock` to `live`, and any `PHASE7*_*_ENABLED` flag from `false` to `true`. Until then everything stays on the current rails.

---

## 10. Safe next action

**The safe next action is: DO NOT START CODING YET.**

1. **Director reviews this audit** (Phase 16A SHIPPED).
2. **Director answers §9 decisions** in writing.
3. **Director issues a written Phase 16B directive** that names exactly one of:
   - "Phase 16B — Customer Lifecycle UI Backbone kick-off — scope: items 1-6 from §7 Phase 16B" (recommended)
   - "Phase 16C — Director Daily Briefing + Team Roles UI kick-off" (if Director wants the briefing first)
   - "Phase 16E — Payment / Logistics Integration Hardening kick-off" (if Director wants a live shipment first)
   - "Phase 16E — WhatsApp Business Workflow Activation kick-off" (if Director wants live customer messages first)
4. **Coding agents do NOT interpret silence as authorisation.** No Phase 16B file should be created until the directive lands.

**If coding starts despite this caution, the narrowest safe scope is Phase 16B #1: wire `Confirmation.tsx` action buttons to call `api.recordConfirmationOutcome`.** This is a 1-2 hour change with a clean diff and immediate Director-visible value, no env flip required, no migration required, no safety-shell touch required.

---

## 11. Evidence appendix

### A. Backend Django apps inventory (26 apps)

`accounts`, `agents`, `ai_governance`, `analytics`, `audit`, `caio`, `calls`, `catalog`, `compliance`, `crm`, `dashboards`, `diagnostics`, `integrations`, `learning`, `learning_engine`, `mcp_gateway`, `orders`, `payments`, `rewards`, `saas`, `shipments`, `whatsapp` (plus underscore-prefixed config modules).

### B. Frontend pages inventory (27 pages)

`Agents`, `Analytics`, `AuditTimeline`, `Caio`, `Calling`, `CallingDashboard`, `CeoAi`, `Claims`, `Confirmation`, `Customers`, `Delivery`, `Governance`, `Index`, `Leads`, `Learning`, `LearningProposals`, `Login`, `NotFound`, `Orders`, `Payments`, `PendingPayments`, `Rewards`, `Rto`, `SaasAdmin`, `Scheduler`, `Settings`, `WhatsAppInbox`, `WhatsAppMonitoring`, `WhatsAppTemplates`.

### C. Sidebar nav inventory (25 nav items across 7 groups)

Overview (Command Center) — Sales (Leads CRM, Customer 360, AI Calling Console) — Operations (Orders Pipeline, Confirmation Queue, Payments, Delhivery & Tracking, RTO Rescue Board) — AI Layer (AI Agents Center, CEO AI Briefing, CAIO Audit Center, AI Scheduler & Cost, AI Governance) — Governance (Reward & Penalty, Call Learning Studio, Claim Vault, Audit Timeline) — Insights (Analytics) — Messaging (WhatsApp Inbox, WhatsApp Templates, WhatsApp Monitoring) — System (SaaS Admin, Settings & Control).

### D. Top-level URL routes (from `backend/config/urls.py`)

`/admin/`, `/api/healthz/`, `/api/auth/`, `/api/settings/`, `/api/dashboard/`, `/api/audit/`, `/api/analytics/`, `/api/leads/`, `/api/customers/`, `/api/orders/`, `/api/confirmation/`, `/api/calls/`, `/api/payments/`, `/api/shipments/`, `/api/rto/`, `/api/agents/`, `/api/ai/`, `/api/compliance/`, `/api/rewards/`, `/api/learning/`, `/api/catalog/`, `/api/whatsapp/`, `/api/webhooks/{razorpay,delhivery,vapi,meta/leads,whatsapp/meta}/`, `/api/v1/auth/{login,refresh}/`, `/api/v1/whatsapp/`, `/api/v1/saas/`, `/api/v1/mcp/`, `/api/v1/customer-success/`, `/api/v1/rto-prevention/`, `/api/v1/cfo/`, `/api/v1/data-analyst/`, `/api/v1/calling-team-leader/`, `/api/v1/ceo-orchestration/`, `/api/v1/diagnostics/`, `/api/v1/caio/`, `/api/v1/learning/`, `/api/v1/calls/`.

### E. Frontend api.ts surface size

**249 api.ts methods** — full read+mutate surface for the entire backend. Most are READ-only consumed by pages; a subset of POST/PATCH (login, manual template send, manual call trigger, leads create/assign, customers create/update, prompt rollback, kill switch toggle, sandbox toggle, etc.) exists.

### F. Env flag inventory (from `.env.production.example`)

Provider modes (all default `mock`): `RAZORPAY_MODE`, `DELHIVERY_MODE`, `VAPI_MODE`, `META_MODE`, `WHATSAPP_PROVIDER`.

Locked-OFF gates: `AI_PROVIDER=disabled`, `AI_SANDBOX_MODE=false`, `WHATSAPP_AI_AUTO_REPLY_ENABLED`, `WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`, `AI_CALLING_ENABLED`, `MCP_ENABLED`, `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED`, `PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED`, `PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED`, `PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED`, `PHASE7G_COURIER_EXECUTION_ENABLED`, `PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED`, `PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED`.

### G. Daily Celery beat schedule (13 IST entries from `backend/config/celery.py`)

07:00 call-outcome-classification — 08:00 customer-success — 08:30 post-call-followup — 09:00 rto-prevention + ai-daily-briefing-morning — 10:00 cfo — 11:00 data-analyst — 12:00 calling-team-leader — 13:00 ceo-orchestration — 14:00 caio-audit — 18:00 ai-daily-briefing-evening — 23:00 transcript-ingestion — 23:30 call-quality-scoring.

### H. Health endpoint contract

`GET /api/healthz/` → `{"status":"ok","service":"nirogidhara-backend"}` (verified by `docker-compose.prod.yml` healthcheck + Director's local check).

### I. Test counts

- Backend: 2200+ passing (Test Hygiene Hotfix-1 mock-mode pinning in `conftest.py`).
- Frontend: **275 / 275 passing** (post-Phase-15L baseline; Phase 16A added zero tests because no code was modified).
- Migrations: `makemigrations --check --dry-run` → `No changes detected`.
- System check: `python manage.py check` → `System check identified no issues (0 silenced).`

### J. Docs reviewed for this audit

- `nd.md` head-of-file (TL;DR §0 + §8 Phase 15M / 15L narratives + §11 phase roadmap).
- `AGENTS.md` (Current operational baseline post Phase 15M + hard stops + rules).
- `CLAUDE.md` (Current operational baseline post Phase 15M + working agreement).
- `docs/PHASE_15M_DIRECTOR_SIGNOFF_PACK.md` (all 11 sections — freeze rule + smoke checklist + accepted risks).
- `docs/RUNBOOK.md` (Foundation Release Freeze + State semantics + Director playbooks).
- `docs/MASTER_BLUEPRINT_V2.md` (top operational supersession note + Document Control historical rows).
- `docs/BACKEND_API.md` (Phase 15M operational baseline note).
- `docs/DEPLOYMENT_VPS.md` (production posture historical note).
- `docs/FRONTEND_AUDIT.md` (historical frontend audit snapshot).
- `docs/FUTURE_BACKEND_PLAN.md` (historical SaaS runtime gate snapshot).
- `docs/WHATSAPP_INTEGRATION_PLAN.md` (historical WhatsApp status snapshot).
- `docs/README.md` (docs index with Phase 15M baseline + sign-off pack pointer).
- `README.md` (Phase 15M operational baseline + repo overview).
- `ndmemory.txt` (Phase 14B historical warning block).

---

> **End of Phase 16A — Business MVP Gap Audit.**
>
> **Recommendation:** Director reviews this audit, answers §9 decisions, issues a written Phase 16B directive (recommended: Phase 16B — Customer Lifecycle UI Backbone). Coding agents must NOT start Phase 16B without that directive.
>
> **Phase 15 safety shell remains FROZEN at code commit `eefd8b3`.** This audit does not modify any frozen surface.
