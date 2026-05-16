# Runbook — Nirogidhara AI Command Center

> **This file is the LOCAL DEVELOPMENT runbook.** Production is live at
> <https://ai.nirogidhara.com> from `/opt/nirogidhara-command` on a
> Hostinger VPS — see [`docs/DEPLOYMENT_VPS.md`](DEPLOYMENT_VPS.md) and
> [`nd.md`](../nd.md) §17 for the production runbook (URL, containers,
> SSL, commands, troubleshooting). Do not run the local-dev steps below
> on the VPS.

How to bring the full stack up locally on Windows / macOS / Linux.

## Prerequisites

- **Node** 18+ (frontend) — verify with `node --version`
- **Python** 3.10+ (backend) — verify with `python --version`
- Git

## One-time setup

```bash
git clone <repo-url> nirogidhara-command
cd nirogidhara-command

# Backend
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env       # cp on macOS/Linux
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py createsuperuser   # optional, for /admin/

# Frontend
cd ..\frontend
npm install
copy .env.example .env       # cp on macOS/Linux
```

## Daily dev loop

Open two terminals.

**Terminal 1 (backend):**
```bash
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py runserver 0.0.0.0:8000
```

**Terminal 2 (frontend):**
```bash
cd frontend
npm run dev
```

Open [http://localhost:8080](http://localhost:8080).

## Verifying the wiring

```bash
# Backend healthcheck
curl http://localhost:8000/api/healthz/
curl http://localhost:8000/api/leads/ | head -c 400

# Frontend dev server (in browser)
# - Open http://localhost:8080
# - Open the Network tab — every page request should hit /api/...
# - Stop the backend → frontend keeps rendering via mock fallback
```

## Tests

```bash
# Backend
cd backend
python -m pytest -q                     # Phase 1 -> 7B inclusive (1540 tests)
python manage.py makemigrations --check --dry-run    # must report "No changes detected"
python manage.py check                  # must report "0 issues"

# Frontend
cd ../frontend
npm test                                # Phase 1 -> 7B vitest tests (64 tests)
npm run lint                            # 0 errors, ~8 pre-existing shadcn warnings
npm run build                           # Production build
```

> Working agreement: every meaningful change must keep the full
> verification suite green. `makemigrations --check --dry-run` MUST be
> clean — Phase 5E-Hotfix added `RenameIndex` migrations specifically
> because index-name drift was caught only at deploy time.

## Phase 6H runtime live audit gate diagnostics

Phase 6G Controlled Runtime Routing Dry Run is **FULL PASS**. Phase 6H
adds the live audit gate only: runtime providers still use env/config,
dry-run remains the default, the global runtime kill switch defaults
enabled, and approval in Phase 6H does not execute external calls. Do not
send WhatsApp messages, create payment links/orders, create shipments,
place calls, or call provider side-effect endpoints from this phase.

```bash
cd backend
python manage.py ensure_default_organization --json
python manage.py inspect_saas_admin_readiness --json
python manage.py inspect_controlled_runtime_routing_dry_run --operation all --include-ai --json
python manage.py inspect_runtime_live_audit_gate --json
python manage.py preview_live_gate_decision --operation whatsapp.send_text --json
python manage.py preview_live_gate_decision --operation razorpay.create_order --live-requested --json
```

Expected Phase 6H posture: `runtimeSource=env_config`,
`perOrgRuntimeEnabled=false`, `dryRun=true`,
`defaultLiveExecutionAllowed=false`, `externalCallWillBeMade=false`,
global kill switch enabled, and
`nextAction=ready_for_phase_6i_single_internal_live_gate_simulation` only
when missing-provider warnings are understood and all live execution stays
blocked. `/saas-admin` should show **Controlled Runtime Live Audit Gate**
with the warning: "Approving in Phase 6H does not execute external calls."

## Phase 6I single internal live-gate simulation diagnostics

Phase 6I is simulation-only. It prepares, requests, approves, runs, and
rolls back a single internal live-gate rehearsal without external side
effects. Allowed operations are `razorpay.create_order` (default),
`whatsapp.send_text`, and `ai.smoke_test`.

```bash
cd backend
python manage.py prepare_single_internal_live_gate_simulation --operation razorpay.create_order --json
python manage.py inspect_single_internal_live_gate_simulation --json
```

Optional lifecycle rehearsal, still without provider calls:

```bash
python manage.py request_single_internal_live_gate_approval --simulation-id <id> --reason "internal rehearsal" --json
python manage.py approve_single_internal_live_gate_simulation --simulation-id <id> --reason "approved for simulation only" --json
python manage.py run_single_internal_live_gate_simulation --simulation-id <id> --reason "run simulation only" --json
python manage.py rollback_single_internal_live_gate_simulation --simulation-id <id> --reason "close rehearsal" --json
```

Expected Phase 6I posture in every CLI/API/UI response:
`dryRun=true`, `liveExecutionAllowed=false`,
`externalCallWillBeMade=false`, `externalCallWasMade=false`,
`providerCallAttempted=false`, global kill switch active, no raw secrets,
no full phone numbers, and no real customer data. `/saas-admin` should show
**Single Internal Live Gate Simulation** with no send/payment/shipment/call
or provider-execution controls.

## Phase 6J single internal provider test plan diagnostics

Phase 6J is **plan-only**. It records a paper trail for a future Razorpay
test-mode call without ever calling Razorpay. The synthetic payload is
locked: `{amount: 100, currency: "INR", receipt: "phase6j_internal_test_plan_<plan_id>"}`.

```bash
cd backend
python manage.py inspect_single_provider_test_plan --json
python manage.py prepare_single_provider_test_plan --provider razorpay --operation create_order --json
python manage.py validate_single_provider_test_plan --plan-id <id> --json
python manage.py approve_single_provider_test_plan --plan-id <id> --reason "internal rehearsal" --json
python manage.py reject_single_provider_test_plan --plan-id <id> --reason "blocker" --json
python manage.py archive_single_provider_test_plan --plan-id <id> --reason "close" --json
```

Expected posture: every plan response keeps `dry_run=true`,
`provider_call_allowed=false`, `external_call_will_be_made=false`,
`external_call_was_made=false`, `provider_call_attempted=false`,
`real_money=false`, `real_customer_data_allowed=false`. Approval ONLY
unlocks a future Phase 6K execution gate; it never authorises a provider
call in Phase 6J. `/saas-admin` shows **Single Internal Provider Test
Plan** with safety-invariant + Razorpay env-readiness sub-cards. **No
"Execute Razorpay" / "Create Order" / "Create Payment Link" buttons exist
on the UI.**

## Phase 6K-A single internal Razorpay test-mode execution gate (code/gate/readiness only)

Phase 6K-A ships the gate. It does **not** execute against Razorpay until
a separate, explicit one-shot CLI run with the env flag flipped. The
defaults stay safe: `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=false`,
amount locked to 100 paise, real-money locked false, real-customer-data
locked false, max one execution per approved plan.

```bash
cd backend
python manage.py inspect_single_provider_execution_gate --json
python manage.py prepare_single_provider_execution_attempt --plan-id <approved-plan-id> --json
# the next two commands DO touch Razorpay test infra — see Phase 6K-B
# python manage.py execute_single_razorpay_test_order --attempt-id <id> --confirm-test-execution --json
# python manage.py rollback_single_provider_execution_attempt --attempt-id <id> --json
python manage.py archive_single_provider_execution_attempt --attempt-id <id> --reason "close" --json
```

Expected posture for read-only diagnostics: `business_mutation_was_made=false`,
`payment_link_created=false`, `payment_captured=false`,
`customer_notification_sent=false`, no raw secrets in any output,
`provider_object_id=""` until execution. `/saas-admin` shows **Single
Internal Razorpay Test-Mode Execution Gate** with readiness +
invariants sub-cards + attempts table. **No "Execute Razorpay" / "Capture"
/ "Go Live" / "Send" buttons on the UI** — execution is exclusively CLI.

## Phase 6K-B verification of the immutable artefact

Phase 6K-B is the one-shot real Razorpay test-mode execution that already
ran on the VPS. The artefact is `pex_8f309650e9644cfaae4418f9` →
`order_Sks3KPf0vntKhf`, ₹1.00, rolled back. Re-verify any time without
calling Razorpay:

```bash
cd backend
python manage.py inspect_single_provider_execution_gate --json
python manage.py inspect_razorpay_webhook_handler_readiness --json
```

Or audit-replay the artefact end-to-end:

```bash
python manage.py inspect_razorpay_test_execution_audit --execution-id pex_8f309650e9644cfaae4418f9 --json
```

Expected: `passed=true`, every Phase 6K invariant green, no leaked secret
in any linked AuditEvent, `rollback_status=completed`, `business_mutation_was_made=false`.

## Phase 6L Razorpay audit review + webhook readiness diagnostics

Phase 6L is read-only / planning-only. It never calls Razorpay, never
creates a payment link, never captures, and never returns the raw Razorpay
response (whitelisted summary only).

```bash
cd backend
python manage.py inspect_razorpay_test_execution_audit --execution-id <execution_id> --json
python manage.py inspect_razorpay_webhook_readiness --json
python manage.py plan_razorpay_webhook_readiness --json
```

`/saas-admin` shows **Razorpay Test Execution Audit + Webhook Readiness**
with audit-invariants / readiness / webhook-plan cards (allowlist +
denylist tables). Webhook plan output documents the future
`POST /api/webhooks/razorpay/test/` design (HMAC-SHA256, constant-time
compare, `x_razorpay_event_id` idempotency, 300-second replay window).

## Phase 6M-0 MCP Gateway readiness diagnostics

Phase 6M-0 is the dormant MCP scaffolding. **Do not flip any `MCP_*` env
flag** — `MCP_ENABLED=false`, `MCP_READ_ONLY_MODE=true`,
`MCP_WRITE_TOOLS_ENABLED=false`, `MCP_PROVIDER_TOOLS_ENABLED=false` are
the locked defaults.

```bash
cd backend
python manage.py inspect_mcp_gateway_readiness --json
python manage.py seed_mcp_gateway_registry --json   # idempotent; emits mcp.registry.seeded
python manage.py inspect_mcp_tool_invocations --hours 24 --json   # expect zero invocations
```

`/saas-admin` shows **MCP Gateway Readiness** as dormant. The 13-name
forbidden-tool list is asserted by tests; PII / raw-secret detectors
(`detect_raw_secret`, `detect_full_pii` with `\b\d{10,}\b` word-boundary
match) keep ISO timestamps from being mis-flagged.

## Phase 6M Razorpay webhook handler diagnostics (test-mode, dormant)

Phase 6M wires `POST /api/webhooks/razorpay/test/` but keeps it dormant by
default (`RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false`). Production webhook
secret is **never** consumed by this handler. **Do not** flip
`RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED` or
`RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED` — Phase 6M ships the handler
alone; business mutation is Phase 6N planning territory.

```bash
cd backend
python manage.py inspect_razorpay_webhook_handler_readiness --json
python manage.py simulate_razorpay_webhook_event --event-type payment.captured --dry-run --json
python manage.py inspect_razorpay_webhook_events --hours 24 --json
python manage.py purge_razorpay_webhook_test_events --older-than-days 30 --dry-run --json
```

Expected posture in every response:
`razorpay_webhook_handler_dormant=true` (when the env flag is off),
`business_mutation_was_made=false`, `customer_notification_sent=false`,
`raw_secret_exposed=false`, `full_pii_exposed=false`. The webhook
handler asserts `assert_no_business_mutation` in tests — Order /
Payment / Shipment / DiscountOfferLog / Customer rows are never touched
by Phase 6M code paths.

`/saas-admin` shows **Razorpay Webhook Handler (Test Mode)** with the
event list (masked summary only) and the readiness card. **No "Replay"
/ "Apply mutation" / "Go Live" buttons on the UI.**

## Phase 6S Razorpay limited internal dispatch pilot plan diagnostics

Phase 6S is **planning-only and CLI-only** for review state changes.
Review state changes write to `RazorpayPaymentDispatchPilotPlan` only —
they NEVER execute a pilot, NEVER send a WhatsApp message, NEVER call
Meta Cloud / Delhivery / Razorpay, NEVER create a shipment / AWB,
NEVER touch real `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer` / `Lead` rows. **There is no API
endpoint or frontend button that dispatches Phase 6S approval.**

```bash
cd backend
# Read-only diagnostics first.
python manage.py inspect_razorpay_payment_dispatch_pilot_plan_readiness --json
python manage.py inspect_razorpay_payment_dispatch_pilot_plans --json
python manage.py preview_razorpay_payment_dispatch_pilot_plan --readiness-id <PHASE_6R_READINESS_ID> --json

# CLI-only review lifecycle. ``prepare``/``approve``/``reject``/``archive`` write
# to RazorpayPaymentDispatchPilotPlan only. Approve requires --reason.
python manage.py prepare_razorpay_payment_dispatch_pilot_plan --readiness-id <PHASE_6R_READINESS_ID> --json
python manage.py approve_razorpay_payment_dispatch_pilot_plan --plan-id <PLAN_ID> --reason "Director sign-off for Phase 6S internal pilot plan" --json
python manage.py reject_razorpay_payment_dispatch_pilot_plan --plan-id <PLAN_ID> --reason "Not yet" --json
python manage.py archive_razorpay_payment_dispatch_pilot_plan --plan-id <PLAN_ID> --reason "Close" --json
```

Expected posture: `phase=6S`, `status=pilot_planning_only`,
`razorpayPaymentDispatchPilotPlanEnabled=false`,
`pilotExecutionEnabled=false`, `businessMutationEnabled=false`,
`customerNotificationEnabled=false`, `providerCallAttempted=false`,
`frontendCanExecute=false`, `apiEndpointCanExecute=false`,
`apiEndpointCanApprove=false`, `executionPath="cli_only"`,
`maxPilotOrders=1`, `maxSafeAmountPaise=100`. `safeToStartPhase6T=true`
only after at least one Phase 6S pilot plan has been approved via the
CLI.

`/saas-admin` shows **Razorpay Limited Internal Dispatch Pilot Plan**
with the readiness grid, 9-row pilot contract table (every "Pilot in
6S" / "Send in 6S" / "Courier in 6S" cell `No`), recent pilot plans
table (read-only — no buttons), four readiness checklists (internal
staff cohort / WhatsApp / courier / dispatch), abort criteria,
verification checklist, forbidden-action chips, and a "Pilot plan
only" banner. **No "Start Pilot" / "Run Pilot" / "Execute Pilot" /
"Send WhatsApp" / "Queue WhatsApp" / "Notify Customer" / "Create
Shipment" / "Create AWB" / "Book Courier" / "Dispatch Order" / "Call
Delhivery" / "Call Meta" / "Mark Paid" / "Capture Payment" / "Refund"
/ "Apply Mutation" / "Mutate Order" / "Create Payment Link" /
"Execute Webhook" / "Replay Event" / "Enable Mutation" / "Go Live" /
"Run MCP Tool" / "Execute Workflow" / "Apply Order Update" / "Confirm
Paid Order" / "Start Live Workflow" / "Approve Pilot Plan" / "Reject
Pilot Plan" buttons exist anywhere.**

## Phase 7B Razorpay controlled pilot execution gate diagnostics

Phase 7B is **gate-only and CLI-only** for review state changes. The
service writes to `RazorpayControlledPilotExecutionGate` +
`RazorpayControlledPilotGateDryRunRecord` +
`RazorpayControlledPilotGateRollbackDryRunRecord` only - it NEVER
executes a pilot, NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi,
NEVER sends or queues a WhatsApp message, NEVER creates a shipment /
AWB, NEVER mutates real `Order` / `Payment` / `Customer` / `Lead`. Phase
7B does **not** validate the live `RAZORPAY_KEY_ID`; provider-execution
key validation belongs to Phase 7C+. **There is no API endpoint or
frontend button that dispatches Phase 7B review state changes, and there
is no `execute_*` command anywhere in the Phase 7B surface.**

```bash
cd backend
# Read-only diagnostics first.
python manage.py inspect_razorpay_controlled_pilot_gate_readiness --json
python manage.py inspect_razorpay_controlled_pilot_gates --limit 25 --json
python manage.py preview_razorpay_controlled_pilot_gate \
    --phase6t-lock-id <PHASE_6T_LOCK_ID> --json

# CLI-only review lifecycle. ``prepare`` / ``dry_run`` /
# ``rollback_dry_run`` / ``approve`` / ``reject`` / ``archive`` write
# to Phase 7B tables only. Approve requires --reason AND
# dry_run_passed=true AND rollback_dry_run_passed=true.
python manage.py prepare_razorpay_controlled_pilot_gate \
    --phase6t-lock-id <PHASE_6T_LOCK_ID> --json
python manage.py dry_run_razorpay_controlled_pilot_gate \
    --gate-id <GATE_ID> --json
python manage.py rollback_dry_run_razorpay_controlled_pilot_gate \
    --gate-id <GATE_ID> --reason "Pre-execution rehearsal" --json
python manage.py approve_razorpay_controlled_pilot_gate \
    --gate-id <GATE_ID> \
    --reason "Director sign-off for future Phase 7C review" --json
python manage.py reject_razorpay_controlled_pilot_gate \
    --gate-id <GATE_ID> --reason "Not yet" --json
python manage.py archive_razorpay_controlled_pilot_gate \
    --gate-id <GATE_ID> --reason "Close" --json
```

Expected posture: `phase=7B`, `status=controlled_pilot_gate_only`,
`phase7ControlledPilotGateEnabled=false` on production,
`phase7BMakesProviderCall=false`,
`phase7BSendsOrQueuesWhatsApp=false`,
`phase7BCreatesShipmentOrAwb=false`,
`phase7BMutatesBusinessRow=false`, `phase7BCallsRazorpay=false`,
`phase7BValidatesLiveRazorpayKey=false`, `frontendCanExecute=false`,
`apiEndpointCanExecute=false`, `apiEndpointCanApprove=false`,
`executionPath="cli_only_review"`, `maxPilotOrders=1`,
`maxSafeAmountPaise=100`. `safeToStartPhase7CExecutionReviewFlow=true`
only after at least one Phase 7B gate has been approved via CLI -
**this status name is gate-readiness, not Phase 7C approval**.

## Phase 6T Razorpay final Phase 6 audit lock diagnostics

Phase 6T is **final-audit-lock-only and CLI-only** for review state
changes. It composes Phase 6N -> 6S into a final attestation record and
does not approve or execute a live pilot.

Safe default:

```bash
RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=false
```

Read-only inspection:

```bash
cd backend
python manage.py inspect_razorpay_phase6_final_audit_lock_readiness --json
python manage.py preview_razorpay_phase6_final_audit_lock --plan-id <PHASE6S_PLAN_ID> --json
python manage.py inspect_razorpay_phase6_final_audit_locks --json
```

CLI-only review state changes (only when the flag is explicitly enabled
for the controlled review window):

```bash
python manage.py prepare_razorpay_phase6_final_audit_lock --plan-id <PHASE6S_PLAN_ID> --json
python manage.py lock_razorpay_phase6_final_audit_lock --audit-lock-id <ID> --reason "Director reviewed Phase 6 final audit chain" --json
python manage.py reject_razorpay_phase6_final_audit_lock --audit-lock-id <ID> --reason "..." --json
python manage.py archive_razorpay_phase6_final_audit_lock --audit-lock-id <ID> --reason "..." --json
```

Expected posture: `phase=6T`, `status=final_audit_lock_only`,
`futureControlledPilotAllowedByPhase6T=false`,
`controlledPilotExecutionAllowedInPhase6T=false`,
`safeToStartPhase7A=false`. No API endpoint or frontend button prepares,
locks, rejects, archives, or executes anything. Phase 6T never sends or
queues WhatsApp, never calls Meta Cloud / Delhivery / Razorpay, never
creates shipment / AWB rows, and never mutates real business tables.

## Phase 6R Razorpay payment → WhatsApp / courier dispatch readiness diagnostics

Phase 6R is **audit-only readiness contract and CLI-only** for review
state changes. Review state changes write to
`RazorpayPaymentDispatchReadinessGate` only — they NEVER send a
WhatsApp message, NEVER call Meta Cloud / Delhivery, NEVER create a
shipment / AWB, NEVER touch real `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer` / `Lead` rows, NEVER call Razorpay.
**There is no API endpoint or frontend button that dispatches Phase
6R approval.**

```bash
cd backend
# Read-only diagnostics first.
python manage.py inspect_razorpay_payment_dispatch_readiness --json
python manage.py inspect_razorpay_payment_dispatch_readiness_gates --json
python manage.py preview_razorpay_payment_dispatch_readiness_gate --gate-id <PHASE_6Q_GATE_ID> --json

# CLI-only review lifecycle. ``prepare``/``approve``/``reject``/``archive`` write
# to RazorpayPaymentDispatchReadinessGate only. Approve requires --reason.
python manage.py prepare_razorpay_payment_dispatch_readiness_gate --gate-id <PHASE_6Q_GATE_ID> --json
python manage.py approve_razorpay_payment_dispatch_readiness_gate --readiness-id <READINESS_ID> --reason "Director sign-off for Phase 6R readiness" --json
python manage.py reject_razorpay_payment_dispatch_readiness_gate --readiness-id <READINESS_ID> --reason "Not yet" --json
python manage.py archive_razorpay_payment_dispatch_readiness_gate --readiness-id <READINESS_ID> --reason "Close" --json
```

Expected posture: `phase=6R`, `status=dispatch_readiness_only`,
`razorpayPaymentDispatchReadinessEnabled=false`,
`businessMutationEnabled=false`,
`customerNotificationEnabled=false`, `providerCallAttempted=false`,
`frontendCanExecute=false`, `apiEndpointCanExecute=false`,
`apiEndpointCanApprove=false`, `executionPath="cli_only"`.
`safeToStartPhase6S=true` only after at least one Phase 6R readiness
review has been approved via the CLI.

`/saas-admin` shows **Razorpay Payment → WhatsApp / Courier
Dispatch Readiness** with the readiness grid, 9-row dispatch
readiness contract table (every "Send allowed in 6R" / "Courier in
6R" cell `No`), recent readiness gates table (read-only — no
buttons), three readiness checklists (WhatsApp / courier /
dispatch), forbidden-action chips, and a "Readiness contract only"
banner. **No "Send WhatsApp" / "Queue WhatsApp" / "Create Shipment"
/ "Create AWB" / "Book Courier" / "Dispatch Order" / "Notify
Customer" / "Mark Paid" / "Capture Payment" / "Refund" / "Apply
Mutation" / "Mutate Order" / "Create Payment Link" / "Execute
Webhook" / "Replay Event" / "Enable Mutation" / "Go Live" / "Run
MCP Tool" / "Execute Workflow" / "Apply Order Update" / "Confirm
Paid Order" / "Start Live Workflow" / "Approve Readiness" / "Reject
Readiness" buttons exist anywhere.**

## Phase 6Q Razorpay payment → order workflow safety gate diagnostics

Phase 6Q is **audit-gate-only and CLI-only** for review state
changes. Gate state changes write to
`RazorpayPaymentOrderWorkflowGate` only — they NEVER touch real
`Order` / `Payment` / `Shipment` / `DiscountOfferLog` / `Customer` /
`Lead` rows. **There is no API endpoint or frontend button that
dispatches Phase 6Q approval.**

```bash
cd backend
# Read-only diagnostics first.
python manage.py inspect_razorpay_payment_order_workflow_gate_readiness --json
python manage.py inspect_razorpay_payment_order_workflow_gates --json
python manage.py preview_razorpay_payment_order_workflow_gate --attempt-id <PHASE_6P_ATTEMPT_ID> --json

# CLI-only review lifecycle. ``prepare``/``approve``/``reject``/``archive`` write
# to RazorpayPaymentOrderWorkflowGate only. Approve requires --reason.
python manage.py prepare_razorpay_payment_order_workflow_gate --attempt-id <PHASE_6P_ATTEMPT_ID> --json
python manage.py approve_razorpay_payment_order_workflow_gate --gate-id <GATE_ID> --reason "Director sign-off for sandbox proof" --json
python manage.py reject_razorpay_payment_order_workflow_gate --gate-id <GATE_ID> --reason "Not yet" --json
python manage.py archive_razorpay_payment_order_workflow_gate --gate-id <GATE_ID> --reason "Close" --json
```

Expected posture: `phase=6Q`, `status=audit_gate_only`,
`razorpayPaymentOrderWorkflowGateEnabled=false`,
`businessMutationEnabled=false`,
`customerNotificationEnabled=false`, `providerCallAttempted=false`,
`frontendCanExecute=false`, `apiEndpointCanExecute=false`,
`apiEndpointCanApprove=false`, `executionPath="cli_only"`.
`safeToStartPhase6R=true` only after at least one gate has been
approved via the CLI.

`/saas-admin` shows **Razorpay Payment → Order Workflow Safety
Gate** with the readiness grid, 9-row Payment → Order workflow
contract table (every cell "Disabled" for real mutation), gate
review records table (read-only — no buttons), CLI-only reminder
list, and forbidden-action chips. **No "Mark Paid" / "Capture
Payment" / "Refund" / "Apply Payment" / "Apply Mutation" / "Mutate
Order" / "Send WhatsApp" / "Create Payment Link" / "Execute
Webhook" / "Replay Event" / "Enable Mutation" / "Go Live" / "Run
MCP Tool" / "Execute Workflow" / "Apply Order Update" / "Confirm
Paid Order" / "Start Live Workflow" buttons exist anywhere.**

## Phase 6P Razorpay sandbox paid-status mutation test diagnostics

Phase 6P is **sandbox-ledger-only, CLI-only execution**. Mutation
paths write to `RazorpaySandboxPaidStatusLedger` +
`RazorpaySandboxPaidStatusMutationAttempt` only — they NEVER touch
real `Order` / `Payment` / `Shipment` / `DiscountOfferLog` /
`Customer` / `Lead` rows. **There is no API endpoint or frontend
button that dispatches Phase 6P mutation.**

```bash
cd backend
# Read-only diagnostics first.
python manage.py inspect_razorpay_sandbox_paid_status_mutation_readiness --json
python manage.py inspect_razorpay_sandbox_paid_status_mutation_attempts --json
# Per-review preview (no rows created).
python manage.py preview_razorpay_sandbox_paid_status_mutation --review-id <APPROVED_PHASE_6O_REVIEW_ID> --json

# CLI-only mutation lifecycle. ``prepare`` is safe; ``execute`` and
# ``rollback`` write to the Phase 6P sandbox ledger only.
python manage.py prepare_razorpay_sandbox_paid_status_mutation --review-id <APPROVED_PHASE_6O_REVIEW_ID> --json
python manage.py execute_razorpay_sandbox_paid_status_mutation \
    --review-id <APPROVED_PHASE_6O_REVIEW_ID> \
    --confirm-sandbox-paid-status-mutation \
    --director-signoff "Director PS - sandbox rehearsal" --json
python manage.py rollback_razorpay_sandbox_paid_status_mutation \
    --attempt-id <ATTEMPT_ID> \
    --confirm-sandbox-rollback \
    --reason "rehearsal complete" --json
python manage.py archive_razorpay_sandbox_paid_status_mutation_attempt \
    --attempt-id <ATTEMPT_ID> --reason "close rehearsal" --json
```

Expected posture for the readiness command (default state on a clean
VPS): `phase=6P`, `status=sandbox_ledger_only`,
`razorpaySandboxPaidStatusMutationEnabled=false`,
`businessMutationEnabled=false`, `customerNotificationEnabled=false`,
`providerCallAttempted=false`, `frontendCanExecute=false`,
`apiEndpointCanExecute=false`, `executionPath="cli_only"`,
`mutationAllowedInPhase6O=false` propagated through the mapping rows.
`safeToStartPhase6Q=true` only after at least one Phase 6P attempt
has been executed AND rolled back via the CLIs above.

`/saas-admin` shows **Razorpay Sandbox Paid-Status Mutation Test**
with the readiness grid, 9-row event-to-ledger mapping table,
attempts table, CLI-only reminder, and forbidden-action chips. **No
"Mark Paid" / "Capture Payment" / "Refund" / "Apply Payment" /
"Apply Mutation" / "Mutate Order" / "Send WhatsApp" / "Create
Payment Link" / "Execute Webhook" / "Replay Event" / "Enable
Mutation" / "Go Live" / "Run MCP Tool" buttons exist anywhere.**

## Phase 6O Razorpay sandbox status mapping + manual review diagnostics

Phase 6O is **sandbox-review-only**. It maps verified Phase 6M
`RazorpayWebhookEvent` rows into proposed sandbox status reviews.
**It never mutates `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer`, never sends a customer notification,
never calls Razorpay, never flips an env flag.** Approving a review
flips its `status` to `approved_for_future_phase6p` only — Phase 6P
will own the actual sandbox `Order.status` / `Payment.status` flip.

```bash
cd backend
python manage.py inspect_razorpay_sandbox_status_mapping_readiness --json
python manage.py preview_razorpay_sandbox_status_mapping --event-id <RAZORPAY_WEBHOOK_EVENT_PK> --json
# The next four commands change RazorpaySandboxStatusReview state only;
# they NEVER touch business tables. ``prepare`` requires
# RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=true AND a synthetic-eligible event.
python manage.py prepare_razorpay_sandbox_status_review --event-id <RAZORPAY_WEBHOOK_EVENT_PK> --json
python manage.py approve_razorpay_sandbox_status_review --review-id <ID> --reason "ok" --json
python manage.py reject_razorpay_sandbox_status_review --review-id <ID> --reason "not synthetic" --json
python manage.py archive_razorpay_sandbox_status_review --review-id <ID> --reason "close" --json
```

Expected posture for the readiness command:
`phase=6O`, `status=sandbox_review_only`,
`businessMutationEnabled=false`, `customerNotificationEnabled=false`,
`providerCallAttempted=false`,
`razorpaySandboxStatusMappingEnabled=false` (default),
`mutationAllowedInPhase6O=false` on every event-mapping row,
`reviewCounts.businessMutationWasMade=0`,
`reviewCounts.customerNotificationSent=0`,
`reviewCounts.providerCallAttempted=0`. `safeToStartPhase6P=true`
only after at least one review row has `status=approved_for_future_phase6p`.

`/saas-admin` shows **Razorpay Sandbox Status Mapping + Manual Review**
with the readiness grid, 9-row event-to-status mapping table, reviews
table (with per-row "Approve Review Only" / "Reject Review" /
"Archive Review" buttons), manual review checklist, and forbidden-action
chips. **No "Mark Paid" / "Capture Payment" / "Refund" / "Send WhatsApp"
/ "Apply Mutation" / "Mutate Order" / "Execute Webhook" / "Replay Event"
/ "Enable Mutation" / "Go Live" / "Run MCP Tool" buttons exist
anywhere.**

## Phase 6N Razorpay business-mutation sandbox plan diagnostics

Phase 6N is **planning-only**. It defines the policy, eligibility,
manual-review checklist, rollback plan, safety invariants, and audit
plan for a future Phase 6O sandbox-only mutation path against synthetic
test orders. **It never calls Razorpay, never mutates any business
record, never sends a customer notification, and never flips an env
flag.**

```bash
cd backend
python manage.py inspect_razorpay_business_mutation_sandbox_plan --json
python manage.py inspect_razorpay_business_mutation_sandbox_readiness --json
```

Expected posture for both commands:
`businessMutationEnabled=false`, `customerNotificationEnabled=false`,
`rawPayloadStorageEnabled=false`. The readiness command returns
`safeToStartPhase6O=true` only when the Phase 6M handler flags stay
locked off, every safety counter on `RazorpayWebhookEvent` is zero
(`businessMutationCount`, `customerNotificationCount`,
`rawSecretExposureCount`, `fullPiiExposureCount`), and the plan is
complete (9-event mapping + 8-item manual review + 7-step rollback).

`/saas-admin` shows **Razorpay Business Mutation Sandbox Plan** with the
readiness grid + event-to-status mapping table + synthetic eligibility
list + manual review checklist + rollback step list + forbidden-action
chips. **No "Mark Paid" / "Capture Payment" / "Refund" / "Send WhatsApp"
/ "Mutate Order" / "Execute Webhook" / "Replay Event" / "Enable
Mutation" / "Go Live" / "Run MCP Tool" buttons exist anywhere on the
page.**

## Phase 6E SaaS admin diagnostics

Phase 6D org-aware write assignment is **FULL PASS**. Phase 6E adds safe
SaaS admin/readiness tooling and per-organization integration settings
metadata only. Runtime providers still use env/config, not DB integration
settings; raw secrets are rejected and API responses return masked secret
references only. Per-org runtime provider routing is deferred to Phase 6F.
Global tenant filtering is still not blanket-enabled, org/branch FKs remain
nullable, and WhatsApp flags remain untouched/off.

```bash
cd backend
python manage.py ensure_default_organization --json
python manage.py inspect_default_organization_coverage --json
python manage.py inspect_org_scoped_api_readiness --json
python manage.py inspect_org_write_path_readiness --json
python manage.py inspect_saas_admin_readiness --json
python manage.py inspect_org_integration_settings --json
```

Expected SaaS posture for Phase 6E: `runtimeUsesPerOrgSettings=false`,
`globalTenantFilteringEnabled=false`, `WHATSAPP_AI_AUTO_REPLY_ENABLED=false`,
campaigns/broadcast/lifecycle/call/rescue/RTO/reorder locked/off, and
`nextAction=ready_for_phase_6f_per_org_runtime_integration_routing_plan`
when coverage is clean.

## Phase 3C — Celery scheduler (optional in development)

Local development runs in **Celery eager mode** by default
(`CELERY_TASK_ALWAYS_EAGER=true`), so calling `.delay()` runs synchronously
without Redis. Tests don't need Redis. Day-to-day dev doesn't need Redis.

Spin Redis + a worker up only when you actually want the cron schedule
to fire on the wall clock:

```bash
# Terminal 1 — local Redis (root of repo)
docker compose -f docker-compose.dev.yml up -d redis

# Terminal 2 — Celery worker + beat
cd backend
celery -A config worker -B --loglevel=info
```

Beat schedule fires `apps.ai_governance.tasks.run_daily_ai_briefing_task`
at **09:00 IST** (morning) and **18:00 IST** (evening) by default. Hours
and minutes are env-driven (`AI_DAILY_BRIEFING_*`). VPS Redis is **never**
used in development — local dev only uses the Docker Redis above.

Manual trigger (no Redis required):

```bash
python manage.py run_daily_ai_briefing
python manage.py run_daily_ai_briefing --skip-caio
python manage.py run_daily_ai_briefing --skip-ceo
```

### Phase 5F-Gate Internal Allowed-Number Cohort Tooling

The single allowed test number passed every scenario in the matrix.
This phase adds tooling to safely expand the controlled live test
to a tiny internal cohort of 2–3 staff numbers — without unlocking
any broad automation.

**Procedure (do exactly this; do not paste real phone numbers in
public docs / Slack / GitHub issues).**

**A. Edit `.env.production` on the VPS.**

```bash
# /opt/nirogidhara-command/.env.production
WHATSAPP_PROVIDER=meta_cloud
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS=+918949879990,+91XXXXXXXXXX,+91YYYYYYYYYY
WHATSAPP_AI_AUTO_REPLY_ENABLED=false
WHATSAPP_CALL_HANDOFF_ENABLED=false
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false
WHATSAPP_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_REORDER_DAY20_ENABLED=false
```

**B. Recreate backend / worker / beat / nginx so the new env is read.**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never backend worker beat nginx
```

**C. Inspect the cohort (read-only; phones masked).**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_internal_cohort --json
```

Required JSON outcomes:

- `allowedListSize` matches the count of staff numbers added.
- `autoReplyEnabled=false`, every other automation flag `false`.
- `wabaSubscription.active=true`.
- For numbers already prepared: `readyForControlledTest=true`,
  `consentState="granted"`, `missingSetup=[]`.
- For new numbers (just added to env): `customerFound=false`,
  `nextAction=register_missing_customers_or_consent`.

`--show-full-numbers` is **operator-only** — surfaces full E.164 with
a "do not paste publicly" warning. Default is masked-only.

**D. Prepare each new number (creates / reuses Customer + grants
WhatsAppConsent).**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py prepare_whatsapp_internal_test_number \
    --phone +91XXXXXXXXXX \
    --name "Internal Staff Name" \
    --source internal_cohort_test \
    --json
```

Required JSON outcomes:

- `passed=true`
- `toAllowed=true`
- `consentState="granted"`
- `auditEvents` includes `whatsapp.internal_cohort.number_prepared`
- `nextAction="ready_for_controlled_scenario_test"`

The command refuses outright if the phone is not on
`WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`. The audit row carries
phone last-4 only — full E.164 NEVER appears in the audit payload.

**E. Run the controlled scenario matrix per number.**

```bash
# Scenario 1 — normal product info (Section above for outcomes).
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +91XXXXXXXXXX \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Scenario 2 — discount objection.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +91XXXXXXXXXX \
    --message "weight management product accha hai lekin thoda mehenga lag raha hai. Kuch kam ho sakta hai?" \
    --send --json

# Scenarios 3–7 (side-effect / legal / human request / unknown
# category / cure-guarantee unsafe claim) — see the matching
# RUNBOOK / DEPLOYMENT_VPS sections above for the exact messages
# and required outcomes.
```

**F. Audit + mutation safety check after each number.**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
print('DiscountOfferLog:', DiscountOfferLog.objects.count())
print('Order:', Order.objects.count())
print('Payment:', Payment.objects.count())
print('Shipment:', Shipment.objects.count())
print('---')
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.internal_cohort.').order_by('-occurred_at')[:10]:
    print(e.occurred_at, '|', e.kind, '|', e.text)
"
```

Required: `DiscountOfferLog` / `Order` / `Payment` / `Shipment`
counts unchanged from the pre-test snapshot.

### Phase 5F-Gate - Approved Customer Pilot Readiness

This is the current safe next step after the accelerated WhatsApp
auto-reply soak. It is **not** a broad rollout: auto-reply remains OFF,
limited Meta test mode stays ON, campaigns/broadcast stay locked, and
call handoff / lifecycle / rescue / RTO / reorder remain OFF.

Read-only overview:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_customer_pilot --json
```

Prepare one approved customer for pilot review. This does **not** send a
WhatsApp message and does **not** create or mutate Order / Payment /
Shipment / Discount rows. If explicit WhatsApp consent is missing, the
member stays `pending`.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py prepare_whatsapp_customer_pilot_member \
    --phone +91XXXXXXXXXX \
    --name "Customer Name" \
    --source approved_customer_pilot \
    --json
```

Pause a pilot member without messaging the customer:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py pause_whatsapp_customer_pilot_member \
    --phone +91XXXXXXXXXX \
    --reason "pilot paused by Director" \
    --json
```

Pilot readiness is also available through the admin-only read API:

```bash
curl -H "Authorization: Bearer <admin-jwt>" \
    "https://ai.nirogidhara.com/api/v1/whatsapp/monitoring/pilot/?hours=2" | jq

curl -H "Authorization: Bearer <admin-jwt>" \
    "https://ai.nirogidhara.com/api/v1/whatsapp/monitoring/overview/?hours=2" | jq
```

Healthy pilot readiness requires:

- `autoReplyEnabled=false`
- `limitedTestMode=true`
- campaign and broadcast locks active
- call handoff / lifecycle / rescue / RTO / reorder all false
- every approved pilot member has explicit WhatsApp consent
- every ready pilot phone is still in the limited-mode allow-list
- `unexpectedNonAllowedSendsCount=0`
- Order / Payment / Shipment / Discount mutation counts remain zero

The `/whatsapp-monitoring` dashboard includes the read-only "Approved
Customer Pilot Readiness" section. It shows counts, blockers,
`nextAction`, masked phones, consent state, readiness, and daily caps.
It intentionally has no send, enable, approve, pause, or automation
buttons.

### Phase 6F — Per-Org Runtime Integration Routing Plan

After Phase 6E ships the SaaS admin + integration-settings foundation,
Phase 6F adds the **read-only resolver + preview surface** for the
future per-org runtime. Live runtime stays on env / config; this phase
only tells the operator what a per-org switch would look like.

```bash
# 1. Confirm the diagnostic on the VPS.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_runtime_integration_routing \
    --json | jq '{
        runtimeUsesPerOrgSettings,
        perOrgRuntimeEnabled,
        providers: (.providers | map({
            providerType,
            integrationSettingExists,
            settingStatus,
            runtimeSource,
            secretRefsPresent,
            missingSecretRefs,
            nextAction
        })),
        safeToStartPhase6G: .global.safeToStartPhase6G,
        nextAction
    }'
# Expect: runtimeUsesPerOrgSettings=false, perOrgRuntimeEnabled=false,
#         every provider runtimeSource=env_config.

# 2. Smoke-test the API.
ADMIN_JWT=$(curl -s -X POST https://ai.nirogidhara.com/api/auth/login/ \
    -H "Content-Type: application/json" \
    -d '{"username":"director","password":"<admin-password>"}' | jq -r .access)
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/runtime-routing-readiness/ | jq

# Read-only — POST returns 405.
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/runtime-routing-readiness/  # 405

# 3. (Optional) seed ENV: refs for the default org. Dry-run first.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_default_org_integration_refs \
    --dry-run --json | jq

# Apply only after reviewing the dry-run output. Stores ENV: refs only;
# never raw secret values; never activates runtime routing.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_default_org_integration_refs \
    --apply --json | jq
```

What this phase deliberately did NOT do (drives Phase 6G scope):

- No live runtime is switched off env / config.
- No provider is contacted by the diagnostic.
- No raw secret value is stored, logged, or returned.
- No activation / enable / send buttons land on the UI.
- WhatsApp env flags untouched.

Open `https://ai.nirogidhara.com/saas-admin` (logged in as
director / admin) and verify the new **"Runtime Integration Routing
Preview"** section renders with six provider rows and the
**"Per-org runtime routing is not active. Runtime still uses
env/config."** footer banner.

### Phase 6D — Org-Aware Write Path Assignment

After Phase 6C wires the read-side foundation, Phase 6D wires the
write side. New business-state rows automatically inherit org/branch
from their parent (or the seeded default) via a pre_save signal. The
backfill command is still the way to scope pre-Phase-6D rows.

```bash
# 1. Confirm the diagnostic on the VPS.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_write_path_readiness \
    --json | jq '{
        defaultOrganizationExists,
        writeContextHelpersAvailable,
        auditAutoOrgContextEnabled,
        recentRowsWithoutOrganizationLast24h,
        recentRowsWithoutBranchLast24h,
        safeToStartPhase6E,
        nextAction
    }'
# Expect: writeContextHelpersAvailable=true,
#         auditAutoOrgContextEnabled=true,
#         recentRowsWithoutOrganizationLast24h=0,
#         nextAction=ready_for_phase_6e_org_scoped_write_enforcement_plan.

# 2. Smoke-test the API.
ADMIN_JWT=$(curl -s -X POST https://ai.nirogidhara.com/api/auth/login/ \
    -H "Content-Type: application/json" \
    -d '{"username":"director","password":"<admin-password>"}' | jq -r .access)
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/write-path-readiness/ | jq

# Read-only — POST returns 405.
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/write-path-readiness/   # 405
```

Operational notes:

- The signal NEVER fires on `QuerySet.update()` bulk writes — that
  remains the canonical path for the Phase 6B backfill command.
- The signal NEVER overwrites an explicit `organization=...` /
  `branch=...` assignment passed in `Model.objects.create(...)`.
- `audit.AuditEvent` is NOT wired into the signal — the Phase 6C
  `write_event` upgrade already covers it with full request/user
  context resolution.

What this phase deliberately did NOT do (drives Phase 6E scope):

- No global queryset-filtering middleware. Phase 6E adds the
  middleware + makes the FKs non-nullable + ships the SaaS admin
  panel.
- Per-org WhatsApp / Razorpay / Delhivery / Meta / Vapi credentials
  still live in env vars.
- Business-state status logic untouched — the signal only fills in
  org/branch FK slots.

### Phase 6C — Org-Scoped API Filtering Plan

After Phase 6B reaches ≥99.85% coverage, Phase 6C lays the read-only
filtering foundation. No global middleware yet; existing single-tenant
production keeps working unchanged.

```bash
# 1. Confirm readiness on the VPS.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_scoped_api_readiness \
    --json | jq '{
        defaultOrganizationExists,
        organizationCoveragePercent,
        auditAutoOrgContextEnabled,
        globalTenantFilteringEnabled,
        safeToStartPhase6D,
        nextAction
    }'
# Expect: auditAutoOrgContextEnabled=true,
#         globalTenantFilteringEnabled=false,
#         nextAction=ready_for_phase_6d_write_path_org_assignment.

# 2. Smoke-test the API.
ADMIN_JWT=$(curl -s -X POST https://ai.nirogidhara.com/api/auth/login/ \
    -H "Content-Type: application/json" \
    -d '{"username":"director","password":"<admin-password>"}' | jq -r .access)
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/org-scope-readiness/ | jq

# Read-only — POST returns 405.
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/org-scope-readiness/   # 405
```

What this phase deliberately did NOT do (drives Phase 6D / 6E):

- No global queryset-filtering middleware — call sites still need to
  invoke `scoped_queryset_for_request` / `scoped_queryset_for_user`
  explicitly.
- Write-path org assignment is Phase 6D.
- FKs stay nullable.
- WhatsApp env flags untouched.

### Phase 6B — Default Org Data Backfill

After Phase 6A seeded the default org + branch, Phase 6B attaches
every existing business row to that default. Defaults are safe — the
backfill is dry-run unless `--apply` is passed.

**Deploy steps**:

```bash
# 1. Pull + rebuild + apply the new nullable-FK migrations.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never backend worker beat nginx
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate

# 2. Make sure the default org + branch exist.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py ensure_default_organization --json

# 3. Dry-run first. Always.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py backfill_default_organization_data \
    --dry-run --json | jq '{
        passed,
        dryRun,
        totalRows,
        totalWouldUpdateOrganization,
        totalWouldUpdateBranch,
        nextAction
    }'
# Expect: dryRun=true, passed=true, totalWouldUpdate* > 0 on first run.

# 4. Apply. Idempotent — safe to run repeatedly.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py backfill_default_organization_data \
    --apply --json | jq '{
        passed,
        totalUpdatedOrganization,
        totalUpdatedBranch,
        nextAction
    }'

# 5. Verify coverage.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_default_organization_coverage \
    --json | jq '{
        defaultOrganizationExists,
        defaultBranchExists,
        globalTenantFilteringEnabled,
        safeToStartPhase6C,
        totals,
        nextAction
    }'
# Expect: safeToStartPhase6C=true once nothing else is being written
# during the backfill window. globalTenantFilteringEnabled stays false
# until Phase 6C lands.

# 6. (Optional) verify the API endpoint.
ADMIN_JWT=$(curl -s -X POST https://ai.nirogidhara.com/api/auth/login/ \
    -H "Content-Type: application/json" \
    -d '{"username":"director","password":"<admin-password>"}' | jq -r .access)
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/data-coverage/ | jq
```

**What this phase deliberately did NOT do**:

- The new `organization` / `branch` FKs are still nullable — Phase 6C
  is what makes them non-nullable.
- No request middleware filters existing endpoints by organization.
- No queryset is scoped per tenant yet.
- WhatsApp env flags untouched.
- No real provider credentials migrated into `OrganizationSetting`.

**Rollback**: this phase only adds nullable columns + an idempotent
backfill + a read-only API. Rolling back is a git revert + a Django
migration rollback (`python manage.py migrate <app> <prev>`). The
already-backfilled `organization_id` columns are harmless to keep.

### Phase 6A — SaaS Foundation Safe Migration

The multi-tenant scaffold is in place; the existing single-tenant
production system stays running unchanged under the seeded default
organization (`Nirogidhara Private Limited`, code `nirogidhara`) +
default branch (`Main Branch`, code `main`).

**One-time deploy steps** (after `git pull` and a backend rebuild):

```bash
# 1. Apply the new saas migration.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate

# 2. Idempotent default-org seed. Safe to re-run on every deploy.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py ensure_default_organization --json

# Required JSON outcome on a clean first run:
#   { "passed": true, "organizationCode": "nirogidhara",
#     "branchCode": "main", "createdOrganization": true,
#     "createdBranch": true, ... }
# Re-running shows createdOrganization=false / createdBranch=false +
# nextAction=ready_for_phase_6b_default_org_data_backfill.

# 3. Smoke-test the SaaS API (admin JWT required).
ADMIN_JWT=$(curl -s -X POST https://ai.nirogidhara.com/api/auth/login/ \
    -H "Content-Type: application/json" \
    -d '{"username":"director","password":"<admin-password>"}' | jq -r .access)

curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/current-organization/ | jq

curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/my-organizations/ | jq

curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/feature-flags/ | jq

# Read-only — POST must return 405.
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/v1/saas/current-organization/  # 405
```

**What this phase deliberately did NOT do** (drives Phase 6B+ scope):

- No existing model got an `organization` FK in the migration —
  `Customer / Lead / Order / Payment / Shipment / WhatsAppMessage /
  WhatsAppConversation` all stay un-tenant-scoped.
- No middleware filters existing endpoints by organization.
- WhatsApp / Razorpay / Delhivery / Meta credentials remain in env
  vars; nothing was moved into `OrganizationSetting`.
- WhatsApp env flags untouched.

**Rollback**: this phase only adds tables, an idempotent seed, three
read-only endpoints, and a small frontend badge. Rolling back is a
git revert of the commit + a migration rollback (`python manage.py
migrate saas zero`). The default org row is harmless to keep.

### Phase 5F-Gate — Auto-Reply Monitoring Dashboard

The dashboard surface is the read-only operator view of every inspector
that already exists on the CLI. It lives at `/whatsapp-monitoring`
(sidebar group "Messaging") and is fed by seven admin-only DRF
endpoints under `/api/whatsapp/monitoring/`.

What the dashboard surfaces:

- **Status badge** — `Safe OFF`, `Limited Auto-Reply ON`,
  `Needs attention`, or `Danger / Roll back`. The status is derived
  by `get_whatsapp_monitoring_dashboard` on the backend; the frontend
  renders it directly without re-deriving safety logic.
- **Gate status cards** — provider, limited test mode, auto-reply
  enabled, allowed list size, WABA active, campaigns locked, final-
  send guard, consent + Claim Vault required.
- **Broad-automation flag pills** — call handoff, lifecycle, rescue,
  RTO, reorder, campaigns. All show `OFF / locked` when healthy.
- **Activity metrics** (default 2-hour trailing window) — inbound,
  outbound, auto replies sent, deterministic builder used,
  objection replies, blocked, delivered, read, guard blocks, and
  unexpected non-allowed sends.
- **Mutation safety** — orders / payments / shipments / discount logs
  / lifecycle events / handoff events created in the window. Green
  confirmation ("All clean — auto-reply path mutated nothing") when
  every count is zero.
- **Internal cohort table** — masked phone, suffix, customer found,
  consent state, latest inbound + outbound, status, ready flag.
  Phones are last-4 only on the dashboard wire (the operator-only
  `--show-full-numbers` CLI flag is intentionally NOT exposed).
- **Recent audit timeline** — latest WhatsApp-prefixed audit rows
  with `kind`, `tone`, `text`, `phoneSuffix`, `category`,
  `blockReason`, `finalReplySource`, `deterministicFallbackUsed`.
  Tokens / verify token / app secret are scrubbed defence-in-depth
  even though the orchestrator already masks.
- **Backend `nextAction` panel** — read-only string surfacing the
  selector's recommendation (`ready_to_enable_limited_auto_reply_flag`
  / `limited_auto_reply_enabled_monitor_real_inbound` /
  `keep_auto_reply_disabled_fix_blockers` / `rollback_auto_reply_flag`).

The dashboard auto-refreshes every 30 seconds and exposes an explicit
Refresh button. **There are no send / enable / disable / flag-flip
controls on the page.** Flag flips happen only on the VPS via
`.env.production` and a container recreate.

Smoke-testing the dashboard endpoints from the VPS:

```bash
# Combined overview (status + gate + activity + cohort + mutation +
# unexpected outbound).
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.whatsapp import dashboard
import json
print(json.dumps(dashboard.get_whatsapp_monitoring_dashboard(hours=2), default=str)[:1000])
"

# Same data via the API (admin JWT required).
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/whatsapp/monitoring/overview/?hours=2 | jq

# Per-section endpoints.
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/whatsapp/monitoring/gate/ | jq
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    "https://ai.nirogidhara.com/api/whatsapp/monitoring/activity/?hours=2" | jq
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    https://ai.nirogidhara.com/api/whatsapp/monitoring/cohort/ | jq
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    "https://ai.nirogidhara.com/api/whatsapp/monitoring/audit/?hours=2&limit=25" | jq
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    "https://ai.nirogidhara.com/api/whatsapp/monitoring/mutation-safety/?hours=2" | jq
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
    "https://ai.nirogidhara.com/api/whatsapp/monitoring/unexpected-outbound/?hours=2" | jq
```

A healthy "Limited Auto-Reply ON" soak shows:

- `status = limited_auto_reply_on`
- `gate.readyForLimitedAutoReply = true`
- Every broad-automation flag false; `campaignsLocked = true`.
- `activity.unexpectedNonAllowedSendsCount = 0`
- `activity.replyAutoSentCount` matches the expected real inbounds.
- `mutationSafety.allClean = true`
- `unexpectedOutbound.unexpectedSendsCount = 0`
- `nextAction = limited_auto_reply_enabled_monitor_real_inbound`

If the dashboard ever shows `status = danger` or
`unexpectedOutbound.rollbackRecommended = true`, follow the rollback
runbook below — flip `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` in
`.env.production` and recreate `backend worker beat nginx`.

### Phase 5F-Gate — Real Inbound Deterministic Fallback Fix

The first real-inbound auto-reply test on the VPS (allowed test
number suffix `9990`) was blocked with `claim_vault_not_used` even
though backend grounding was valid. Root cause: the deterministic
Claim-Vault-grounded fallback ran only inside the controlled-CLI
command — the real-inbound webhook path never benefited. The
fallback is now inside `apps.whatsapp.ai_orchestration` at every
soft non-safety blocker site (`claim_vault_not_used`,
`low_confidence`, `ai_handoff_requested`, `no_action`).

How it works for the real-inbound webhook path:

1. The webhook persists the inbound `WhatsAppMessage` and enqueues
   `run_whatsapp_ai_agent_for_conversation` (Celery).
2. The orchestrator dispatches the LLM, applies safety validation
   (downgrades flags whose vocabulary is absent from the LATEST
   inbound), and runs the safety / confidence / action gates.
3. If the LLM blocks with a soft non-safety reason BUT auto-reply is
   enabled (`WHATSAPP_AI_AUTO_REPLY_ENABLED=true` OR `force_auto_reply`)
   AND the inbound is a normal product-info inquiry AND the category
   maps to a `Claim.product` AND at least one approved phrase exists
   AND no live safety flag is set on the LATEST inbound, the
   orchestrator builds the deterministic Hinglish reply and dispatches
   it through `services.send_freeform_text_message` — every existing
   gate (limited-mode allow-list, consent, CAIO, idempotency) stays
   in force.
4. Discount/price objections route through `build_objection_aware_reply`
   ahead of the standard grounded reply (same priority order as the
   CLI command).
5. The orchestrator emits `whatsapp.ai.deterministic_grounded_reply_used`
   (or `whatsapp.ai.objection_reply_used`), `whatsapp.ai.reply_auto_sent`,
   `whatsapp.ai.auto_reply_flag_path_used` (only when the global flag
   drove the run, not on `force_auto_reply=True`), and
   `whatsapp.ai.run_completed`.

**What still blocks even with auto-reply on:**

- Latest inbound contains real side-effect / medical / legal /
  refund / blocked-phrase vocabulary → safety stack handles the
  block; fallback never sees it.
- Customer phone not on `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`
  → final-send guard refuses, `whatsapp.ai.auto_reply_guard_blocked`
  fires, `outcome.sent` stays False.
- Consent missing → orchestrator returns at the consent guard
  before LLM dispatch.
- Auto-reply flag off and `force_auto_reply=False` → suggestion is
  stored, no auto-send. The fallback respects that.

**Latest-inbound safety isolation.** The
`whatsapp.ai.safety_downgraded` audit now carries:

- `latest_inbound_message_id`
- `latest_inbound_safety_flags`
- `history_safety_flags`
- `history_safety_ignored_for_current_safe_query` (true / false)

If older synthetic scenario messages biased the LLM into flagging
side-effect / legal / medical on a clean current query, the
corrector flips those flags down based on the LATEST inbound text
vocabulary and `history_safety_ignored_for_current_safe_query`
flips to true. Real safety phrases in the LATEST inbound stay
flagged and the fallback never fires.

**Verifying the fix on the VPS.**

```bash
# 1. Rebuild backend so the orchestrator + tests land in the container.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never backend worker beat nginx

# 2. Pre-flip readiness gate.
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_auto_reply_gate --json

# 3. Set WHATSAPP_AI_AUTO_REPLY_ENABLED=true in .env.production and
# recreate backend/worker/beat. Then send a real WhatsApp message
# from the allowed test number:
#   "Namaste. Mujhe weight management product ke price aur capsule
#    quantity ke baare me bataye."

# 4. After ~30 seconds, run the soak monitor:
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_recent_whatsapp_auto_reply_activity \
    --hours 1 --json
```

Required outcomes after the test inbound:

- `replyAutoSentCount >= 1`
- `autoReplyFlagPathUsedCount >= 1`
- `deterministicBuilderUsedCount >= 1`
- `unexpectedNonAllowedSendsCount == 0`
- `ordersCreatedInWindow == 0`
- `paymentsCreatedInWindow == 0`
- `shipmentsCreatedInWindow == 0`
- `discountOfferLogsCreatedInWindow == 0`
- `nextAction = limited_auto_reply_enabled_monitor_real_inbound`

The phone receives the deterministic Claim-Vault-grounded reply on
WhatsApp (literal approved phrase + ₹3000 / 30 capsules / ₹499
advance + conservative usage + doctor escalation). If anything
amber, roll back: `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` + recreate
containers.

### Phase 5F-Gate — Limited Auto-Reply Flag Plan inspectors

Two strictly read-only management commands prepare and observe the
flip of `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` on real inbound
webhooks. Run them on the VPS through the backend container.

**Pre-flip readiness inspector.**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_auto_reply_gate --json
```

Required JSON outcomes before flipping the flag:

- `provider="meta_cloud"`, `limitedTestMode=true`,
  `allowedListSize >= 1`, `wabaSubscription.active=true`.
- Every broad-automation flag false: `callHandoffEnabled`,
  `lifecycleEnabled`, `rescueDiscountEnabled`, `rtoRescueEnabled`,
  `reorderEnabled` — all `false`. `campaignsLocked=true`.
- `readyForLimitedAutoReply=true`, `blockers=[]`.
- `nextAction="ready_to_enable_limited_auto_reply_flag"` (when the
  flag is still off) or `"limited_auto_reply_enabled_monitor_real_inbound"`
  (after the flip).

The inspector NEVER mutates the DB, NEVER writes audit rows, NEVER
prints tokens / verify token / app secret. Phones in `allowedNumbersMasked`
are last-4 only (e.g. `+91*****99001`).

**Post-flip soak monitor.**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_recent_whatsapp_auto_reply_activity \
    --hours 2 --json
```

Required JSON outcomes during a healthy soak:

- `unexpectedNonAllowedSendsCount=0` (any non-zero value
  → `nextAction="rollback_auto_reply_flag"` immediately).
- `ordersCreatedInWindow / paymentsCreatedInWindow /
  shipmentsCreatedInWindow / discountOfferLogsCreatedInWindow` all
  zero unless an intentional manual booking happened.
- `replyAutoSentCount` matches the Director's expected real-inbound
  count for the window. `autoReplyFlagPathUsedCount` should equal
  `replyAutoSentCount` for any AI auto-send that fired through the
  real flag-driven path; CLI-forced runs (controlled-test command)
  do not increment this counter.
- `autoReplyGuardBlockedCount` is non-zero only if a final-send
  limited-mode allow-list refusal fired — investigate every entry in
  the latest-events block for the masked phone suffix.

`nextAction` priorities:

| Token | Meaning |
| --- | --- |
| `rollback_auto_reply_flag` | A non-allowed outbound landed. Roll back `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` immediately. |
| `limited_auto_reply_enabled_monitor_real_inbound` | Healthy soak — keep monitoring. |
| `no_recent_ai_activity_in_window` | No inbound traffic to assess. |
| `review_blocked_or_suggestion_paths` | AI runs happened but no auto-send fired — inspect blocked / suggestion / handoff counts. |

### Phase 5F-Gate Objection & Handoff Reason Refinement

The Phase 5F-Gate Scenario Matrix Test passed safety-wise but flagged
two refinements:

1. **Discount Objection** — safety-correct (no discount mutation,
   no upfront discount, no >50% issue) but the reply was a generic
   product-info reply instead of an objection-aware acknowledgement.
2. **Human Call Request** — safety-correct (no automation
   triggered) but `blockedReason` came back as `claim_vault_not_used`
   instead of the desired `human_advisor_requested`.

Both refinements ship in this phase.

**Module:** `apps.whatsapp.grounded_reply_builder` (extended).

**Intent classifier.** `classify_inbound_intent(text)` returns an
`IntentResult` whose `primary` field follows this priority:

```
1. unsafe          — cure / guarantee / 100% / permanent / side-effect
                     / consumer-forum / fraud / police vocabulary in
                     the inbound. Safety stack handles the block.
2. human_request   — explicit human-advisor / call / callback /
                     "talk to a human" vocabulary.
3. discount_objection — discount / price / negotiation vocabulary,
                     classified into objection_type ∈ {discount, price}.
4. product_info    — normal price / quantity / safe-use / approved-info
                     question.
5. unknown         — none of the above. Fail closed.
```

Detector helpers exposed: `detect_discount_objection`,
`detect_human_request`, `detect_purchase_intent`,
`detect_unsafe_signal`. Each is deterministic substring matching on
explicit keyword lists.

**Objection-aware reply builder.** `can_build_objection_reply(...)`
gates the reply on (a) discount-objection signal present, (b) inbound
NOT unsafe, (c) category mapped + ≥1 approved Claim row, (d) every
safety flag false. `build_objection_aware_reply(normalized_product,
approved_claims, inbound_text, purchase_intent)` composes:

```
Namaste ji 🙏 Price concern samajh sakta/sakti hoon. <Product>:
<first approved phrase>. ₹3000 / 30 capsules; order par fixed
advance ₹499.

Hum upfront pricing par koi guaranteed concession promise nahi
karte; product approved process ke according hi support karta hai.

Approved: <remaining approved phrases>.

<soft next-step invitation, purchase-intent-aware>

<usage line> <doctor-escalation line>
```

`validate_objection_reply(...)` extends the grounded validator with
`objectionPromisedDiscount` / `objectionPromisedDiscountTerm` flags
that reject `discount confirmed`, `guaranteed discount`, `50%
discount`, `100% discount`, `50 percent discount`.

**Controlled-test command priority order.**

1. Safety blockers (handled by orchestrator).
2. Human request — short-circuits the orchestrator. Emits:
   - `whatsapp.ai.human_request_detected`
   - `whatsapp.ai.handoff_required` (`reason=human_advisor_requested`)
   - `whatsapp.ai.controlled_test.blocked` + `whatsapp.ai.controlled_test.completed`
   - JSON: `blockedReason=human_advisor_requested`,
     `handoffReason=human_advisor_requested`,
     `nextAction=human_handoff_requested`,
     `finalReplySource=blocked_handoff`, `safetyBlocked=false`.
   - Vapi NEVER fires (gated by `WHATSAPP_CALL_HANDOFF_ENABLED=false`).
3. Unknown category / no Claim Vault → fail closed unchanged.
4. Discount/price objection with grounding → objection-aware fallback.
   - JSON: `finalReplySource=deterministic_objection_reply`,
     `objectionDetected=true`, `objectionType ∈ {discount, price}`,
     `replyPolicy.upfrontDiscountOffered=false`,
     `replyPolicy.discountMutationCreated=false`,
     `replyPolicy.businessMutationCreated=false`.
5. Normal product-info → existing grounded fallback.
6. Else → fail closed.

**Four new audit kinds.**

| Kind | Tone | Payload |
| --- | --- | --- |
| `whatsapp.ai.objection_detected` | INFO | `objection_type`, `purchase_intent`, `phone_suffix` |
| `whatsapp.ai.objection_reply_used` | SUCCESS | `category`, `normalized_claim_product`, `approved_claim_count`, `objection_type`, `purchase_intent`, `outbound_message_id`, `phone_suffix`, `used_approved_phrases`, `discount_mutation_created=false`, `business_mutation_created=false` |
| `whatsapp.ai.objection_reply_blocked` | WARNING | `category`, `normalized_claim_product`, `approved_claim_count`, `fallback_reason`, `phone_suffix` |
| `whatsapp.ai.human_request_detected` | INFO | `phone_suffix`, `matched` |

Audit payloads NEVER carry tokens / verify token / app secret.

**Hard rules preserved.**

- Cure / guarantee / unsafe-claim demand inside an objection
  sentence still routes to safety (unsafe wins).
- Side-effect / legal / refund / unknown-category still fail closed.
- Final-send limited-mode guard still refuses non-allowed numbers.
- Zero mutation of `Order` / `Payment` / `Shipment` /
  `DiscountOfferLog` from any controlled-test path (asserted in tests).
- The fallback is controlled-test-only — webhook-driven production
  runs stay strict through the orchestrator.
- Phase 5F (broadcast campaigns) remains LOCKED.

### Phase 5F-Gate Deterministic Grounded Reply Builder

After the Controlled Reply Confidence Fix landed, the live `--send`
against the allowed test number STILL failed: `WAM-100008` came back
with `action=handoff`, `confidence=0.7`, `safety.claimVaultUsed=false`
even though the backend audit proved
`claimRowCount=1 / approvedClaimCount=3 /
groundingStatus.promptGroundingInjected=true /
groundingStatus.businessFactsInjected=true` and every safety flag
was false. **The LLM's self-reported `claimVaultUsed=false` was
contradicted by the backend's own grounding diagnostics.**

**Root cause.** Relying only on the LLM's self-reported
`safety.claimVaultUsed` flag is insufficient. The fix is a
**backend-only deterministic Claim-Vault-grounded reply fallback**.

**Module:** `apps.whatsapp.grounded_reply_builder`

| Function | Purpose |
| --- | --- |
| `is_normal_product_info_inquiry(text)` | Deterministic intent detector — explicit keyword list (price / capsule / quantity / use guidance / jaankari / bataye / …) AND explicit disqualifier list (cure / guarantee / 100% / side-effect / consumer forum / …). |
| `can_build_grounded_product_reply(...)` | Eligibility gate — requires mapped category, ≥1 approved claim, no safety flag set, qualified intent. |
| `build_grounded_product_reply(...)` | Composes a Hinglish reply that literally embeds the first approved phrase + ₹3000 / 30 capsules + ₹499 advance + conservative usage line + doctor escalation. |
| `validate_reply_uses_claim_vault(...)` | Final validator — must contain ≥1 approved phrase, no `BLOCKED_CLAIM_PHRASES` entry, no discount vocabulary. |

**When the fallback fires.** The controlled-test command runs the
fallback ONLY when ALL of:

- `outcome.blocked_reason ∈ { "claim_vault_not_used", "low_confidence",
  "ai_handoff_requested", "auto_reply_disabled", "no_action", "" }`
- backend grounding is valid (`category_to_claim_product` mapped,
  `Claim.product__iexact` row exists, `approved_claim_count ≥ 1`)
- every safety flag is false
- inbound is a normal product-info inquiry per the detector

Safety blockers (`medical_emergency` / `side_effect_complaint` /
`legal_threat` / `blocked_phrase` / `limited_test_number_not_allowed`)
**NEVER** trigger the fallback. The fallback dispatches via the
existing `services.send_freeform_text_message` path so the
limited-mode allow-list guard, consent, CAIO, and idempotency gates
all stay in force.

**Locked safety contract.**

- `claimVaultUsed=true` flips ONLY because the validator confirmed
  the reply text literally embeds at least one approved phrase.
- The reply text is built ONLY from `Claim.approved` + locked
  business facts. No invented benefits.
- No discount, cure, guarantee, "no side effects", or "doctor not
  needed" content — ever.
- The fallback is **controlled-test-only**. The orchestrator's
  webhook-driven path (`run_whatsapp_ai_agent` for inbound webhook
  deliveries) NEVER invokes this builder. Webhook runs stay strict.

**Two new audit kinds.**

- `whatsapp.ai.deterministic_grounded_reply_used` — emitted when
  the fallback dispatched a real send. Payload carries category,
  normalized product, claim row count, approved claim count,
  fallback reason (the LLM block reason), final reply source, phone
  last-4, outbound message id, and the list of approved phrases
  used. Never carries tokens.
- `whatsapp.ai.deterministic_grounded_reply_blocked` — emitted when
  eligibility passed but the validator refused the built reply
  (e.g. discount vocabulary slipped through, blocked phrase
  detected, missing approved phrase).

**Controlled-test JSON additions.**

- `deterministicFallbackUsed` (bool)
- `fallbackReason` (e.g. `claim_vault_not_used`, `low_confidence`)
- `deterministicReplyPreview` (180 chars max)
- `finalReplySource`: `"llm"` or `"deterministic_grounded_builder"`
- `finalReplyValidation`: `{ containsApprovedClaim, matchedApprovedPhrase,
  blockedPhraseFree, blockedPhrase, discountOffered, discountVocab,
  safeBusinessFactsOnly, passed, violation }`

### Phase 5F-Gate Controlled Reply Confidence Fix

After the Claim Vault Grounding Fix landed on the VPS, the live
`--send` against the allowed test number still failed:
`WAM-100007` came back with `blockedReason=low_confidence`,
`confidence=0.7`, `action=handoff`. The audit showed Claim Vault
product was correctly detected, yet the AI still chose handoff.

**Root cause.** The prompt did not tell the LLM explicitly that a
normal grounded inquiry must use `action=send_reply` with
`confidence ≥ 0.85`. The LLM defaulted to handoff out of caution.

**Fix.** Three pieces in `apps.whatsapp.ai_orchestration._build_prompt`
+ `_build_context`:

1. **Business facts injected**: a new `BUSINESS FACTS YOU MAY
   STATE FREELY` section in the system prompt lists:

   - Standard price ₹3000 for one bottle of 30 capsules.
   - Fixed advance ₹499 on order booking.
   - Conservative usage guidance ("use as directed on label / by a
     qualified Ayurvedic practitioner"). No invented dosages.
   - Lifestyle support (diet + activity) **only** when the Claim
     Vault carries a lifestyle phrase.
   - Doctor escalation for pregnancy / serious illness / allergies
     / existing medication / adverse reaction.

   The `settings` block in the user JSON also carries the new
   fields: `standardCapsuleCount=30`, `currency=INR`,
   `discountDiscipline` description, and `businessFactsAllowed`
   whitelist.

2. **Action discipline**: a new `ACTION SELECTION DECISION TREE`
   maps every common inbound to the canonical action:

   - **A** Normal product / price / capsule-quantity / safe-use
     inquiry, claims block has at least one APPROVED phrase, every
     safety flag false, no blocked-phrase trigger →
     `action='send_reply'`, `confidence ≥ 0.85`,
     `safety.claimVaultUsed=true`, `replyText` literally includes
     one of the APPROVED phrases.
   - **B** Open question with no approved Claim Vault entry →
     `action='handoff'`, `confidence` may be low,
     `safety.claimVaultUsed=false`.
   - **C** Category is `unknown` AND the customer hasn't named the
     product → `action='ask_question'`.
   - **D** Customer confirmed booking AND complete address +
     pincode + phone present → `action='book_order'`.
   - **E** Safety vocabulary in the inbound → `action='handoff'` +
     matching safety flag true.

   A `FINAL CHECK` paragraph at the end of the schema
   instructions reinforces case A: *"Defaulting to action='handoff'
   on a grounded inquiry is a defect."*

3. **Diagnostics cleanup**: the ambiguous `claim_count` (which
   sometimes meant rows and sometimes phrases — the
   `controlled_test.blocked` audit said `claim_count=3` while
   `category_detected` / `reply_blocked` said `claim_count=1`) is
   split into three explicit fields on every payload:

   - `claim_row_count` — number of `Claim` rows for the category
     (typically 0 or 1).
   - `approved_claim_count` — sum of all `Claim.approved` phrase
     counts.
   - `disallowed_phrase_count` — sum of all `Claim.disallowed`
     phrase counts.

   `claim_count` is preserved as a backward-compat alias for
   `approved_claim_count` (the count operators care about for
   grounding). The four affected audit kinds are
   `whatsapp.ai.{category_detected, reply_blocked,
   handoff_required, controlled_test.blocked}`.

**Confidence threshold is unchanged.** The env
`WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.75` is **never**
lowered globally to fix a confidence problem — the prompt comes
first.

**Operator-facing diagnostics** added to the controlled-test JSON:

| Field | Meaning |
| --- | --- |
| `claimRowCount` | Number of `Claim` rows (0 or 1). |
| `approvedClaimCount` | Sum of approved phrases. |
| `disallowedPhraseCount` | Sum of disallowed phrases. |
| `claimCount` | Backward-compat alias for `approvedClaimCount`. |
| `confidenceThreshold` | The configured threshold for auto-send. |
| `actionReason` | LLM-supplied handoff reason (when action=handoff). |
| `sendEligibilitySummary` | One-sentence operator summary of why the run is in its current state. |
| `groundingStatus.claimRowCount` | Same as top-level `claimRowCount`. |
| `groundingStatus.businessFactsInjected` | Always `true` post-fix; documents the contract. |

**Hard rules preserved.**

- `claimVaultUsed=false` still blocks the send. Prompt fixes
  grounding; it does not weaken the safety contract.
- Adding a new business fact requires updating the system prompt's
  `BUSINESS FACTS` section AND the `settings.businessFactsAllowed`
  whitelist in `_build_context`. No silent expansion.
- "Guaranteed cure" / "100% cure" replies still blocked by the
  blocked-phrase filter, even with grounding.
- Side-effect / medical-emergency / legal-threat inbounds still
  route to handoff via `_safety_block`.
- The final-send limited-mode guard still refuses non-allowed
  numbers.
- CAIO never executes; no campaigns / broadcasts. Phase 5F LOCKED.

### Phase 5F-Gate Claim Vault Grounding Fix

The deployed Controlled AI Auto-Reply Test Harness produced two
safety-correct blocks against the allowed test number on the VPS:

1. `WAM-100005` blocked by `low_confidence` (`confidence=0.7`) —
   correct safety behaviour.
2. `WAM-100006` blocked by `claim_vault_not_used`
   (`nextAction=blocked_for_unapproved_claim`) — but the Weight
   Management Claim Vault row **did exist** with three approved
   phrases.

**Root cause.** `_claims_for_category("weight-management", customer)`
ran `Claim.objects.filter(product__icontains="weight-management")`
against `Claim(product="Weight Management")` — hyphen vs space — and
silently fell through to `product__icontains=customer.product_interest
or ""` which returned **every claim row** when the customer's
`product_interest` was blank.

**Fix.** New deterministic helper
`apps.whatsapp.claim_mapping.category_to_claim_product` (eight
canonical slugs + ~25 aliases). `_claims_for_category` now runs
`Claim.product__iexact=normalized_product`. The empty-string fallback
is gone — unknown / empty category fails closed (returns `[]`). The
disallowed-phrase list still flows into the prompt avoid list.

**Diagnostics.** The controlled-test command's JSON output gains a
full grounding block:

```json
"detectedCategory": "weight-management",
"normalizedClaimProduct": "Weight Management",
"claimCount": 3,
"confidence": 0.9,
"action": "send_reply",
"replyPreview": "Namaskar! Weight management ke liye …",
"safetyFlags": {
  "claimVaultUsed": true,
  "medicalEmergency": false,
  "sideEffectComplaint": false,
  "legalThreat": false,
  "angryCustomer": false
},
"groundingStatus": {
  "claimProductFound": true,
  "approvedClaimCount": 3,
  "disallowedPhraseCount": 2,
  "promptGroundingInjected": true
}
```

The orchestrator's `whatsapp.ai.{category_detected, reply_blocked,
handoff_required}` audits gain matching grounding fields
(`category` / `normalized_claim_product` / `claim_count` /
`confidence`); the harness's `whatsapp.ai.controlled_test.blocked`
audit carries the same. Tokens / verify token / app secret are NEVER
in any payload.

**Adding a new category.** Update
`apps.whatsapp.claim_mapping.CATEGORY_SLUG_TO_PRODUCT` with the new
slug → human label entry, and `apps.whatsapp.ai_schema.SUPPORTED_CATEGORIES`
with the slug. Do NOT add fuzzy substring matchers — every alias is
explicit.

**Hard rules preserved.** `claimVaultUsed=false` still blocks the
send. `claim_vault_not_used` still routes through the handoff path.
No free-style medical claims. No campaigns / broadcasts. Phase 5F
remains LOCKED.

### Phase 5F-Gate Controlled AI Auto-Reply Test Harness

The single safe surface for verifying a real live AI reply against
exactly one allowed test number, **without** flipping the global
`WHATSAPP_AI_AUTO_REPLY_ENABLED` env. The flag stays `false`
everywhere else; only this CLI may produce a real AI reply during the
gate phase.

**How it works:**

- A new final-send guard inside `apps.whatsapp.services.
  _limited_test_mode_blocks_send` runs both inside
  `services.send_freeform_text_message` (AI auto-reply path) and
  `services.queue_template_message` (template path). When
  `WHATSAPP_PROVIDER=meta_cloud` AND `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`,
  every customer-facing send must target a phone on
  `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` or it raises
  `WhatsAppServiceError(block_reason="limited_test_number_not_allowed")`
  and writes a `whatsapp.send.blocked` audit row.
- `apps.whatsapp.ai_orchestration.run_whatsapp_ai_agent` gains a new
  `force_auto_reply: bool = False` kwarg. The new CLI sets it to
  `True` for one orchestrator call; webhook-driven runs never set it.
- The CLI persists ONE synthetic inbound `WhatsAppMessage` per real
  `--send` run and feeds it to the orchestrator. Failures during AI
  dispatch never mutate `Order` / `Payment` / `Shipment`.

```bash
# Dry-run — runs every precondition (provider, limited mode,
# automation flags off, allow-list, customer + consent, WABA active)
# and exits without persisting an inbound or hitting the LLM.
python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste mujhe weight loss product ke baare me bataye" \
    --dry-run --json

# Live `--send` — drives the orchestrator with auto-reply forced ON
# for one call only. Refused if any safety gate is amber.
python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste mujhe weight loss product ke baare me bataye" \
    --send --json
```

**Required outputs:**

- Dry-run: `passed=true`, `nextAction=dry_run_passed_ready_for_send`,
  no synthetic inbound persisted.
- `--send`: `passed=true`, `replySent=true`, `outboundMessageId` set,
  `providerMessageId` set, `auditEvents` includes
  `whatsapp.ai.controlled_test.sent`,
  `nextAction=live_ai_reply_sent_verify_phone`.

**Typed `nextAction` table:**

| `nextAction` | Meaning |
| --- | --- |
| `dry_run_passed_ready_for_send` | Every gate passed; safe to flip to `--send`. |
| `live_ai_reply_sent_verify_phone` | Real AI reply dispatched; verify the test phone received it. |
| `add_number_to_allowed_list` | Destination not on `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`. |
| `grant_consent_on_test_number` | No Customer or no granted `WhatsAppConsent`. |
| `enable_meta_cloud_provider` | `WHATSAPP_PROVIDER` is not `meta_cloud`. |
| `enable_limited_test_mode` | `WHATSAPP_LIVE_META_LIMITED_TEST_MODE` is not `true`. |
| `disable_automation_flags` | One of the six automation flags is on. |
| `fix_waba_subscription` | WABA `subscribed_apps` is empty. |
| `fix_claim_vault_coverage` | LLM marked `claimVaultUsed=false` or product coverage is missing. |
| `blocked_for_medical_safety` | Safety flag (`medicalEmergency` / `sideEffectComplaint` / `legalThreat`) tripped. |
| `blocked_for_unapproved_claim` | LLM omitted Claim Vault grounding. |
| `blocked_by_limited_mode_guard` | Final-send guard refused the destination. |
| `inspect_live_test` | Other amber state — re-run the inspector for full diagnostics. |

**Five new audit kinds**:
`whatsapp.ai.controlled_test.{started,dry_run_passed,sent,blocked,completed}`.
Audit payloads carry phone last-4 only, body 120-char preview, no
tokens / verify token / app secret.

**Hard constraints (do not relax):**

- The CLI refuses to run if `WHATSAPP_AI_AUTO_REPLY_ENABLED=true`
  globally — it's the only sanctioned path during the gate phase.
- It refuses to run if any of `WHATSAPP_CALL_HANDOFF_ENABLED`,
  `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`,
  `WHATSAPP_RESCUE_DISCOUNT_ENABLED`,
  `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, or
  `WHATSAPP_REORDER_DAY20_ENABLED` is on.
- It does NOT introduce broadcast / campaign / MARKETING-tier
  behaviour. Phase 5F (broadcast campaigns) remains LOCKED.

### Phase 5F-Gate Hardening Hotfix — diagnostics layer

The live one-number gate passed on the VPS (`WAM-100003` outbound +
`WAM-100004` inbound after fixing empty WABA `subscribed_apps`). Three
gaps surfaced and are now closed:

**1. Duplicate idempotency crash → clean JSON.** A second run of
`run_meta_one_number_test --send` on the same number / template / day
used to crash with a unique-constraint traceback
(`uniq_whatsapp_message_idempotency_key`). The CLI now returns:

```json
{
  "passed": false,
  "duplicateIdempotencyKey": true,
  "alreadyQueued": false,
  "alreadySent": true,
  "existingMessageId": "WAM-100003",
  "auditEvents": ["...", "whatsapp.meta_test.duplicate_idempotency", "..."],
  "nextAction": "inspect_existing_message"
}
```

The audit row carries only the **last 12 chars** of the idempotency
key — never the raw key, never any token.

**2. WABA subscription diagnostics.** `--check-webhook-config` now
runs `GET https://graph.facebook.com/{api}/{WABA_ID}/subscribed_apps`
with the configured `META_WA_ACCESS_TOKEN` (read-only) and reports:

```json
"webhook": {
  "callbackUrl": "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/",
  "wabaSubscriptionChecked": true,
  "wabaSubscriptionActive": false,
  "wabaSubscribedAppCount": 0,
  "wabaSubscriptionWarning": "subscribed_apps is empty — Meta will NOT deliver inbound webhooks. ...",
  "overrideCallbackExpected": "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/",
  "recommendedSubscribeCommandHint": "POST /{api}/{WABA_ID}/subscribed_apps with Authorization: Bearer <META_WA_ACCESS_TOKEN> (token, app secret, and verify token NEVER printed here).",
  ...
}
```

If `data=[]` the command flips `nextAction` to
`subscribe_waba_to_app_webhooks` and emits a
`whatsapp.meta_test.webhook_subscription_checked` audit row. Token /
verify token / app secret are NEVER printed.

**3. Read-only inspector.** New command:

```bash
python manage.py inspect_whatsapp_live_test --phone +91XXXXXXXXXX --json
```

Surfaces in a single JSON document:

- `customer` (found / id / phone / consent_whatsapp)
- `whatsappConsent` (state / granted_at / revoked_at / last_inbound_at)
- `conversation` (id / status / unread_count / updated_at)
- `messages.latestOutbound` + `messages.latestInbound`
  (id / direction / type / status / bodyPreview / provider_message_id / created_at)
- `webhookEvents` (count + latest 5 with signature_verified, processing_status)
- `statusEvents` (count + latest 5)
- `auditEvents` (latest 25 `whatsapp.*` rows)
- `wabaSubscription` (live `subscribed_apps` check)
- `latestProviderMessageId`
- `nextAction`

**Inspector contract:** never sends, never mutates the DB (no audit
row, no message row, no status row, no webhook envelope written),
never prints tokens / verify token / app secret. Gracefully handles
missing Meta credentials (Graph check skipped with warning).

`nextAction` priorities (most-blocking first):

| Token | Meaning |
| --- | --- |
| `subscribe_waba_to_app_webhooks` | WABA `subscribed_apps` is empty — Meta won't deliver inbound webhooks. |
| `run_one_number_send` | No outbound message on file for the number. |
| `verify_inbound_webhook_callback` | Outbound exists but no inbound has arrived. |
| `observe_status_events_optional` | Outbound + inbound both present, but no `WhatsAppMessageStatusEvent` rows yet. Soft signal — Meta may still send delivery webhooks. |
| `gate_hardened_ready_for_limited_ai_auto_reply_plan` | Ready to plan a tightly-scoped controlled AI auto-reply test against the allowed test number. |

### Phase 5F-Gate — Limited Live Meta WhatsApp One-Number Test

The single safe surface for verifying real Meta Cloud sends without
flipping any automation flag. Defaults to `--dry-run`; `--send` is
required for a real dispatch and refuses if any safety gate is amber.

```bash
# Print the expected webhook callback URL + verify-token / app-secret
# presence summary so the operator can wire the Meta Developer Console.
python manage.py run_meta_one_number_test --check-webhook-config --json

# Verify-only — runs the precondition stack and exits without sending.
python manage.py run_meta_one_number_test \
    --to +91XXXXXXXXXX \
    --template nrg_greeting_intro \
    --verify-only --json

# Real send — refused unless every gate is green.
python manage.py run_meta_one_number_test \
    --to +91XXXXXXXXXX \
    --template nrg_greeting_intro \
    --send --json
```

The command refuses with a typed `nextAction` field on every amber gate:

| `nextAction` | Meaning |
| --- | --- |
| `fix_provider_credentials` | Provider is not `meta_cloud` or required Meta env keys are missing. |
| `enable_limited_test_mode` | `WHATSAPP_LIVE_META_LIMITED_TEST_MODE` is not `true`. |
| `add_number_to_allowed_list` | Destination is not in `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`. |
| `sync_or_approve_template` | Template missing / not approved / inactive / MARKETING tier. |
| `disable_automation_flags` | One of the six automation flags is on; the gate refuses live sends until they're all off. |
| `grant_consent_on_test_number` | Test customer has no WhatsApp consent. |
| `verify_only_passed` | `--verify-only` succeeded; safe to flip to `--send`. |
| `ready_to_send` | All gates green and the user did not pass `--send`. |
| `verify_inbound_webhook_callback` | Real send dispatched — now confirm the inbound webhook arrives at `/api/webhooks/whatsapp/meta/`. |

Audit ledger emits eight `whatsapp.meta_test.*` rows per run
(`started`, `config_ok` or `config_failed`, optionally
`blocked_number` / `template_missing`, `sent` or `failed`,
`completed`). Audit payloads NEVER carry tokens; the destination
number is masked to its last 4 digits.

**Phase 5F (broadcast campaigns / growth automation) remains LOCKED
until this gate passes on a live test number.**

### Phase 5E-Smoke-Fix-3 — false-positive safety classification fix

The VPS OpenAI smoke run reported `overallPassed=false` because the
orchestrator wrongly classified a normal product inquiry
(`Hi mujhe weight loss product ke baare me batana`) as a
`side_effect_complaint`. Phase 5E-Smoke-Fix-3 adds a server-side
corrector that runs immediately before the safety blockers are
evaluated.

```python
from apps.whatsapp.safety_validation import validate_safety_flags

corrected, downgraded = validate_safety_flags(
    inbound_text=inbound.body,
    safety_flags=decision.safety,
)
# downgraded == ["sideEffectComplaint"] for the smoke false positive.
```

For each blocker flag the LLM set true (`sideEffectComplaint`,
`medicalEmergency`, `legalThreat`), the corrector checks whether the
inbound text contains the corresponding signal vocabulary
(English / Hindi / Hinglish). Flags whose vocabulary is absent are
flipped to false and a `whatsapp.ai.safety_downgraded` audit row is
emitted; flags whose vocabulary IS present (real complaints) stay
flagged exactly as the LLM said.

Hard rules:

- Never flips false → true (purely additive correction).
- Never touches `angryCustomer` or `claimVaultUsed`.
- The LLM prompt now carries an explicit `SAFETY FLAG DISCIPLINE`
  block listing required vocabulary per flag — false positives should
  be rare even before the corrector runs.

VPS rebuild is **required** after this commit so the new orchestrator
+ prompt land in the backend image. After rebuild re-run:

```bash
python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hinglish --use-openai --json
```

…and verify `detail.openaiSucceeded=true`, `detail.providerPassed=true`,
`overallPassed=true`. If a `whatsapp.ai.safety_downgraded` audit row
appears in the output, that is **expected** — the LLM over-flagged a
normal inquiry and the corrector caught it before the customer was
silently routed to handoff.

### Phase 5E-Smoke-Fix-2 — OpenAI Chat Completions token-parameter hotfix

Modern OpenAI Chat Completions models (gpt-4o, gpt-5, o1, o3, …)
**reject** the legacy `max_tokens` parameter and require
`max_completion_tokens`. The adapter at
`apps.integrations.ai.openai_client.dispatch` now builds its request
kwargs through a unit-testable helper:

```python
from apps.integrations.ai.openai_client import build_request_kwargs

kwargs = build_request_kwargs(messages=msgs, model="gpt-5.1", config=config)
# kwargs["max_completion_tokens"] == config.max_tokens
# "max_tokens" not in kwargs  ← never sent
```

If you see *"Unsupported parameter: 'max_tokens' is not supported"* in
the smoke harness's `providerError` field again, the adapter has
regressed — re-run `python -m pytest tests/test_phase5e_smoke_fix2.py`
to confirm the kwargs-shape contract.

VPS rebuild is **required** after this commit so the new adapter code
lands in the backend image. Then re-run the OpenAI smoke and confirm
`detail.openaiSucceeded=true`.

### Phase 5E-Smoke-Fix — OpenAI provider semantics

The Phase 5E-Smoke harness adds four new detail fields to the
`ai-reply` scenario when `--use-openai` is passed:

| Field | Meaning |
| --- | --- |
| `openaiAttempted` | True when `--use-openai` is on. |
| `openaiSucceeded` | True only when the OpenAI adapter actually returned `SUCCESS`. False if the SDK is missing, the API key is wrong, or the adapter raised. |
| `providerPassed` | True when no provider was attempted OR when the attempted provider succeeded. |
| `safeFailure` | True when `--use-openai` was on AND the adapter did NOT succeed but the customer send stayed blocked (i.e. safety held but the provider integration is broken). |

A safe-failure is **safety-correct** (no real customer was messaged)
but **does NOT count as a pass**. `scenario.passed=false` and
`overallPassed=false` so operators see the failure clearly.

Required gate before flipping any automation flag with real OpenAI:

```bash
python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hinglish --use-openai --json
```

Expected JSON keys (must all be true):

```
detail.openaiAttempted = true
detail.openaiSucceeded = true
detail.providerPassed = true
detail.safeFailure   = false
overallPassed        = true
```

If `safeFailure=true`, fix the OpenAI integration first. Common causes:

1. `openai` Python SDK not installed in the backend container — rebuild after a `pip install`.
2. `OPENAI_API_KEY` missing or wrong in `.env` / `.env.production`.
3. `AI_PROVIDER` not set to `openai` (default is `disabled`).
4. Network egress blocked from the VPS (rare on Hostinger but possible behind a strict firewall).

### Phase 5E-Smoke — Controlled Mock + OpenAI Smoke Testing Harness

Run before flipping any automation flag in production. Defaults are
SAFE (dry-run + mock-WhatsApp + mock-Vapi + OpenAI off). The harness
never sends a real customer message and refuses to use the live Meta
provider.

```bash
# Single scenario.
python manage.py run_controlled_ai_smoke_test --scenario claim-vault --json
python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hindi
python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hinglish
python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language english
python manage.py run_controlled_ai_smoke_test --scenario rescue-discount --json
python manage.py run_controlled_ai_smoke_test --scenario vapi-handoff --mock-vapi
python manage.py run_controlled_ai_smoke_test --scenario reorder-day20 --dry-run

# All five scenarios (claim-vault → ai-reply → rescue-discount → vapi-handoff → reorder-day20).
python manage.py run_controlled_ai_smoke_test --scenario all --json

# Hit real OpenAI for the ai-reply scenario only (WhatsApp stays mock).
# Requires OPENAI_API_KEY in the environment.
python manage.py run_controlled_ai_smoke_test --scenario ai-reply --use-openai

# Refresh demo Claim Vault rows before running the coverage scenario.
python manage.py run_controlled_ai_smoke_test --scenario claim-vault --reset-demo-claims
```

Recommended rollout sequence (do not skip steps):

1. `WHATSAPP_PROVIDER=mock`, `VAPI_MODE=mock`, `AI_PROVIDER=disabled`.
2. `python manage.py seed_default_claims --reset-demo` then
   `python manage.py check_claim_vault_coverage`.
3. `python manage.py run_controlled_ai_smoke_test --scenario all --json` — must report `overallPassed: true`.
4. Set `AI_PROVIDER=openai` (key in env), re-run with `--use-openai` for `ai-reply` scenario.
5. Flip `WHATSAPP_PROVIDER=meta_cloud` with `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` and exactly one number in `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`. Send the locked greeting + payment reminder + confirmation reminder templates manually.
6. Enable feature flags one at a time with 24+ hours of soak between flips: `WHATSAPP_AI_AUTO_REPLY_ENABLED` → `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED` → `WHATSAPP_CALL_HANDOFF_ENABLED` → `WHATSAPP_RESCUE_DISCOUNT_ENABLED` → `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED` → `WHATSAPP_REORDER_DAY20_ENABLED`.

The harness emits four audit kinds: `system.smoke_test.{started,completed,failed,warning}`. Look at the latest rows after each run:

```bash
python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='system.smoke_test')[:10]:
    print(e.occurred_at, e.kind, e.text)
"
```

### Phase 5E-Hotfix-2 — Strengthened demo Claim Vault seed

The first VPS coverage report after Phase 5E flagged Blood Purification
(`approved=1, usage=no`) and Lungs Detox (`approved=2, usage=no`) as
`weak`. Hotfix-2 merges four universal safe usage-guidance phrases
into every demo seed row and widens the coverage keyword list so the
detector recognises label / hydration / practitioner phrasing.

After pulling Hotfix-2 on the VPS:

```bash
# Refresh demo-v1 rows to demo-v2. Real admin claims are NEVER touched.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_default_claims --reset-demo

# Confirm coverage no longer flags any demo row as weak.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py check_claim_vault_coverage
```

Expected: every seeded category reports `demo_ok`, not `weak`. If a
product still reports `weak`, that row is a real admin-added claim
whose `approved` list lacks usage keywords — replace it via the Django
admin with a doctor-approved phrase. Production must still ship real
doctor-approved claims before flipping any rescue / lifecycle / chat
auto-reply flag to true.

### Phase 5E-Hotfix — Migration drift gate

After Phase 5E shipped, the VPS first-deploy reported "models in app(s)
'orders', 'whatsapp' have changes that are not yet reflected in a
migration" because the Phase 5D / 5E migrations hand-rolled short
index names that don't match Django's auto-suffix form. The hotfix
adds two `RenameIndex` migrations under `apps/orders/migrations/0004_*`
and `apps/whatsapp/migrations/0004_*` — pure metadata renames, no
schema rewrite.

**Working agreement now requires** the migration drift gate before
every commit:

```bash
cd backend
python manage.py makemigrations --check --dry-run    # MUST report "No changes detected"
```

If new migrations include custom index names, generate them via
`python manage.py makemigrations` (or copy the auto-suffix form
verbatim from `--dry-run -v 3`); never hand-roll a short name like
`whatsapp_wh_status_h0_idx` again.

VPS deploy sequence after every `git pull`:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run
# Expected: "No changes detected"
```

### Phase 5E — Rescue Discount + Day-20 Reorder

```bash
# Seed conservative demo Claim Vault rows for the 8 current categories.
# Idempotent. Real admin-added Claim rows are NEVER overwritten.
python manage.py seed_default_claims
python manage.py seed_default_claims --reset-demo   # refresh demo seeds
python manage.py seed_default_claims --json          # machine-readable

# Run the Day-20 reorder reminder sweep. Idempotent — safe on cron.
python manage.py run_reorder_day20_sweep
python manage.py run_reorder_day20_sweep --dry-run

# Coverage audit (already shipped Phase 5D, extended for Phase 5E demo rows).
python manage.py check_claim_vault_coverage          # exits 1 on missing
python manage.py check_claim_vault_coverage --strict-weak
```

Phase 5E env flags (all default OFF / SAFE — flip in `backend/.env` after
the WhatsApp + AI Calling teams verify the flow on a controlled set of
test numbers):

```
WHATSAPP_RESCUE_DISCOUNT_ENABLED=false       # confirmation + delivery rescue
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false   # RTO automatic rescue offer
WHATSAPP_REORDER_DAY20_ENABLED=false         # Day-20 reorder reminder cadence
DEFAULT_CLAIMS_SEED_DEMO_ONLY=true           # surface demo rows as risk=demo_ok
```

Cumulative cap is **50% absolute hard cap** across confirmation /
delivery / RTO / reorder stages. AI never offers a discount above the
cap automatically; over-cap requests mint an `ApprovalRequest` via the
new `discount.rescue.ceo_review` matrix row (CEO AI / admin) or
`discount.above_safe_auto_band` (director-only). CAIO is refused at the
service entry. Customer acceptance applies via the existing
`apps.orders.services.apply_order_discount` path — no module mutates
`Order.discount_pct` directly.

Frontend Scheduler Status page lives at `http://localhost:8080/ai-scheduler`
(admin/director only) — pulls `GET /api/ai/scheduler/status/`.

## Database

- Default: `backend/db.sqlite3` (SQLite).
- Postgres: set `DATABASE_URL=postgres://user:pass@host:5432/db` in
  `backend/.env` and `pip install "psycopg[binary]"`.
- Reset: `python manage.py flush --no-input` (wipes data) or delete
  `db.sqlite3` and re-run `migrate` + `seed_demo_data`.

## Phase 2A flows — full workflow via curl

After `python manage.py runserver`, drive the lead → delivery chain end-to-end.
Requires an `operations` (or higher) user — quickly create one in the Django
shell:

```bash
python manage.py shell -c "from apps.accounts.models import User; u = User.objects.create_user(username='ops', password='ops12345', email='ops@local'); u.role = 'operations'; u.save()"
```

Then:

```bash
# 1. Get a JWT token.
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"ops","password":"ops12345"}' | jq -r .access)

# 2. Create a lead.
curl -s -X POST http://localhost:8000/api/leads/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Demo","phone":"+91 9000000001","state":"Maharashtra","city":"Pune","productInterest":"Weight Management"}' | jq .

# 3. Punch an order.
ORDER_ID=$(curl -s -X POST http://localhost:8000/api/orders/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"customerName":"Demo","phone":"+91 9000000001","product":"Weight Management","amount":2640,"discountPct":12,"state":"Maharashtra","city":"Pune"}' | jq -r .id)
echo "Order: $ORDER_ID"

# 4. Move to confirmation queue.
curl -s -X POST "http://localhost:8000/api/orders/$ORDER_ID/move-to-confirmation/" \
  -H "Authorization: Bearer $TOKEN" | jq .stage

# 5. Confirm the order.
curl -s -X POST "http://localhost:8000/api/orders/$ORDER_ID/confirm/" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"outcome":"confirmed","notes":"address verified"}' | jq .stage

# 6. Generate a mock payment link.
curl -s -X POST http://localhost:8000/api/payments/links/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"orderId\":\"$ORDER_ID\",\"amount\":499,\"gateway\":\"Razorpay\",\"type\":\"Advance\"}" | jq .paymentUrl

# 7. Move to Dispatched, create a mock shipment.
curl -s -X POST "http://localhost:8000/api/orders/$ORDER_ID/transition/" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"stage":"Dispatched"}' | jq .stage

curl -s -X POST http://localhost:8000/api/shipments/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"orderId\":\"$ORDER_ID\"}" | jq '{awb, status, timeline}'

# 8. Trigger an RTO rescue + update outcome.
RESCUE_ID=$(curl -s -X POST http://localhost:8000/api/rto/rescue/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"orderId\":\"$ORDER_ID\",\"channel\":\"AI Call\",\"notes\":\"first attempt\"}" | jq -r .id)
echo "Rescue: $RESCUE_ID"

curl -s -X PATCH "http://localhost:8000/api/rto/rescue/$RESCUE_ID/" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"outcome":"Convinced","notes":"agreed to receive"}' | jq .

# 9. The activity feed should now show every step.
curl -s http://localhost:8000/api/dashboard/activity/ | jq '.[0:10]'
```

Anonymous and viewer-role tokens get 401/403 respectively — the same flow run
without `Authorization` returns 401 on every step.

## Auth (Phase 1)

- Most read endpoints are open (`AllowAny`) so the prototype frontend works
  without a login UI.
- JWT endpoints are wired and tested:
  - `POST /api/auth/token/` — body `{"username", "password"}`
  - `POST /api/auth/refresh/`
  - `GET /api/auth/me/` — requires `Authorization: Bearer <access>`
- Frontend reads any token from `localStorage["nirogidhara.jwt"]` and attaches
  it as `Authorization: Bearer …`. No login page yet — Phase 2.

## Phase 3E — Business configuration foundation

Phase 3E ships the policy + catalog layer **before** Phase 4 turns AgentRun
suggestions into business writes. No new frontend pages — this is a
backend-only phase. Highlights:

- **Product catalog** (`apps.catalog`): admin/director-managed via Django
  admin (`/admin/catalog/`). Read APIs at `/api/catalog/{categories,products,skus}/`
  are public; writes are admin/director-only.
- **Discount policy** (`apps.orders.discounts`): import
  `validate_discount(discount_pct, actor_role, approval_context=None)` from
  any service that needs to gate a discount. Bands are 0–10% auto, 11–20%
  approval, > 20% director-override only.
- **Advance payment** (`apps.payments.policies`): `FIXED_ADVANCE_AMOUNT_INR = 499`.
  `POST /api/payments/links/` with no `amount` defaults to ₹499 for type
  `Advance`. Existing callers that pass an explicit amount keep working.
- **Reward / penalty scoring** (`apps.rewards.scoring`): pure formula —
  Phase 4B will sweep delivered orders and roll up the leaderboard.
- **Approval matrix** (`apps.ai_governance.approval_matrix`): policy table
  read via `GET /api/ai/approval-matrix/`. Phase 4C middleware enforces it.
- **WhatsApp design scaffold** (`apps.crm.whatsapp_design`): no live sender;
  the constants drive the future Phase 4+ integration.

## Phase 4B — Reward / Penalty Engine

Phase 4B turns the Phase 3E pure scoring formula into persisted, auditable
per-order events. Headline points:

- **Scope**: AI agents only — no human staff scoring in this phase.
- **Eligible stages**: Delivered (rewards), RTO + Cancelled (penalties).
- **CEO AI net accountability**: every delivered / RTO / cancelled order
  generates a CEO AI event. Always present, every sweep.
- **CAIO is excluded** from business scoring (audit-only).
- **Idempotent**: re-running a sweep updates rows in place via
  `unique_key = phase4b_engine:{order_id}:{agent_id}:{event_type}`.

Manual sweep (no Redis required):

```bash
python manage.py calculate_reward_penalties
python manage.py calculate_reward_penalties --order-id NRG-20410
python manage.py calculate_reward_penalties --dry-run
python manage.py calculate_reward_penalties --start-date 2026-04-01 --end-date 2026-04-28
```

Celery (production):
```bash
# Already wired; pulled in by the existing worker / beat command.
celery -A config worker -B --loglevel=info
```

Frontend Rewards page at `/rewards` shows the agent-wise leaderboard,
order-wise scoring events table, sweep summary cards, and Run Sweep
button (admin / director only on the API; viewer / operations / anonymous
are blocked).

## Phase 4C — Approval Matrix Middleware

The Phase 3E approval matrix is now actively enforced. Any service that
performs a gated business write calls
`apps.ai_governance.approval_engine.enforce_or_queue(...)` first; when
the matrix demands approval / override / escalation, the engine creates
an `ApprovalRequest` row and the service stops.

What is enforced today (Phase 4C scope):

- **Custom-amount payment links**: `POST /api/payments/links/` with a
  custom amount → `payment.link.custom_amount` requires admin approval.
  ₹0 / ₹499 advance is auto.
- **Prompt activation**: `POST /api/ai/prompt-versions/{id}/activate/` is
  recorded as auto-approved (admin/director already cleared the role gate).
- **Sandbox disable**: `PATCH /api/ai/sandbox/status/` with `isEnabled=false`
  → `ai.sandbox.disable` (`director_override`). Admin → 403; director with
  `director_override=true` + `note` → allowed.

How to approve / reject from the API:

```bash
TOKEN=...   # admin or director JWT

# List pending approvals.
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/ai/approvals/?status=pending" | jq .

# Approve.
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"note":"OK"}' \
  "http://localhost:8000/api/ai/approvals/APR-90001/approve/" | jq .

# Reject.
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"note":"too risky"}' \
  "http://localhost:8000/api/ai/approvals/APR-90002/reject/" | jq .
```

The Governance page at `/ai-governance` exposes the same operations as
buttons (admin/director only on the API; the frontend just renders).

**Important**: `approve_request` flips status to `approved` and writes
audits. It does **not** silently execute the underlying business write.

## Phase 4D + 4E — Approved Action Execution Layer

`POST /api/ai/approvals/{id}/execute/` runs an already-approved
`ApprovalRequest` through a strict allow-listed registry. The Phase 4E
expansion brought the total to 6 actions; everything else returns
HTTP 400 + `ai.approval.execution_skipped` audit.

1. `payment.link.advance_499` — calls
   `apps.payments.services.create_payment_link` with the amount
   resolved to `FIXED_ADVANCE_AMOUNT_INR` (₹499). Tampered payload
   amounts are ignored.
2. `payment.link.custom_amount` — same service, requires `amount > 0`.
3. `ai.prompt_version.activate` — calls
   `apps.ai_governance.prompt_versions.activate_prompt_version`.
   Idempotent on already-active.
4. **Phase 4E** `discount.up_to_10` — calls
   `apps.orders.services.apply_order_discount` for the 0–10% band.
   Accepts `approved` OR `auto_approved` ApprovalRequest status.
   Mutates ONLY `Order.discount_pct`; writes `discount.applied` audit.
5. **Phase 4E** `discount.11_to_20` — same service, 11–20% band.
   Same approve / auto_approve gate; auto_approved is trusted only
   because the backend approval_engine put it there.
6. **Phase 4E** `ai.sandbox.disable` — flips the SandboxState
   singleton off via the existing helper. **Director-only** via
   matrix `director_override` (admin → 403). Idempotent on already-
   off (`alreadyDisabled=true`). Requires `note` or `overrideReason`.

Pre-checks (defense in depth, fail closed in this order):

- Already executed → 200 + prior result, no handler call.
- `requested_by_agent == "caio"` or metadata.actor_agent == "caio" → 403.
- Caller is not admin / director → 403.
- Caller is admin while `policy.mode == director_override` → 403.
- `ApprovalRequest.status` not `approved` / `auto_approved` → 409.

Curl example (admin or director JWT):

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"note":"director-approved"}' \
  "http://localhost:8000/api/ai/approvals/APR-90004/execute/" | jq .
```

The Governance page at `/ai-governance` now shows an Execution column
+ Execute button on approved rows. Pending / rejected / blocked /
escalated / expired / already-executed rows do not show the button.

Locked Phase 4D hard stops (do NOT relax without explicit Prarit
sign-off + matching tests): no autonomous AI execution, no ad-budget
changes, no refunds, no live WhatsApp, no discount execution in this
first pass, no sandbox-disable execution in this first pass, idempotent
re-execute, director-only override on `director_override` actions.

## Phase 4A — Real-time AuditEvent WebSockets

The Master Event Ledger now streams to a WebSocket alongside the
existing polling endpoints. Local dev defaults to the in-memory
channel layer so neither Redis nor a separate ASGI worker is
required for `pytest` / `manage.py runserver`. Spin up Redis only
when you want to validate the production path.

### Local dev (in-memory layer, no Redis)

Just run the stack normally:

```bash
# Terminal 1
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py runserver 0.0.0.0:8000

# Terminal 2
cd frontend
npm run dev
```

Open [http://localhost:8080](http://localhost:8080). The Dashboard
"Live Activity" feed and the Governance "Approval queue" both show a
realtime status pill (`connecting` → `live` once the socket opens).
Trigger any write action (e.g. a payment-link curl) and the new
AuditEvent appears in the feed without a page refresh.

### Manual WebSocket smoke test

Browser DevTools → Network → WS → open `/ws/audit/events/` → expect:

1. An `audit.snapshot` frame with the latest 25 events.
2. An `audit.event` frame for every new audit row.

Or via `wscat`:

```bash
npx wscat -c ws://localhost:8000/ws/audit/events/
```

### Production / Redis-backed channel layer

Bring up Redis (the same `docker-compose.dev.yml` works for staging
smoke tests), then flip the env:

```bash
docker compose -f docker-compose.dev.yml up -d redis
# backend/.env
CHANNEL_LAYER_BACKEND=redis
CHANNEL_REDIS_URL=redis://localhost:6379/2
```

Channels uses Redis index 2 so it does not collide with Celery's 0/1.
For real production traffic, run the ASGI worker via daphne (or
uvicorn / gunicorn-with-uvicorn-workers) instead of `runserver`:

```bash
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

The polling endpoints (`/api/dashboard/activity/`,
`/api/ai/approvals/`) stay live as fallback — frontend pages keep
working when the WebSocket is unreachable.

## Phase 5A — WhatsApp (Meta Cloud) live sender

The local stack defaults to `WHATSAPP_PROVIDER=mock` so neither
`graph.facebook.com` nor a real WABA number is ever touched in dev / CI.
The mock provider mints deterministic `wamid.MOCK_<sha1>` ids and accepts
any non-empty webhook signature so test fixtures stay simple.

### Switching to Meta Cloud (production target)

1. **Create a Meta Business app** at <https://developers.facebook.com/apps/> and add the **WhatsApp** product.
2. Note the **WABA id** (`META_WA_BUSINESS_ACCOUNT_ID`), **phone-number id** (`META_WA_PHONE_NUMBER_ID`), and **system-user access token** (`META_WA_ACCESS_TOKEN`).
3. Open **App settings → Basic** and copy the **App secret** (`META_WA_APP_SECRET`). Optionally set `WHATSAPP_WEBHOOK_SECRET` to use a separate value just for the webhook.
4. Set a **verify token** (`META_WA_VERIFY_TOKEN`) to any random string — Meta echoes it during the GET handshake.
5. Update `backend/.env`:
   ```bash
   WHATSAPP_PROVIDER=meta_cloud
   META_WA_PHONE_NUMBER_ID=...
   META_WA_BUSINESS_ACCOUNT_ID=...
   META_WA_ACCESS_TOKEN=...
   META_WA_VERIFY_TOKEN=...
   META_WA_APP_SECRET=...
   ```
6. Configure the webhook subscription in Meta to point at `https://<your-host>/api/webhooks/whatsapp/meta/`.

### Sync templates

```bash
cd backend
python manage.py sync_whatsapp_templates           # seeds 8 default lifecycle templates
python manage.py sync_whatsapp_templates --from-file path/to/meta-templates.json
```

The command writes a `whatsapp.template.synced` audit per row. Only
`status=APPROVED && is_active=True` rows can be used for live sends.

### Trigger a manual send

```bash
curl -X POST -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  http://localhost:8000/api/whatsapp/send-template/ \
  -d '{"customerId":"NRG-CUST-1","actionKey":"whatsapp.payment_reminder","variables":{"customer_name":"Aditi","context":"₹499"}}'
```

The pipeline checks consent + approved-template + Claim Vault + approval
matrix + idempotency before queuing. With `CELERY_TASK_ALWAYS_EAGER=true`
(local default) the Celery task runs synchronously and the response
already shows the `sent` status with the provider message id.

### Webhook test (mock-mode)

```bash
curl -X POST http://localhost:8000/api/webhooks/whatsapp/meta/ \
  -H 'X-Hub-Signature-256: sha256=anything' \
  -H 'Content-Type: application/json' \
  -d '{"object":"whatsapp_business_account","entry":[{"id":"E1","changes":[{"field":"messages","value":{"metadata":{"phone_number_id":"PNID"},"messages":[{"id":"wamid.IN1","from":"919999900001","type":"text","text":{"body":"hi"},"timestamp":"1714290000"}]}}]}]}'
```

Mock mode accepts any non-empty signature. Production (`WHATSAPP_PROVIDER=meta_cloud`) refuses any
signature mismatch and rejects bodies older than `WHATSAPP_WEBHOOK_REPLAY_WINDOW_SECONDS` (default 300 s).

### Locked safety rules (Phase 5A)

- Production target is **Meta Cloud**. Baileys is dev/demo only and refuses to load
  unless `DJANGO_DEBUG=true AND WHATSAPP_DEV_PROVIDER_ENABLED=true`.
- Every send runs through **consent + approved template + Claim Vault + approval matrix**.
- Failed sends NEVER mutate `Order` / `Payment` / `Shipment`.
- CAIO can never originate a customer-facing send.
- Phase 5A does NOT implement the AI Chat Agent (5C), inbound auto-reply, chat-to-call handoff,
  Order booking from chat, lifecycle automation triggers, rescue discount, or campaigns.

## Phase 5B — Inbox + Customer 360 timeline

The operator inbox at `/whatsapp-inbox` is **manual-only**. AI auto-reply,
chat-to-call handoff, rescue discount and campaigns all stay deferred to
Phase 5C–5F. Phase 5B only adds: inbound conversation listing + filters,
internal notes (never sent to the customer), mark-read, safe-field
conversation update, and a per-conversation manual template send that
routes through Phase 5A's `queue_template_message`.

### Quick smoke

```bash
# Aggregate inbox snapshot (admin / operations / viewer all read).
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/api/whatsapp/inbox/

# Add an internal note (operations+).
curl -X POST -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  http://localhost:8000/api/whatsapp/conversations/<id>/notes/ \
  -d '{"body":"customer asked for callback"}'

# Mark conversation read (operations+).
curl -X POST -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/whatsapp/conversations/<id>/mark-read/

# Manual template send (operations+).
curl -X POST -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  http://localhost:8000/api/whatsapp/conversations/<id>/send-template/ \
  -d '{"actionKey":"whatsapp.payment_reminder","variables":{"customer_name":"Aditi","context":"₹499"}}'

# WhatsApp-only customer timeline.
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/api/whatsapp/customers/<customer_id>/timeline/
```

The frontend `/whatsapp-inbox` page refreshes itself in real time via
the existing Phase 4A `/ws/audit/events/` channel filtered on
`whatsapp.*` audit kinds — no new WebSocket route was added.

## Phase 5C — WhatsApp AI Chat Sales Agent

The agent runs automatically on every inbound but **auto-reply is OFF
by default** (`WHATSAPP_AI_AUTO_REPLY_ENABLED=false`). With auto-reply
off, every inbound still produces a stored AI suggestion + audit row;
operators can review via `GET /api/whatsapp/conversations/{id}/ai-runs/`
and trigger the same path manually with `POST .../run-ai/`.

### Local dev quick checks

```bash
# Inspect the global runtime state.
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/api/whatsapp/ai/status/

# Toggle a single conversation's AI mode (operations+).
curl -X PATCH -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  http://localhost:8000/api/whatsapp/conversations/<id>/ai-mode/ \
  -d '{"aiEnabled": true, "aiMode": "auto"}'

# Manual trigger of the orchestrator.
curl -X POST -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/whatsapp/conversations/<id>/run-ai/

# Recent AI events for the conversation.
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/api/whatsapp/conversations/<id>/ai-runs/

# Operator-driven handoff and resume.
curl -X POST -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  http://localhost:8000/api/whatsapp/conversations/<id>/handoff/ -d '{"reason":"manual review"}'
curl -X POST -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/whatsapp/conversations/<id>/resume-ai/
```

### Enabling auto-reply in production

1. Set `AI_PROVIDER=openai` and `OPENAI_API_KEY` in `.env.production`.
2. Sync at least the locked greeting template (`whatsapp.greeting`) — the agent fails closed otherwise.
3. Verify `Claim` rows exist for the products you sell (the agent refuses product-specific text without them).
4. Flip `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` and restart the backend container.
5. Watch `whatsapp.ai.run_completed` / `whatsapp.ai.reply_auto_sent` audit rows for the first hour. If anything looks off, run `POST /conversations/{id}/handoff/` to force-escalate.

Locked safety (still in force at the application layer):

- No medical-emergency replies.
- No freeform claims outside `apps.compliance.Claim.approved`.
- No discount on first ask.
- 50% total discount cap is non-negotiable.
- Order booking requires explicit customer confirmation in the latest inbound.
- No shipment / dispatch from chat in Phase 5C.
- CAIO can never originate a customer-facing send.

## Production deploy (Hostinger VPS)

For the live `ai.nirogidhara.com` deployment see
[`docs/DEPLOYMENT_VPS.md`](DEPLOYMENT_VPS.md). Highlights:

- Six isolated containers under Docker Compose project name
  `nirogidhara-command` (Postgres / Redis / Daphne backend / Celery worker
  / Celery beat / Nginx serving the Vite SPA).
- One host port: `18020 → 80`. The host Nginx (or Hostinger Traefik)
  terminates TLS and proxies `ai.nirogidhara.com → 127.0.0.1:18020`.
- All `*_MODE` env vars default to `mock` / `disabled` so the first
  deploy never sends a live message.
- Existing Postzyo / OpenClaw containers must not be touched.

The runbook covers DNS, TLS via Certbot, smoke tests, backups, security
checklist, and shared-VPS resource notes.

## Production infra targets (for Phase 4+ deployment — NOT shipped yet)

The repo currently runs on SQLite + Celery eager mode + no Redis. The
target production topology is:

| Component | Target | Notes |
| --- | --- | --- |
| Database | **Postgres 15+** | Set `DATABASE_URL=postgres://...` in `backend/.env` and `pip install "psycopg[binary]"`. Run `python manage.py migrate`. |
| Cache + broker | **Redis 7+** | `CELERY_BROKER_URL` + `CELERY_RESULT_BACKEND`. Use a managed Redis on the prod VPS. **Never** point dev at production Redis. |
| Worker | `celery -A config worker --loglevel=info` | One systemd unit per worker. |
| Scheduler | `celery -A config beat --loglevel=info` | One systemd unit. Fires `run_daily_ai_briefing_task` at 09:00 + 18:00 IST. |
| Real-time (Phase 4A) | **Django Channels** + `daphne` ASGI worker | WebSocket channel layer backed by Redis. |
| Reverse proxy | **Nginx** | Terminates TLS, proxies HTTP + WebSocket upgrades. |
| TLS | **Let's Encrypt** via certbot | Auto-renew via systemd timer. |
| Domain | Bound by ops in `DJANGO_ALLOWED_HOSTS` + `CORS_ALLOWED_ORIGINS` | |
| Static / media | Local volume now; S3 / Cloudflare R2 in Phase 7 multi-tenant. | `python manage.py collectstatic`. |
| Backups | Daily `pg_dump` + offsite copy | Plus periodic test restore. |
| Logs | Standard `LOGGING` to stdout; Nginx access log | Aggregate to Loki / Datadog when ops decides. |
| Health checks | `/api/healthz/` | Used by load balancer / uptime monitor. |
| Secrets | `backend/.env` (gitignored) | All gateway + AI keys live here. **Never** commit. |

Deployment automation is intentionally **not implemented** in Phase 3E —
this section documents the target so the ops handoff is unambiguous.
Phase 4+ may add a `docker-compose.prod.yml` and an Ansible / Fabric
playbook once the VPS is provisioned.

## Common issues

| Symptom | Fix |
| --- | --- |
| Frontend pages load but data is mock-only | Check the dev console for `[api] Falling back…` warnings. Backend is probably down or `VITE_API_BASE_URL` is wrong. |
| `CORS` error in browser | Add the frontend origin to `CORS_ALLOWED_ORIGINS` in `backend/.env`. Default covers `http://localhost:8080` and `http://127.0.0.1:8080`. |
| `relation "..." does not exist` on Postgres | Run `python manage.py migrate`. |
| `OperationalError: no such table` | Same — run migrations. |
| `python` command not found on Windows | Use `py -3.10` or install Python 3.10+ from python.org. |
| `npm test` hangs | The Vitest run completes in ~7s. If it hangs there's likely a stale process — `Ctrl+C` and retry. |

## Phase 7D - Razorpay Controlled Pilot one-shot TEST execution diagnostics (post-rollback, read-only)

Phase 7D was executed once on 2026-05-07 (`order_SmThqpK6sc6Dhs`,
attempt id 1, rolled back). The CLI execute path is **never** re-run
in this runbook. **Phase 7D-Hotfix-1 (structured UTC window guard)
is SHIPPED**; both `execute_razorpay_controlled_pilot_test_order`
and `execute_single_razorpay_test_order` now refuse to dispatch
unless the Director sign-off carries structured `BEGIN_UTC=<ISO-Z>`
/ `END_UTC=<ISO-Z>` markers, the window length is ≤ 15 min, the
window is fresh (≤ 24h old), and `now ∈ [window_start,
window_end]` at runtime. Historical Phase 7D attempt id 1 stays
`NULL` on the new `recorded_signoff_window_*` fields and **MUST
NOT be edited** — it is the canonical legacy free-text row that
Phase 7E acknowledges via
`--acknowledge-source-phase7d-window-violation`.

```bash
# Read-only readiness; no provider call, no business mutation
python manage.py inspect_razorpay_controlled_pilot_execution_readiness \
    --json --no-audit

# List the attempt history (whitelisted summary; never raw provider response)
python manage.py inspect_razorpay_controlled_pilot_execution_attempts \
    --limit 25 --json
```

**Do NOT** run `execute_razorpay_controlled_pilot_test_order` from
this runbook. Director-approved one-shot execution requires a fresh
dated written directive AND Phase 7D-Hotfix-1 to ship first.

## Phase 7E - WhatsApp Internal Notification Readiness Gate diagnostics (read-only)

Phase 7E is gate-only. It never sends WhatsApp, never queues, never
calls Meta Cloud, never calls Delhivery, never creates a shipment /
AWB / payment link, never captures, never refunds, never mutates
real business rows, never edits any `.env*` file. Approval flips
status to `approved_for_future_phase7f_or_7e_send_review` only — it
does NOT enable any send path.

```bash
# 1. Read-only readiness
python manage.py inspect_razorpay_whatsapp_internal_notification_readiness \
    --json --no-audit

# 2. Read-only preview from a Phase 7D rolled-back attempt (no row creation)
python manage.py preview_razorpay_whatsapp_internal_notification_gate \
    --attempt-id 1 --json

# 3. Prepare a Phase 7E gate (creates ONE gate row per Phase 7D attempt)
python manage.py prepare_razorpay_whatsapp_internal_notification_gate \
    --attempt-id 1 --json
# Requires PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED=true.
# Idempotent on the source Phase 7D attempt id.

# 4. Dry-run rehearsal (Claim-Vault grounding + invariant guard)
python manage.py dry_run_razorpay_whatsapp_internal_notification_gate \
    --gate-id <ID> --json

# 5. Rollback-dry-run rehearsal (proves no row leaked between rehearsals)
python manage.py rollback_dry_run_razorpay_whatsapp_internal_notification_gate \
    --gate-id <ID> --reason "Rehearsal complete" --json

# 6. Approve the gate (status -> approved_for_future_phase7f_or_7e_send_review)
# - Reason MUST be non-empty.
# - Director sign-off MUST contain BEGIN_UTC=... / END_UTC=... markers
#   AND literally reference phase7d_attempt_id_<ID>.
# - Review window length must be <= 24h.
# - For legacy free-text source Phase 7D signoff (every existing pre-Hotfix-1
#   attempt is): set --acknowledge-source-phase7d-window-violation AND
#   include literal token "acknowledged_phase7d_window_violation_ref_attempt_<ID>"
#   in the --reason body.
python manage.py approve_razorpay_whatsapp_internal_notification_gate \
    --gate-id <ID> \
    --reason "Director sign-off Phase 7E review. acknowledged_phase7d_window_violation_ref_attempt_1" \
    --director-signoff "Director sign-off Phase 7E review window. phase7d_attempt_id_1 BEGIN_UTC=2026-05-08T09:00:00Z END_UTC=2026-05-08T10:00:00Z" \
    --acknowledge-source-phase7d-window-violation \
    --json

# 7. Reject (only valid from draft / pending_manual_review)
python manage.py reject_razorpay_whatsapp_internal_notification_gate \
    --gate-id <ID> --reason "Director paused future-send review" --json

# 8. List gates (read-only summary)
python manage.py inspect_razorpay_whatsapp_internal_notification_gates \
    --limit 25 --json
```

**Do NOT** add a `--send` flag, **do NOT** invoke any
`apps.whatsapp.services.send_*` helper, **do NOT** call Meta Cloud,
**do NOT** edit `.env.production`. Phase 7E is gate-only by design.

## Phase 7F - Delhivery / Courier Controlled Readiness Gate diagnostics (read-only)

Phase 7F is gate-only. It never calls the Delhivery API, never
creates a `Shipment` / `WorkflowStep` / `RescueAttempt` row, never
creates an AWB, never books a pickup, never generates a courier
label, never sends or queues WhatsApp, never calls Meta Cloud /
Razorpay / Vapi, never sends a customer notification, never
mutates real business rows, never edits any `.env*` file.
Approval flips status to
`approved_for_future_phase7g_or_courier_execution_review` only —
it does NOT enable any provider call. Phase 7G (live courier
execution) requires a separate Director directive AND a future
"execute-window guard for Delhivery" extension reusing
`apps.saas.utc_window.validate_within_director_window` (15-minute
cap, mirrors Phase 7D-Hotfix-1).

```bash
# 1. Read-only readiness
python manage.py inspect_delhivery_courier_readiness \
    --json --no-audit

# 2. Read-only preview from a Phase 7E approved gate (no row creation)
python manage.py preview_delhivery_courier_readiness_gate \
    --phase7e-gate-id 1 --json

# 3. Prepare a Phase 7F gate (creates ONE gate row per Phase 7E gate)
python manage.py prepare_delhivery_courier_readiness_gate \
    --phase7e-gate-id 1 --json
# Requires PHASE7F_COURIER_READINESS_GATE_ENABLED=true.
# Idempotent on the source Phase 7E gate id.
# Refuses if DELHIVERY_MODE=live, kill switch off, or Hotfix-1 absent.

# 4. Dry-run rehearsal (invariant guard + Shipment leak check)
python manage.py dry_run_delhivery_courier_readiness_gate \
    --gate-id <ID> --json

# 5. Rollback-dry-run rehearsal (proves no row leaked between rehearsals)
python manage.py rollback_dry_run_delhivery_courier_readiness_gate \
    --gate-id <ID> --reason "Rehearsal complete" --json

# 6. Approve the gate (status -> approved_for_future_phase7g_or_courier_execution_review)
# - Reason MUST be non-empty.
# - NO --director-signoff argument.
# - Refuses unless dry_run_passed=True AND rollback_dry_run_passed=True
#   AND phase7d_hotfix_1_present=True (re-checked at approve time).
python manage.py approve_delhivery_courier_readiness_gate \
    --gate-id <ID> \
    --reason "Director Phase 7F approve" \
    --json

# 7. Reject (only valid from draft / pending_manual_review)
python manage.py reject_delhivery_courier_readiness_gate \
    --gate-id <ID> --reason "Director paused future-courier review" --json

# 8. List gates (read-only summary)
python manage.py inspect_delhivery_courier_readiness_gates \
    --limit 25 --json
```

**Do NOT** add a `--send` / `--book` / `--create-awb` flag, **do
NOT** invoke any `apps.shipments.integrations.delhivery_client`
helper, **do NOT** call `apps.shipments.services.create_shipment`,
**do NOT** edit `.env.production`. Phase 7F is gate-only by
design. Phase 7G (one-shot Delhivery TEST/MOCK execution) is the
only currently approved design path in this controlled Phase 7
chain that may later issue one Delhivery TEST/MOCK API request
after fresh Director approval. Phase 7G-Live (real customer
courier execution) remains NOT approved.

### Phase 7G — One-shot Delhivery TEST/MOCK Courier Execution Gate

Phase 7G ships the one-shot Delhivery TEST/MOCK courier execution
capability (CLI-only execution path; **never run on the VPS**;
**no `Shipment` row at execute time**). Provider/AWB summary
lives on `RazorpayCourierExecutionAttempt.provider_object_id` +
`safe_response_summary` only — the existing
`apps.shipments.Shipment` model has a plain `customer` CharField
that would surface synthetic Phase 7G rows in operator dashboards
/ RTO boards / shipment listings, so Phase 7G deliberately writes
NO Shipment row.

The execute path lives behind three locked-OFF env flags
(`PHASE7G_COURIER_EXECUTION_ENABLED=false`,
`PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION=false`,
`PHASE7G_ALLOW_DELHIVERY_TEST_AWB=false`). The
`execute_delhivery_courier_one_shot` command is the only CLI
command that may dispatch — it refuses unless every flag is
`true`, the Director sign-off mentions the source Phase 7F gate
id, the operator name is non-empty, the
`--mode-acknowledgement` matches the live `DELHIVERY_MODE` ∈
{`mock`, `test`} (live is refused), the operator acknowledges
record-only rollback, the kill switch is enabled, the source
chain Phase 7F → 7E → 7D → 7B → 6T is green, and no prior
provider call has been recorded for this attempt (idempotency
lock).

```bash
# 1. Read-only readiness
python manage.py inspect_delhivery_courier_execution_readiness \
    --json --no-audit

# 2. Read-only preview from a Phase 7F approved gate (no row creation)
python manage.py preview_delhivery_courier_execution_attempt \
    --gate-id <PHASE7F_GATE_ID> --json

# 3. Prepare a Phase 7G attempt (creates ONE attempt row per Phase 7F gate)
python manage.py prepare_delhivery_courier_execution_attempt \
    --gate-id <PHASE7F_GATE_ID> --json
# Requires PHASE7G_COURIER_EXECUTION_ENABLED=true.
# Idempotent on the source Phase 7F gate id.
# Refuses if DELHIVERY_MODE=live, kill switch off, or any
# WhatsApp / Phase 7D / Phase 6K execute flag is on.
#
# Phase 7G-Hotfix-2 (safe retry after pre-window block): if the
# LATEST attempt for this gate is `rolled_back_recorded` AND
# every provider / business / send boolean is False AND
# `executed_at is None` (e.g. the previous attempt was blocked by
# the Hotfix-1 structured UTC window guard before the Delhivery
# wrapper ran), re-running prepare mints a FRESH retry row with
# idempotency key
# `phase7g::courier_execution::phase7f_gate::<gate>::retry::<N>`
# instead of returning the terminal row. The original attempt is
# never mutated. Terminal attempts that DID touch the provider
# (`executed`, `failed`, or `rolled_back_recorded` with any
# provider/business boolean True) refuse auto-retry with
# `nextAction=phase7g_attempt_terminal_manual_review_required` -
# manual operator review is required so the on-call human can
# decide whether an AWB landed.

# 4. Approve the attempt (status -> approved_for_one_shot_courier_test_or_live_review)
# - Reason MUST be non-empty.
# - Refuses unless PHASE7G_COURIER_EXECUTION_ENABLED=true.
# - Approval does NOT enable any provider call.
python manage.py approve_delhivery_courier_execution_attempt \
    --attempt-id <ID> \
    --reason "Director Phase 7G approve" \
    --json

# 5. Reject (only valid from draft / pending_director_signoff /
#    approved_for_one_shot_run / blocked)
python manage.py reject_delhivery_courier_execution_attempt \
    --attempt-id <ID> --reason "Director paused live execution" --json

# 6. List attempts (read-only summary)
python manage.py inspect_delhivery_courier_execution_attempts \
    --limit 25 --json
```

**The `execute_delhivery_courier_one_shot` command is documented
for completeness but MUST NOT be run during normal operations.**
It requires the three Phase 7G env flags AND
`--confirm-one-shot-courier-execution` AND `--director-signoff`
mentioning the Phase 7F gate id AND `--operator-name` AND
`--mode-acknowledgement` matching the live `DELHIVERY_MODE` ∈
{`mock`, `test`} AND `--rollback-record-only-acknowledged`.
**Phase 7G-Hotfix-1:** the `--director-signoff` body MUST also
contain literal `BEGIN_UTC=<ISO-8601-UTC-Z>` and
`END_UTC=<ISO-8601-UTC-Z>` markers, the parsed window length must
be `≤ 15 minutes`, the window must be fresh (`window_start` not
older than 24h), `END_UTC > BEGIN_UTC`, and
`datetime.now(tz=UTC)` must fall inside `[window_start,
window_end]` at runtime — refusal happens before the lazy
`_create_awb_via_dedicated_wrapper` import + Delhivery client
touch. Free-text-only sign-off is refused. On success the parsed
window is persisted via `recorded_signoff_window_valid=True` +
`recorded_signoff_window_start_utc` +
`recorded_signoff_window_end_utc` on the attempt row. It calls
the Delhivery client exactly once via the lazy-import
`_create_awb_via_dedicated_wrapper` and records the AWB / status
/ tracking-url summary on the attempt row. It writes NO
`Shipment` / `WorkflowStep` / `RescueAttempt` row, never books a
courier pickup separately, never generates / prints a courier
label, never sends or queues WhatsApp, never calls Meta Cloud /
Razorpay / Vapi, never sends a customer notification, never
mutates real `Order` / `Payment` / `Customer` / `Lead` /
`DiscountOfferLog` rows.

```bash
# Record-only rollback (NEVER calls Delhivery cancel)
python manage.py rollback_delhivery_courier_execution_attempt \
    --attempt-id <ID> \
    --reason "Director-directed rollback" \
    --json
```

`rollback_status` flips to `recorded_only_no_provider_cancel`;
the value `completed` is intentionally not in the enum.

**Do NOT** invoke `apps.shipments.integrations.delhivery_client`
from anywhere outside `_create_awb_via_dedicated_wrapper`, **do
NOT** call `apps.shipments.services.create_shipment`, **do NOT**
add a `--send-whatsapp` / `--book-pickup` / `--generate-label`
flag, **do NOT** edit `.env.production`. Phase 7G-Live (real
customer courier execution) remains NOT approved.

### Phase 7H — Final Audit / Evidence Lock for Completed Phase 7G Execution

Phase 7H is **lock-only**. It snapshots the immutable fields off a
completed Phase 7G TEST/MOCK courier execution attempt (status =
`rolled_back_recorded`, `provider_call_attempted=True`,
`awb_created=True`, all locked-False booleans still `False`) into a
separate `RazorpayCourierExecutionEvidenceLock` row. Approval flips
status to `locked` only — it does NOT authorize any live execution.
Phase 7H NEVER calls Delhivery, never creates a `Shipment` /
AWB row, never sends or queues WhatsApp, never calls Meta Cloud /
Razorpay / Vapi, never sends a customer notification, never mutates
real business rows.

```bash
# 1. Read-only readiness
python manage.py inspect_phase7h_courier_execution_evidence_lock \
    --json --no-audit

# 2. Read-only preview from a completed Phase 7G attempt (no row creation)
python manage.py preview_phase7h_courier_execution_evidence_lock \
    --attempt-id <PHASE7G_ATTEMPT_ID> --json

# 3. Prepare a Phase 7H evidence-lock row (one per attempt; idempotent)
python manage.py prepare_phase7h_courier_execution_evidence_lock \
    --attempt-id <PHASE7G_ATTEMPT_ID> --json

# 4. Approve (status -> locked). Mandatory non-empty reason.
python manage.py approve_phase7h_courier_execution_evidence_lock \
    --lock-id <ID> --reason "Director Phase 7H lock" --json

# 5. Reject (only from draft / pending_manual_review / blocked).
python manage.py reject_phase7h_courier_execution_evidence_lock \
    --lock-id <ID> --reason "Director paused lock review" --json

# 6. Archive (after locked / rejected).
python manage.py archive_phase7h_courier_execution_evidence_lock \
    --lock-id <ID> --reason "Director archive" --json
```

### Phase 7E-Live-A — Internal Allowed-list WhatsApp One-shot Send Gate

Phase 7E-Live-A is the **only currently approved design path** for a
real Meta Cloud WhatsApp HTTP send in this controlled Phase 7 chain
after fresh Director approval. The recipient MUST be on
`WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` (stored as last-4 only);
the template MUST be an approved Meta template with Claim Vault
grounding; no freeform medical text. Execute path is **CLI-only**
and requires `PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED=true` +
`WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` + a fresh Director
sign-off with structured `BEGIN_UTC=` / `END_UTC=` markers (≤ 15
min; reuses `apps.saas.utc_window.validate_within_director_window`)
+ non-empty operator name + kill switch enabled + every broad
WhatsApp automation flag (`WHATSAPP_AI_AUTO_REPLY_ENABLED` /
`WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED` /
`WHATSAPP_CALL_HANDOFF_ENABLED` /
`WHATSAPP_RESCUE_DISCOUNT_ENABLED` /
`WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED` /
`WHATSAPP_REORDER_DAY20_ENABLED`) off + no prior provider call.

```bash
# 1. Read-only readiness
python manage.py inspect_phase7e_live_internal_whatsapp_send_readiness \
    --json --no-audit

# 2. Read-only preview from an approved Phase 7E gate
python manage.py preview_phase7e_live_internal_whatsapp_send \
    --gate-id <PHASE7E_GATE_ID> --json

# 3. Prepare an internal send attempt (one per Phase 7E gate; idempotent)
python manage.py prepare_phase7e_live_internal_whatsapp_send \
    --gate-id <PHASE7E_GATE_ID> \
    --template-name "nrg_internal_test_intro" \
    --template-language "en" \
    --allowed-recipient-last4 NNNN \
    --json
#
# Phase 7E-Live-A-Hotfix-2 (safe retry after pre-hotfix wrapper
# failure): if the LATEST attempt for this gate is
# `rollback_recorded` / `failed` AND `provider_message_id` is empty
# AND every Meta-side boolean is False AND the warnings list
# contains the known pre-hotfix marker
# `Meta Cloud client does not expose send_template_message`,
# re-running prepare mints a FRESH retry row with idempotency key
# `phase7e_live::internal_send::phase7e_gate::<gate>::retry::<N>`
# instead of returning the terminal row. The original attempt is
# never mutated. Terminal attempts that DID create / queue a
# WhatsApp message, that DID touch a real customer phone, that
# carry a `provider_message_id`, or that failed with any other
# reason refuse auto-retry with
# `nextAction=phase7e_live_attempt_terminal_manual_review_required`
# - manual operator review is required so the on-call human can
# decide whether a real WhatsApp landed.
#
# Phase 7E-Live-A-Hotfix-3 (safe retry after no-provider manual
# rollback before execution): if the LATEST attempt for this gate
# is `rollback_recorded` AND `provider_call_attempted=False` AND
# `meta_cloud_call_attempted=False` AND `executed_at is None` AND
# `failed_at is None` AND the locked-False contract still holds
# (every Meta-side / business-side boolean still False,
# `provider_message_id` / `provider_status` empty), re-running
# prepare ALSO mints a fresh retry row (sequence increments to 3
# when both attempt 1 = wrapper-failure and attempt 2 = no-provider
# rollback already exist). Uses the same
# `phase7e.internal_send.retry_prepared` audit kind as Hotfix-2.
# `provider_call_attempted=True`, `meta_cloud_call_attempted=True`,
# `executed_at is not None`, or `failed_at is not None` with an
# unknown failure reason still refuse auto-retry.

# 4. Approve (state transition only; requires reason + signoff)
python manage.py approve_phase7e_live_internal_whatsapp_send \
    --attempt-id <ID> \
    --reason "Director approve" \
    --director-signoff "Director PS approve." \
    --json

# 5. THE ONLY MET-A-CLOUD-TOUCHING COMMAND - never run during normal ops.
# Requires three Phase 7E-Live env flags + structured BEGIN_UTC/END_UTC
# (≤ 15 min) + operator name + kill switch + all broad-automation flags off.
python manage.py execute_phase7e_live_internal_whatsapp_send \
    --attempt-id <ID> \
    --confirm-internal-whatsapp-send \
    --operator-name "Prarit Sidana" \
    --director-signoff "...BEGIN_UTC=2026-05-09T10:00:00Z END_UTC=2026-05-09T10:10:00Z..." \
    --json

# 6. Record-only rollback (never calls Meta Cloud delete/cancel).
python manage.py rollback_phase7e_live_internal_whatsapp_send \
    --attempt-id <ID> --reason "Director rollback" --json
```

**Phase 7E-Live-A NEVER sends to a real customer phone (recipient
must be on `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`); NEVER queues
broad automation; NEVER calls Delhivery / Razorpay / Vapi; NEVER
sends a customer notification; NEVER mutates real `Order` /
`Payment` / `Customer` / `Lead` / `DiscountOfferLog` rows; NEVER
sends freeform medical text (approved Meta template only); NEVER
edits any `.env*` file.**

### Phase 7E-Live-B — Real Customer WhatsApp One-shot Send Gate

Phase 7E-Live-B is the **CLI-only real-customer WhatsApp one-shot
gate**. It may send exactly one approved Phase 5A template to
exactly one real customer for each approved gate. There is no
rollback because WhatsApp messages cannot be unsent.

Safety contract:
- No frontend approve / execute / cancel buttons.
- No broadcast, campaign, AI freeform, or bulk send.
- `.env.production` is not edited; `PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=true`
  must be passed with a runtime env prefix for an approved run.
- Templates are limited to `confirmation_reminder`,
  `delivery_reminder`, `rto_rescue`, `reorder_reminder`,
  `payment_reminder`, and `usage_explanation`.
- Approval and execute require kill switch enabled, explicit
  confirmation, non-empty operator, no prior executed gate, and a
  Director signoff containing `phase7e_live_b_gate_id_<ID>`,
  `target_phone_<last4>`, `template_<name>`,
  `phase7eLiveBApproval`, plus structured `BEGIN_UTC=` /
  `END_UTC=` markers validated by
  `apps.saas.utc_window.validate_within_director_window` (15-minute
  cap, now inside the window).
- Execute calls `apps.whatsapp.services.queue_template_message(...,
  override_limited_test_mode=True)` for this one CLI path only; all
  existing consent, approved-template, Claim Vault, approval matrix,
  CAIO, idempotency, and audit gates stay in force.

```bash
# 1. Read-only readiness.
python manage.py inspect_phase7e_live_b_real_customer_gate --json --no-audit

# 2. Prepare one draft gate.
python manage.py prepare_phase7e_live_b_real_customer_gate \
    --target-phone "+91XXXXXXXXXX" \
    --target-customer-name "Customer Name" \
    --template-name payment_reminder \
    --template-params '{"customer_name":"Customer Name"}' \
    --operator-name "Prarit Sidana" \
    --json

# 3. Approve one gate. BEGIN/END must be current and <= 15 minutes.
BEGIN=$(date -u -d "-1 minute" +"%Y-%m-%dT%H:%M:%SZ")
END=$(date -u -d "+12 minutes" +"%Y-%m-%dT%H:%M:%SZ")
PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=true \
python manage.py approve_phase7e_live_b_real_customer_gate \
    --gate-id <GATE_ID> \
    --operator-name "Prarit Sidana" \
    --director-signoff "phase7eLiveBApproval phase7e_live_b_gate_id_<GATE_ID> target_phone_<LAST4> template_<TEMPLATE> BEGIN_UTC=${BEGIN} END_UTC=${END}" \
    --confirm-phase7e-live-b-real-customer-send \
    --json

# 4. Execute the one-shot send. Use a fresh current window.
BEGIN=$(date -u -d "-1 minute" +"%Y-%m-%dT%H:%M:%SZ")
END=$(date -u -d "+12 minutes" +"%Y-%m-%dT%H:%M:%SZ")
PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=true \
python manage.py execute_phase7e_live_b_real_customer_send \
    --gate-id <GATE_ID> \
    --operator-name "Prarit Sidana" \
    --director-signoff "phase7eLiveBApproval phase7e_live_b_gate_id_<GATE_ID> target_phone_<LAST4> template_<TEMPLATE> BEGIN_UTC=${BEGIN} END_UTC=${END}" \
    --confirm-phase7e-live-b-real-customer-send \
    --json

# 5. Cancel only before execute. Executed gates refuse cancellation.
python manage.py cancel_phase7e_live_b_real_customer_gate \
    --gate-id <GATE_ID> \
    --reason "Director cancelled before send" \
    --operator-name "Prarit Sidana" \
    --json
```

Read-only operator visibility:

```bash
curl -sS "$BASE_URL/api/v1/saas/phase7e-live-b/gates/?limit=25"
```

The `/saas-admin` page shows only masked gate rows. It cannot
approve, execute, or cancel a Phase 7E-Live-B gate.

### Phase 7I — Final Phase 7 Payment + WhatsApp + Courier Audit Lock

Phase 7I is **lock-only meta-audit** over the full controlled
Phase 7 chain: Phase 7D Razorpay TEST execution + Phase 7E-Live-A
internal allowed-list WhatsApp one-shot send + Phase 7G Delhivery
TEST/MOCK courier execution + Phase 7H courier execution evidence
lock. It snapshots the immutable fields off all four source
records into a single `RazorpayPhase7FinalAuditLock` row. Approval
flips status to `locked` only — it does NOT authorize any live
execution. Phase 7I NEVER calls Razorpay / Meta Cloud / Delhivery
/ Vapi, NEVER sends or queues WhatsApp, NEVER creates a `Shipment`
/ AWB / payment link, NEVER captures / refunds, NEVER sends a
customer notification, NEVER mutates real business rows.

```bash
# 1. Read-only readiness composition.
python manage.py inspect_phase7i_final_audit_lock \
    --json --no-audit

# 2. Read-only preview from Phase 7G + Phase 7H sources (auto-
#    resolves Phase 7E-Live-A and Phase 7D from the chain; pass
#    explicitly when the chain has multiple eligible Phase 7E
#    attempts).
python manage.py preview_phase7i_final_audit_lock \
    --phase7g-attempt-id <PHASE7G_ATTEMPT_ID> \
    --phase7h-evidence-lock-id <PHASE7H_LOCK_ID> \
    [--phase7e-live-attempt-id <PHASE7E_LIVE_ATTEMPT_ID>] \
    [--phase7d-attempt-id <PHASE7D_ATTEMPT_ID>] --json

# 3. Prepare a Phase 7I row (one per Phase 7H lock; idempotent).
python manage.py prepare_phase7i_final_audit_lock \
    --phase7g-attempt-id <PHASE7G_ATTEMPT_ID> \
    --phase7h-evidence-lock-id <PHASE7H_LOCK_ID> \
    [--phase7e-live-attempt-id <PHASE7E_LIVE_ATTEMPT_ID>] \
    [--phase7d-attempt-id <PHASE7D_ATTEMPT_ID>] --json

# 4. Lock the Phase 7I row (status -> locked). Mandatory non-empty
#    reason. No provider call, no business mutation, no live
#    execution enabled.
python manage.py approve_phase7i_final_audit_lock \
    --lock-id <ID> \
    --reason "Director Phase 7I final audit lock" --json

# 5. Reject (only from draft / pending_manual_review / blocked).
python manage.py reject_phase7i_final_audit_lock \
    --lock-id <ID> \
    --reason "Director paused final-audit review" --json

# 6. Archive (after locked / rejected).
python manage.py archive_phase7i_final_audit_lock \
    --lock-id <ID> --reason "Director archive" --json
```

**Phase 7I refuses to prepare unless:**
- Phase 7H lock is in `status=locked`.
- Phase 7E-Live-A attempt is `rollback_recorded` with non-empty
  `provider_message_id`, `whatsapp_message_created=True`,
  `recorded_signoff_window_valid=True`, `claim_vault_grounded=True`,
  `recipient_scope=internal_staff_allow_list`, and every customer /
  business / real-customer-phone boolean False.
- Phase 7G attempt is `rolled_back_recorded` with `awb_created=True`,
  `rollback_status=recorded_only_no_provider_cancel`, and every
  shipment / business / customer-notification boolean False.
- Phase 7D attempt is `executed` or `rolled_back` with every
  business / customer / shipment / WhatsApp / Meta-cloud / Delhivery
  / payment-link / capture / refund boolean False.
- The kill switch is enabled.

Phase 7E-Live-B gate code is shipped, but each real-customer execute
still requires a separate Director directive, runtime env prefix, and
fresh 15-minute UTC window.

### Phase 7G-Live — Real Customer Delhivery One-shot Dispatch Gate

Phase 7G-Live is the **CLI-only real-customer Delhivery one-shot
dispatch gate**. It authorises exactly one Delhivery live AWB creation
against exactly one confirmed customer order per approved gate.

Safety contract:
- No frontend approve / execute / rollback buttons.
- No bulk / auto / AI dispatch. One gate, one order.
- Only orders in stage `Confirmed` are dispatch-ready; the gate
  refuses to prepare against any other stage.
- `.env.production` is not edited; both
  `PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=true` and
  `DELHIVERY_MODE=live` must be supplied with a runtime env prefix
  for an approved run.
- Approve and execute both require kill switch enabled, explicit
  confirmation, non-empty operator, no prior executed gate against
  the same order id, and a Director signoff containing
  `phase7g_live_gate_id_<ID>`, `target_order_<ID>`,
  `phase7gLiveApproval`, plus structured `BEGIN_UTC=` / `END_UTC=`
  markers validated by
  `apps.saas.utc_window.validate_within_director_window` (15-minute
  cap, now inside the window).
- Execute calls `apps.shipments.services.create_shipment(order=...)`
  once inside `transaction.atomic()`. Locked-False flags
  `payment_mutation_made`, `order_payment_status_changed`,
  `whatsapp_sent`, and `razorpay_called` are asserted to stay False;
  any flip raises and rolls the transaction back, marking the gate
  failed.
- Rollback attempts the Delhivery cancellation API for the gate's
  AWB and records the provider result honestly. Delhivery may refuse
  if the shipment is already in transit — the gate transitions to
  `rollback_recorded` either way; the `cancellation_result` JSON is
  the truthful record.
- The kill switch helper uses the Phase 7E-Live-B Hotfix-1 pattern:
  an explicit `scope="global", enabled=False` row always wins over
  any seeded enabled default, ordered by `-pk` for determinism.

### Phase 10B — Targeted Payment Reminder Preparer

Phase 10B is a **stage-aware CLI wrapper** around the existing
Phase 7E-Live-B real-customer WhatsApp gate. It NEVER sends. It
creates a `Phase7ELiveBRealCustomerSendGate` row in `draft` status
pre-filled with payment-reminder template params; Director still
runs the existing approve + execute commands (full structured UTC
window + runtime env flags) to send.

Full Director payment-recovery playbook:

1. **Inspect the pending-payment cohort.**
   ```
   python manage.py inspect_pending_payments
   ```
   Surfaces every pending / partial payment with phone (via the
   Phase 10A Hotfix-1 fallback chain), days-pending, and last-comm
   metadata. Pick the candidate `payment_id`.

2. **Prepare the Phase 7E-Live-B gate.**
   ```
   python manage.py prepare_payment_reminder_send PAY-30125
   ```
   Stage-aware validation runs here:
   - **ALLOWED stages** (`Confirmed`, `Order Punched`) — proceeds
     silently.
   - **WARN stages** (`Interested`, `Confirmation Pending`) —
     refuses unless `--force` is passed. With `--force` a
     `phase10b.payment_reminder.warn_forced` audit row is written.
   - **BLOCKED stages** (`RTO`, `Out for Delivery`, `Cancelled`,
     `Delivered`, `Dispatched`, `Payment Link Sent`, `New Lead`,
     `internal_sandbox`) — refuses with exit 1; no gate row is
     created.
   - Payment must be `Pending` or `Partial`, amount > 0,
     `payment_url` non-empty.
   - Phone must resolve via Payment → Order → Customer fallback
     AND not be the internal sandbox placeholder `"0000000000"`.
   - On success: prints the new Phase 7E-Live-B gate id and the
     exact next commands. The `phase10b.payment_reminder.prepared`
     audit row records the prepare event with the gate id, stage,
     and operator note.

3. **Inspect the prepared gate.**
   ```
   python manage.py inspect_phase7e_live_b_real_customer_gate
   ```
   Verifies the gate is in `draft` status and that every blocker
   (env flag off, kill switch, etc.) is visible before approval.

4. **Approve with structured UTC window + Director signoff.**
   ```
   PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=true \
   python manage.py approve_phase7e_live_b_real_customer_gate \
     --gate-id <GATE_ID> \
     --director-signoff 'phase7e_live_b_gate_id_<GATE_ID> target_phone_<LAST4> template_payment_reminder phase7eLiveBApproval BEGIN_UTC=<ISO> END_UTC=<ISO>' \
     --operator-name '<DIRECTOR_NAME>' \
     --confirm-phase7e-live-b-real-customer-send
   ```
   Director signoff must literally contain all four phrases plus
   structured `BEGIN_UTC=` / `END_UTC=` markers; 15-minute cap;
   now-inside-window required.

5. **Execute the one-shot send.**
   ```
   PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=true \
   python manage.py execute_phase7e_live_b_real_customer_send \
     --gate-id <GATE_ID> \
     --director-signoff '<SAME STRUCTURED SIGNOFF>' \
     --operator-name '<DIRECTOR_NAME>' \
     --confirm-phase7e-live-b-real-customer-send
   ```
   Execute is the only step that actually queues the WhatsApp
   message. It calls `queue_template_message(...,
   override_limited_test_mode=True)` for this one CLI path only;
   consent / approved-template / Claim Vault / approval matrix /
   CAIO / idempotency / audit gates all stay in force. No rollback
   exists because WhatsApp cannot be unsent.

Phase 7E-Live-B CLI signatures (for reference):

```
inspect_phase7e_live_b_real_customer_gate [--no-audit] [--json]
prepare_phase7e_live_b_real_customer_gate
    --target-phone +91XXXXXXXXXX
    --target-customer-name "..."
    --template-name payment_reminder
    [--template-params '{"customer_name": "...", ...}']
    --operator-name "..."
    [--json]
approve_phase7e_live_b_real_customer_gate
    --gate-id <ID>
    --director-signoff "..."
    --operator-name "..."
    --confirm-phase7e-live-b-real-customer-send
    [--json]
execute_phase7e_live_b_real_customer_send
    --gate-id <ID>
    --director-signoff "..."
    --operator-name "..."
    --confirm-phase7e-live-b-real-customer-send
    [--json]
cancel_phase7e_live_b_real_customer_gate
    --gate-id <ID>
    --reason "..."
    --operator-name "..."
    [--json]
```

Safety contract for Phase 10B specifically:
- NEVER calls `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The defensive safety test patches all four and runs the
  CLI happy path; assert_not_called everywhere.
- NEVER mutates `Payment` / `Order` / `Customer` / `Lead` /
  `Shipment` rows (asserted with before/after counts).
- The ONE side-effect is the Phase 7E-Live-B gate row creation.
  Phase 7E-Live-B itself is a *governance* table — its `draft`
  status carries no live-customer action.
- Stage-aware refusals never create a gate row.

### Phase 10A — Pending Payments Drilldown (Diagnostics V1)

Phase 10A is the first module under the new `apps/diagnostics/`
Django app. It is **read-only** — no models, no migrations, no
mutations, no outbound calls. The Phase 9F CEO orchestration's
first real run flagged `high_pending_payments` as the #1 Director
priority (9 pending payments totalling ~₹20,440); Phase 10A is the
review surface that answers that priority without crossing the
action boundary.

Surfaces:
- `apps.diagnostics.service.list_pending_payments_drilldown` —
  pure read-only aggregation function. Reads `Payment` rows with
  status `Pending` (+ optionally `Partial`), joins with `Order` +
  `crm.Customer` + last-outbound `WhatsAppMessage` + last `Call`,
  returns rows sorted oldest-first.
- `GET /api/v1/diagnostics/pending-payments/?include_partial=true|false&limit=N&state=Delhi`
  — admin / director / superuser only. POST/PATCH/PUT/DELETE return
  405. Response: `{count, filters, results}`.
- `python manage.py inspect_pending_payments [--include-partial /
  --no-include-partial] [--limit N] [--state STATE] [--json]` —
  pretty-print to stdout or emit JSON. Useful for SSH / cron
  debugging.
- `/operations/pending-payments` frontend page — sortable table
  with client-side search; "Include Partial" toggle; "Read-only
  diagnostic" banner; no action buttons.

Field availability (discovered before coding):
- `Payment.payment_url` exists (URLField); surfaced as
  `payment_link_url`.
- `Payment.gateway_reference_id` exists; surfaced as-is.
- `Call` has no dedicated `outcome` field; `Call.status` is the
  closest action-relevant signal and is surfaced as
  `last_call_outcome`.
- `WhatsAppMessage.direction` is the inbound/outbound/system enum;
  the last-WhatsApp lookup filters to `OUTBOUND` only.

Phone-source fallback (Phase 10A Hotfix-1):
- `Payment.customer_phone` is empty for most real pending payments
  (the VPS smoke test surfaced this — only the test sandbox payment
  carried a phone). The drilldown therefore walks a fallback chain
  per row:
  1. `Payment.customer_phone` → `phone_source = "payment"`
  2. `Order.phone` → `phone_source = "order"`
  3. `crm.Customer.phone` (resolved by phone-or-name match) →
     `phone_source = "customer"`
  4. nothing found → `customer_phone = null`,
     `phone_source = "none"`
- The first non-empty value wins; empty string and `None` are
  treated identically as missing.
- Each row carries a `phone_source` field so the operator can see
  which join surfaced the number. The CLI prints
  ``+91XXXXXXXXXX (order)`` etc.; the frontend renders a small gray
  caption ``from order`` / ``from customer`` under the phone cell.
- The last-Call lookup uses the resolved phone (not just
  `Payment.customer_phone`); the last-WhatsApp lookup uses the
  resolved `crm.Customer`. Both lookups are batched per resolved
  customer / phone to keep the join cost flat.

Safety contract:
- The module NEVER imports / calls
  `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The safety test patches all four entrypoints and asserts
  no calls and stable Payment / Order / Customer / Call /
  WhatsAppMessage row counts across BOTH the API endpoint AND the
  CLI command.
- Action on pending payments still requires the existing
  approval-gated CLI workflows (Phase 7E-Live-B for real customer
  WhatsApp reminders; future Razorpay live-collect gate for
  payment-side actions). Phase 10A surfaces the records; it does
  not act on them.
- API + CLI are admin / director / superuser only. The frontend
  route lives under `/operations/pending-payments` and is not
  exposed to operations / viewer roles.

### Phase 9F — CEO AI Orchestration V1 (synthesis layer)

Phase 9F is the **synthesis layer** over the Phase 9A–9E agent
stack and is **recommendations-only**. It produces ONE daily
director briefing per task invocation aggregating the latest
snapshots from all five upstream agents into a composite business
health view. It never triggers outbound action; downstream gates
(Phase 5D / 5E / 7E-Live-B / 7G-Live) remain the only paths to a
real customer action.

Phase 9F does NOT modify or call the legacy
`ai_governance.CeoBriefing` model or its `ai-daily-briefing-morning`
/ `ai-daily-briefing-evening` scheduled tasks — they remain
untouched alongside the new Phase 9F surface.

Run shape:
- Celery beat task
  `apps.agents.ceo_orchestration.tasks.run_ceo_orchestration_agent_daily`
  scheduled at 13:00 IST (env-shiftable via
  `AI_CEO_ORCHESTRATION_DAILY_HOUR` / `_MINUTE`). Runs after
  Customer Success (08:00), RTO Prevention (09:00), CFO (10:00),
  Data Analyst (11:00), and Calling Team Leader (12:00).
- One `CeoOrchestrationSnapshot` row per invocation, one linked
  `AgentRun` (`agent="ceo"`, model `"deterministic_v1"`,
  provider `"disabled"`, `cost_usd=0`, `dry_run=True`,
  `triggered_by="celery_beat_daily"`), one
  `ceo_orchestration.snapshot.created` AuditEvent, and one
  `ceo_orchestration.daily_run.completed` summary event.

Health score formula:
- `score = clamp(70 + cfo_factor + rto_factor + cs_factor +
  data_analyst_factor + ctl_factor, 0, 100)` where each factor
  applies the agent's penalties / bonuses (CFO −15/−10/−10/−10/+5;
  RTO −min(critical*3,20)−min(high*1,10); CS −min(at_risk,10) +
  min(reorder//5,5); DA −min(active_alerts*10,30); CTL
  −min(active_alerts*5,20) excluding `all_clear` +
  `no_agent_attribution_field`). Missing agents incur −5 each.
- Tier mapping: 0–19 critical / 20–39 poor / 40–59 fair / 60–79
  good / 80–100 excellent.

Cross-cutting alerts:
- Union of every agent's alerts, excluding `all_clear`.
- Each entry: `{code, severity (critical/high/medium/low),
  source_agent, rationale}`. The severity map normalises codes
  from Phase 9C / 9D / 9E.
- For every missing upstream snapshot, one `data_gap` alert is
  added with `source_agent=<missing_agent>` (severity high).
- Final list is severity-sorted (critical → low).

Top-3 priorities:
- First 3 actionable alerts (excluding `all_clear` and
  `no_agent_attribution_field`), each with deterministic
  `recommended_action` string (internal-only). Fewer than 3
  actionable alerts → list of what's available. Zero → `[{"priority":
  "1", "issue": "all_clear", "source_agent": "none",
  "recommended_action": "Continue monitoring."}]`.

Agent status summary:
- Per-agent `{status: "ok"|"alert"|"missing", summary: <one-line
  factual>}` covering Customer Success, RTO Prevention, CFO, Data
  Analyst, Calling Team Leader. "missing" means no snapshot was
  found in the last 24h.

Briefing text:
- Multi-line factual summary covering health_score + tier,
  per-agent status, top priorities, and cross-cutting alert count.
  Internal-only. NEVER customer-facing.

Safety contract:
- The agent NEVER imports / calls
  `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The safety test patches all four entrypoints and asserts
  no calls and stable upstream snapshot row counts after a sweep
  (Phase 9F is strictly read-only over the agent layer — it must
  not add per-customer or per-order rows).
- `briefing_text` is a deterministic internal-only summary; it is
  **never** a customer-facing message.
- Kill switch uses the Phase 7E-Live-B Hotfix-1 Postgres-safe
  pattern: any `RuntimeKillSwitch(scope="global", enabled=False)`
  row wins (ordered by `-pk`) and the task exits with one
  `ceo_orchestration.daily_run.blocked` audit event.
- Sandbox mode: when
  `apps.ai_governance.sandbox.is_sandbox_enabled()` is True, the
  snapshot row and its linked AgentRun both carry the sandbox flag.
- API: `/api/v1/ceo-orchestration/snapshots/`,
  `/api/v1/ceo-orchestration/snapshots/latest/`, and
  `/api/v1/ceo-orchestration/snapshots/<id>/` are admin+ only and
  strictly read-only. POST/PATCH/DELETE return 405. The
  `/saas-admin` CEO card carries no "Approve Priority" /
  "Trigger Workflow" / "Send Briefing" / "Run Agent" /
  "Apply Recommendation" buttons.

### Phase 9E — Calling Team Leader Agent V1 (call-performance lens)

Phase 9E is the call-performance lens and is **recommendations-only**.
It produces ONE daily snapshot per task invocation summarising call
counts, connection rate, avg duration, per-agent metrics, and
transcript backlog. It never triggers outbound action.

Run shape:
- Celery beat task `apps.agents.calling_team_leader.tasks.
  run_calling_team_leader_agent_daily` scheduled at 12:00 IST
  (env-shiftable via `AI_CALLING_TEAM_LEADER_DAILY_HOUR` /
  `_MINUTE`). Runs after Customer Success (08:00), RTO Prevention
  (09:00), CFO (10:00), and Data Analyst (11:00).
- One `CallingTeamLeaderSnapshot` row per invocation, one linked
  `AgentRun` (`agent="calling_team_leader"`, model
  `"deterministic_v1"`, provider `"disabled"`, `cost_usd=0`,
  `dry_run=True`, `triggered_by="celery_beat_daily"`), one
  `calling_team_leader.snapshot.created` AuditEvent, and one
  `calling_team_leader.daily_run.completed` summary event.

Field availability (V1):
- `Call.agent` is a `CharField(max_length=80)` — per-agent metrics
  ARE supported.
- `Call.duration` stores `"m:ss"` / `"mm:ss"` / `"h:mm:ss"`. The
  service module parses it with a garbage-tolerant fallback to 0.
- `Call.outcome` does not exist — outcome breakdown groups by
  `Call.status` (Live / Queued / Completed / Missed / Failed).
- "Answered" rule (V1): `status="Completed"`.
- Transcript backlog: `Call.created_at < now - 24h` AND no
  `CallTranscriptLine` rows linked.

Anomaly thresholds (deterministic):
- `low_connection_rate` when `call_count_30d >= 10` AND
  `connection_rate_30d < 0.30`.
- `high_transcript_backlog` when backlog > 20.
- `no_calls_today` when `call_count_24h == 0` AND
  `call_count_7d > 0`.
- `agent_concentration_risk` when top agent's call_count
  > 0.70 × `call_count_30d` AND `call_count_30d > 10`.
- `no_agent_attribution_field` (informational only; never blocks
  `all_clear`) — fires only when the agent breakdown path is
  disabled.
- `all_clear` when no real problem fires.

Safety contract:
- The agent NEVER imports / calls
  `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The safety test patches all four entrypoints and asserts
  no calls and stable Call / Customer / Order row counts after a
  sweep.
- `alert_text` is a short internal rationale; it is **never** a
  customer-facing message and is **never** sent to a customer.
- Kill switch uses the Phase 7E-Live-B Hotfix-1 Postgres-safe
  pattern: any `RuntimeKillSwitch(scope="global", enabled=False)`
  row wins (ordered by `-pk`) and the task exits with one
  `calling_team_leader.daily_run.blocked` audit event.
- Sandbox mode: when
  `apps.ai_governance.sandbox.is_sandbox_enabled()` is True, the
  snapshot row and its linked AgentRun both carry the sandbox flag.
- API: `/api/v1/calling-team-leader/snapshots/`,
  `/api/v1/calling-team-leader/snapshots/latest/`, and
  `/api/v1/calling-team-leader/snapshots/<id>/` are admin+ only and
  strictly read-only. POST/PATCH/DELETE return 405. The
  `/saas-admin` Calling Team Leader card carries no "Trigger Call" /
  "Reassign Agent" / "Send Coaching Note" / "Run Agent" /
  "Auto-dial" buttons.

### Phase 9D — Data Analyst Agent V1 (operational / funnel analytics)

Phase 9D is the second **business-level** agent and is
**recommendations-only**. It produces ONE daily operational snapshot
per task invocation summarising the conversion funnel, top
geographic states, day-of-week distribution, and anomaly alert
codes. It never triggers outbound action; downstream gates (Phase
5D / 5E / 7E-Live-B / 7G-Live) remain the only paths to a real
customer action.

Run shape:
- Celery beat task
  `apps.agents.data_analyst.tasks.run_data_analyst_agent_daily`
  scheduled at 11:00 IST (env-shiftable via
  `AI_DATA_ANALYST_DAILY_HOUR` / `_MINUTE`). Runs after the Customer
  Success (08:00), RTO Prevention (09:00), and CFO (10:00) sweeps.
- One `DataAnalystSnapshot` row per invocation, one linked
  `AgentRun` (`agent="data_analyst"`, model `"deterministic_v1"`,
  provider `"disabled"`, `cost_usd=0`, `dry_run=True`,
  `triggered_by="celery_beat_daily"`), one
  `data_analyst.snapshot.created` AuditEvent, and one
  `data_analyst.daily_run.completed` summary event.

Snapshot fields:
- Funnel counts (30d): `lead_count_30d`, `call_count_30d`,
  `confirmed_order_count_30d` (stages Confirmed / Dispatched /
  Out for Delivery / Delivered), `delivered_order_count_30d`,
  `reorder_count_30d`.
- Conversion rates (0.0–1.0): `lead_to_call_rate`,
  `call_to_confirmed_rate`, `confirmed_to_delivered_rate`,
  `delivered_to_reorder_rate`. Each rate has a divide-by-zero
  guard.
- `top_states`: list of `{state, order_count, revenue}` dicts,
  capped at 5 by default, sorted by `order_count` DESC.
- `day_of_week_counts`: dict with keys `mon` through `sun`,
  zero-filled.
- `alerts` + `alert_text`: anomaly codes + short factual rationale.

Reorder rule:
- An in-window order is a reorder *unless* it is the customer's
  earliest-ever order. For each phone with at least one in-window
  order, look up `Order.objects.filter(phone=phone).order_by("created_at").first()`.
  If the earliest order is in-window: `reorder += max(0, in_window - 1)`.
  Otherwise: `reorder += in_window`.

Anomaly thresholds (deterministic):
- `conversion_drop` when any of the 4 rates < 0.10 AND the
  corresponding upstream count > 5 (small-sample false-positive
  guard).
- `geographic_concentration_shift` when top state's share > 70 %
  AND top state's `order_count` > 10.
- `dead_end_calls` when `call_count_30d > 0` AND
  `call_to_confirmed_rate < 0.05`.
- `lead_volume_drop` when `lead_count_30d == 0`.
- `all_clear` when none of the above fires.

Safety contract:
- The agent NEVER imports / calls
  `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The safety test patches all four entrypoints and asserts
  no calls and stable Lead / Call / Order / Customer row counts
  after a sweep.
- `alert_text` is a short internal rationale stored on the snapshot
  for operator review; it is **never** a customer-facing message
  and is **never** sent to a customer.
- Kill switch uses the Phase 7E-Live-B Hotfix-1 Postgres-safe
  pattern: any `RuntimeKillSwitch(scope="global", enabled=False)`
  row wins (ordered by `-pk`) and the task exits with one
  `data_analyst.daily_run.blocked` audit event.
- Sandbox mode: when
  `apps.ai_governance.sandbox.is_sandbox_enabled()` is True, the
  snapshot row and its linked AgentRun both carry the sandbox flag.
- API: `/api/v1/data-analyst/snapshots/`,
  `/api/v1/data-analyst/snapshots/latest/`, and
  `/api/v1/data-analyst/snapshots/<id>/` are admin+ only and
  strictly read-only. POST/PATCH/DELETE return 405. The
  `/saas-admin` Data Analyst card carries no "Send Report" /
  "Trigger Funnel Fix" / "Apply Discount" / "Run Agent" /
  "Auto-rebalance" buttons.

### Phase 9C — CFO Agent V1 (business-level daily snapshot)

Phase 9C is the first **business-level** agent and is
**recommendations-only**. It produces ONE daily financial snapshot
per task invocation summarising the operational state of the
business. It never triggers outbound action; downstream gates
(Phase 5D / 5E / 7E-Live-B / 7G-Live) remain the only paths to a
real customer action.

Run shape:
- Celery beat task `apps.agents.cfo.tasks.run_cfo_agent_daily`
  scheduled at 10:00 IST (env-shiftable via `AI_CFO_DAILY_HOUR` /
  `_MINUTE`). Runs after the 08:00 IST Customer Success sweep and
  the 09:00 IST RTO Prevention sweep.
- One `CfoFinancialSnapshot` row per invocation, one linked
  `AgentRun` (`agent="cfo"`, model `"deterministic_v1"`,
  provider `"disabled"`, `cost_usd=0`, `dry_run=True`,
  `triggered_by="celery_beat_daily"`), one
  `cfo.snapshot.created` AuditEvent, and one
  `cfo.daily_run.completed` summary event.

Snapshot fields:
- `revenue_24h` / `revenue_7d` / `revenue_30d`: `Sum(Payment.amount)`
  where `Payment.status=Paid` and `Payment.created_at` is within the
  rolling window.
- `order_count_24h` / `_7d` / `_30d`: `Order.objects.filter(created_at__gte=cutoff).count()`.
- `paid_count` / `partial_count` / `pending_count` + matching
  `_amount` fields: 30-day Payment status breakdown.
- `average_order_value`: 30-day `Sum(Order.amount) / Count` (₹).
- `rto_count_30d` / `rto_loss_amount_30d`: 30-day count and ₹ loss
  for `Order.stage=RTO`.
- `new_customer_count_30d` / `returning_customer_count_30d`:
  customers (phones with a matching Customer row) bucketed by
  whether they have a prior order before the 30-day window.

Anomaly thresholds (deterministic):
- `revenue_drop_24h` when `revenue_24h < revenue_7d / 7 * 0.5`.
- `rto_spike` when `rto_count_30d / order_count_30d > 15%`.
- `high_pending_payments` when `pending_count > paid_count`.
- `low_order_volume` when `order_count_24h == 0` and
  `order_count_7d > 0`.
- `all_clear` when none of the above fires.

Safety contract:
- The agent NEVER imports / calls
  `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The safety test patches all four entrypoints and asserts
  no calls and stable Order / Customer / Payment row counts after a
  sweep.
- `alert_text` is a short internal rationale stored on the snapshot
  for operator review; it is **never** a customer-facing message and
  is **never** sent to a customer.
- Kill switch uses the Phase 7E-Live-B Hotfix-1 Postgres-safe
  pattern: any `RuntimeKillSwitch(scope="global", enabled=False)`
  row wins (ordered by `-pk`) and the task exits with one
  `cfo.daily_run.blocked` audit event.
- Sandbox mode: when
  `apps.ai_governance.sandbox.is_sandbox_enabled()` is True, the
  snapshot row and its linked AgentRun both carry the sandbox flag.
- API: `/api/v1/cfo/snapshots/`, `/api/v1/cfo/snapshots/<id>/`, and
  `/api/v1/cfo/latest/` are admin+ only and strictly read-only.
  POST/PATCH/DELETE return 405. The `/saas-admin` CFO card carries
  no "Send Report" / "Trigger Refund" / "Apply Discount" /
  "Run Agent" / "Auto-collect" buttons.

### Phase 9B — RTO Prevention Agent V1

Phase 9B is a **recommendations-only** deterministic daily Celery
sweep over in-flight orders. It scores each order's return-to-origin
risk, classifies tier and lifecycle stage, and emits a structured
recommendation. The agent never triggers outbound action; downstream
gates (Phase 5D / 5E / 7E-Live-B / 7G-Live) remain the only path to
a real call / send / discount / dispatch.

Run shape:
- Celery beat task
  `apps.agents.rto_prevention.tasks.run_rto_prevention_agent_daily`
  scheduled at 09:00 IST (after the Customer Success sweep at 08:00).
  Env-shiftable via `AI_RTO_PREVENTION_DAILY_HOUR` /
  `_MINUTE`.
- Scope: orders with `stage in (Confirmed, Dispatched, Out for
  Delivery)` AND `created_at` within the last 30 days. Orders in
  `Delivered`, `RTO`, or `Cancelled` are explicitly excluded
  (asserted in tests).
- Each in-flight order receives one `RtoRiskSnapshot` per run, one
  linked `AgentRun` (`agent="rto_prevention"`, model
  `"deterministic_v1"`, `cost_usd=0`, `dry_run=True`,
  `triggered_by="celery_beat_daily"`), and one
  `rto_prevention.snapshot.created` AuditEvent.
- The task closes with a `rto_prevention.daily_run.completed`
  summary event carrying tier / kind / stage counts.

Score + tier:
- `score = clamp(30 + min(rto*15, 45) + min(complaint*10, 20)
  + 15 if not Paid + 10 if amount > 5000 + min(days, 10)
  − min(delivered*5, 20) + 15*failed_attempts, 0, 100)`.
- Tier mapping: 0–39 `low` → `monitor_only`, 40–59 `medium` →
  `send_confirmation_reminder`, 60–79 `high` →
  `send_pre_delivery_call_request`, 80–100 `critical` →
  `escalate_to_team_lead`.
- Lifecycle: `pre_dispatch` (no shipment), `in_transit` (shipment +
  no failure indicator), `delivery_at_risk` (Delhivery status
  contains NDR / undelivered / reattempt / failed delivery).
- Reason codes populated from signals: `high_rto_history` (rto ≥ 1),
  `recent_complaint` (>0 complaints in last 14d),
  `cod_payment` (payment_status ≠ Paid),
  `high_value_order` (amount > ₹5000),
  `stale_order` (days_since_order > 14),
  `multiple_failed_attempts` (failed_attempts ≥ 1).
- `recommendation_text` is a short internal rationale; it is
  **never** a customer-facing message and is **never** sent to a
  customer.

Safety contract:
- The agent NEVER imports / calls
  `apps.whatsapp.services.queue_template_message`,
  `apps.whatsapp.services.send_freeform_text_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. The safety test patches all four entrypoints and asserts
  no calls and stable Order / Customer / Payment / Shipment row
  counts after a sweep.
- Kill switch uses the Phase 7E-Live-B Hotfix-1 Postgres-safe
  pattern (same helper shape as Phase 9A): any
  `RuntimeKillSwitch(scope="global", enabled=False)` row wins
  (ordered by `-pk`) and the task exits with one
  `rto_prevention.daily_run.blocked` audit event.
- Sandbox mode: when
  `apps.ai_governance.sandbox.is_sandbox_enabled()` is True, the
  snapshot row and its linked AgentRun both carry the sandbox flag,
  so downstream consumers can filter pilot data cleanly.
- API: `/api/v1/rto-prevention/snapshots/`,
  `/api/v1/rto-prevention/snapshots/<id>/`, and
  `/api/v1/rto-prevention/cohorts/` are admin+ only and strictly
  read-only. POST/PATCH/DELETE return 405. The `/saas-admin` RTO
  Prevention card surfaces masked order ids only and carries no
  "Call Customer" / "Send WhatsApp" / "Apply Discount" /
  "Force Dispatch" / "Run Agent" / "Auto-rescue" buttons.

### Phase 9A — Customer Success / Reorder Agent V1

Phase 9A is a **recommendations-only** deterministic daily Celery
sweep that scores each delivered customer's reorder readiness,
lifecycle stage, and at-risk signals. It never triggers outbound
action; downstream gates remain the only path to a real send /
call / payment / dispatch.

Run shape:
- Celery beat task `apps.agents.customer_success.tasks.
  run_customer_success_agent_daily` scheduled at 08:00 IST
  (`AI_CUSTOMER_SUCCESS_DAILY_HOUR` / `_MINUTE` env-shiftable).
- Iterates the distinct `Order.phone` values that have at least one
  Delivered order in the last 60 days, joins back to `Customer` and
  writes one fresh `CustomerSuccessSnapshot` per customer per run.
- Each snapshot links to a freshly created `AgentRun`
  (`agent="customer_success"`, model `"deterministic_v1"`,
  `cost_usd=0`, `dry_run=True`, `triggered_by="celery_beat_daily"`
  by default).
- One `AuditEvent` per snapshot
  (`customer_success.snapshot.created`); one summary event
  (`customer_success.daily_run.completed`) at the end of each run.

Score + recommendation:
- `score = clamp(60 + min(delivered*5, 30) + min(reorder*10, 20)
  − min(rto*10, 20) − (15 if complaint within 14d else 0), 0, 100)`.
- Lifecycle: 0–2d `fresh_delivery`, 3–7d `early_usage`, 8–19d
  `mid_usage`, 20–30d `reorder_window`, 31–45d `late_reorder`,
  46+d `lapsed`.
- `reorder_candidate` requires the 20–30d window AND no active
  Pending/Confirmed/Dispatched order AND no complaint AuditEvent
  in the last 14 days.
- `at_risk` fires when `lapsed_no_reorder` OR `repeat_rto`
  (≥ 2) OR `recent_complaint` (≤ 14d).
- Recommendation priority: `send_reorder_reminder` →
  `send_winback_offer` (late_reorder / lapsed + at_risk) →
  `send_usage_reminder` (early_usage) → `monitor_only`.
- `recommendation_text` is a short internal rationale (e.g. "Day 22
  post-delivery, 1 prior delivery, no active reorder"); it is
  **never** a customer-facing message and is **never** sent to a
  customer.

Safety contract:
- The agent NEVER imports / calls `apps.whatsapp.services.send_*`,
  `apps.whatsapp.services.queue_template_message`,
  `apps.calls.services.trigger_call_for_lead`,
  `apps.shipments.services.create_shipment`, Razorpay, Meta Cloud,
  or Vapi. Tests patch all four entrypoints and assert no calls
  and stable Order/Customer counts after a sweep.
- Kill switch uses the Phase 7E-Live-B Hotfix-1 Postgres-safe
  pattern: any `RuntimeKillSwitch(scope="global", enabled=False)`
  row wins (ordered by `-pk`) and the task exits with one
  `customer_success.daily_run.blocked` audit event.
- Sandbox mode: when `apps.ai_governance.sandbox.is_sandbox_enabled()`
  is True, the snapshot row and its linked AgentRun both carry the
  sandbox flag, so downstream consumers can filter pilot data
  cleanly.
- API: `/api/v1/customer-success/snapshots/`,
  `/api/v1/customer-success/snapshots/<id>/`, and
  `/api/v1/customer-success/cohorts/` are admin+ only and strictly
  read-only. POST/PATCH/DELETE return 405. The `/saas-admin`
  Customer Success card surfaces masked customer ids only and
  carries no "Send" / "Trigger Call" / "Run Agent" / "Auto-dispatch"
  buttons.

### Phase 8A — Payment → Order Mutation Sandbox Gate

Phase 8A is **sandbox / dry-run only**. It designs how a verified
Razorpay paid evidence (Phase 7I locked audit + Phase 7D rolled-back
attempt) could map to a synthetic / test `Order` status change in
future phases. Approval flips status to
`approved_for_future_phase8b_review` only — it does NOT authorize
any real mutation. Phase 8A NEVER calls Razorpay / Meta Cloud /
Delhivery / Vapi, NEVER sends or queues WhatsApp, NEVER creates a
`Shipment` / AWB / payment link, NEVER captures / refunds, NEVER
sends a customer notification, NEVER mutates real business rows.

```bash
# 0. Enable the sandbox-only env flag (defaults locked OFF).
export PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=true

# 1. Read-only readiness composition.
python manage.py inspect_phase8a_payment_order_mutation_sandbox \
    --json --no-audit

# 2. Read-only preview from a locked Phase 7I lock.
python manage.py preview_phase8a_payment_order_mutation_sandbox \
    --phase7i-lock-id <PHASE7I_LOCK_ID> --json

# 3. Prepare a Phase 8A gate row (one per Phase 7I lock; idempotent).
python manage.py prepare_phase8a_payment_order_mutation_sandbox \
    --phase7i-lock-id <PHASE7I_LOCK_ID> --json

# 4. Run a sandbox dry-run with a synthetic-only reference (one of
#    `phase8a::sandbox::...` / `phase8a-sandbox-...` / `sandbox::...`).
python manage.py dry_run_phase8a_payment_order_mutation_sandbox \
    --gate-id <ID> \
    --synthetic-order-reference "phase8a::sandbox::ord_test_001" --json

# 5. Approve (only from dry_run_passed). Mandatory non-empty reason.
python manage.py approve_phase8a_payment_order_mutation_sandbox \
    --gate-id <ID> --reason "Director Phase 8A approve" --json
```

### Phase 8B — Payment → Order Mutation Review Gate

Phase 8B is **review / dry-run only**. It converts an approved
Phase 8A sandbox gate into a review-only contract for a future
Phase 8C controlled-mutation phase. Approval flips status to
`approved_for_future_phase8c_controlled_mutation_review` only — it
does NOT authorize any real mutation. Phase 8B NEVER calls
Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends or queues
WhatsApp, NEVER creates a `Shipment` / AWB / payment link, NEVER
captures / refunds, NEVER sends a customer notification, NEVER
mutates real business rows.

```bash
# 0. Enable the review-only env flag (defaults locked OFF).
export PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=true

# 1. Read-only readiness composition.
python manage.py inspect_phase8b_payment_order_mutation_review_gate \
    --json --no-audit

# 2. Read-only preview from an approved Phase 8A sandbox gate.
python manage.py preview_phase8b_payment_order_mutation_review_gate \
    --phase8a-gate-id <PHASE8A_GATE_ID> --json

# 3. Prepare a Phase 8B review gate row (one per Phase 8A gate;
#    idempotent).
python manage.py prepare_phase8b_payment_order_mutation_review_gate \
    --phase8a-gate-id <PHASE8A_GATE_ID> --json

# 4. Run a review dry-run with a review-only reference (one of
#    `phase8b::review::order::...` / `phase8b-review-...` /
#    `review::phase8b::...`).
python manage.py dry_run_phase8b_payment_order_mutation_review_gate \
    --gate-id <ID> \
    --target-order-reference "phase8b::review::order::001" --json

# 5. Record a rollback against the passed dry-run (mandatory reason).
python manage.py rollback_dry_run_phase8b_payment_order_mutation_review_gate \
    --dry-run-id <ID> --reason "Director rollback dry-run" --json

# 6. Approve (only from dry_run_passed). Mandatory non-empty reason.
#    Requires at least one passed dry-run AND a recorded rollback
#    dry-run.
python manage.py approve_phase8b_payment_order_mutation_review_gate \
    --gate-id <ID> --reason "Director Phase 8B approve" --json

# 7. Reject (only from draft / pending_manual_review / dry_run_passed
#    / blocked).
python manage.py reject_phase8b_payment_order_mutation_review_gate \
    --gate-id <ID> --reason "Director paused review" --json

# 8. Archive.
python manage.py archive_phase8b_payment_order_mutation_review_gate \
    --gate-id <ID> --reason "Director archive" --json
```

**Phase 8B refuses to prepare unless:**
- Phase 8A gate is in
  `status=approved_for_future_phase8b_review` AND every locked-False
  contract field (`real_business_mutation_allowed` /
  `real_order_mutation_allowed` / `real_payment_mutation_allowed` /
  `customer_notification_allowed` / `whatsapp_allowed` /
  `courier_allowed`) is still False.
- Phase 7I lock is in `status=locked`.
- Phase 7D attempt is in `status=rolled_back` with
  `business_mutation_was_made=False` AND
  `customer_notification_sent=False`.
- The runtime kill switch is enabled.
- `PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=true`.
- Phase 8C, Phase 7E-Live-B, and Phase 7G-Live remain not-approved.

### Phase 8C — Controlled Real Payment → Order Mutation

Phase 8C is the **CLI-only one-shot controlled mutation** framework
against a single explicitly selected internal / sandbox / test
`Order` + `Payment` pair. Execute requires three env flags ALL
true, the kill switch enabled, a structured Director sign-off UTC
window (≤ 15 min), AND runtime safety proof that the target rows
are not real customer data. The only mutation performed is writing
the target `Order.payment_status` and `Payment.status` to `"Paid"`.
Phase 8C NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi,
NEVER sends or queues WhatsApp, NEVER creates a `Shipment` / AWB /
payment link, NEVER captures / refunds, NEVER sends a customer
notification, NEVER mutates real `Customer` / `Lead` / `Shipment` /
`DiscountOfferLog` rows.

**Important:** the VPS should run **inspect / preview / prepare /
dry-run / approve only** unless the Director separately authorises
the execute step. The execute command is implemented but must NOT
be run against production data without explicit Director approval.

```bash
# 0a. Seed exactly ONE safe internal sandbox Order + Payment pair
#     for the dry-run / execute target (CLI-only, idempotent,
#     audit-logged). Defaults to dry-run; pass --apply to actually
#     create the rows. Creates Order.id=phase8c-controlled-order-001
#     and Payment.id=phase8c-controlled-payment-001 with
#     raw_response.phase8c_sandbox=true. No provider call, no
#     WhatsApp, no customer notification, no Shipment / AWB.
python manage.py seed_phase8c_internal_controlled_mutation_fixture \
    --apply --json

# 0b. Enable the controlled-mutation gate env flag (defaults locked
#     OFF). DO NOT enable the other two flags until the Director
#     explicitly approves the one-shot execution.
export PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED=true

# 1. Read-only readiness composition.
python manage.py inspect_phase8c_payment_order_controlled_mutation \
    --json --no-audit

# 2. Read-only preview from an approved Phase 8B review gate.
python manage.py preview_phase8c_payment_order_controlled_mutation \
    --phase8b-gate-id <PHASE8B_GATE_ID> --json

# 3. Prepare a Phase 8C controlled-mutation gate row (one per
#    Phase 8B gate; idempotent).
python manage.py prepare_phase8c_payment_order_controlled_mutation \
    --phase8b-gate-id <PHASE8B_GATE_ID> --json

# 4. Run a controlled-mutation dry-run against a proven
#    internal/sandbox target Order + Payment pair (references must
#    start with `phase8c::controlled::order::` / `phase8c::
#    controlled::payment::` or the `phase8c-controlled-*` variant).
#    Use the Phase 8C-Hotfix-1 seeded sandbox pair:
python manage.py dry_run_phase8c_payment_order_controlled_mutation \
    --gate-id <ID> \
    --target-order-id phase8c-controlled-order-001 \
    --target-payment-id phase8c-controlled-payment-001 \
    --target-order-reference "phase8c::controlled::order::001" \
    --target-payment-reference "phase8c::controlled::payment::001" \
    --json

# 5. Approve (only from dry_run_passed). Mandatory non-empty reason.
#    Requires at least one passed dry-run AND a pending-director-
#    signoff attempt. Approval does NOT execute the mutation.
python manage.py approve_phase8c_payment_order_controlled_mutation \
    --gate-id <ID> --reason "Director Phase 8C approve" --json

# 6. Execute. CLI-only one-shot. Refuses unless every safety gate
#    is satisfied. DO NOT run on the VPS unless the Director has
#    separately approved this exact one-shot execution.
export PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION=true
export PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION=true
python manage.py execute_phase8c_payment_order_controlled_mutation \
    --attempt-id <ID> \
    --confirm-one-shot-mutation \
    --director-signoff "phase8c_attempt_id_<ID> phase8b_gate_id_<ID> BEGIN_UTC=2026-05-12T12:00:00Z END_UTC=2026-05-12T12:10:00Z" \
    --operator-name "Director Prarit Sidana" --json

# 7. Rollback (record-only restore of the original statuses).
python manage.py rollback_phase8c_payment_order_controlled_mutation \
    --attempt-id <ID> --reason "Director rollback" --json

# 8. Reject / archive (any time).
python manage.py reject_phase8c_payment_order_controlled_mutation \
    --gate-id <ID> --reason "Director paused review" --json
python manage.py archive_phase8c_payment_order_controlled_mutation \
    --gate-id <ID> --reason "Director archive" --json
```

**Phase 8C refuses to execute unless:**
- `PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED=true`
- `PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION=true`
- `PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION=true`
- The runtime kill switch is enabled.
- `--confirm-one-shot-mutation` is supplied.
- `--operator-name` is non-empty.
- `--director-signoff` body contains `phase8c_attempt_id_<ID>`,
  `phase8b_gate_id_<ID>`, `BEGIN_UTC=<ISO-Z>`, `END_UTC=<ISO-Z>`.
- The parsed window is ≤ 15 min, fresh (≤ 24h old), and `now` is
  within it.
- The gate is in `status=approved_for_one_shot_controlled_mutation`
  and the attempt is in `approved_for_one_shot_mutation`.
- The gate has no prior `executed` attempt.
- The target Order + Payment pair STILL passes the internal /
  sandbox / test safety proof (`id` / `confirmation_notes` /
  `gateway_reference_id` contains one of `phase8c::controlled::` /
  `phase8c-controlled-` / `internal-test` / `sandbox`, OR
  `Order.confirmation_checklist["phase8c_sandbox"]==True`, OR
  `Payment.raw_response["phase8c_sandbox"]==True`).
- Phase 7E-Live-B, Phase 7G-Live, and broad customer automation
  remain NOT approved.

**Phase 7E-Live-B (real customer WhatsApp send), Phase 7G-Live
(real customer courier execution), and broad customer automation
all remain NOT approved.**

### Phase 8D — Phase 8C Controlled Mutation Evidence Lock

Phase 8D is the **lock-only meta-audit** over the completed Phase
8C executed + rolled_back chain. It snapshots the full status
timeline (Pending → Paid → Pending), the target Order + Payment
ids, the Director sign-off window validity, the rollback restore
state, and every locked-False contract boolean into a single
immutable evidence row. Approval flips status to `locked` only —
it does NOT execute Phase 8C again, NEVER rolls back Phase 8C
again. Phase 8D NEVER calls Razorpay / Meta Cloud / Delhivery /
Vapi, NEVER sends or queues WhatsApp, NEVER creates a `Shipment` /
AWB / payment link, NEVER captures / refunds, NEVER sends a
customer notification, NEVER mutates real `Order` / `Payment` /
`Customer` / `Lead` / `Shipment` / `DiscountOfferLog` /
`WhatsAppMessage` rows.

```bash
# 1. Read-only readiness composition.
python manage.py inspect_phase8d_controlled_mutation_evidence_lock \
    --json --no-audit

# 2. Read-only preview from a Phase 8C rolled_back gate.
python manage.py preview_phase8d_controlled_mutation_evidence_lock \
    --phase8c-gate-id <PHASE8C_GATE_ID> --json

# 3. Prepare a Phase 8D evidence lock row (one per Phase 8C gate;
#    idempotent).
python manage.py prepare_phase8d_controlled_mutation_evidence_lock \
    --phase8c-gate-id <PHASE8C_GATE_ID> --json

# 4. Lock the Phase 8D row (status -> locked). Mandatory non-empty
#    reason. Revalidates eligibility at lock time so a tampered
#    Phase 8C chain refuses to be locked. No provider call, no
#    business mutation, no live execution enabled.
python manage.py lock_phase8d_controlled_mutation_evidence_lock \
    --lock-id <ID> \
    --reason "Director Phase 8D controlled mutation evidence lock" --json

# 5. Reject (only from draft / pending_manual_review / blocked).
python manage.py reject_phase8d_controlled_mutation_evidence_lock \
    --lock-id <ID> \
    --reason "Director paused review" --json

# 6. Archive (after locked / rejected).
python manage.py archive_phase8d_controlled_mutation_evidence_lock \
    --lock-id <ID> --reason "Director archive" --json
```

**Phase 8D refuses to prepare unless:**
- Phase 8C gate is in `status=rolled_back` AND `dry_run_passed=True`.
- A `RazorpayPaymentOrderControlledMutationRollback` row exists
  for an attempt of that gate with `status=rollback_recorded` AND
  `rollback_was_made=True` AND `restored_order_status="Pending"`
  AND `restored_payment_status="Pending"` AND its
  `customer_notification_sent` / `whatsapp_sent` / `courier_called`
  / `provider_call_attempted` all False. **Phase 8D-Hotfix-1: the
  Phase 8C source attempt is resolved via this rollback record,
  not via `attempt.status`** — so a later blocked re-run that
  flipped `attempt.status="blocked"` after execute + rollback had
  already completed does NOT block evidence locking, as long as
  the rollback record's evidence remains intact.
- The Phase 8C attempt that the rollback points at has
  `executed_at` present AND `recorded_signoff_window_valid=True`
  AND `order_mutation_was_made=True` AND
  `payment_mutation_was_made=True` AND
  `business_mutation_was_made=True` AND every
  `customer_notification_sent` / `whatsapp_sent` /
  `courier_called` / `provider_call_attempted` / `shipment_created`
  is still False. The current `attempt.status` value (which may
  be `rolled_back`, `executed`, or `blocked`) is snapshotted onto
  the lock row's `phase8c_attempt_status_snapshot` for evidence
  but does not gate the lock.
- The current target `Order.payment_status == "Pending"` AND
  target `Payment.status == "Pending"` (post-rollback state
  has not been tampered with).
- The current target `Payment.raw_response["phase8c_sandbox"]`
  is still `True` (the live Payment row still carries the explicit
  sandbox proof Phase 8C used at execute time).
- The runtime kill switch is enabled.
- Phase 7E-Live-B, Phase 7G-Live, and broad customer automation
  all remain not-approved.

The `evidence_json` persisted on every Phase 8D lock row carries
the Phase 8D-Hotfix-1 normalized top-level fields
`executionEvidenceValid` / `rollbackEvidenceValid` /
`attemptStatusAtEvidenceLock` / `rollbackStatus` /
`finalDbRestored` — downstream readers should consume these
canonical signals instead of re-deriving from the nested
`phase8c` snapshot.

**Phase 7E-Live-B (real customer WhatsApp send), Phase 7G-Live
(real customer courier execution), and broad customer automation
all remain NOT approved.**

### Phase 8E — Real Customer Payment → Order Mutation Pilot Gate

Phase 8E is the **review-only and dry-run-only** pilot gate that
designs how a future Phase 8F would mutate `Order.payment_status`
and `Payment.status` on REAL customer rows (after a Razorpay
webhook payment.captured). It chains off a `locked` Phase 8D
evidence lock and is the first gate that handles real-customer
candidates. Approval flips status to
`approved_for_future_phase8f_real_customer_controlled_mutation`
only — it does NOT enable any mutation. Phase 8E NEVER calls
Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends or queues
WhatsApp, NEVER creates a `Shipment` / AWB / payment link, NEVER
captures / refunds, NEVER sends a customer notification, NEVER
mutates real `Order` / `Payment` / `Customer` / `Lead` /
`Shipment` / `DiscountOfferLog` / `WhatsAppMessage` rows. **All
PII is masked at every surface**: phone numbers are last-4 only;
customer names show first letter of each word followed by
asterisks; raw provider payloads (`raw_response`,
`gateway_reference_id`, full payment URLs) NEVER appear in any
candidate row, audit payload, or API response.

```bash
# 1. Read-only readiness composition.
python manage.py inspect_phase8e_real_customer_payment_order_pilot \
    --json --no-audit

# 2. Read-only preview from a locked Phase 8D evidence lock.
python manage.py preview_phase8e_real_customer_payment_order_pilot \
    --phase8d-lock-id <PHASE8D_LOCK_ID> --json

# 3. Prepare a Phase 8E pilot gate row (one per Phase 8D lock;
#    idempotent inside transaction.atomic()). Refuses outright
#    when PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED=false.
python manage.py prepare_phase8e_real_customer_payment_order_pilot \
    --phase8d-lock-id <PHASE8D_LOCK_ID> --json

# 4. Select a real-customer candidate (Order + Payment pair from
#    a Razorpay webhook payment.captured event). Refuses Phase 8C
#    sandbox rows. Refuses mismatched Order/Payment. Phones masked
#    to last-4 only. Idempotent on (gate, order_id, payment_id).
python manage.py select_phase8e_real_customer_candidate \
    --gate-id <ID> \
    --order-id <REAL_ORDER_ID> \
    --payment-id <REAL_PAYMENT_ID> \
    --webhook-event-id <RAZORPAY_WEBHOOK_EVENT_ID> --json

# 5. Dry-run the proposed mutation on a candidate (would_*
#    locked-False booleans; never actually flips Order or
#    Payment status; emits `phase8e.pilot.dry_run_passed` or
#    `dry_run_failed`).
python manage.py dry_run_phase8e_real_customer_payment_order_pilot \
    --candidate-id <CANDIDATE_ID> --json

# 6. Approve (status -> approved_for_future_phase8f_real_customer_controlled_mutation).
#    Mandatory non-empty reason. Refuses unless gate.dry_run_passed=True
#    AND at least one passed dry-run AND a recorded rollback dry-run
#    AND the runtime kill switch is enabled AND Phase 7E-Live-B /
#    7G-Live / broad customer automation all remain not-approved.
python manage.py approve_phase8e_real_customer_payment_order_pilot \
    --gate-id <ID> \
    --reason "Director Phase 8E pilot approval" --json

# 7. Reject (only from draft / pending_manual_review /
#    dry_run_passed / blocked).
python manage.py reject_phase8e_real_customer_payment_order_pilot \
    --gate-id <ID> \
    --reason "Director paused real-customer pilot review" --json

# 8. Archive (after approved / rejected).
python manage.py archive_phase8e_real_customer_payment_order_pilot \
    --gate-id <ID> --reason "Director archive" --json
```

**Phase 8E refuses to prepare unless:**
- Phase 8D lock is `status=locked` AND `final_db_restored_snapshot=True`
  AND `phase8c_gate_status_snapshot="rolled_back"`.
- `PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED=true` env flag.
- The runtime kill switch is enabled.
- Phase 7E-Live-B (real customer WhatsApp send), Phase 7G-Live (real
  customer courier execution), and broad customer automation all
  remain not-approved.

**Phase 8E candidate validation refuses any Order/Payment pair that:**
- Carries the Phase 8C sandbox marker on `Payment.raw_response.phase8c_sandbox=True`
  or matches the `phase8c-controlled-` / `phase8c::controlled::` id markers
  (Phase 8E is real-customer-only; sandbox rows are explicitly out of scope).
- Has mismatched references (Payment does not point at the supplied Order id).
- Is already in a terminal state (Order.payment_status not currently
  `"Pending"` AND Payment.status not currently `"Pending"`).

Approval flips status to
`approved_for_future_phase8f_real_customer_controlled_mutation`
only — Phase 8F (the real-customer one-shot controlled mutation) is
NOT implemented in Phase 8E and requires fresh explicit Director
approval to design and ship.

**Phase 7E-Live-B (real customer WhatsApp send), Phase 7G-Live
(real customer courier execution), Phase 8F (real customer
controlled mutation), and broad customer automation all remain
NOT approved.**

### Phase 8E-Hotfix-1 — Candidate Pool Inspector + Partial+Pending Review-Only

Phase 8E-Hotfix-1 is a **review-only widening** of the Phase 8E
candidate validator + a new read-only candidate pool inspector
command. Real business data ships orders whose
`Order.payment_status="Partial"` (advance captured, balance still
outstanding) with `Payment.status="Pending"`. The strict
Pending/Pending query returned 0 rows on the VPS; the pool
contains 6 Partial+Pending real-customer pairs. The hotfix
widens the candidate validator to accept `Partial`+`Pending` as a
**review-only** candidate (a typed warning
`phase8e_candidate_partial_order_pending_payment_review_only` is
attached). This is NOT mutation approval; Phase 8F remains
NOT approved.

```bash
# 1. Read-only candidate pool inspector. Classifies every Order
#    + Payment row pair by Phase 8E eligibility reason.
#    Phones masked to last-4. Raw provider payload never exposed.
python manage.py inspect_phase8e_real_customer_candidate_pool \
    --json

# 2. Read-only with blocked rows included (still masked).
python manage.py inspect_phase8e_real_customer_candidate_pool \
    --include-blocked --limit 200 --json

# 3. Read-only via HTTP (auth + admin only).
GET /api/v1/saas/phase8/real-customer-payment-order-pilot-candidate-pool/?limit=50&include_blocked=false

# 4. Now select a recommended candidate as before; Partial+Pending
#    rows are accepted with the review-only warning.
python manage.py select_phase8e_real_customer_candidate \
    --gate-id <ID> \
    --order-id <ORDER_ID> \
    --payment-id <PAYMENT_ID> \
    --webhook-event-id <RAZORPAY_WEBHOOK_EVENT_ID> --json
```

**Classification reasons returned by the pool inspector:**

- `strict_pending_pending` — `Order.payment_status="Pending"` AND
  `Payment.status="Pending"` AND non-terminal stage. Canonical
  happy path.
- `partial_pending_review_only` — `Order.payment_status="Partial"`
  AND `Payment.status="Pending"` AND non-terminal stage.
  Phase 8E-Hotfix-1 review-only path; the candidate carries the
  `phase8e_candidate_partial_order_pending_payment_review_only`
  warning.
- `blocked_terminal_stage` — Order stage is `DELIVERED` / `RTO` /
  `CANCELLED`.
- `blocked_payment_not_pending` — `Payment.status` is not
  `"Pending"` (i.e. `PAID` / `REFUNDED` / `FAILED` / etc.).
- `blocked_order_status_not_pending_or_partial` — Order is in some
  other payment state.
- `blocked_phase8c_sandbox` — row pair carries a Phase 8C sandbox
  marker (`phase8c-controlled-` / `phase8c::controlled::` /
  `internal-test` / `sandbox` substring OR
  `Payment.raw_response.phase8c_sandbox=True` /
  `Order.confirmation_checklist.phase8c_sandbox=True`).
- `blocked_missing_required_data` — `Payment.order_id` points at a
  non-existent Order.
- `blocked_order_payment_mismatch` — reserved for the manual
  candidate-selection path (the pool walker can't reach this).

**Phase 8E-Hotfix-1 refuses to mutate:**

- `Order.payment_status` / `Order.state` / `Payment.status`
- `Customer` / `Lead` / `Shipment` / `DiscountOfferLog` /
  `WhatsAppMessage`
- any `.env*` file

**Phase 8E-Hotfix-1 NEVER calls** Razorpay / Meta Cloud /
Delhivery / Vapi, **NEVER sends or queues** WhatsApp, **NEVER
creates** a `Shipment` / AWB / payment link, **NEVER captures**,
**NEVER refunds**, **NEVER sends a customer notification**.
Approval still only flips status to
`approved_for_future_phase8f_real_customer_controlled_mutation`.

### Phase 8F — Controlled Real Customer Payment → Order Mutation

Phase 8F is the **CLI-only one-shot controlled mutation** path for
the ONE Phase 8E-approved real customer `Order` + `Payment`
candidate. Execute mutates ONLY `Order.payment_status` AND
`Payment.status` to `"Paid"` on the named target rows.
`Order.state` is **NEVER** mutated. Phase 8F NEVER calls Razorpay
/ Meta Cloud / Delhivery / Vapi, NEVER sends or queues WhatsApp,
NEVER creates a `Shipment` / AWB / payment link, NEVER captures /
refunds, NEVER sends a customer notification, NEVER mutates
`Customer` / `Lead` / `Shipment` / `DiscountOfferLog` /
`WhatsAppMessage` rows. Approval ALONE does NOT execute — the
execute CLI command is the ONLY path that may write the model
fields.

```bash
# 1. Read-only readiness.
python manage.py inspect_phase8f_real_customer_controlled_mutation \
    --json --no-audit

# 2. Read-only preview from an approved Phase 8E pilot gate.
python manage.py preview_phase8f_real_customer_controlled_mutation \
    --phase8e-gate-id <PHASE8E_GATE_ID> --json

# 3. Prepare a Phase 8F gate row (one per Phase 8E gate; idempotent).
#    Refuses unless PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=true.
python manage.py prepare_phase8f_real_customer_controlled_mutation \
    --phase8e-gate-id <PHASE8E_GATE_ID> --json

# 4. Approve the gate (mints a matching attempt). require_reason=True.
python manage.py approve_phase8f_real_customer_controlled_mutation \
    --gate-id <PHASE8F_GATE_ID> \
    --reason "Director Phase 8F approve" --json

# 5. CLI-only one-shot execute. Refuses unless:
#      - PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=true
#      - PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION=true
#      - PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION=true
#      - --confirm-one-shot-real-mutation
#      - non-empty --operator-name
#      - structured 15-min Director sign-off UTC window that names
#        phase8f_attempt_id_<ID> AND phase8f_gate_id_<ID> AND
#        phase8e_gate_id_<ID> AND target_order_<ORDER_ID> AND
#        target_payment_<PAYMENT_ID>
#      - kill switch enabled, no prior executed attempt on this gate,
#        current Order.payment_status ∈ {Pending, Partial} AND
#        Payment.status=Pending AND Payment.order_id==Order.id.
#
# DO NOT run this on the VPS until Director approves it separately.
python manage.py execute_phase8f_real_customer_controlled_mutation \
    --attempt-id <ATTEMPT_ID> \
    --operator-name "Operator Prarit" \
    --confirm-one-shot-real-mutation \
    --director-signoff "Director sign-off Phase 8F controlled real customer mutation. phase8f_attempt_id_<A> phase8f_gate_id_<G> phase8e_gate_id_<E> target_order_<NRG-20435> target_payment_<PAY-30125> BEGIN_UTC=<ISO-Z> END_UTC=<ISO-Z>" \
    --json

# 6. Rollback (record-only restore of old_* snapshots). require_reason=True.
python manage.py rollback_phase8f_real_customer_controlled_mutation \
    --attempt-id <ATTEMPT_ID> --reason "Director rollback" --json

# 7. Reject (only from draft / pending_manual_review / blocked).
python manage.py reject_phase8f_real_customer_controlled_mutation \
    --gate-id <PHASE8F_GATE_ID> --reason "Director paused" --json

# 8. Archive (after executed / rolled_back / rejected).
python manage.py archive_phase8f_real_customer_controlled_mutation \
    --gate-id <PHASE8F_GATE_ID> --reason "Director archive" --json
```

**Phase 8F refuses to execute unless:**

- All three Phase 8F env flags are `true` at runtime.
- The runtime kill switch is enabled.
- The Phase 8F gate is in `approved_for_one_shot_real_customer_mutation`
  status AND the Phase 8F attempt is in
  `approved_for_one_shot_real_mutation` status.
- No prior `executed` attempt exists on the same gate.
- The Director sign-off body literally contains `phase8f_attempt_id_<ID>`
  AND `phase8f_gate_id_<ID>` AND `phase8e_gate_id_<ID>` AND
  `target_order_<ORDER_ID>` AND `target_payment_<PAYMENT_ID>` AND
  `BEGIN_UTC=<ISO-Z>` AND `END_UTC=<ISO-Z>` markers, the window is
  ≤ 15 min, fresh, and `now ∈ [BEGIN_UTC, END_UTC]`.
- `--confirm-one-shot-real-mutation` is set AND `--operator-name`
  is non-empty.
- The current `Order.payment_status` is still `"Pending"` or
  `"Partial"` AND the current `Payment.status` is still `"Pending"`
  AND `Payment.order_id == Order.id`.
- Phase 7E-Live-B (real customer WhatsApp send), Phase 7G-Live
  (real customer courier execution), and broad customer automation
  all remain NOT approved.

**Phase 8F execute mutates ONLY** `Order.payment_status` and
`Payment.status` on the named target rows. `Order.state` is NEVER
written. No row is created or deleted in any business table
(`Customer` / `Lead` / `Shipment` / `DiscountOfferLog` /
`WhatsAppMessage` / `WhatsAppLifecycleEvent` /
`WhatsAppHandoffToCall` all stay at 0-delta).

**Phase 8F rollback** restores the original
`Order.payment_status` + `Payment.status` from the attempt's
`old_*` snapshots. No provider call, no notification, no WhatsApp,
no business-row count drift.

**Phase 7E-Live-B (real customer WhatsApp send), Phase 7G-Live
(real customer courier execution), and broad customer automation
all remain NOT approved.**

### Phase 8F Live Execute — 2026-05-14

Phase 8F live execute was run on the VPS for the first time on
2026-05-14 as Reading 1 mechanism proof, then rolled back. This
was a controlled Order/Payment status mutation only; it did not
call any provider and did not notify the customer.

Execute facts:

- `attempt_id=1`
- `gate_id=1`
- `source_phase8e_gate_id=1`
- `target_order=NRG-20435`
- `target_payment=PAY-30125`
- `operator=Prarit Sidana`
- Director signoff window:
  `BEGIN_UTC=2026-05-14T09:32:29Z` to
  `END_UTC=2026-05-14T09:45:29Z`
- Result: `ok=True`, `status=executed`
- Mutation: Order `NRG-20435.payment_status -> Paid`, Payment
  `PAY-30125.status -> Paid`

Safety confirmations:

- `customer_notification_sent=False`
- `whatsapp_sent=False`
- `courier_called=False`
- `provider_call_attempted=False`
- `shipment_created=False`
- No Razorpay / Meta Cloud / Delhivery / Vapi call
- No WhatsApp send
- No customer notification
- No shipment/AWB
- No `Order.state` mutation

The three `PHASE8F_*` flags were passed via runtime env prefix
only. `.env.production` was NOT edited.

Rollback Reading 1:

- Result: `ok=True`, `status=rollback_recorded`, `rollbackId=1`
- psql confirmed Order `NRG-20435.payment_status` restored to
  `Partial`
- psql confirmed Payment `PAY-30125.status` restored to `Pending`
- Health endpoint returned `{"status": "ok"}`

Pre-execute audit trail:

- Multiple execute attempts with placeholder signoffs were
  correctly refused by the guard:
  `phase8f_director_signoff_missing_structured_utc_window`,
  `phase8f_now_outside_director_signoff_utc_window_before_start`.
- Hotfix-3 recovery was used to restore `attempt.status` between
  each refused run.
- Safety gates worked correctly throughout: no mutation occurred
  on any refused attempt.

Confirmed working UTC-window shell pattern for future reference:

```bash
BEGIN=$(date -u -d "-1 minute" +"%Y-%m-%dT%H:%M:%SZ")
END=$(date -u -d "+12 minutes" +"%Y-%m-%dT%H:%M:%SZ")

# Embed ${BEGIN} and ${END} in the Director signoff text as:
# BEGIN_UTC=${BEGIN} END_UTC=${END}
```

Phase 8F Reading 1 is complete as executed + rolled back with no
lasting change: system state is back to Order Partial / Payment
Pending. Phase 7E-Live-B and Phase 7G-Live remain NOT approved.

### Phase 8F-Hotfix-1 — Recover Blocked Approval Gate

Phase 8F-Hotfix-1 patches `approve_phase8f_real_customer_controlled_mutation`
so a gate that landed in `blocked` SOLELY because the runtime
gate env flag was off at the prior approve attempt may be safely
recovered to approval AFTER the flag is flipped on. The recovery
path is narrowly scoped — every other safety condition must still
hold. This is approval-only; it does NOT execute the mutation.

```bash
# 1. Apply the new index-rename migration on the VPS:
python manage.py migrate payments

# 2. Verify makemigrations is clean:
python manage.py makemigrations --check --dry-run
#   -> No changes detected

# 3. Flip the Phase 8F gate env flag ON (in .env.production):
#    PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=true
#    (the other two execute env flags STAY false until separate
#    Director approval).

# 4. Retry approve. The recovery path triggers only when:
#    gate.status="blocked"
#    AND gate.blockers == [
#      "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
#    ]   (exactly this single blocker, no others)
#    AND PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=true
#    AND no attempt on this gate carries executed_at OR any
#      *_mutation_was_made flag True OR any provider/send/courier/
#      notification flag True
#    AND current Order.payment_status ∈ {Pending, Partial}
#    AND current Payment.status = Pending
#    AND Payment.order_id == Order.id
#    AND Phase 8E source gate still approved_for_future_phase8f_real_customer_controlled_mutation
#    AND kill switch enabled
#    AND Phase 7E-Live-B / 7G-Live / broad customer automation NOT approved.
python manage.py approve_phase8f_real_customer_controlled_mutation \
    --gate-id 1 \
    --reason "Phase 8F-Hotfix-1: recovery approval after env flag flipped true." \
    --json
```

On success, the response includes
`phase8fHotfix1RecoveredFromMissingEnvApprovalBlock=true` and
`gate.evidence_json.phase8fHotfix1Recovery` is stamped with
`recoveredFromMissingEnvApprovalBlock=true`,
`recoveredBlocker="PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"`,
`executionStillNotRun=true`. The `phase8f.real_mutation.approved`
audit row carries the same recovery markers.

**Phase 8F-Hotfix-1 refuses recovery when any of these are false:**

- Gate blockers contains anything other than the single env-flag
  blocker — fix the other blockers first.
- Env flag still off at the new approve attempt.
- Any attempt on the gate has `executed_at` set OR any
  `*_mutation_was_made` flag True OR any provider/send/courier/
  notification flag True — the gate has already crossed execute.
- Current `Order.payment_status` has drifted away from
  `{Pending, Partial}` OR `Payment.status` is no longer `Pending`
  OR `Payment.order_id` no longer matches `Order.id`.

**Phase 8F-Hotfix-1 NEVER executes Phase 8F, NEVER rolls back
Phase 8F, NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi,
NEVER sends or queues WhatsApp, NEVER creates a `Shipment` / AWB
/ payment link, NEVER captures / refunds, NEVER sends a customer
notification, NEVER mutates `Order.payment_status` /
`Order.state` / `Payment.status` / `Customer` / `Lead` /
`Shipment` / `DiscountOfferLog` / `WhatsAppMessage` rows, NEVER
edits any `.env*` file.** Recovery is a status transition only —
the execute CLI command remains the ONLY path that may write the
model fields, and it still requires all three Phase 8F env flags
true + structured 15-min Director UTC window + kill switch
enabled + `--confirm-one-shot-real-mutation` + non-empty
`--operator-name`.

**Phase 8F-Hotfix-1 — Field outcome (2026-05-14).** The recovery
CLI documented above was run on the VPS against Phase 8F gate
id=1. The gate transitioned from `blocked` to
`approved_for_one_shot_real_customer_mutation`; attempt id=1 was
minted in `approved_for_one_shot_real_mutation` status with every
locked-False flag still False and `executed_at=NULL`; the gate's
`evidence_json.phase8fHotfix1Recovery` block carries
`recoveredFromMissingEnvApprovalBlock=true`,
`recoveredBlocker="PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"`,
`executionStillNotRun=true`, `phase8fHotfix1=true`. **At the
Hotfix-1 field-outcome checkpoint, Phase 8F EXECUTE had not yet
run** — `Order.NRG-20435` was still
`payment_status="Partial"`, `Payment.PAY-30125` was still
`status="Pending"`, no real customer was charged, no provider was
called, no notification was sent.

### Phase 8F-Hotfix-2 — Postgres-safe Phase 8F execute tests

Phase 8F-Hotfix-2 is a **test-only fix** (no production code, no
model, no migration, no service, no env flag, no API touched).
The fix patches `backend/tests/test_phase8f_real_customer_controlled_mutation.py`
so the Postgres + full-file run no longer fails on the two happy-
path tests (`test_phase8f_execute_happy_path_mutates_only_target_statuses`
and `test_phase8f_rollback_restores_old_statuses_no_side_effect`).

**Root cause:** the helper `_prep_approve(...)` created a Phase 8E
gate but did not return its `pk`. The tests then hardcoded
`phase8e_gate_id=1` (and the literal `phase8e_gate_id_1` in
inline signoff strings). Postgres `ROLLBACK` does **not** reset
`AUTOINCREMENT` sequences between tests in the same file run, so
the real Phase 8E gate id is rarely 1 — and the execute path's
literal-ref check (`phase8e_gate_id_<ID>` must appear in the
Director sign-off body) then refused with
`phase8f_director_signoff_must_reference_phase8e_gate_id`.
SQLite (local dev) effectively resets the sequence so the bug
was invisible locally; it only surfaced on the Postgres VPS
under a full-file run.

**Fix:**

1. `_prep_approve` now returns a 5-tuple
   `(attempt_id, gate_id, phase8e_gate_pk, order, payment)`.
2. Every caller of `_prep_approve` unpacks the new
   `phase8e_gate_id` value.
3. The two happy-path tests pass the dynamic `phase8e_gate_id`
   into `_structured_signoff` instead of the literal `1`.
4. Every refusal test replaces inline `phase8e_gate_id_1`
   fragments with `f"phase8e_gate_id_{phase8e_gate_id}"`.

Test intent, counts, and assertion logic are unchanged. Phase 8F
test count stays at **40 passed**; verification baseline stays
at **2188 backend / 82 frontend** with `makemigrations --check
--dry-run`, `manage.py check`, frontend lint, vitest, and build
all green.

**Phase 8F-Hotfix-2 did NOT execute or roll back Phase 8F, did
NOT call Razorpay / Meta Cloud / Delhivery / Vapi, did NOT send
or queue WhatsApp, did NOT send a customer notification, did NOT
create a `Shipment` / AWB / payment link, did NOT mutate any
business row, did NOT edit any `.env*` file.**

### Phase 8F-Hotfix-3 - Recover Blocked Attempt

Phase 8F-Hotfix-3 adds a governance-only recovery command for the
specific case where a Phase 8F attempt was blocked by a failed
pre-execute Director signoff check before any mutation happened.
The confirmed root cause was attempt id=1 receiving placeholder
signoff (`<FILL>`), failing the UTC window precheck, and being set
to `blocked`. Since execute requires
`approved_for_one_shot_real_mutation`, that blocked status would
refuse every future execute even with a proper signoff.

This recovery is NOT execute. It requires no UTC window because it
does not mutate Order/Payment. It only transitions the attempt from
`blocked` back to `approved_for_one_shot_real_mutation` and appends
`phase8fHotfix3Recovery_recovered_from_blocked` to
`attempt.blockers` for audit evidence.

```bash
python manage.py recover_phase8f_attempt_to_approved \
    --attempt-id 1 \
    --director-signoff "Director Phase 8F-Hotfix-3 recovery. phase8f_attempt_id_1 phase8f_gate_id_1 phase8fHotfix3AttemptRecovery" \
    --operator-name "Operator Prarit" \
    --confirm-phase8f-attempt-recovery \
    --json
```

The command refuses unless all of these are true:

- `PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=true`.
- Runtime kill switch is enabled.
- `--confirm-phase8f-attempt-recovery` is present.
- `--operator-name` is non-empty.
- The attempt exists and is currently `blocked`.
- The gate is `approved_for_one_shot_real_customer_mutation`.
- No attempt on the gate has status `executed`.
- Director signoff contains `phase8f_attempt_id_<ID>`.
- Director signoff contains `phase8f_gate_id_<ID>`.
- Director signoff contains `phase8fHotfix3AttemptRecovery`.

On success:

- `attempt.status` becomes `approved_for_one_shot_real_mutation`.
- `attempt.blockers` gains
  `phase8fHotfix3Recovery_recovered_from_blocked`.
- A `phase8f.real_mutation.approved` audit event records
  `recovery="phase8fHotfix3AttemptRecovery"`.
- `nextAction` is
  `run_execute_phase8f_with_proper_director_directive`.

**Field outcome before Reading 1 execute (2026-05-14).** Hotfix-3
restored attempt id=1 to `approved_for_one_shot_real_mutation` after
placeholder-signoff execute attempts were refused. No mutation occurred
on any refused attempt.

**Phase 8F-Hotfix-3 NEVER executes Phase 8F, NEVER rolls back
Phase 8F, NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi,
NEVER sends or queues WhatsApp, NEVER creates a `Shipment` / AWB
/ payment link, NEVER captures / refunds, NEVER sends a customer
notification, NEVER mutates `Order.payment_status` / `Order.state`
/ `Payment.status` / `Customer` / `Lead` / `Shipment` /
`DiscountOfferLog` / `WhatsAppMessage` rows, NEVER edits any
`.env*` file.** It was a recovery command only; the later Reading 1
execute + rollback is recorded in the section above.

### Test Hygiene Hotfix-1 — Pin integration modes in conftest for VPS-safe full-suite runs

Test Hygiene Hotfix-1 is a **TEST-ONLY** fix that resolves the
~43 VPS full-suite failures observed when `pytest -q` was first
run against the live `.env.production` on the VPS. No production
code, model, migration, service, view, env flag, `.env*` file,
or frontend was touched.

**Root cause.** The VPS `.env.production` has non-mock values
for several integration adapters:

- `RAZORPAY_MODE=test` (NOT `mock`) — real Razorpay TEST API
- `WHATSAPP_PROVIDER=meta_cloud` (NOT `mock`) — real Meta Cloud client
- `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` — final-send allow-list guard

Tests that don't carry their own `override_settings` inherit
these values. The cascade of failures observed:

- Phase 4D / `test_writes` — real Razorpay TEST API created live
  `rzp.io` payment links instead of the mock placeholder; URL
  mismatch + Razorpay 500s.
- Phase 5A webhook — Meta Cloud signature verification rejected
  the test fixtures' app-secret HMAC because the live
  `META_WA_APP_SECRET` was in scope.
- Phase 5A / 5B / 5C / 5D / 5E sends — the final-send limited-mode
  allow-list guard refused outbounds to any phone not in
  `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`, surfacing as
  `Limited test mode: destination not on allow-list`.

**Reproduce locally** (proves these are env-leak failures, not
product defects):

```bash
cd backend
RAZORPAY_MODE=test \
WHATSAPP_PROVIDER=meta_cloud \
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true \
python -m pytest -q
# Before the hotfix: 49 failures (matched the ~43 the VPS saw).
# After the hotfix: all 2188 passed.
```

**Fix.** `backend/tests/conftest.py` extends the existing
`_force_eager_celery` session-autouse fixture to also pin every
integration adapter to `mock` for the whole test session:

```python
with override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    RAZORPAY_MODE="mock",
    WHATSAPP_PROVIDER="mock",
    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=False,
    DELHIVERY_MODE="mock",
    VAPI_MODE="mock",
    META_MODE="mock",
):
    yield
```

Tests that intentionally need a non-mock value already carry
their own `override_settings`, which wins over the session pin
inside that test. **Zero stragglers needed manual cleanup** — no
test file other than `backend/tests/conftest.py` was touched.

**Verification.** Both runs are now all-green at **2188 backend
tests + 82 frontend tests**:

```bash
# Normal run.
python -m pytest -q                    # 2188 passed
python manage.py makemigrations --check --dry-run   # No changes detected
python manage.py check                              # 0 issues

# Faked-`.env.production` run — must also pass.
RAZORPAY_MODE=test \
WHATSAPP_PROVIDER=meta_cloud \
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true \
python -m pytest -q                    # 2188 passed

cd ../frontend
npm run lint && npm test && npm run build    # all green
```

**Director reconciliation note.** The current VPS
`.env.production` has drifted from the canonical "stays mock-mode
in production" list in nd.md §17. The WhatsApp pair
(`WHATSAPP_PROVIDER=meta_cloud` + `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`)
appears intentional for the controlled-pilot posture that powered
the Phase 7E-Live-A real send + the Phase 5F-Gate real-inbound
auto-reply test. `RAZORPAY_MODE=test` must be flipped to `live`
before any real customer payment collection — that flip is a
separate Director directive. **Do NOT edit `.env.production`
without Director sign-off.**

**Test Hygiene Hotfix-1 did NOT execute or roll back anything,
did NOT call Razorpay / Meta Cloud / Delhivery / Vapi, did NOT
send or queue WhatsApp, did NOT send a customer notification,
did NOT create a `Shipment` / AWB / payment link, did NOT mutate
any business row, did NOT edit any `.env*` file or any frontend
file.**
