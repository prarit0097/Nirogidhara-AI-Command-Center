# Runbook — Nirogidhara AI Command Center

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
python -m pytest -q                     # 401 tests (Phase 1 → 5A inclusive)

# Frontend
cd ../frontend
npm test                                # 13 vitest tests
npm run lint                            # 0 errors, ~8 pre-existing shadcn warnings
npm run build                           # Production build
```

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
