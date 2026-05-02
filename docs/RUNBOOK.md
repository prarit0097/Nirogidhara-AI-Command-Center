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
python -m pytest -q                     # Phase 1 -> 6H inclusive

# Frontend
cd ../frontend
npm test                                # Phase 1 -> 6H vitest tests
npm run lint                            # 0 errors, ~8 pre-existing shadcn warnings
npm run build                           # Production build
```

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
