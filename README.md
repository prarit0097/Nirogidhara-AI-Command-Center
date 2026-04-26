# Nirogidhara AI Command Center

AI Business Operating System for Ayurveda sales, CRM, AI calling, payments,
Delhivery delivery tracking, RTO control, AI agents, CEO AI, CAIO governance,
reward/penalty engine, and the human-call learning loop.

> Full vision: see *Nirogidhara AI Command Center — Master Blueprint v1.0*.

## Monorepo layout

```
nirogidhara-command/
  frontend/   # React 18 + Vite + TS + shadcn UI (current Lovable app)
  backend/    # Django 5 + DRF — implements the api.ts contract
  docs/       # RUNBOOK, BACKEND_API, FRONTEND_AUDIT, FUTURE_BACKEND_PLAN
```

## Quickstart

```bash
# 1. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                  # cp on macOS/Linux
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py runserver 0.0.0.0:8000

# 2. Frontend (new terminal)
cd frontend
npm install
copy .env.example .env                  # cp on macOS/Linux
npm run dev
```

Open [http://localhost:8080](http://localhost:8080) — the dashboard now reads
real data from Django. Stop the backend and the frontend transparently falls
back to the deterministic mock fixtures in
`frontend/src/services/mockData.ts`.

Full setup detail in [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Architecture rule

The frontend never holds business logic. It calls the API service layer
(`frontend/src/services/api.ts`); every function in that layer maps 1-to-1 to
a Django REST endpoint documented in [`docs/BACKEND_API.md`](docs/BACKEND_API.md).

```
┌────────────┐    /api/...      ┌─────────────────┐
│  React UI  │  ─────────────▶  │   Django + DRF  │
└────────────┘   (JSON, JWT)    └─────────────────┘
       │                              │
       └──── mock fallback ───────────┘
            (offline-safe dev)
```

## Tests

```bash
# Backend (pytest, 26 tests)
cd backend && python -m pytest -q

# Frontend (vitest, 8 tests)
cd frontend && npm test
```

## Phase scope

Phase 1 (current) ships:

- All 14 Django apps from blueprint Section 15.
- 25 read endpoints matching `frontend/src/services/api.ts`.
- JWT auth, CORS, Master Event Ledger via signals.
- Seed command that mirrors the frontend's mock fixtures (42 leads, 60 orders,
  18 calls, 19 agents, etc.).
- Frontend wired to backend with mock fallback.

Phase 2+ roadmap (real integrations, LLM agents, WebSockets, sandbox,
governance UI, multi-tenant SaaS) lives in
[`docs/FUTURE_BACKEND_PLAN.md`](docs/FUTURE_BACKEND_PLAN.md).

## Stack

**Frontend:** React 18, Vite, TypeScript, Tailwind, shadcn UI, React Router, Recharts, Vitest

**Backend:** Python 3.10+, Django 5.1, Django REST Framework, simplejwt, django-cors-headers, dj-database-url, pytest

## License

Proprietary — Nirogidhara Private Limited. Internal use only.
