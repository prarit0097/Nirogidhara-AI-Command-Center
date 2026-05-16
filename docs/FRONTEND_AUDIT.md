# Frontend Audit

Frontend was generated using Lovable, then refined for the AI command-center
direction.

## Status (current)

**Test Hygiene Hotfix-1 baseline.** `/saas-admin` now renders the Phase 6 →
Phase 8F read-only section grid, with no execute buttons and CLI-only
review/approve banners on every section:

- **Phase 6E** — SaaS overview + integration settings metadata (read-only).
- **Phase 6F** — Runtime Integration Routing Preview (`runtimeSource=env_config`, `perOrgRuntimeEnabled=false`).
- **Phase 6G** — Controlled Runtime Routing Dry Run (14-row operation table) + AI Provider Routing Preview (NVIDIA primary / OpenAI + Anthropic fallback).
- **Phase 6H** — Controlled Runtime Live Audit Gate (kill-switch state, approval queue, recent audit events).
- **Phase 6I** — Single Internal Live Gate Simulation.
- **Phase 6J** — Single Internal Provider Test Plan (safety-invariant + Razorpay env-readiness sub-cards).
- **Phase 6K-A / 6K-B** — Single Internal Razorpay Test-Mode Execution Gate + attempts table (immutable Phase 6K-B artefact `pex_8f309650e9644cfaae4418f9` → `order_Sks3KPf0vntKhf` rendered as historical).
- **Phase 6L** — Razorpay Test Execution Audit Review + Webhook Readiness Plan (audit invariants / readiness / webhook plan with allowlist + denylist tables).
- **Phase 6M-0** — MCP Gateway Readiness (dormant: `MCP_ENABLED=false`).
- **Phase 6M** — Razorpay Webhook Handler (Test Mode) — readiness card + sanitized event list.
- **Phase 6N** — Razorpay Business Mutation Sandbox Plan (planning-only) — readiness grid + 9-row event-to-status mapping table + synthetic eligibility list + 8-item manual review checklist + 7-step rollback list + forbidden-action chips. **Read-only.** No mutation buttons.
- **Phase 6O** — Razorpay Sandbox Status Mapping + Manual Review (sandbox-review-only) — readiness grid + 9-row event-to-status mapping table + reviews table with per-row "Approve Review Only" / "Reject Review" / "Archive Review" buttons (clearly labelled review-only) + manual review checklist + forbidden-action chips. Phase 6O buttons NEVER mutate Order/Payment/Shipment/DiscountOfferLog; they only flip the review row's `status`.
- **Phase 6P** — Razorpay Sandbox Paid-Status Mutation Test (sandbox-ledger-only, CLI-only execution) — readiness grid + 9-row event-to-ledger mapping table + attempts table + CLI-only reminder block + forbidden-action chips. **No execute / rollback buttons exist** — Phase 6P mutation is exclusively dispatched via the seven CLI commands; the page renders status only.
- **Phase 6Q** — Razorpay Payment → Order Workflow Safety Gate (audit-gate-only, CLI-only review state changes) — readiness grid + 9-row Payment → Order workflow contract table + gate review records table + CLI-only reminder block + forbidden-action chips. **No prepare / approve / reject / archive buttons exist** — Phase 6Q gate state changes are exclusively dispatched via the seven CLI commands; the page renders status only.
- **Phase 6R** — Razorpay Payment → WhatsApp / Courier Dispatch Readiness (audit-only readiness contract, CLI-only review state changes) — readiness grid + 9-row dispatch readiness contract table (every "Send allowed in 6R" / "Courier in 6R" cell `No`) + recent readiness gates table + three readiness checklists (WhatsApp / courier / dispatch) + forbidden-action chips + "Readiness contract only" banner. **No Send WhatsApp / Queue WhatsApp / Create Shipment / Create AWB / Book Courier / Dispatch Order / Notify Customer / Approve Readiness / Reject Readiness buttons exist** — review state changes are exclusively dispatched via the seven CLI commands; the page renders status only.
- **Phase 6S** — Razorpay Limited Internal Dispatch Pilot Plan (planning-only, CLI-only review state changes) — readiness grid + 9-row Limited Internal Dispatch Pilot contract table (every "Pilot in 6S" / "Send in 6S" / "Courier in 6S" cell `No`) + recent pilot plans table + four readiness checklists (internal staff cohort / WhatsApp / courier / dispatch) + abort criteria + verification checklist + forbidden-action chips + "Pilot plan only" banner. **No Start Pilot / Run Pilot / Execute Pilot / Send WhatsApp / Queue WhatsApp / Notify Customer / Create Shipment / Create AWB / Book Courier / Dispatch Order / Call Delhivery / Call Meta / Approve Pilot Plan / Reject Pilot Plan buttons exist** — review state changes are exclusively dispatched via the seven CLI commands; the page renders status only.
- **Phase 6T** — Razorpay Phase 6 Final Audit + Lock (audit-lock-only, CLI-only review state changes) — readiness grid + Phase 6N -> 6S audit-chain table + final audit lock records table + Director signoff / kill-switch / rollback contracts + abort criteria + operator checklist + safety invariants + CLI-only reminder. **No live execution / pilot / provider / WhatsApp / courier / mutation buttons exist**; the page renders status only.
- **Phase 7B → 7I** — controlled pilot, Razorpay TEST execution evidence, WhatsApp readiness/internal-send, courier readiness/execution, and final Phase 7 audit-lock sections. All runtime-changing operations remain CLI-only; Phase 7E-Live-B and Phase 7G-Live remain NOT approved.
- **Phase 8A → 8F** — payment → order mutation sandbox/review/controlled-mutation/evidence-lock/real-customer pilot/controlled real-customer mutation sections. The Phase 8E section includes the candidate-pool subsection; the Phase 8F section shows the controlled real-customer mutation readiness and target snapshot for Order `NRG-20435` / Payment `PAY-30125`. **Phase 8F execute is NOT approved and no UI execute control exists.**

**Forbidden UI buttons (asserted in `frontend/src/test/saas-admin.test.tsx`):**
no "Execute Razorpay" / "Create Order" / "Create Payment Link" / "Capture"
/ "Send WhatsApp" / "Place Call" / "Create Shipment" / "Replay Webhook" /
"Apply Mutation" / "Go Live" / "Activate Provider" / "Run Live" /
"Disable Kill Switch" buttons exist on any Phase 6 page. Raw env-var
names like `RAZORPAY_KEY_SECRET` are never rendered (label is "Razorpay
key secret" / "Razorpay key id" — the test asserts on the absence of the
literal env-var name).

Phase 5F-Gate pilot readiness update: `/whatsapp-monitoring` now includes
a read-only "Approved Customer Pilot Readiness" section backed by
`/api/v1/whatsapp/monitoring/pilot/`. Phones are masked, blockers and
daily caps render from the backend, and there are no send / enable /
approve / pause buttons. Auto-reply remains OFF, campaigns/broadcast stay
locked, and the customer pilot requires explicit consent + approval. The
earlier 4-hour soak was accelerated, not full-duration.

Phase 5F-Gate pilot readiness update: `/whatsapp-monitoring` now includes
a read-only "Approved Customer Pilot Readiness" section backed by
`/api/v1/whatsapp/monitoring/pilot/`. Phones are masked, blockers and
daily caps render from the backend, and there are no send / enable /
approve / pause buttons. Auto-reply remains OFF, campaigns/broadcast stay
locked, and the customer pilot requires explicit consent + approval. The
earlier 4-hour soak was accelerated, not full-duration.

Item | Status
--- | ---
Phase 6S `/saas-admin` | done — adds read-only "Razorpay Limited Internal Dispatch Pilot Plan" section: phase status / safeToStartPhase6T badge / pilot plan flag display / 9-row Limited Internal Dispatch Pilot contract table (Pilot in 6S / Send in 6S / Courier in 6S cells = "No") / recent pilot plans table (no buttons) / four readiness checklists (internal staff cohort / WhatsApp / courier / dispatch) / abort criteria / verification checklist / forbidden-action chips / "Pilot plan only" banner / `data-testid` hooks (`razorpay-payment-dispatch-pilot-plan-section`, `phase6s-safe-to-start-phase6t-badge`, `phase6s-pilot-contract-table`, `phase6s-forbidden-actions`). No Start Pilot / Run Pilot / Execute Pilot / Send WhatsApp / Queue WhatsApp / Notify Customer / Create Shipment / Create AWB / Book Courier / Dispatch Order / Call Delhivery / Call Meta / Mark Paid / Capture Payment / Refund / Apply Payment / Apply Mutation / Mutate Order / Create Payment Link / Execute Webhook / Replay Event / Enable Mutation / Go Live / Run MCP Tool / Execute Workflow / Apply Order Update / Confirm Paid Order / Start Live Workflow / Approve Pilot Plan / Reject Pilot Plan buttons.
Phase 6R `/saas-admin` | done — adds read-only "Razorpay Payment → WhatsApp / Courier Dispatch Readiness" section: phase status / safeToStartPhase6S badge / readiness flag display / 9-row dispatch readiness contract table (Send allowed in 6R / Courier in 6R cells = "No") / recent readiness gates table (no buttons) / three readiness checklists / forbidden-action chips / "Readiness contract only" banner / `data-testid` hooks (`razorpay-payment-dispatch-readiness-section`, `phase6r-safe-to-start-phase6s-badge`). No Send WhatsApp / Queue WhatsApp / Create Shipment / Create AWB / Book Courier / Dispatch Order / Notify Customer / Mark Paid / Capture Payment / Refund / Apply Payment / Apply Mutation / Mutate Order / Create Payment Link / Execute Webhook / Replay Event / Enable Mutation / Go Live / Run MCP Tool / Execute Workflow / Apply Order Update / Confirm Paid Order / Start Live Workflow / Approve Readiness / Reject Readiness buttons.
Phase 6Q `/saas-admin` | done — adds read-only "Razorpay Payment → Order Workflow Safety Gate" section: phase status / safeToStartPhase6R badge / gate flag display / 9-row Payment → Order workflow contract table (all "Disabled" for real mutation) / gate review records table (no buttons) / CLI-only reminder list / forbidden-action chips / `data-testid` hooks (`phase6q-contract-table`, `phase6q-gates-table`, `phase6q-cli-list`, `phase6q-forbidden-actions`, `phase6q-safe-to-start-phase6r-badge`). No Mark Paid / Capture Payment / Refund / Apply Payment / Apply Mutation / Mutate Order / Send WhatsApp / Create Payment Link / Execute Webhook / Replay Event / Enable Mutation / Go Live / Run MCP Tool / Execute Workflow / Apply Order Update / Confirm Paid Order / Start Live Workflow / Approve Gate / Reject Gate buttons.
Phase 6P `/saas-admin` | done — adds read-only "Razorpay Sandbox Paid-Status Mutation Test" section: phase status / safeToStartPhase6Q badge / sandbox flag display / 9-row event-to-ledger mapping table (all "Disabled" for real mutation) / attempts table (no execute/rollback buttons) / CLI-only reminder list / forbidden-action chips / `data-testid` hooks (`phase6p-event-mapping-table`, `phase6p-attempts-table`, `phase6p-cli-list`, `phase6p-forbidden-actions`, `phase6p-safe-to-start-phase6q-badge`). No Mark Paid / Capture Payment / Refund / Apply Payment / Apply Mutation / Mutate Order / Send WhatsApp / Create Payment Link / Execute Webhook / Replay Event / Enable Mutation / Go Live / Run MCP Tool / Execute Sandbox / Rollback Sandbox buttons.
Phase 6O `/saas-admin` | done — adds review-only "Razorpay Sandbox Status Mapping + Manual Review" section: phase status / safeToStartPhase6P badge / sandbox flag display / 9-row event-to-status mapping table (all "Disabled") / reviews table with per-row "Approve Review Only" / "Reject Review" / "Archive Review" buttons / manual review checklist / forbidden-action chips / `data-testid` hooks (`phase6o-event-mapping-table`, `phase6o-reviews-table`, `phase6o-manual-review-list`, `phase6o-forbidden-actions`, `phase6o-safe-to-start-phase6p-badge`, `phase6o-review-{id}-{approve\|reject\|archive}`). No Mark Paid / Capture Payment / Refund / Mutate Order / Apply Mutation / Execute Payment / Replay Event / Enable Mutation / Go Live / Run MCP Tool / Send WhatsApp / Create Payment Link buttons.
Phase 6N `/saas-admin` | done — adds read-only "Razorpay Business Mutation Sandbox Plan" section: phase / status / safeToStartPhase6O badge / Phase 6M flag-lock summary / 9-row event-to-status table / synthetic eligibility list / manual review checklist / rollback step list / forbidden-action chips / `data-testid` hooks (`phase6n-event-mapping-table`, `phase6n-manual-review-list`, `phase6n-rollback-list`, `phase6n-forbidden-actions`, `phase6n-safe-to-start-phase6o-badge`). No Mark Paid / Capture Payment / Refund / Mutate Order / Send WhatsApp / Create Payment Link / Replay Event / Enable Mutation / Go Live / Run MCP Tool buttons.
Phase 6M `/saas-admin` | done — adds read-only "Razorpay Webhook Handler (Test Mode)" + "MCP Gateway Readiness" sections on top of the Phase 6E → Phase 6L stack. All sections strictly read-only; no Replay / Apply mutation / Go Live / Activate connector controls. `RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false` and `MCP_ENABLED=false` rendered as locked states.
Phase 6L `/saas-admin` | done — Razorpay Test Execution Audit Review + Webhook Readiness Plan section; audit-invariant / readiness / webhook-plan cards (allowlist + denylist tables); no Execute / Register Webhook / Capture / Send WhatsApp buttons.
Phase 6K `/saas-admin` | done — Single Internal Razorpay Test-Mode Execution Gate; readiness + invariants + attempts table (renders Phase 6K-B immutable artefact). No Execute / Capture / Go Live buttons; execution is CLI-only.
Phase 6J `/saas-admin` | done — Single Internal Provider Test Plan; safety-invariant + Razorpay env-readiness sub-cards. No Execute Razorpay / Create Order / Create Payment Link buttons.
Phase 6I `/saas-admin` | done — SaaS admin panel includes Single Internal Live Gate Simulation with default operation, allowed operations, kill-switch state, simulation table, and explicit `externalCallWasMade=false` / `providerCallAttempted=false`; no provider execution, WhatsApp send/enable, payment/shipment/call, campaign, or org-switch mutation controls.
All 21 pages exist | done — Phase 3C added Scheduler page; Phase 3D added Governance page; Phase 4B enhanced the Rewards page; Phase 4C added an Approval queue table on Governance; Phase 4D added an Execute button on approved rows; Phase 4A added a `services/realtime.ts` WebSocket client wired into the Dashboard "Live Activity" feed and the Governance "Approval queue"; Phase 4E is backend-only; Phase 5A added a read-only `/whatsapp-templates` page + Settings → WABA section + new "Messaging" sidebar group; Phase 5B added a three-pane `/whatsapp-inbox` page + Customer 360 WhatsApp tab; Phase 5C replaces the Phase 5B "AI suggestions disabled" placeholder with a live `AiAgentPanel`; Phase 5D adds a "Call customer" button on the `AiAgentPanel` + handoff and lifecycle event endpoints; **Phase 5E** adds a Rescue Discount cap card to the `AiAgentPanel` (current cumulative %, cap remaining out of 50%, customer ask count) plus six new TS types (`DiscountOffer`, `DiscountOfferListResponse`, `CreateRescueOfferPayload`, `DiscountOfferCap`, `ReorderDay20StatusResponse`, `ReorderDay20RunResponse`) and six new `api` methods (`getOrderDiscountOffers`, `createRescueDiscountOffer`, `acceptRescueDiscountOffer`, `rejectRescueDiscountOffer`, `getReorderDay20Status`, `runReorderDay20Sweep`). All cap math and CEO escalation logic lives in the backend (`apps.orders.rescue_discount`); the frontend renders cap state and dispatches API calls only.
Pages go through `src/services/api.ts` only | done — no page imports `mockData.ts` directly
TypeScript shared types in `src/types/domain.ts` | done
Sidebar collapse layout | done — shared collapsed state
Mobile responsiveness | baseline done — KPI stack, sidebar drawer, tables horizontal-scroll on small screens; per-page tuning continues
Dashboard polish | baseline done — premium spacing, hierarchy, executive feel; iterate as needed
Workflow visuals | UI-component diagrams in `WorkflowMap`
Vitest tests | 82 tests today. Phase 6 → Phase 8F assertions in `frontend/src/test/saas-admin.test.tsx` cover render of every current `/saas-admin` section, the Phase 8E candidate-pool subsection, the Phase 8F controlled real-customer mutation section, absence of forbidden execute/send/courier/payment-mutation buttons, no raw env-var names like `RAZORPAY_KEY_SECRET` / `RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED` in body text, no full Indian phone numbers, and no raw secrets in any rendered preview.
ESLint warnings | 8 pre-existing shadcn warnings (`react-refresh/only-export-components`); 0 errors
Mock fallback in `api.ts` | done — pages never break when backend is offline

## Backend wiring

`src/services/api.ts` calls `${VITE_API_BASE_URL}/...` (default
`http://localhost:8000/api`). On any network or HTTP failure, the request
falls back to the deterministic fixtures in `mockData.ts`.

To talk to the real backend in dev:

```bash
copy .env.example .env       # cp on macOS/Linux
# Backend running at :8000:
cd ../backend && python manage.py runserver 0.0.0.0:8000
# Frontend:
cd ../frontend && npm run dev
```

## Open improvements

- Iterate per-page mobile tuning where data tables remain dense.
- Replace placeholder login flow when JWT auth is wired (Phase 2).
- Bundle is ~900 KB gzipped to ~257 KB — code-split heavy charts (recharts is
  the dominant chunk) when bundle size matters.

## Page inventory (Phase 3D)

| Route | Page | Phase | Notes |
| --- | --- | --- | --- |
| `/` | `Index.tsx` | 1 | Command Center dashboard |
| `/leads` | `Leads.tsx` | 1 / 2A | Leads CRM |
| `/customers` | `Customers.tsx` | 1 / 2A | Customer 360 |
| `/calling` | `Calling.tsx` | 1 / 2D | AI Calling Console |
| `/orders` | `Orders.tsx` | 1 / 2A | Orders Pipeline |
| `/confirmation` | `Confirmation.tsx` | 1 / 2A | Confirmation Queue |
| `/payments` | `Payments.tsx` | 1 / 2B | Payments — Razorpay link generation |
| `/delivery` | `Delivery.tsx` | 1 / 2C | Delhivery + Tracking |
| `/rto` | `Rto.tsx` | 1 / 2A | RTO Rescue Board |
| `/agents` | `Agents.tsx` | 1 | AI Agents Center |
| `/ceo-ai` | `CeoAi.tsx` | 1 / 3B | CEO AI Briefing |
| `/caio` | `Caio.tsx` | 1 / 3B | CAIO Audit Center |
| `/ai-scheduler` | `Scheduler.tsx` | 3C | Celery beat + cost / fallback snapshot (admin/director only on the API) |
| `/ai-governance` | `Governance.tsx` | 3D | Sandbox toggle + prompt version rollback + per-agent USD budgets |
| `/rewards` | `Rewards.tsx` | 1 | Reward & Penalty leaderboard |
| `/learning` | `Learning.tsx` | 1 | Call Learning Studio |
| `/claims` | `Claims.tsx` | 1 | Claim Vault |
| `/analytics` | `Analytics.tsx` | 1 | Analytics |
| `/whatsapp-inbox` | `WhatsAppInbox.tsx` | 5B | Three-pane manual-only WhatsApp inbox + internal notes + manual template send + AI-suggestions-disabled placeholder |
| `/whatsapp-templates` | `WhatsAppTemplates.tsx` | 5A | Meta-mirrored WhatsApp templates (read-only) + Sync from Meta button |
| `/whatsapp-monitoring` | `WhatsAppMonitoring.tsx` | 5F-Gate | Read-only auto-reply safety dashboard + Approved Customer Pilot Readiness; masked phones only; no send/enable controls |
| `/saas-admin` | `SaasAdmin.tsx` | 6E-8F | SaaS admin panel: full Phase 6 → Phase 8F section grid, including Phase 8E candidate-pool subsection and Phase 8F controlled real-customer mutation readiness. Read-only; no activation / send / provider-execution / replay / apply-mutation / go-live / disable-kill-switch / mark-paid / capture-payment / refund / mutate-order / run-mcp-tool / execute controls anywhere. |
| `/settings` | `Settings.tsx` | 1 / 5A | Settings & Control + WABA section |

Phase 8F baseline note: `/saas-admin` is the central read-only command-center for
every Phase 6 → Phase 8F surface. It does not render send, create-payment,
create-shipment, place-call, run-live, replay-webhook, apply-mutation,
or activate-connector controls.
Current total: 23 pages. Sidebar groups include Overview, Sales, Operations, AI Layer, Governance, Insights, Messaging, and System.

## Phase 9-10 Frontend Additions (as of Phase 10B Hotfix-2 baseline)

**Test baseline:** 82 frontend tests (unchanged across Phase 9-10 —
new UI cards land in `/saas-admin` which is rendered read-only and
its existing assertions cover the absence of execute / send / mutate
buttons).

### New `/saas-admin` cards (all read-only, no action buttons)

Each Phase 9 agent surfaces its latest deterministic snapshot in a
read-only card; none expose a "Run Agent" / "Approve Priority" /
"Send Briefing" / "Trigger Workflow" / "Apply Recommendation" /
"Send WhatsApp" / "Send Reminder" button. The CEO Orchestration
card sits at the **top** of the agent stack because it is the
synthesis layer over the other five.

| Card | Phase | Source data shape |
| --- | --- | --- |
| CEO AI — Daily Director Briefing | 9F | health score / health tier badge / 5-row agent status table / top-3 priorities ordered list / severity-tagged cross-cutting alerts / scrollable deterministic briefing text |
| Customer Success Agent V1 | 9A | cohort counts (`fresh_delivery` → `lapsed`), reorder candidate count, at-risk count |
| RTO Prevention Agent V1 | 9B | risk tier breakdown (`low` / `medium` / `high` / `critical`), in-flight order count, top risk reasons |
| CFO Agent V1 | 9C | revenue 24h / 7d / 30d, paid / pending / partial breakdown, RTO 30d ₹ loss, AOV, customer mix, **plus a "View pending payments →" link to `/operations/pending-payments`** |
| Data Analyst Agent V1 | 9D | 30-day funnel counts (lead → call → confirmed → delivered → reorder), 4 conversion rates, top-5 states by volume + ₹ revenue, day-of-week distribution |
| Calling Team Leader Agent V1 | 9E | call counts (24h / 7d / 30d), connection rate, avg duration, outcome breakdown, top-10 per-agent table, transcript backlog |

### New page

| Route | Page | Phase | Notes |
| --- | --- | --- | --- |
| `/operations/pending-payments` | `PendingPayments.tsx` | 10A | Read-only Director review surface. Sortable table with columns Order / Customer / Phone / Amount / Status / State / Days Pending / Last WhatsApp / Last Call / Last Call Outcome. Client-side search box (customer / phone / order / state). "Include Partial" toggle (default on). Loading / empty / error states. Permanent "Read-only diagnostic" banner at the bottom. **No "Send Reminder" / "Mark Paid" / "Refund" / "Cancel" / "Trigger Call" buttons exist on the page** (asserted in the safety test). Linked from the CFO `/saas-admin` card. |

Current total: **24 pages** after the Phase 10A page lands.

### What is NOT on the frontend (intentionally)

- Phase 10B (`prepare_payment_reminder_send`) has no UI — CLI-only
  for the Director SSH workflow.
- Phase 10C (`prepare_/approve_/execute_/rollback_/cancel_/inspect_phase10c_payment_link_refresh_gate`)
  has no UI — CLI-only heavyweight gate. The refreshed `Payment.payment_url`
  surfaces in the existing Phase 10A drilldown table via its
  `payment_link_url` column.
- Phase 9F priorities are surfaced **as text** in the
  `/saas-admin` card; no "Acknowledge" / "Dispatch action" /
  "Approve priority" button.

### Phase 10B Hotfix-2 — no frontend change

Phase 10B Hotfix-2 fixed only the backend `template_params` dict in
`apps.diagnostics.payment_reminder_service.build_payment_reminder_attempt`
to match the live Meta-approved `nrg_payment_reminder` template
schema (`{{1}} {{2}}` body, `variables_schema.order = ["customer_name",
"context"]`). No TypeScript types or pages changed; the existing
Phase 7E-Live-B gate-row consumer renders the corrected
`template_params` shape verbatim.
