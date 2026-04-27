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
python -m pytest -q                     # 219 tests (Phase 1 → 3E)

# Frontend
cd ../frontend
npm test                                # ~8 vitest tests
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
