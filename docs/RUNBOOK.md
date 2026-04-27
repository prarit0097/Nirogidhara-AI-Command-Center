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
python -m pytest -q                     # ~26 tests

# Frontend
cd ../frontend
npm test                                # ~8 vitest tests
npm run lint                            # 0 errors, ~8 pre-existing shadcn warnings
npm run build                           # Production build
```

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

## Common issues

| Symptom | Fix |
| --- | --- |
| Frontend pages load but data is mock-only | Check the dev console for `[api] Falling back…` warnings. Backend is probably down or `VITE_API_BASE_URL` is wrong. |
| `CORS` error in browser | Add the frontend origin to `CORS_ALLOWED_ORIGINS` in `backend/.env`. Default covers `http://localhost:8080` and `http://127.0.0.1:8080`. |
| `relation "..." does not exist` on Postgres | Run `python manage.py migrate`. |
| `OperationalError: no such table` | Same — run migrations. |
| `python` command not found on Windows | Use `py -3.10` or install Python 3.10+ from python.org. |
| `npm test` hangs | The Vitest run completes in ~7s. If it hangs there's likely a stale process — `Ctrl+C` and retry. |
