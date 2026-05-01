# Deploying Nirogidhara AI Command Center to Hostinger VPS

> Target domain: **`ai.nirogidhara.com`**
> App folder on VPS: **`/opt/nirogidhara-command`**
> Stack: isolated Postgres + Redis + Daphne backend + Celery worker + Celery beat + Nginx (Vite SPA)
> Compose project name: **`nirogidhara-command`**

This runbook is the authoritative production deploy path. Every command
below runs on the VPS unless explicitly marked _(local)_. Local dev keeps
using `python manage.py runserver` + `npm run dev` — Docker is **production
only**.

---

## 0. Why this stack

| Need | Choice | Why |
| --- | --- | --- |
| HTTP + WebSockets in one process | Daphne ASGI | Phase 4A `/ws/audit/events/` requires Channels. Gunicorn alone would not work. |
| Background tasks + cron | Celery worker + beat | Phase 3C scheduler + Phase 5A retry/backoff/jitter on WhatsApp sends. |
| Database | Postgres 16 (container) | SQLite is dev only. Postgres handles concurrent webhooks (Razorpay / Delhivery / Vapi / Meta / WhatsApp). |
| Cache + broker + Channels layer | Redis 7 (container) | Three indices (0/1/2) used by Celery broker / Celery results / Channels group fan-out. |
| Static assets + reverse proxy | Nginx (container) with built Vite SPA | Single host port (18020) serves the SPA + proxies API/WS/admin to the backend container. |
| Host-port isolation | **18020 → 80** | Existing Postzyo / OpenClaw containers already use other host ports. 18020 is free. The host Nginx / Hostinger Traefik then proxies `ai.nirogidhara.com → 127.0.0.1:18020`. |

---

## 1. Prerequisites on the VPS

```bash
# Already present from Postzyo / OpenClaw — just verify.
docker --version          # >= 24
docker compose version    # v2 plugin
git --version             # any
```

If Docker is missing, install via Docker's official `get.docker.com`
script. **Do not** add this user to the `docker` group on a shared VPS
without confirming with the team — the existing setup may already use
`sudo docker`.

---

## 2. Initial setup (one-time)

```bash
# Clone into the production folder.
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/prarit0097/Nirogidhara-AI-Command-Center.git nirogidhara-command
cd /opt/nirogidhara-command

# Stamp the production env file from the example.
sudo cp .env.production.example .env.production
sudo chmod 600 .env.production
sudo nano .env.production
```

Inside `.env.production`, fill in at minimum:

- `DJANGO_SECRET_KEY` — `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `JWT_SIGNING_KEY` — different long random string
- `POSTGRES_PASSWORD` — strong; reflect the same string into `DATABASE_URL`
- `DJANGO_ALLOWED_HOSTS` — `ai.nirogidhara.com,localhost,127.0.0.1`
- `CORS_ALLOWED_ORIGINS` — `https://ai.nirogidhara.com`
- `CSRF_TRUSTED_ORIGINS` — `https://ai.nirogidhara.com`

Leave `WHATSAPP_PROVIDER=mock`, `RAZORPAY_MODE=mock`, `DELHIVERY_MODE=mock`,
`VAPI_MODE=mock`, `META_MODE=mock`, `AI_PROVIDER=disabled` until the
production credentials for each are confirmed by Prarit. Switching them
to live before keys are valid will fail closed (the adapters refuse to
load), but configuring them prematurely with the wrong values risks
sending a customer message during a smoke test — keep them mocked.

Phase 6E integration settings are readiness metadata only. Do not move live
Meta/Razorpay/PayU/Delhivery/Vapi/OpenAI secrets from `.env.production` into
the database in this phase. Only `ENV:` / `VAULT:` secret references are
allowed, and runtime providers still read env/config until Phase 6F.

> **Never commit `.env.production`.** It is gitignored at the repo root.

---

## 3. First boot

```bash
cd /opt/nirogidhara-command
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Compose builds two images (`nirogidhara/backend`, `nirogidhara/nginx`)
and starts six containers:

```
nirogidhara-db          postgres:16-alpine        internal-only
nirogidhara-redis       redis:7-alpine            internal-only
nirogidhara-backend     custom (Daphne :8000)     internal-only
nirogidhara-worker      custom (celery worker)    internal-only
nirogidhara-beat        custom (celery beat)      internal-only
nirogidhara-nginx       custom (vite + nginx)     127.0.0.1:18020 → 80
```

Wait ~60 seconds for the healthchecks, then verify:

```bash
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

Expected output: `db reachable at postgres:5432 → redis reachable at redis:6379 → migrate → collectstatic → daphne listening on 0.0.0.0:8000`.

---

## 4. Migrate + create superuser

The backend entrypoint already runs `migrate` on every restart, but the
first boot may not have a Django admin user. Create one:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py createsuperuser
```

After **every** `git pull` on the VPS, run the migration drift gate so
schema drift is caught at deploy time, not at the next dev session:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py makemigrations --check --dry-run

# Phase 6E — SaaS admin + integration settings foundation.
# Phase 6D org-aware write assignment is FULL PASS. These checks are
# read-only except ensure_default_organization, which is idempotent and
# keeps the single-tenant default org/branch present.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py ensure_default_organization --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_default_organization_coverage --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_scoped_api_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_write_path_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_saas_admin_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_integration_settings --json

# Phase 5E-Hotfix-2 — refresh demo Claim Vault rows to demo-v2 once.
# Real admin / doctor-approved claims are NEVER overwritten.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_default_claims --reset-demo

# Confirm no demo row is reported as weak.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py check_claim_vault_coverage

# Phase 5E-Smoke — controlled smoke harness. Defaults are SAFE
# (dry-run + mock-WhatsApp + mock-Vapi + OpenAI off). Run before
# flipping any automation flag. Refuses real Meta provider outright.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario all --json

# Phase 5E-Smoke-Fix-2 — adapter code change. Modern OpenAI Chat
# models (gpt-4o, gpt-5, o1, o3, …) reject 'max_tokens' and require
# 'max_completion_tokens'. The adapter now always uses the modern
# parameter. After this commit, rebuild + restart so the new adapter
# code lands in the backend image, then re-run the OpenAI smoke.

# Phase 5E-Smoke-Fix — when the requirements.txt changes (e.g. the
# openai SDK was added), rebuild the backend image so pip install
# picks up the new dep, then re-run the OpenAI provider smoke. The
# expected outcome is openaiSucceeded=true + providerPassed=true.
# A safeFailure=true result means the SDK / API key / AI_PROVIDER
# is wrong — fix it before flipping any automation flag.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production build backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d backend worker beat
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python -c "from openai import OpenAI; print('openai SDK OK')"
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test \
        --scenario ai-reply --language hinglish --use-openai --mock-whatsapp --dry-run --json

# Single-scenario examples (use these to debug a specific surface).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario claim-vault --json

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hinglish --mock-whatsapp --dry-run

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario rescue-discount --dry-run --json

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario vapi-handoff --mock-vapi --dry-run

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario reorder-day20 --dry-run
```

Expected output: `No changes detected`. If the `--check` reports
pending migrations, **stop the deploy** — a hand-rolled migration
drifted from the model definition. Generate the missing migration
locally with `python manage.py makemigrations`, push the new
`apps/<app>/migrations/0XXX_*.py` file, then re-pull on the VPS.

Phase 5E-Hotfix is the canonical example of this drift: Phase 5D / 5E
shipped with hand-rolled short index names (`whatsapp_wh_convers_h0_idx`,
`orders_disc_order_i_dol_idx`, …) that did not match Django's auto-suffix
form, and the VPS first-deploy after commit `8374863` reported pending
migrations until two `RenameIndex` migrations (`0004_rename_*`) were
generated locally and re-pulled.

Optional demo seed (do **not** run on a live customer DB):

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_demo_data --reset
```

Sync the canonical lifecycle WhatsApp templates so the `/whatsapp-templates`
page has working rows:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py sync_whatsapp_templates
```

---

## 5. Smoke tests

```bash
# Backend health (DRF)
curl -fsS http://127.0.0.1:18020/api/healthz/
# {"status":"ok","service":"nirogidhara-backend"}

# Frontend SPA root
curl -fsSI http://127.0.0.1:18020/

# WebSocket route exists (will 426 / 400 without a proper Upgrade header)
curl -fsSI http://127.0.0.1:18020/ws/audit/events/ | head -1
```

Browser tour (after the host Nginx / Traefik step in §6):

- `https://ai.nirogidhara.com/` — Command Center dashboard
- `https://ai.nirogidhara.com/whatsapp-inbox` — Phase 5B inbox (manual-only)
- `https://ai.nirogidhara.com/admin/` — Django admin (login with the superuser above)

### 5.1 Phase 5F-Gate — Limited Live Meta WhatsApp One-Number Test

Required gate before flipping any of the six automation flags. Run on
the VPS, against the production-target backend container:

```bash
# 1. Print the expected Meta webhook callback URL + verify-token presence.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_meta_one_number_test \
    --check-webhook-config --json

# 2. Add ONE approved test MSISDN to .env.production:
#    WHATSAPP_PROVIDER=meta_cloud
#    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
#    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS=+91XXXXXXXXXX
#    META_WA_ACCESS_TOKEN=<approved Meta WA Cloud token>
#    META_WA_PHONE_NUMBER_ID=<from WABA>
#    META_WA_BUSINESS_ACCOUNT_ID=<from WABA>
#    META_WA_VERIFY_TOKEN=<random secret you choose, paste same in Meta console>
#    META_WA_APP_SECRET=<from Meta App settings>
#    Restart the backend + worker containers after editing.

# 3. Verify-only — runs the precondition stack and exits without sending.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_meta_one_number_test \
    --to +91XXXXXXXXXX --template nrg_greeting_intro --verify-only --json

# 4. Real send (only after verify-only reports passed=true).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_meta_one_number_test \
    --to +91XXXXXXXXXX --template nrg_greeting_intro --send --json
```

Required outputs:

- `passed=true` for both `--verify-only` and `--send` runs.
- `auditEvents` for the `--send` run includes
  `whatsapp.meta_test.sent` and `nextAction=verify_inbound_webhook_callback`.
- The destination phone receives the locked greeting on WhatsApp.
- The Meta webhook posts a status (`sent`/`delivered`) back to
  `https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/`; check the
  audit ledger for `whatsapp.message.delivered`.

If anything is amber, the JSON output's `nextAction` field tells you
exactly what to fix (see RUNBOOK §"Phase 5F-Gate"). The harness refuses
outright if any of the six automation flags is on.

### 5.2 Phase 5F-Gate Hardening Hotfix — post-live-pass diagnostics

Once the one-number test has passed at least once, run the
**read-only inspector** after every deploy to confirm the limited
live state stays healthy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_live_test \
    --phone +918949879990 --json
```

Required output for a clean state:

- `nextAction == "gate_hardened_ready_for_limited_ai_auto_reply_plan"`
  (or `observe_status_events_optional` if Meta has not yet posted any
  status webhooks — soft signal only).
- `customer.found == true` and `whatsappConsent.consent_state == "granted"`.
- `messages.latestOutbound[0].status == "sent"` (or `delivered` / `read`).
- `messages.latestInbound[0]` present.
- `wabaSubscription.wabaSubscriptionActive == true`.
- `errors == []`.

Inspector is **strictly read-only** — never sends, never mutates the
DB, never prints `META_WA_ACCESS_TOKEN` / `META_WA_VERIFY_TOKEN` /
`META_WA_APP_SECRET`. Safe to re-run any time. If `nextAction ==
"subscribe_waba_to_app_webhooks"`, the WABA's webhook subscription has
fallen out — re-run the curl `POST /{WABA_ID}/subscribed_apps` +
override-callback fix from §5.1.

Re-run the harness's `--check-webhook-config --json` whenever the
inspector flags `subscribe_waba_to_app_webhooks` — the new diagnostics
block surfaces `wabaSubscriptionActive` + `wabaSubscribedAppCount`
without printing tokens.

### 5.3 Phase 5F-Gate Controlled AI Auto-Reply Test

After the inspector reports a clean state, run the controlled AI
auto-reply test against the **single allowed test number** without
flipping the global `WHATSAPP_AI_AUTO_REPLY_ENABLED` env. The flag
must stay `false` for this test to run — the harness is the only
sanctioned path that may produce a real AI reply during the gate
phase.

```bash
# 1. Dry-run — every precondition, no LLM call, no DB inbound row.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste mujhe weight loss product ke baare me bataye" \
    --dry-run --json

# 2. Live `--send` — drives the orchestrator with force_auto_reply=True
# for ONE call only. Refused on any amber gate.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste mujhe weight loss product ke baare me bataye" \
    --send --json
```

Required outputs for a clean live `--send` run:

- `passed == true`
- `replySent == true`
- `outboundMessageId` and `providerMessageId` populated
- `auditEvents` includes `whatsapp.ai.controlled_test.sent` and
  `whatsapp.ai.controlled_test.completed`
- `nextAction == "live_ai_reply_sent_verify_phone"`
- The test phone receives the AI reply on WhatsApp

**Rollback / safety check.** If anything looks wrong, immediately
verify automation flags stay off:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend printenv | grep -E \
    "WHATSAPP_AI_AUTO_REPLY_ENABLED|WHATSAPP_CALL_HANDOFF_ENABLED|\
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED|WHATSAPP_RESCUE_DISCOUNT_ENABLED|\
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED|WHATSAPP_REORDER_DAY20_ENABLED|\
WHATSAPP_LIVE_META_LIMITED_TEST_MODE|WHATSAPP_PROVIDER"
```

Expected safe state:

```
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
WHATSAPP_PROVIDER=meta_cloud
WHATSAPP_AI_AUTO_REPLY_ENABLED=false
WHATSAPP_CALL_HANDOFF_ENABLED=false
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false
WHATSAPP_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_REORDER_DAY20_ENABLED=false
```

If `WHATSAPP_AI_AUTO_REPLY_ENABLED` is `true`, **stop and revert it**.
Phase 5F (broadcast campaigns) remains LOCKED until a 24-hour soak
under the controlled harness has been observed cleanly.

### 5.4 Phase 5F-Gate Claim Vault Grounding Fix — re-run after deploy

After the Claim Vault Grounding Fix lands on the VPS, re-run the
dry-run + live-send with an explicit weight-management prompt and
require the **new grounding diagnostics** to come back clean before
proceeding:

```bash
# Confirm the Claim Vault still has the Weight Management row.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py check_claim_vault_coverage --json

# Inspector check (read-only).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_live_test \
    --phone +918949879990 --json

# Dry-run with the explicit weight-management prompt.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --dry-run --json
```

Required JSON fields on the dry-run:

- `passed == true`
- `nextAction == "dry_run_passed_ready_for_send"`
- `groundingStatus.claimProductFound == true`
- `groundingStatus.approvedClaimCount >= 1`
- `groundingStatus.promptGroundingInjected == true`

```bash
# Live --send (only after dry-run passes).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Post-live audit tail to confirm the grounding context is in the
# audit ledger (no tokens, last-4 phone only).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.ai').order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

If the live `--send` returns `nextAction=blocked_for_unapproved_claim`
again with `groundingStatus.approvedClaimCount=0`, the Claim Vault
seed has not been re-applied — re-run `seed_default_claims --reset-demo`
or restore the doctor-approved row before retrying.

### 5.5 Phase 5F-Gate Controlled Reply Confidence Fix — re-run

After the Confidence Fix lands on the VPS, re-run the live `--send`
and verify the LLM now chooses `action=send_reply` with
`confidence ≥ confidenceThreshold` and the reply literally carries
both an approved Claim Vault phrase AND the ₹3000/30-capsules/₹499
business facts.

```bash
# Same dry-run from §5.4 — must still pass.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --dry-run --json

# Live --send. Required JSON:
#   passed=true
#   replySent=true
#   action="send_reply"
#   claimVaultUsed=true
#   confidence>=confidenceThreshold (0.75 default)
#   replyPreview literally contains at least one approved phrase
#     (e.g. "Supports healthy metabolism") AND ₹3000 / 30 capsules
#     when the customer asked about price/quantity
#   nextAction="live_ai_reply_sent_verify_phone"
#   sendEligibilitySummary="Live AI reply sent ..."
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Audit tail — verify the new split counts (claim_row_count vs
# approved_claim_count vs disallowed_phrase_count) appear cleanly.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.ai').order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

If the LLM still returns `action=handoff` on a grounded inquiry,
inspect the audit row's `confidence`, `approved_claim_count`, and
`category` fields and confirm the prompt rebuild reached the
backend container (`docker compose ... build --no-cache backend`).
The fix is in the prompt — not in lowering the threshold. Do **not**
edit `WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD` to compensate.

### 5.6 Phase 5F-Gate Deterministic Grounded Reply Builder — re-run

After the Deterministic Grounded Reply Builder lands on the VPS,
the controlled-test command's `--send` no longer depends on the
LLM choosing `action=send_reply`. If the LLM blocks with a soft
non-safety reason (`claim_vault_not_used` / `low_confidence` /
`ai_handoff_requested` / `auto_reply_disabled`) AND the backend has
valid grounding AND the inbound is a normal product-info inquiry,
the command **falls back** to a deterministic Hinglish reply built
from `Claim.approved` + locked business facts and dispatches it
through the same `services.send_freeform_text_message` path.

```bash
# Inspector first.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_live_test \
    --phone +918949879990 --json

# Dry-run.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --dry-run --json

# Live --send. Two outcomes count as success:
#   (a) LLM honoured the prompt → finalReplySource="llm",
#       deterministicFallbackUsed=false.
#   (b) LLM still blocked but backend fallback dispatched →
#       finalReplySource="deterministic_grounded_builder",
#       deterministicFallbackUsed=true,
#       fallbackReason ∈ {"claim_vault_not_used", "low_confidence",
#                         "ai_handoff_requested",
#                         "auto_reply_disabled"}.
# Either way: passed=true, replySent=true, claimVaultUsed=true,
# finalReplyValidation.passed=true,
# finalReplyValidation.containsApprovedClaim=true.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Audit tail — confirm whatsapp.ai.deterministic_grounded_reply_used
# fires (path b) or whatsapp.ai.controlled_test.sent fires alone
# (path a). No tokens / secrets in payloads.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.ai').order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

If `deterministicFallbackUsed=true` and the test phone receives the
deterministic reply, the gate is **passing safely** — the LLM's
inability to self-report `claimVaultUsed=true` no longer blocks the
controlled live test. Webhook-driven production runs still flow
through the orchestrator's strict path; this fallback is
controlled-test-only.

### 5.7 Phase 5F-Gate Objection & Handoff Reason Refinement — re-run

After this phase lands on the VPS, re-run the **scenario matrix
subset** to confirm the typed reasons now appear correctly:

```bash
# Scenario A — discount objection.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "weight management product accha hai lekin thoda mehenga lag raha hai. Kuch kam ho sakta hai?" \
    --send --json
# Expected:
#   passed=true, replySent=true,
#   detectedIntent="discount_objection",
#   objectionDetected=true, objectionType ∈ {discount, price},
#   finalReplySource="deterministic_objection_reply",
#   replyPolicy.upfrontDiscountOffered=false,
#   replyPolicy.discountMutationCreated=false,
#   replyPolicy.businessMutationCreated=false,
#   replyPreview embeds an approved Claim Vault phrase + ₹3000 / 30 capsules.

# Scenario B — human call request.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "AI se baat nahi karni, mujhe call karwa do" \
    --send --json
# Expected:
#   passed=false, replySent=false, replyBlocked=true,
#   detectedIntent="human_request", humanRequestDetected=true,
#   blockedReason="human_advisor_requested",
#   handoffReason="human_advisor_requested",
#   nextAction="human_handoff_requested",
#   finalReplySource="blocked_handoff", safetyBlocked=false.
#   The whatsapp.ai.handoff_required audit row payload reason MUST
#   be "human_advisor_requested" — NOT "claim_vault_not_used".

# Scenario C — side-effect complaint.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "medicine khane ke baad ulta asar ho gaya, vomiting bhi hui" \
    --send --json
# Expected: passed=false, safetyBlocked=true,
#   nextAction="blocked_for_medical_safety",
#   detectedIntent="unsafe".

# Scenario D — legal/refund threat.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "consumer forum me complaint karunga, refund chahiye" \
    --send --json
# Expected: passed=false, replyBlocked=true, no sales reply,
#   detectedIntent="unsafe" (legal vocabulary disqualifies).

# Scenario E — mutation safety check (read-only Python shell).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
print('DiscountOfferLog:', DiscountOfferLog.objects.count())
print('Order:', Order.objects.count())
print('Payment:', Payment.objects.count())
print('Shipment:', Shipment.objects.count())
"
# Expected: counts unchanged from pre-test snapshot — the controlled
# objection / human-request paths NEVER mutate business state.
```

Then tail the audit ledger and confirm the new typed reasons + the
four new audit kinds appear cleanly:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__in=[
    'whatsapp.ai.objection_detected',
    'whatsapp.ai.objection_reply_used',
    'whatsapp.ai.objection_reply_blocked',
    'whatsapp.ai.human_request_detected',
    'whatsapp.ai.handoff_required',
]).order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

Confirm the `whatsapp.ai.handoff_required` row from Scenario B
carries `payload['reason'] == 'human_advisor_requested'`. **Do not
proceed to flag flips if any row carries `reason=claim_vault_not_used`
on a human-request inbound.**

### 5.8 Phase 5F-Gate Internal Allowed-Number Cohort Tooling — expand to 2–3 staff numbers

After the one-number scenario matrix passes cleanly, expand the
controlled live test to a tiny internal cohort of 2–3 staff numbers
without unlocking any broad automation.

```bash
# 1. Edit .env.production to ADD staff numbers (start with 2–3 only).
#    KEEP every automation flag default OFF.
#    DO NOT paste real phone numbers in public docs / Slack / GitHub.

# 2. Recreate backend/worker/beat/nginx so the new env is read.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never backend worker beat nginx

# 3. Inspect cohort readiness (phones masked to last-4 by default).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_internal_cohort --json

# 4. Prepare each new number (refuses non-allow-list phones).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py prepare_whatsapp_internal_test_number \
    --phone +91XXXXXXXXXX \
    --name "Internal Staff Name" \
    --source internal_cohort_test \
    --json

# 5. (Optional) Cohort dry-run readiness across all five scenarios.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_whatsapp_internal_cohort_dry_run --json

# 6. Run the 7-scenario matrix per number (use the messages from
#    §5.7 and §5.4–5.6). Do this one number at a time and confirm
#    the WhatsApp phone receives the correct reply / no reply per
#    scenario before moving to the next number.

# 7. Audit + mutation safety check.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
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
for e in AuditEvent.objects.filter(kind__in=[
    'whatsapp.internal_cohort.number_prepared',
    'whatsapp.ai.controlled_test.sent',
    'whatsapp.ai.controlled_test.blocked',
    'whatsapp.ai.handoff_required',
]).order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.payload)
"
```

**Hard constraints during cohort expansion:**

- `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` stays.
- `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` stays.
- `WHATSAPP_CALL_HANDOFF_ENABLED=false` stays.
- `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false` stays.
- `WHATSAPP_RESCUE_DISCOUNT_ENABLED=false` stays.
- `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false` stays.
- `WHATSAPP_REORDER_DAY20_ENABLED=false` stays.
- Cohort starts with 2–3 numbers only. Do NOT add customer
  numbers; this is for internal staff testing only.
- Full phone numbers NEVER committed to docs / git / audit
  payloads. The audit row carries `phone_suffix` only.

---

## 6. DNS + TLS for `ai.nirogidhara.com`

### 6.1 DNS

Add an A record at the registrar:

```
Type:  A
Host:  ai
Value: <Hostinger VPS public IP>     # e.g. 187.127.132.106
TTL:   300
```

Wait for propagation (`dig +short ai.nirogidhara.com`) before requesting
a TLS cert.

### 6.2 Option A — Host-level Nginx + Certbot (recommended)

This is the cleanest path on a Hostinger VPS that already runs other
Docker projects. Each project keeps its own internal Nginx and exposes
one host port; the host Nginx terminates TLS and routes by domain.

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

sudo tee /etc/nginx/sites-available/ai.nirogidhara.com >/dev/null <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name ai.nirogidhara.com;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:18020;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/ai.nirogidhara.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Auto-issues + auto-renews. Pick redirect-to-HTTPS when prompted.
sudo certbot --nginx -d ai.nirogidhara.com
```

After certbot completes, browse to `https://ai.nirogidhara.com/`.

### 6.3 Option B — Hostinger Traefik / Docker Manager

If the VPS is managed entirely through Hostinger's Docker UI, point the
`ai.nirogidhara.com` route at this project's container port `80` (the
inner Nginx). Hostinger's Traefik handles TLS via Let's Encrypt
automatically. The container's host port (`18020`) is unchanged so it
stays compatible with the host-Nginx fallback above.

> Pick **one** of A or B — running both at the same time leaks the same
> upstream behind two domains and confuses CSRF / consent telemetry.

---

## 7. Daily operations

### 7.1 Logs

```bash
cd /opt/nirogidhara-command
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f beat
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f nginx
```

### 7.2 Restart / stop

```bash
# Restart everything (keeps volumes + data).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production restart

# Stop the stack (keeps volumes + data).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production down

# Stop + delete volumes (DANGER — wipes DB + Redis state).
# Only on explicit user confirmation.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production down -v
```

### 7.3 Update deployment

```bash
cd /opt/nirogidhara-command
sudo git pull origin main

# Rebuild + restart. `--pull never` keeps the local image cache in
# place; without it Compose tries to pull `nirogidhara/backend:latest`
# from a registry that does not exist and the deploy stalls.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never

# Run migrations explicitly (the entrypoint also does this, but an
# explicit run is easier to scan for warnings).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    run --rm --entrypoint sh backend -lc "python manage.py migrate --no-input"
```

### 7.4 Backups (recommended before going live)

```bash
# Postgres dump → host filesystem.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec -T postgres pg_dump -U nirogidhara nirogidhara | gzip > \
    /opt/nirogidhara-command/backups/db-$(date +%F).sql.gz

# Static + media (rarely needed but cheap to copy).
sudo docker run --rm \
    -v nirogidhara_static_volume:/from \
    -v /opt/nirogidhara-command/backups:/to alpine \
    sh -c 'cd /from && tar czf /to/static-$(date +%F).tgz .'
```

Schedule via cron once the customer DB is live.

---

## 8. Resource safety on a shared VPS

Postzyo + OpenClaw already run on this host. Do **not** prune Docker
state globally without checking with the user.

```bash
# Safe — read-only.
docker stats
sudo docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker system df
docker network ls
docker volume ls | grep nirogidhara

# DANGER — deletes images, networks, volumes for ALL stacks.
# docker system prune -a --volumes      ← only on explicit user approval.
```

Tuning knobs that are safe to dial up after watching `docker stats` for
a day:

- `worker.command` → bump `--concurrency=1` to 2 once memory is stable.
- `nirogidhara-redis` → keep `--appendonly yes`; rotate `appendonly.aof`
  via Redis if it grows past a few hundred MB.
- Postgres → 16-alpine ships sensible defaults; only tune
  `max_connections` if observed contention happens.

---

## 8.5 Troubleshooting — duplicate Postgres index on first migrate

If the **first** `migrate` against a fresh Postgres errors out with one
or more of:

```
django.db.utils.ProgrammingError: relation "calls_calltranscriptline_call_id_5bc33dc3" already exists
django.db.utils.ProgrammingError: relation "calls_calltranscriptline_call_id_5bc33dc3_like" already exists
```

…you have hit a known production-only data race in
`apps/calls/migrations/0002_phase2d_vapi_fields.py`. Django creates the
support indexes for the FK in two passes; under Postgres 16 + Daphne
+ Celery worker / beat all booting at once, a stale index from a prior
half-applied migration can survive into the next attempt.

**Fix without dropping the database:**

```bash
cd /opt/nirogidhara-command

# 1) Stop everything that talks to the schema. Keep only Postgres + Redis up.
docker compose -f docker-compose.prod.yml --env-file .env.production stop \
    backend worker beat nginx
docker compose -f docker-compose.prod.yml --env-file .env.production up -d \
    postgres redis

# 2) Drop the two clashing indexes (idempotent — safe to re-run).
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c \
    'DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3; DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3_like;'

# 3) Re-run migrate via a one-shot backend container (entrypoint runs
#    migrate automatically, so we override it to a plain shell here to
#    avoid double-collectstatic in the recovery path).
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
    --entrypoint sh backend -lc "python manage.py migrate --no-input"

# 4) Bring the rest of the stack back up. `--pull never` keeps the local
#    image in place (the recovery already proved it works).
docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never
```

If multiple FK index variants exist (e.g. after several failed retries),
sweep all of them in one shot:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c "DO \$\$ DECLARE r RECORD; BEGIN FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'calls_calltranscriptline_call_id_%' LOOP EXECUTE format('DROP INDEX IF EXISTS %I', r.indexname); END LOOP; END \$\$;"
```

> **Do not** edit `apps/calls/migrations/0002_phase2d_vapi_fields.py` to
> "fix" this in the repo. Migration files are append-only history; a
> patch that works for one customer's DB will silently desync from
> another. Keep the workaround in this runbook.

After the sweep:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
curl -fsS http://127.0.0.1:18020/api/healthz/
```

The backend should boot cleanly and `migrate` should be a no-op.

## 8.1 Phase 5F-Gate customer pilot readiness post-deploy

This phase prepares a tiny approved customer pilot only. It does not
enable broad rollout, does not send WhatsApp messages, and does not
mutate Order / Payment / Shipment / Discount rows. Keep:

```bash
WHATSAPP_AI_AUTO_REPLY_ENABLED=false
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
WHATSAPP_CALL_HANDOFF_ENABLED=false
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false
WHATSAPP_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_REORDER_DAY20_ENABLED=false
```

After deploy:

```bash
cd /opt/nirogidhara-command

docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate --no-input

docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py makemigrations --check --dry-run

docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_customer_pilot --json

curl -fsS -H "Authorization: Bearer <admin-jwt>" \
    "https://ai.nirogidhara.com/api/v1/whatsapp/monitoring/pilot/?hours=2" | jq
```

Use `prepare_whatsapp_customer_pilot_member --phone +91XXXXXXXXXX
--name "Customer Name" --source approved_customer_pilot --json` only
after explicit customer consent is documented. Missing consent leaves the
pilot member pending. The dashboard section at `/whatsapp-monitoring`
must show masked phones only and no send/enable controls. The prior
4-hour soak was accelerated, not full-duration, so this customer pilot
still needs conservative monitoring before any flag flip.

## 9. Security checklist before customers go live

- [ ] `DJANGO_SECRET_KEY` and `JWT_SIGNING_KEY` are unique, long, and never committed.
- [ ] `DEBUG=false` everywhere in `.env.production`.
- [ ] `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` all include `ai.nirogidhara.com` and nothing wildcarded.
- [ ] Postgres password is strong and matches the value embedded in `DATABASE_URL`.
- [ ] `WHATSAPP_PROVIDER`, `RAZORPAY_MODE`, `DELHIVERY_MODE`, `VAPI_MODE`, `META_MODE` all stay `mock` until Prarit confirms each integration's live credentials.
- [ ] `AI_PROVIDER` stays `disabled` until OpenAI / Anthropic keys are in place.
- [ ] `WHATSAPP_DEV_PROVIDER_ENABLED=false` (the Baileys stub refuses to load anyway when DEBUG=false, but this is belt + braces).
- [ ] Postgres `pg_dump` backup taken before the first real customer payment / order.
- [ ] Host Nginx (or Traefik) terminates TLS; HTTP 80 either redirects to HTTPS or is closed at the firewall.
- [ ] `docker stats` confirms the new stack is leaving headroom for Postzyo + OpenClaw.
- [ ] **Phase 5C — WhatsApp AI Chat Sales Agent.** `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` until: (a) `AI_PROVIDER=openai` + `OPENAI_API_KEY` set, (b) the locked greeting template (`whatsapp.greeting`) is synced and approved, (c) `Claim` rows exist for every product the agent must explain, (d) a controlled run on test numbers passes. Flip the env to `true` and restart the backend / worker / beat containers to enable auto-mode.

---

## 10. What's intentionally NOT here

This deployment scaffold ships **only** Phase 1 → 5B. The following stay
locked out at the application layer regardless of how the container is
configured:

- AI Chat Sales Agent (Phase 5C)
- WhatsApp inbound auto-reply
- Chat-to-call handoff
- Order booking from WhatsApp chat
- Discount automation / rescue-discount flow
- Campaign / broadcast WhatsApp sends
- Freeform outbound WhatsApp text
- CAIO-originated customer messages

If the deploy somehow turns those on, **stop the rollout** and re-read
`docs/WHATSAPP_INTEGRATION_PLAN.md` and `nd.md` §2 hard stops.
