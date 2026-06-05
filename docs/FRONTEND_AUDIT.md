# Frontend Audit

Frontend was generated using Lovable, then refined for the AI command-center
direction.

> **Current operational UI baseline is Phase 16M — Workboard Analytics + SLA Throughput Dashboard (implemented and pushed to origin/main; VPS production verification pending).** Phase 16M adds a **Workboard Analytics + SLA Throughput** section to the existing `/operations/ai-copilot` page (after the My work queue section): a read-only safety banner ("Read-only analytics only — this dashboard never sends WhatsApp, creates payment links, books shipments, calls customers, invokes Vapi, calls a live AI provider, changes work items, or mutates business data."), **summary cards** (Open work / Overdue / Due soon / Blocked / Completed internal / Avg completion time / Highest-risk department / Director attention), a **department workload table**, a **member workload table**, an **SLA / blocker panel** (top blocker reasons + overdue-by-dept + due-soon-by-dept), and a **throughput-trend table** with a safe empty state. Tables use `overflow-x-auto` (no horizontal overflow); loading / error / empty / dev-mock-fallback states are handled. The section is **strictly read-only — NO mutation / provider / send / call / payment / dispatch / "run AI live" / "auto execute" button anywhere** (asserted by a vitest test scoped to the analytics section). It consumes only the read-only `GET /api/v1/ai-copilot/workboard/analytics/` endpoint; `providerAction*` / `externalAction*` stay false. Frontend 410/410 (+12), lint 0 errors, build green. **Phase 16M is implemented and pushed, VPS production verification pending — confirm the section renders + has no live-action buttons during Director browser validation before marking production verified. Phase 16N is NOT started.** The Phase 16L UI baseline (PRODUCTION VERIFIED + CLOSED at `9d144f5`) is below.
>
> **Phase 16L — Scoped Team Member Work Permissions + My Work Queue (PRODUCTION VERIFIED on the VPS and CLOSED at commit `9d144f5`).** Phase 16L adds a **My work queue** section to the existing `/operations/ai-copilot` page: a no-side-effect safety banner ("Team members can only update internal workboard records they are assigned to or allowed to claim by department membership. These actions never send WhatsApp, create payment links, book shipments, call customers, invoke Vapi, or call a live AI provider."), **summary cards** (My total / Assigned / In progress / Blocked / Due soon / Overdue / Completed), and per-row **permission-gated** Start / Block (reason) / Unblock / Complete internal / Add note controls — only the buttons the API marks allowed for the current user are shown. The Phase 16K Department action workboard now hides Assign/Reassign from non-admins (driven by per-action `permissions` booleans). Every action hits only the internal `/api/v1/ai-copilot/workboard...` + `actions/<id>/{...}/` endpoints (DB-only); `providerAction*` / `externalAction*` stay false; **no live send / call / payment / courier / "run AI live" / "auto execute" button anywhere.** Frontend 398/398 (+13), lint 0 errors, build green. **VPS production verification PASSED (2026-06-05):** Director browser validation of `/operations/ai-copilot` confirmed the AI Copilot Center, Approved action queue, Department action workboard, and My work queue all render; Director/Admin controls (Start / Block / Complete internal / Reassign / Add note / Claim) render; rows show `provider_action_taken=false` / `external_action_taken=false`; the safety shell is unchanged (AI Paused · Sandbox OFF · Briefing STALE · Sync Live); `/operations/pilot-workbench` still loads with internal-control-only state (Live Provider Actions Locked + the blocked-live-actions panel). Scoped-member / viewer login was **not** visually exercised in the browser screenshots; the Phase 16L backend tests cover the scoped-member / non-member / viewer permission matrix. No live WhatsApp / payment / courier / Vapi / live-AI / customer-facing action was triggered. **Phase 16L is CLOSED. Next planned work is Phase 16N (NOT started; separate Director directive required).** The Phase 16K + Phase 16J + Phase 16I baselines are below.
>
> **Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer (PRODUCTION VERIFIED on the VPS and CLOSED at commit `efea751`).** Phase 16K adds a **Department action workboard** section to the existing `/operations/ai-copilot` page: a no-side-effect safety banner ("Completing or updating a workboard action never sends WhatsApp, creates payment links, books shipments, calls customers, invokes Vapi, or calls a live AI provider. This is an internal execution tracker only."), **summary cards** (Total / Unassigned / Assigned / In progress / Blocked / Overdue / Completed / Director attention), **filters** (department / status / priority / SLA / search), a **Director attention** panel (blocked + overdue + unassigned-high/urgent), and per-row **Assign / Claim / Start / Block (requires reason) / Unblock / Complete internal / Reassign / Add note** controls. Every workboard action hits only the internal `/api/v1/ai-copilot/workboard...` + `actions/<id>/{...}/` endpoints (DB-only) — `providerAction*` / `externalAction*` stay false; **no live send / call / payment / courier / "run AI live" / "auto execute" button anywhere.** Frontend 385/385 (+11), lint 0 errors, build green. **VPS production verification PASSED:** browser validation of the Department action workboard on `/operations/ai-copilot` — Assign / Claim / Block (Director attention updated) / Unblock / Complete internal / Add note all PASSED; external action taken=false / provider action taken=false; safety shell unchanged; no live provider / customer-facing action. **Phase 16K is CLOSED (Phase 16L has since shipped on top — PRODUCTION VERIFIED + CLOSED at `9d144f5`).** The Phase 16J + Phase 16I baselines are below.
>
> **Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge (PRODUCTION VERIFIED on the VPS and CLOSED at commit `aa8cf13`).** Phase 16J adds an **Approved action queue** section to the existing `/operations/ai-copilot` page: a no-side-effect safety banner ("Applying internal actions does not send WhatsApp, create payment links, book shipments, call customers, or invoke live AI providers."), an **approved-suggestions list** with a per-suggestion **Create action** control (choose one of 10 internal-only action types), and the **action queue** with per-action **Apply (internal) / Reject / Cancel** controls. Only an approved suggestion can become an action; applying is DB-only (creates an internal `PilotTask` via the Phase 16H safe service, or records a `result_payload`) and never calls a provider — every action reports `providerActionAttempted` / `providerActionTaken` / `externalActionAllowed` / `externalActionTaken` = false. **No live send / call / payment / courier button anywhere** — every action hits only the internal `/api/v1/ai-copilot/actions...` endpoints (DB-only). Frontend 374/374, lint 0, build green. **VPS production verification PASSED:** browser validation of the Approved action queue on `/operations/ai-copilot` — an approved suggestion created an internal action (PENDING INTERNAL ACTION → Apply → APPLIED INTERNAL; Reject → REJECTED); safety flags stayed false; safety shell unchanged; no live provider / customer-facing action. **Phase 16J is CLOSED (Phase 16K has since shipped on top — PRODUCTION VERIFIED + CLOSED at `efea751`).** The Phase 16I baseline is below.
>
> **Phase 16I — AI Copilot Enablement + Human Approval Workflow (PRODUCTION VERIFIED on the VPS and CLOSED at commit `0f91f6b`).** **Browser-verified on the VPS:** `/operations/ai-copilot` opened with the **AI Copilot Center** page + sidebar **AI Copilot** + safety shell AI Paused / Sandbox OFF / Sync Live + AI Mode mock / Live Autonomous Locked / Live Provider unavailable / Provider disabled / Human Approval Required / Provider Call None; a suggestion was generated internally → pending review → approved internally, and another rejected internally; the external-action flags stayed false (external action allowed/taken: false, provider call: false); **no live WhatsApp / Razorpay / PayU / Delhivery / Vapi / live-AI-provider side effect was triggered.** New page **`/operations/ai-copilot`** (sidebar "Operations", Bot icon, "AI Copilot"): a no-side-effect safety banner ("Internal copilot only — no live autonomous execution…"); **AI safety status chips** (AI Paused / Sandbox OFF / AI mode [mock/sandbox] / Live autonomous Locked / Live provider [live_gated|unavailable] / Provider / Human approval Required / Provider call None); a **Generate AI suggestion** form (suggestion type + source type + optional source id + optional compliance text); and a **suggestions queue** of cards (title / type / source / mode + status badge, summary, recommendation, risk-flag pills) with per-card internal-only review controls (**Approve (internal) / Reject / Mark applied (internal only)**, shown only while `pending_review`) and a locked-contract line (`external action allowed/taken: false`, `provider call: false`). **No live send / call / payment / courier button anywhere** — every action hits only the internal `/api/v1/ai-copilot/` endpoints (DB-only) and each suggestion reports `providerCallMade=false` / `externalActionAllowed=false` / `externalActionTaken=false`. Loading / error / empty states render; responsive, no horizontal overflow. **Browser validation PASSED on the VPS (see above).** The Phase 16H page is below.
>
> **Phase 16H UI (PRODUCTION VERIFIED on the VPS and CLOSED at commit `d733cf0`).** **Browser-verified on the VPS:** `/operations/pilot-workbench` opened with the title **Internal Pilot Execution Workbench** + sidebar item **Pilot Workbench** + safety shell AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked + internal-control-only safety copy; a pilot plan ("Phase 16H workbench smoke pilot") was created + approved and shown in the workbench dropdown; **14 internal tasks** were generated across the six team queues (execution panel 0/14 done + per-team progress); the task lifecycle was validated end-to-end — Start→IN PROGRESS, Complete→DONE, Block→BLOCKED, Unblock→IN PROGRESS, Skip→SKIPPED; **no live WhatsApp / payment / courier / Vapi / AI-provider side effect was triggered.** New page **`/operations/pilot-workbench`** (sidebar "Operations", ListChecks icon, "Pilot Workbench"): a no-side-effect safety banner ("Internal control only — no live provider automation…"); safety chips (AI Paused / Sandbox OFF / Sync Live / live provider actions Locked); a **plan selector** + a **"Generate role-based task queues"** button; an **Execution progress dashboard** (per-team progress bars + overall done/total + %); **role-based task queues** (cards grouped by team with title / team / assignee + status badge) with internal-only transition buttons (**Start / Block / Unblock / Complete / Skip / Cancel**, shown only when valid for the current status); and a **blocked-live-actions panel**. **No live action button anywhere** — every action hits only the internal `/api/v1/pilot/` endpoints (DB-only) and each task reports `providerActionsBlocked=true` at every status (including `in_progress`/`done`). Loading / error / empty states render; responsive, no horizontal overflow. **Browser validation PASSED on the VPS (see above).** The Phase 16G page is below.
>
> **Phase 16G UI (PRODUCTION VERIFIED on the VPS and CLOSED at commit `38e8dc8`).** New page **`/operations/pilot-control`** (sidebar "Operations", Gauge icon, "Pilot Control"): a no-side-effect safety banner ("Internal control only — no live provider automation…"); safety chips (AI Paused / Sandbox OFF / Sync Live / live provider actions Locked); a **status-count summary** (Draft / Ready for Review / Approved Internal / Running Internal / Paused / Completed / Cancelled); a **Create pilot plan** form (name + pilot type + owner team + objective); a **pilot plan list**; and a **plan detail panel** with internal-only status-transition buttons ("Mark ready for review", "Approve internal pilot", "Start internal pilot", "Pause pilot", "Resume internal pilot", "Complete pilot", "Cancel pilot", "Add Director note"), a **gate checklist**, a blocked-live-actions list, and a recent-events list. **No live action button anywhere** — every action hits only the internal `/api/v1/pilot/` endpoints (DB-only) and each plan reports `providerActionsBlocked=true` at every state. Loading / error / empty states render; responsive, no horizontal overflow. **Browser-verified on the VPS:** `/operations/pilot-control` opened with the title **Internal Pilot Control Center** + the sidebar item **Pilot Control**; the safety shell was visible + unchanged (AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked); the status counters, Create pilot plan form, and Pilot plans panel all rendered; the safety copy confirmed internal control only / no live provider automation; **no live WhatsApp / payment / courier / Vapi / AI-provider side effect was triggered.** The Phase 16F page is below.
>
> **Phase 16F UI (PRODUCTION VERIFIED on the VPS and CLOSED at commit `967ed3d`).** New page **`/operations/pilot-readiness`** (sidebar "Operations", Rocket icon): a no-side-effect safety banner ("Internal dry-run only — does NOT send WhatsApp, take a payment, book a shipment, place a call…"); safety chips (AI Paused / Sandbox OFF / Sync Live / live provider actions Locked / Phase 15 shell frozen); a **12-gate readiness matrix** (`pilot-gate-matrix` — lead/customer data, calling outcome flow, order creation, confirmation flow, payment readiness [live-blocked], shipment readiness [live-blocked], delivery/RTO, WhatsApp automation [blocked], Vapi/AI calling [blocked], Claim Vault coverage, team roles, safety state) where provider live-gate gates render **blocked** as the EXPECTED safe state; a **"Run internal dry-run" form** (name + scenario select [`fresh_lead`/`imported_campaign`/`existing_order`/`payment_logistics`/`full_lifecycle`] + button — the ONLY action on the page); a blocked-live-actions list; a Director sign-off checklist; and a recent-dry-runs table. **No live action button anywhere.** The dry-run hits only the internal `/api/v1/pilot/` endpoints (DB-only); each stored run carries `providerActionsBlocked=true`. Loading / error / empty states render; responsive, no horizontal overflow. **Browser-verified on the VPS:** `/operations/pilot-readiness` opened with the title **Controlled Internal Pilot Readiness**; safety shell visible + unchanged (AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked); gate matrix showed Lead/Customer data **PASS**, Calling outcome flow **PASS**, Order creation **PASS**, Confirmation flow **PASS**, Payment readiness **BLOCKED**, Shipment readiness **BLOCKED**, Vapi/AI calling **BLOCKED**, Safety state **PASS**; an internal dry-run ran (toast **"Internal dry-run recorded: blocked."**) and the recent-dry-runs list updated to **1 dry-run saved with status BLOCKED** (correct — live provider actions remain locked); the blocked-live-actions panel + Director sign-off checklist were visible; **no live WhatsApp / payment / courier / Vapi / AI-provider side effect was triggered.** An observed gate-matrix warning — **"WhatsApp live automation blocked — WARNING"** / "WhatsApp automation appears enabled — review before pilot." — is a risk to review before any future pilot, NOT a blocker (live provider actions are locked behind a future Director live gate). The Phase 16E page is below.
>
> **Phase 16E UI (PRODUCTION VERIFIED on the VPS; commit `36395f6`).** New page **`/operations/payment-logistics`** (sidebar "Operations", Wallet icon): a no-side-effect safety banner ("Hardening mode only — does NOT create live payment links, capture/refund, or book Delhivery shipments…"); safety chips (AI Paused / Sandbox OFF / live provider actions Locked / Phase 16E hardening); payment readiness cards for **Razorpay** + **PayU** and a logistics card for **Delhivery** (each showing mode / status pill / configured / live-gate / blocked reasons / safe actions); order-workflow gate rows (payment gate, shipment gate — both live-blocked); a recent-internal-events section; and **no live action button** ("Live actions disabled — Director live gate required."). Browser-validated on the VPS: the page loaded in hardening mode showing Razorpay blocked / PayU unavailable / Delhivery ready/mock, payment + shipment gates live-blocked, recent events visible; no live provider action triggered. Loading / error / empty states render; responsive, no horizontal overflow; secrets never shown (presence only). The Phase 16D pages are below.
>
> **Phase 16D UI (PRODUCTION VERIFIED on the VPS, after Hotfix-1; commit `c0be74a`).** Browser-validated: Data Imports loads at `/operations/data-imports`; Imported Campaigns loads at `/operations/imported-campaigns`; CSV upload + validation works; duplicate existing-phone rows flagged + NOT created; a 10-valid-contact dataset → campaign → queue → outcome recording → "Create order" all work; internal Order `NRG-8949879991` from Aarav Sharma appears under Order Punched; no WhatsApp / payment / courier / Vapi / AI-provider action triggered; safety shell unchanged (AI Paused / Sandbox OFF / Sync Live). Two pages were added on top of the Phase 16C baseline:
>
> - **`/operations/data-imports`** (sidebar "Operations", icon Upload) — KPI cards (datasets / valid contacts / duplicates / invalid / active campaigns / pending calls / interested rate / orders created), a CSV upload card (name + problem + source + file `<input type=file>` / textarea), a validation summary (total / valid / duplicate / invalid + problem breakdown + masked rejected-row samples), and a datasets table with a per-row "Create campaign" action. Safety-copy banner. Loading / empty states render; responsive, no horizontal overflow.
> - **`/operations/import-campaigns`** (sidebar "Operations", icon Megaphone) — campaign list table with KPIs (contacts / pending / interested / orders), an "Open queue" action, and a per-campaign call-queue table (S.N. / contact / masked phone / status / attempts / per-row outcome `<select>` / Record button + a "Create order" button shown only for `interested` items). Escalation flags (medical emergency / senior review) render as inline warnings. Safety-copy banner. Empty states render cleanly.
>
> **Both Phase 16D pages are internal-only and trigger NO Vapi/AI/WhatsApp/payment/courier provider call** — recording an outcome or creating an order hits only the internal `/api/v1/imports/` endpoints; phones are rendered masked. The earlier Phase 16C surfaces are below. Browser-verified on the VPS at Phase 16C (`687ef41`): the sidebar shows **Director Daily Briefing**; `/director-briefing` opens with the review-only safety copy, the latest briefing status (STALE / source / health score / tier / age), business readiness, decision checklist, and pending blockers; "Record Director decision" works (toast "Director review recorded (internal only).") and the saved review persists ("Last review: REVIEWED — …"); `/team-roles` opens with the members list + role dropdown; the safety shell is unchanged (AI Paused / Sandbox OFF / Sync Live) with no provider/live side effects. Two new pages were added on top of the Phase 16B baseline:
>
> - **`/director-briefing`** (sidebar "AI Layer", icon NotebookPen) — read-only latest-briefing status pill (`fresh`/`stale`/`missing`/`unavailable`), business-readiness summary, decision checklist, pending blockers/risks, a safety-copy banner ("Review-only: no WhatsApp / payment / courier / calling / AI provider action…"), a clean empty state when no snapshot exists, and an internal-only "Record decision" panel (note + decision-status select + Save). Loading / empty / error states all render; responsive grid, no horizontal overflow.
> - **`/team-roles`** (sidebar "System", icon UsersRound) — a members table (S.N. / user + masked email / account role / active status / per-row operational-role `<select>` / Save). Save is disabled until the role changes; empty state renders cleanly. Assignment is director/admin-gated server-side. No PII beyond masked email; responsive (`overflow-x-auto` table wrapper).
>
> **Both pages are internal-only and trigger NO provider / WhatsApp / payment / courier / Vapi / AI call.** The Phase 16B browser-verified surfaces (Leads CRM phone-only duplicate UX + `S.N.` column, Customer 360 hydrated tabs, Orders Pipeline responsive wrapped layout) are unchanged. The Phase 15 safety shell remains **frozen** at code commit `eefd8b3` and untouched. Use [`nd.md`](../nd.md) head-of-file for current truth. The "Historical frontend audit snapshot" below is preserved as the Phase 12D-era reference; any "current" wording inside it is historical, not current. (This is the Phase 16D sub-block — Phase 16E has since shipped + been production-verified and Phase 16F has shipped + been pushed; see the current UI baseline at the top of this file.) Next planned work: Phase 16G (separate Director directive required).

## Historical frontend audit snapshot

**Phase 12D baseline.** `/saas-admin` rendered the Phase 6 →
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

## Phase 9-10 Frontend Additions (historical — Phase 12D baseline)

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

Current total: **27 pages** after the Phase 10A page lands.

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

### Phase 12D — no frontend change

Phase 12D fixed only the backend `template_params` dict in
`apps.diagnostics.payment_reminder_service.build_payment_reminder_attempt`
to match the live Meta-approved `nrg_payment_reminder` template
schema (`{{1}} {{2}}` body, `variables_schema.order = ["customer_name",
"context"]`). No TypeScript types or pages changed; the existing
Phase 7E-Live-B gate-row consumer renders the corrected
`template_params` shape verbatim.
