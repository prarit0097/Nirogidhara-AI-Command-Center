# Nirogidhara AI Command Center — Project Handoff (`nd.md`)

> Read this file end-to-end before touching the repo.
> If you are a coding agent: this is your single source of truth.
> Reference doc: **Nirogidhara AI Command Center — Master Blueprint v1.0** (PDF in repo).

---

## 0. TL;DR (60-second read)

- **What it is:** A full-stack AI Business Operating System for an Ayurvedic medicine D2C company (Nirogidhara Private Limited).
- **Owner / Director:** Prarit Sidana — final authority for high-risk decisions.
- **Stack:** React 18 + Vite + TypeScript (frontend) ↔ Django 5 + DRF (backend), JWT auth, SQLite (dev) / Postgres (prod-ready).
- **Repo layout:** monorepo — `frontend/`, `backend/`, `docs/`.
- **Status today (Phase 1 + 2A + 2B + 2C + 2D done; Phase 3 env scaffolded):** All 14 Django apps scaffolded, **25 read + 15 write endpoints + Razorpay webhook + Delhivery webhook + Vapi webhook** live, Master Event Ledger via signals + explicit service writes, JWT auth + role-based permissions, order state machine, **Razorpay payment-link integration with mock/test/live modes + HMAC-verified webhook + idempotency**, **Delhivery courier integration with mock/test/live modes + HMAC-verified tracking webhook handling delivered/NDR/RTO**, **Vapi voice trigger + transcript ingest with mock/test/live modes + HMAC-verified webhook handling six handoff flags (medical / side-effect / angry / human-requested / low-confidence / legal-threat)**, **AI provider env scaffolding (OpenAI / Anthropic / Grok — disabled by default, no SDK calls yet)**, seed command, frontend wired with **automatic mock fallback**. **93 backend tests + 8 frontend tests** all green.
- **What's next (Phase 2E+):** Meta Lead Ads webhook, LLM-powered AI agent reasoning, WebSockets, governance UI write paths (kill switch / sandbox / rollback), learning loop pipeline, multi-tenant SaaS.
- **Run it:** `cd backend && python manage.py runserver` + `cd frontend && npm run dev` → open `http://localhost:8080`.

---

## 0.5 Working agreement (binding rule for all contributors / agents)

**Every meaningful change to this project MUST be followed by:**

1. **Update `nd.md`** — adjust the relevant section (TL;DR §0, what's done §8, phase roadmap §11, etc.) so the handoff stays the source of truth.
2. **Update `AGENTS.md`** — if a convention, hard stop, or pointer changed.
3. **Run verification** — `pytest -q` (backend), `npm run lint && npm test && npm run build` (frontend).
4. **Commit** with a Conventional Commit message (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
5. **Push to `origin/main`** at https://github.com/prarit0097/Nirogidhara-AI-Command-Center.

The GitHub remote must mirror local state at the end of every working session. Non-negotiable. AI agents (Claude Code, Cursor, etc.) inherit this rule via `CLAUDE.md` and `AGENTS.md`.

**Never without explicit user authorization**: force-push to `main`, rewrite pushed history, skip hooks, commit secrets.

---

## 1. What is this product?

Nirogidhara sells Ayurvedic medicines across categories like **Weight Management, Blood Purification, Men/Women Wellness, Immunity, Lungs Detox, Body Detox, Joint Care**. Standard product is ₹3000 for 30 capsules; agents may apply 10–30% discount within authority.

Today the business runs on Google Sheets + a local dialer + manual CRM entry. The current process:

1. Meta ads + inbound calls generate **leads**.
2. Calling agents (currently human) talk to leads in Hindi/Hinglish — understand problem & lifestyle, explain product.
3. Agent applies discount (within authority), tries to collect **₹499 advance payment** via Razorpay/PayU.
4. Agent **punches order** in CRM with full address.
5. ~24 hours later, confirmation team verifies the order (name, address, product, amount, intent).
6. Confirmed orders go to **Delhivery** for dispatch.
7. Delivery-day reminder call happens.
8. Delivered / RTO status updates back into CRM.
9. Post-delivery: usage explanation, satisfaction call, reorder cadence (Day 0 / 3 / 7 / 15 / 25 / 30 / 45).

### The vision (why we're building this)

Replace the spreadsheet-and-dialer reality with a **single AI-run command center** where:

- **AI voice agents** make the sales calls (Vapi or similar) in Hindi/Hinglish using only **Approved Claim Vault** content.
- **Department AI agents** (Ads, Marketing, Sales Growth, RTO Prevention, CFO, Compliance, Customer Success, etc.) generate insights and rule-based actions.
- A **CEO AI Agent** approves executions and sends Prarit a daily brief.
- A **CAIO Agent** audits everything (hallucination, weak learning, compliance risk) — it **never executes** business actions; it only reports to CEO AI and alerts Prarit.
- A **Master Event Ledger** logs every important state change (lead/order/payment/shipment/reward).
- Prarit watches a real-time dashboard, approves the high-risk decisions, and runs the company with a small human team.

**Main KPI** (do not optimize anything else above this):
```
Net Delivered Profit = Delivered Revenue
                       − Ad Cost
                       − Discount
                       − Courier Cost
                       − RTO Loss
                       − Payment Gateway Charges
                       − Product Cost
```
Reward/penalty is based on **delivered profitable orders**, not "orders punched".

---

## 2. Final locked non-negotiables (from Master Blueprint §26)

Any change must respect every one of these:

1. Backend is **Django + DRF, API-first**.
2. Frontend consumes APIs only — **no business logic in the frontend**.
3. Real-time dashboard must show live true data (poll-based today, WebSockets in Phase 4).
4. AI must speak only from the **Approved Claim Vault**. No free-style medical claims.
5. **CAIO never executes** business actions. It monitors / audits / alerts only.
6. **CEO AI is the execution approval layer** for low/medium-risk actions.
7. **Prarit is final authority** for high-risk decisions (ad budget changes, refunds, new claims, emergencies).
8. Every critical event is logged in the **Master Event Ledger** (`audit.AuditEvent`).
9. Human call recordings must **never** auto-train live AI without QA → Compliance → CAIO → Sandbox → CEO approval.
10. Reward/penalty is based on **delivered profitable quality orders**, never on punching count alone.
11. **AI Kill Switch, Sandbox Mode, Rollback System, Approval Matrix** are mandatory before any production rollout.
12. Future Android/iOS apps must use the **same backend APIs** — no logic forking.

### Blocked claim phrases (compliance — never let AI emit these)
- "Guaranteed cure"
- "Permanent solution"
- "No side effects for everyone"
- "Works for all people universally"
- "Doctor ki zarurat nahi"
- Emergency medical advice
- Any disease-cure claim without doctor approval

---

## 3. Repo layout

```
nirogidhara-command/
├── README.md                      # Quickstart
├── nd.md                          # ← you are here
├── frontend/                      # React 18 + Vite + TS + shadcn UI
│   ├── package.json
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   ├── tsconfig*.json
│   ├── tailwind.config.ts
│   ├── eslint.config.js
│   ├── .env.example               # VITE_API_BASE_URL=http://localhost:8000/api
│   ├── README.md
│   ├── public/
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                # Router + 17 routes
│       ├── index.css              # Tailwind tokens
│       ├── types/domain.ts        # ← TS contract (every type below maps 1:1 to a Django serializer)
│       ├── services/
│       │   ├── api.ts             # ← THE service layer (HTTP + automatic mock fallback)
│       │   └── mockData.ts        # Deterministic fixtures (42 leads, 60 orders, etc.). Internal to api.ts only.
│       ├── components/
│       │   ├── MetricCard.tsx
│       │   ├── NavLink.tsx
│       │   ├── PageHeader.tsx
│       │   ├── StatusPill.tsx
│       │   ├── WorkflowMap.tsx
│       │   ├── layout/{AppLayout, Sidebar, Topbar}.tsx
│       │   └── ui/                # shadcn components
│       ├── pages/                 # 17 pages — see §6 below
│       ├── hooks/{use-mobile, use-toast}.tsx
│       ├── lib/utils.ts
│       └── test/
│           ├── setup.ts
│           ├── app.test.tsx       # 5 tests — app shell, sidebar, KPI cards, leads, orders
│           └── api-fallback.test.ts # 3 tests — mock fallback when backend is unreachable
│
├── backend/                       # Django 5 + DRF
│   ├── manage.py
│   ├── requirements.txt
│   ├── pyproject.toml             # pytest config
│   ├── .env.example
│   ├── .gitignore
│   ├── README.md
│   ├── db.sqlite3                 # dev only; ignored
│   ├── config/
│   │   ├── settings.py            # env-driven; SQLite default, Postgres via DATABASE_URL
│   │   ├── urls.py                # mounts every app under /api/
│   │   ├── asgi.py
│   │   └── wsgi.py
│   ├── apps/                      # 14 Django apps — see §5 below
│   │   ├── accounts/              # Custom User + JWT auth + /api/settings/
│   │   ├── audit/                 # AuditEvent + cross-app signal receivers (Master Event Ledger)
│   │   ├── crm/                   # Lead, Customer
│   │   ├── calls/                 # Call, ActiveCall, CallTranscriptLine
│   │   ├── orders/                # Order + confirmation queue + RTO board
│   │   ├── payments/              # Payment receipts
│   │   ├── shipments/             # Shipment + WorkflowStep timeline
│   │   ├── agents/                # Agent + hierarchy view
│   │   ├── ai_governance/         # CeoBriefing, CeoRecommendation, CaioAudit
│   │   ├── compliance/            # Claim (Approved Claim Vault)
│   │   ├── rewards/               # RewardPenalty leaderboard
│   │   ├── learning_engine/       # LearningRecording
│   │   ├── analytics/             # KPITrend rollups
│   │   └── dashboards/            # DashboardMetric + activity feed + seed command
│   └── tests/
│       ├── conftest.py
│       ├── test_endpoints.py      # 21 tests, one per api.ts endpoint
│       ├── test_audit_signals.py  # 3 tests — signals fire correctly
│       └── test_seed.py           # 2 tests — fixture counts + idempotency
│
└── docs/
    ├── RUNBOOK.md                 # How to run the stack
    ├── BACKEND_API.md             # Endpoint reference
    ├── FRONTEND_AUDIT.md          # What's done / what's open on the frontend
    └── FUTURE_BACKEND_PLAN.md     # Phase 2+ roadmap
```

---

## 4. Architecture rule (the contract)

```
┌────────────┐   /api/...JSON   ┌──────────────────┐   ORM   ┌──────────────┐
│  React UI  │  ──────────────► │  Django + DRF    │ ──────► │  SQLite/PG   │
└────────────┘   JWT Bearer     └──────────────────┘         └──────────────┘
       │              ▲                    │
       │              │                    │ post_save signals
       │              │                    ▼
       │              │           ┌──────────────────┐
       │              │           │  AuditEvent      │ ← Master Event Ledger
       │              │           │  (activity feed) │
       │              │           └──────────────────┘
       │              │
       └── mock fallback ──────── deterministic fixtures (mockData.ts)
            (offline-safe; pages never break if backend is down)
```

**Frontend → backend** flows through one file: [`frontend/src/services/api.ts`](frontend/src/services/api.ts).

- Every function calls `${VITE_API_BASE_URL}${path}`.
- On any HTTP error or network failure, falls back to the matching fixture in `mockData.ts`.
- Function names + return shapes are **stable** — pages never have to change.

**Backend → frontend** shape rule: Django serializers expose **camelCase** (e.g. `qualityScore`, `paymentLinkSent`, `rtoRisk`) so JSON matches the TypeScript interfaces 1-to-1. DB columns stay snake_case. The mapping lives in each app's `serializers.py`.

---

## 5. Backend apps (Django) — what each one owns

| App | Purpose | Key models | Endpoints |
| --- | --- | --- | --- |
| `accounts` | Custom user + JWT auth + settings/kill-switch read | `User` (with `role`) | `/api/auth/token/`, `/api/auth/refresh/`, `/api/auth/me/`, `/api/settings/` |
| `audit` | Master Event Ledger | `AuditEvent` | (consumed by `dashboards`) |
| `crm` | Leads + Customer 360 | `Lead`, `Customer` | `/api/leads/`, `/api/leads/{id}/`, `/api/customers/`, `/api/customers/{id}/` |
| `calls` | Call logs + live AI calling console | `Call`, `ActiveCall`, `CallTranscriptLine` | `/api/calls/`, `/api/calls/active/`, `/api/calls/active/transcript/` |
| `orders` | Order pipeline + confirmation queue | `Order` | `/api/orders/`, `/api/orders/pipeline/`, `/api/confirmation/queue/` |
| `payments` | Razorpay/PayU receipt records | `Payment` | `/api/payments/` |
| `shipments` | Delhivery AWB + tracking + RTO board | `Shipment`, `WorkflowStep` | `/api/shipments/`, `/api/rto/risk/` |
| `agents` | AI/human agent roster + hierarchy | `Agent` | `/api/agents/`, `/api/agents/hierarchy/` |
| `ai_governance` | CEO daily brief + CAIO audits | `CeoBriefing`, `CeoRecommendation`, `CaioAudit` | `/api/ai/ceo-briefing/`, `/api/ai/caio-audits/` |
| `compliance` | Approved Claim Vault | `Claim` | `/api/compliance/claims/` |
| `rewards` | Reward/penalty leaderboard | `RewardPenalty` | `/api/rewards/` |
| `learning_engine` | Human call learning recordings | `LearningRecording` | `/api/learning/recordings/` |
| `analytics` | KPI rollups (funnel/revenue/state/product) | `KPITrend` | `/api/analytics/`, `/api/analytics/funnel/`, `/api/analytics/revenue-trend/`, `/api/analytics/state-rto/`, `/api/analytics/product-performance/` |
| `dashboards` | Top KPI cards + live activity feed + seed command | `DashboardMetric` | `/api/dashboard/metrics/`, `/api/dashboard/activity/`, `/api/healthz/` |

### How the Master Event Ledger works

`apps/audit/signals.py` registers `post_save` receivers on `crm.Lead`, `orders.Order`, `payments.Payment`, `shipments.Shipment`. Every state change writes a row in `audit.AuditEvent` with:

- `kind` — e.g. `lead.created`, `order.status_changed`, `payment.received`
- `text` — human-readable line (e.g. "Order NRG-20419 confirmed — name, address, amount verified")
- `tone` — `success`/`info`/`warning`/`danger`
- `icon` — Lucide icon hint
- `payload` — JSON breadcrumb

`/api/dashboard/activity/` returns the latest 25 rows with relative time labels ("3m ago", "1h ago"). Stop the dashboard from polling = it goes stale; restart = catches up.

The seed command intentionally **disconnects the signal receivers** during bulk insert so it doesn't pollute the curated activity feed.

---

## 6. Frontend pages (17)

All under `frontend/src/pages/`. Each one calls **only** `import { api } from "@/services/api"` — never `mockData.ts`.

| # | Page | Route | Backend endpoints used |
| --- | --- | --- | --- |
| 1 | Command Center Dashboard | `/` (`Index.tsx`) | `getDashboardMetrics`, `getLiveActivityFeed`, `getCeoBriefing`, `getCaioAudits`, `getAgentStatus`, `getRtoRiskOrders`, `getRewardPenaltyScores` |
| 2 | Leads CRM | `/leads` | `getLeads` |
| 3 | Customer 360 | `/customers` | `getCustomers`, `getCustomerById` |
| 4 | AI Calling Console | `/calling` | `getCalls`, `getActiveCall` |
| 5 | Orders Pipeline | `/orders` | `getOrders`, `getOrderPipeline` |
| 6 | Confirmation Queue | `/confirmation` | `getConfirmationQueue` |
| 7 | Payments | `/payments` | `getPayments` |
| 8 | Delhivery & Delivery Tracking | `/delivery` | `getShipments` |
| 9 | RTO Rescue Board | `/rto` | `getRtoRiskOrders` |
| 10 | AI Agents Center | `/agents` | `getAgentStatus`, `getAgentHierarchy` |
| 11 | CEO AI Briefing | `/ceo-ai` | `getCeoBriefing` |
| 12 | CAIO Audit Center | `/caio` | `getCaioAudits` |
| 13 | Reward & Penalty Engine | `/rewards` | `getRewardPenaltyScores` |
| 14 | Human Call Learning Studio | `/learning` | `getHumanCallLearningItems` |
| 15 | Claim Vault & Compliance | `/claims` | `getClaimVault` |
| 16 | Analytics | `/analytics` | `getAnalyticsData` |
| 17 | Settings & Control Center | `/settings` | `getSettingsMock` |

**Premium Ayurveda + AI SaaS theme:** deep green / emerald / teal / saffron-gold / ivory / charcoal. Rounded cards, soft shadows, clean typography, strong hierarchy. Director should grok business health in 30 seconds. Not an admin template.

---

## 7. AI agent hierarchy

```
                    Prarit Sidana (Director / Final Authority)
                              ▲
                              │ critical alerts
                              │
                       ┌──────┴──────┐
                       │  CEO AI     │ ── execution approval layer
                       │  Agent      │
                       └──────┬──────┘
                              │ approves / rewards
                              ▼
        ┌────────────── Department AI Agents ─────────────────┐
        │  Ads · Marketing · Sales Growth · Calling TL ·     │
        │  Calling QA · Data Analyst · CFO · Compliance ·    │
        │  RTO · Customer Success · Creative · Influencer ·  │
        │  Inventory · HR · Simulation · Consent · DQ        │
        └─────────────────────────────────────────────────────┘
                              ▲
                              │ audits, training suggestions, governance
                              │
                       ┌──────┴──────┐
                       │  CAIO Agent │ ── NEVER executes
                       └─────────────┘
```

19 agents seeded today. Phase 1 they return **structured seeded insights**; Phase 3 swaps in real LLM calls per agent (`services/agents/<name>.py`).

### Permission matrix (locked)
| Agent | Execute? | Approval needed |
| --- | --- | --- |
| CEO AI | Limited | Prarit for high-risk |
| CAIO | **Never** | — (reports through CEO) |
| Calling AI | Rule-based | Auto within approved workflow |
| Confirmation AI | Rule-based | Auto within approved workflow |
| Compliance | Can block risky content | Doctor + Admin final approval |
| CFO | No / limited | CEO/Prarit |
| Ads | Limited later | CEO/Prarit |
| RTO | Approved rescue trigger | Auto / CEO depending on risk |
| Customer Success | Approved follow-up | Auto within rules |
| Data Quality | Flag / fix low-risk | Admin for major merges |

### Reward/penalty formula (Blueprint §10.2)
```
Final Reward Score =
    Delivered Order Score
  + Net Profit Score
  + Advance Payment Score
  + Customer Satisfaction Score
  + Reorder Potential Score
  − Discount Leakage
  − Compliance Risk
  − RTO Risk Ignored
```

---

## 8. What's done so far (Phase 1) — every checkpoint we shipped

### ✅ Frontend (was already in place when we started; we wired it to the backend)
- 17 pages, all routing through `src/services/api.ts`. **No page imports `mockData.ts` directly.**
- Shared TypeScript types in `src/types/domain.ts` covering Lead / Customer / Order / Call / Payment / Shipment / Agent / RewardPenalty / Claim / LearningRecording / CaioAudit / CeoBriefing / DashboardMetrics / ActivityEvent / WorkflowStep / KPITrend.
- Sidebar collapse layout, mobile responsive baseline, dashboard polish, shadcn UI.
- Vitest + React Testing Library configured.

### ✅ Backend (built this session)

**Bootstrap (Checkpoint 1):**
- Django 5.1 + DRF + simplejwt + django-cors-headers + django-filter + dj-database-url + python-dotenv.
- `config/settings.py` driven by env vars. SQLite default, Postgres via `DATABASE_URL`.
- `config/urls.py` mounts every app under `/api/`.
- `/api/healthz/` liveness probe.

**Accounts (Checkpoint 2):**
- Custom `User` extending `AbstractUser` with `role` (Director / Admin / Operations / Compliance / Viewer) and `display_name`.
- JWT endpoints: `POST /api/auth/token/`, `POST /api/auth/refresh/`, `GET /api/auth/me/`.
- `GET /api/settings/` returning approval matrix + integrations + kill-switch state.

**14 apps with models, serializers, viewsets, admin, urls** (Checkpoints 3–9):
- `accounts`, `audit`, `crm`, `calls`, `orders`, `payments`, `shipments`, `agents`, `ai_governance`, `compliance`, `rewards`, `learning_engine`, `analytics`, `dashboards`.
- Each model uses string PKs matching the frontend's seeded IDs (`LD-10234`, `NRG-20410`, `CL-LIVE-001`, `PAY-30100`, etc.) so the cutover from mock to backend is bit-identical.

**Master Event Ledger (Checkpoint 10):**
- `audit.AuditEvent` populated by `post_save` signals on Lead / Order / Payment / Shipment.
- `/api/dashboard/activity/` reads from this table with relative-time labels.

**Seed command (Checkpoint 11):**
- `python manage.py seed_demo_data --reset`
- Ports the deterministic generators from `frontend/src/services/mockData.ts` to Python (same `pick`, `rand`, `phone` math, same indices).
- Idempotent on re-run.
- Disconnects audit signals during bulk insert to avoid polluting the curated activity feed.
- Produces: **42 leads, 24 customers, 60 orders, 18 calls, 1 active call (with 7-line transcript), 30 payments, 39 shipments (with 5-step timelines), 19 agents, 1 CEO briefing (3 recommendations), 5 CAIO audits, 4 claim vault entries, 18 reward leaderboard rows, 5 learning recordings, 29 KPI trend rows (7+7+7+8), 12 dashboard metrics, 8 curated activity events.**

**Frontend wiring (Checkpoint 12):**
- Rewrote `frontend/src/services/api.ts` as `safeFetch<T>(path, fallback)`:
  - Calls `${VITE_API_BASE_URL}${path}` with optional JWT header (`localStorage["nirogidhara.jwt"]`).
  - On any error, falls back to the matching `mockData.ts` fixture and warns once per path.
- Added `frontend/.env.example` (`VITE_API_BASE_URL=http://localhost:8000/api`).
- **No page files modified** — function names and return shapes preserved.
- Added `frontend/src/test/api-fallback.test.ts` (3 tests asserting fallback works when fetch throws).

**Docs (Checkpoint 13):**
- Updated root `README.md`.
- New `docs/RUNBOOK.md`, `docs/BACKEND_API.md`.
- Updated `docs/FRONTEND_AUDIT.md`, `docs/FUTURE_BACKEND_PLAN.md`.
- New `backend/README.md`, `backend/.env.example`, `backend/.gitignore`.

**Verification (Checkpoint 14):**
| Command | Result |
| --- | --- |
| `pip install -r requirements.txt` | OK |
| `python manage.py check` | 0 issues |
| `python manage.py makemigrations` (14 apps) | 14 migrations |
| `python manage.py migrate` | all OK |
| `python manage.py seed_demo_data --reset` | seeded |
| `python -m pytest -q` | **26 passed** |
| `npm run lint` | 0 errors, 8 pre-existing shadcn warnings |
| `npm test` | **8 passed** |
| `npm run build` | OK, 904 KB / 257 KB gzip |
| Live curl across all 25 endpoints (both servers up) | All 200 with seeded data |
| CORS preflight for `localhost:8080` | 200 |

### ✅ Phase 2A — Core Write APIs + Workflow State Machine (built this session)

**Permissions (Checkpoint 1):**
- New `apps/accounts/permissions.py` with `RoleBasedPermission` + role-set constants (`OPERATIONS_AND_UP`, `COMPLIANCE_AND_UP`, `ADMIN_AND_UP`, `DIRECTOR_ONLY`).
- Global DRF default flipped to `IsAuthenticatedOrReadOnly` — reads stay public, writes need auth.
- CAIO is intentionally absent from every role-set (AI agent, not user role).

**Schema (Checkpoint 2):**
- `Order.Stage.CANCELLED` added; `confirmation_outcome` + `confirmation_notes` fields on Order.
- New `shipments.RescueAttempt` model (id, order_id, channel, outcome, notes, attempted_at).
- 2 migrations applied cleanly.

**Service layer (Checkpoint 3):**
- `apps/crm/services.py` — create/update/assign lead, upsert customer.
- `apps/orders/services.py` — `ALLOWED_TRANSITIONS` state-machine dict + `transition_order` / `move_to_confirmation` / `record_confirmation_outcome` / `create_order`.
- `apps/payments/services.py` — `create_payment_link` (mock URL).
- `apps/shipments/services.py` — `create_mock_shipment` (DLH AWB + 5-step timeline) + `create_rescue_attempt` + `update_rescue_outcome`.
- All services run inside `transaction.atomic()`. Invalid transitions raise `OrderTransitionError` → HTTP 400.

**Audit ledger (Checkpoint 4):**
- `ICON_BY_KIND` extended with `lead.updated`, `lead.assigned`, `customer.upserted`, `confirmation.outcome`, `payment.link_created`, `shipment.created`, `rescue.attempted`, `rescue.updated`.
- Existing post-save signals still cover `lead.created`, `order.created`, `order.status_changed`, `payment.received`, `shipment.status_changed`.

**13 new write endpoints (Checkpoint 5):**
- `POST /api/leads/`, `PATCH /api/leads/{id}/`, `POST /api/leads/{id}/assign/`
- `POST /api/customers/`, `PATCH /api/customers/{id}/`
- `POST /api/orders/`, `POST /api/orders/{id}/transition/`, `POST /api/orders/{id}/move-to-confirmation/`, `POST /api/orders/{id}/confirm/`
- `POST /api/payments/links/`
- `POST /api/shipments/`
- `POST /api/rto/rescue/`, `PATCH /api/rto/rescue/{id}/`

**Tests (Checkpoint 6):**
- New `tests/test_writes.py` with **18 tests** covering: anonymous → 401, viewer → 403, all 13 endpoints happy path, invalid state-machine transition blocked, audit ledger growth across the full workflow.
- New conftest fixtures: `operations_user`, `viewer_user`, `admin_user`, `auth_client(user)` factory.

**Frontend (Checkpoint 7):**
- `frontend/src/services/api.ts` gained `safeMutate<T>(path, method, body, fallback)` + 13 new typed methods (`createLead`, `updateLead`, `assignLead`, `createCustomer`, `updateCustomer`, `createOrder`, `transitionOrder`, `moveOrderToConfirmation`, `confirmOrder`, `createPaymentLink`, `createShipment`, `createRescueAttempt`, `updateRescueAttempt`).
- New types in `frontend/src/types/domain.ts`: `RescueAttempt`, `ConfirmationOutcome`, `PaymentLinkResponse`, `*Payload` interfaces for every write.
- **No page files modified.** Existing 8 frontend tests stay green.

**Verification (Checkpoint 8):**
| Command | Result |
| --- | --- |
| `python manage.py makemigrations` | 2 new migrations (orders, shipments) |
| `python manage.py migrate` | all OK |
| `python manage.py check` | 0 issues |
| `python -m pytest -q` | **44 passed** (26 + 18) |
| `npm test` | **8 passed** |
| `npm run lint` | 0 errors, 8 pre-existing shadcn warnings |
| `npm run build` | OK |
| Live curl chain (lead → order → confirm → pay → ship → rescue) | every step 200/201, ledger grew by 7+ events |

### ✅ Phase 2B — Razorpay Payment-Link Integration (built earlier this session)

- Three-mode adapter at `backend/apps/payments/integrations/razorpay_client.py` (`mock` | `test` | `live`). SDK imported lazily so mock works without the package.
- `Payment` model gains `gateway_reference_id`, `payment_url`, `customer_phone/email`, `raw_response`, `updated_at`. New `WebhookEvent` model for idempotency.
- `POST /api/payments/links/` extended with customer info; flat response shape (`paymentId`, `gateway`, `status`, `paymentUrl`, `gatewayReferenceId`) plus Phase 2A backwards-compat `payment` nested object.
- `POST /api/webhooks/razorpay/` verifies HMAC-SHA256, deduplicates by event id, dispatches 6 handlers (paid/partial/cancelled/expired/failed/refunded).
- 13 new pytest tests cover mock + test-mode adapter, auth/role gating, webhook paid/duplicate/invalid-sig/expired/unknown-event, signature helper round-trip, AuditEvent firing.
- New env vars: `RAZORPAY_MODE`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_CALLBACK_URL`. Frontend never sees them.
- Payments page "Generate link" button wired to `api.createPaymentLink`.

### ✅ Phase 3 prep — AI provider env scaffolding (built earlier this session)

- New env block in `backend/.env.example`: `AI_PROVIDER` (default `disabled`), `AI_MODEL`, `AI_TEMPERATURE`, `AI_MAX_TOKENS`, `AI_REQUEST_TIMEOUT_SECONDS`, plus per-provider keys: `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_ORG_ID`, `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`, `GROK_API_KEY`/`GROK_BASE_URL`. All secrets stay server-side.
- Settings constants wired in `backend/config/settings.py` with safe defaults (no float/int parse explosions if env is malformed).
- New helper `backend/apps/_ai_config.py` exposes `current_config()` returning a frozen `AIConfig` dataclass. `enabled` is False whenever `AI_PROVIDER=disabled` or the matching key is empty — Phase 3 adapters refuse to dispatch when not enabled.
- **No SDK installed yet** — `openai` / `anthropic` / `xai_sdk` packages are NOT in `requirements.txt`. They'll be added in Phase 3 alongside actual adapters at `apps/integrations/ai/<provider>.py`.
- 7 new tests in `tests/test_ai_config.py` confirm: disabled default, unknown-provider fallback, per-provider key isolation (no cross-leak), enable-only-with-key, OpenAI / Anthropic / Grok routing.
- **Compliance hard stop documented in code:** every AI module has a header comment reiterating Master Blueprint §26 #4 — AI must speak only from `apps.compliance.Claim`.

### ✅ Phase 2D — Vapi Voice Trigger + Transcript Ingest (built this session)

- Three-mode adapter at `backend/apps/calls/integrations/vapi_client.py` (`mock` | `test` | `live`). `requests` is imported lazily so mock works without the package. Mock mode returns a deterministic provider call id (`call_mock_<lead>_<purpose>`).
- `Call` model gains `provider`, `provider_call_id`, `summary`, `recording_url`, `handoff_flags` (JSON list), `ended_at`, `error_message`, `raw_response`, `updated_at`. Status enum widened with `Failed`. Migration `0002_phase2d_vapi_fields`.
- `CallTranscriptLine` now supports two parents: the legacy `active_call` FK (for the live console) and a new `call` FK (for Vapi-recorded post-call transcripts). Each row has exactly one parent set; the legacy field was renamed in the same migration.
- New endpoint `POST /api/calls/trigger/`. Body `{ leadId, purpose? }` → `201 { callId, provider, status, leadId, providerCallId }`. Roles gated by `OPERATIONS_AND_UP`.
- New webhook `POST /api/webhooks/vapi/` verifies HMAC-SHA256 (`X-Vapi-Signature`) when `VAPI_WEBHOOK_SECRET` is set; signature is skipped when the secret is empty so dev/test fixtures stay simple. Idempotency via per-app `calls.WebhookEvent` (PK = `event_id`). Handlers: `call.started`, `call.ended`, `transcript.updated`, `transcript.final`, `analysis.completed`, `call.failed`.
- Six handoff flags (`medical_emergency`, `side_effect_complaint`, `very_angry_customer`, `human_requested`, `low_confidence`, `legal_or_refund_threat`) are persisted on `Call.handoff_flags` from the analysis payload, with a keyword fallback against the final transcript when Vapi omits the explicit list. `call.handoff_flagged` audit row fires whenever any flag fires; `call.failed` writes a danger-tone audit row.
- 14 new pytest tests cover mock + test-mode adapter, auth/role gating, every webhook event type (started/transcript/failed/analysis/duplicate/invalid-sig/no-secret), keyword-fallback handoff, signature helper round-trip, full audit-ledger flow.
- New env vars: `VAPI_MODE`, `VAPI_API_BASE_URL`, `VAPI_API_KEY`, `VAPI_ASSISTANT_ID`, `VAPI_PHONE_NUMBER_ID`, `VAPI_WEBHOOK_SECRET`, `VAPI_DEFAULT_LANGUAGE`, `VAPI_CALLBACK_URL`. All secrets stay server-side.
- Frontend `Call` type + new `CallTriggerPayload` / `CallTriggerResponse`; `api.triggerCallForLead()` with offline-safe optimistic fallback. The existing AI Calling Console keeps working unchanged.
- `audit.signals.ICON_BY_KIND` extended with `call.triggered`, `call.started`, `call.completed`, `call.failed`, `call.transcript`, `call.analysis`, `call.handoff_flagged`.

**Compliance hard stop (Master Blueprint §26 #4):** the Vapi adapter passes only metadata in the call payload; the assistant prompt is configured server-side in Vapi's dashboard with content sourced from the Approved Claim Vault. No free-form medical text is injected from this codebase. CAIO never executes business actions; nothing in this pipeline routes through CAIO.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **93 passed** (77 + 14 vapi + 2 keyword/no-secret edge tests) |
| `python manage.py check` | 0 issues |

### ✅ Phase 2C — Delhivery Courier Integration (built earlier this session)

- Three-mode adapter at `backend/apps/shipments/integrations/delhivery_client.py` (`mock` | `test` | `live`). `requests` is imported lazily so mock works without the package. Mock mode preserves the seeded `DLH<8 digits>` AWB pattern.
- `Shipment` model gains `delhivery_status`, `tracking_url`, `risk_flag` (`NDR`/`RTO`), `raw_response`, `updated_at` via migration `0003_shipment_delhivery_fields`.
- `services.create_shipment` now routes through the adapter, persists the gateway response, and writes a `shipment.created` audit row with `tracking_url` payload. The Phase 2A name `create_mock_shipment` is kept as an alias for callers that still reference it.
- `POST /api/webhooks/delhivery/` verifies HMAC-SHA256 (`X-Delhivery-Signature`), deduplicates by event id (reusing `payments.WebhookEvent` because its `gateway` field accepts arbitrary strings), and dispatches handlers for `pickup_scheduled` / `picked_up` / `in_transit` / `out_for_delivery` / `delivered` / `ndr` / `rto_initiated` / `rto_delivered`. NDR / RTO transitions bump `Order.rto_risk` to High and write danger-tone audit rows; delivered transitions advance `Order.stage` to `Delivered`.
- 13 new pytest tests cover mock + test-mode adapter, auth/role gating, webhook delivered/NDR/RTO/duplicate/invalid-sig/unknown-event, signature helper round-trip, AuditEvent firing.
- New env vars: `DELHIVERY_MODE`, `DELHIVERY_API_BASE_URL`, `DELHIVERY_API_TOKEN`, `DELHIVERY_PICKUP_LOCATION`, `DELHIVERY_RETURN_ADDRESS`, `DELHIVERY_DEFAULT_PACKAGE_WEIGHT_GRAMS`, `DELHIVERY_WEBHOOK_SECRET`. Frontend never sees them.
- Frontend `Shipment` interface widened with optional `trackingUrl` / `riskFlag` so the existing Delivery page picks them up automatically once the backend serves them.
- `audit.signals.ICON_BY_KIND` extended with `shipment.delivered`, `shipment.ndr`, `shipment.rto_initiated`, `shipment.rto_delivered`.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **77 passed** (44 + 13 razorpay + 7 ai config + 13 delhivery) — pre-Phase-2D snapshot |
| `python manage.py check` | 0 issues |

---

## 9. How to run it (full quickstart)

### Prerequisites
- Python 3.10+
- Node 18+
- Git

### One-time setup
```bash
git clone <repo-url> nirogidhara-command
cd nirogidhara-command

# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
# source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
copy .env.example .env           # cp on macOS/Linux
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py createsuperuser # optional, for /admin/

# Frontend
cd ..\frontend
npm install
copy .env.example .env           # cp on macOS/Linux
```

### Daily dev loop (two terminals)
```bash
# Terminal 1
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py runserver 0.0.0.0:8000

# Terminal 2
cd frontend
npm run dev
```
Open [http://localhost:8080](http://localhost:8080).

### Tests
```bash
# Backend
cd backend && python -m pytest -q   # 93 tests (26 reads + 18 writes + 13 razorpay + 7 ai config + 13 delhivery + 16 vapi)

# Frontend
cd frontend && npm test             # 8 tests
cd frontend && npm run lint         # 0 errors
cd frontend && npm run build        # production build
```

### Useful checks
```bash
curl http://localhost:8000/api/healthz/
curl http://localhost:8000/api/leads/ | head -c 400
curl http://localhost:8000/api/dashboard/metrics/
```

Stop the backend → frontend keeps rendering via mock fallback. **No page crashes.**

---

## 10. The frontend ↔ backend contract (every endpoint)

JSON in, JSON out. Every entry below is consumed by `frontend/src/services/api.ts` and matches an interface in `frontend/src/types/domain.ts`.

| Frontend function | Method | Path | Returns |
| --- | --- | --- | --- |
| `getDashboardMetrics` | GET | `/api/dashboard/metrics/` | `Record<string, DashboardMetric>` |
| `getLiveActivityFeed` | GET | `/api/dashboard/activity/` | `ActivityEvent[]` |
| `getFunnel` | GET | `/api/analytics/funnel/` | `KPITrend[]` |
| `getRevenueTrend` | GET | `/api/analytics/revenue-trend/` | `KPITrend[]` |
| `getStateRto` | GET | `/api/analytics/state-rto/` | `KPITrend[]` |
| `getProductPerformance` | GET | `/api/analytics/product-performance/` | `KPITrend[]` |
| `getAnalyticsData` | GET | `/api/analytics/` | composite `{funnel, revenueTrend, stateRto, productPerformance, discountImpact}` |
| `getLeads` | GET | `/api/leads/` | `Lead[]` |
| `getLeadById` | GET | `/api/leads/{id}/` | `Lead` |
| `getCustomers` | GET | `/api/customers/` | `Customer[]` |
| `getCustomerById` | GET | `/api/customers/{id}/` | `Customer` |
| `getOrders` | GET | `/api/orders/` | `Order[]` |
| `getOrderPipeline` | GET | `/api/orders/pipeline/` | `Order[]` (sorted by stage) |
| `getCalls` | GET | `/api/calls/` | `Call[]` |
| `getActiveCall` | GET | `/api/calls/active/` | `ActiveCall` |
| `getCallTranscripts` | GET | `/api/calls/active/transcript/` | `CallTranscriptLine[]` |
| `getConfirmationQueue` | GET | `/api/confirmation/queue/` | `(Order & {hoursWaiting, addressConfidence, checklist})[]` |
| `getPayments` | GET | `/api/payments/` | `Payment[]` |
| `getShipments` | GET | `/api/shipments/` | `Shipment[]` (with `timeline`, `trackingUrl`, `riskFlag`) |
| `getRtoRiskOrders` | GET | `/api/rto/risk/` | `(Order & {riskReasons, rescueStatus})[]` |
| `getAgentStatus` | GET | `/api/agents/` | `Agent[]` |
| `getAgentHierarchy` | GET | `/api/agents/hierarchy/` | `{root, ceo, caio, departments}` |
| `getCeoBriefing` | GET | `/api/ai/ceo-briefing/` | `CeoBriefing` |
| `getCaioAudits` | GET | `/api/ai/caio-audits/` | `CaioAudit[]` |
| `getRewardPenaltyScores` | GET | `/api/rewards/` | `RewardPenalty[]` |
| `getClaimVault` | GET | `/api/compliance/claims/` | `Claim[]` |
| `getHumanCallLearningItems` | GET | `/api/learning/recordings/` | `LearningRecording[]` |
| `getSettingsMock` | GET | `/api/settings/` | `{approvalMatrix, integrations, killSwitch}` |

Plus auth: `POST /api/auth/token/`, `POST /api/auth/refresh/`, `GET /api/auth/me/`.

**Response envelope:** raw arrays/objects, **no** `{success, data}` wrapper. Pagination disabled in Phase 1 (mock counts are tiny).

---

## 11. Phase roadmap (Master Blueprint §25 — the locked build order)

```
CRM → Workflow → Integrations → Voice AI → Agents → Governance → Learning → Reward/Penalty → Growth → SaaS
 ✅      ✅          □              □         data    data         □            □              □       □
                  (Phase 2)     (Phase 3)   (Phase 1) (Phase 1)   (Phase 6)   (Phase 5)
```

### ✅ Phase 0 + 1 — Foundation (DONE)
14 apps · 25 endpoints · seed · audit ledger · auth · CORS · tests. See §8.

### ✅ Phase 2A — Core Write APIs + Workflow State Machine (DONE)
13 write endpoints · service layer · order state machine · `RoleBasedPermission` · 18 new tests · mock payment + shipment + RTO rescue. See §8.

### ✅ Phase 2B — Razorpay payment-link integration (DONE)
Three-mode adapter, HMAC-verified webhook, idempotency, 13 new tests. See §8.

### ✅ Phase 2C — Delhivery courier integration (DONE)
Three-mode adapter, HMAC-verified tracking webhook, NDR / RTO risk handling, 13 new tests. See §8.

### ✅ Phase 2D — Vapi voice trigger + transcript ingest (DONE)
Three-mode adapter, `POST /api/calls/trigger/`, HMAC-verified webhook, six handoff flags, keyword fallback, 14 new tests. See §8.

### Phase 2E — Other gateways (NEXT)
- **Meta Lead Ads webhook** — `POST /api/webhooks/meta/leads/`, idempotent on `leadgen_id`, maps form fields to the `Lead` model.
- **PayU payment links** — same shape as Razorpay; only the adapter is missing.
- Tighten role permissions per blueprint §8 where needed (compliance writes, settings writes).

### Phase 3 — LLM-powered AI agents
- `AgentRun` model (agent · prompt_version · input · output · latency · cost).
- `services/agents/{ceo,caio,ads,rto,...}.py` — each takes a DB slice, returns the same dataclass shape the seed currently produces.
- Celery beat regenerates the daily CEO briefing.
- Approved Claim Vault is force-injected into every prompt.
- Sandbox mode + prompt versioning.

### Phase 4 — Real-time
- Django Channels + WebSockets pushing `AuditEvent` rows to subscribed dashboards.
- Frontend already polls — push is purely additive.

### Phase 5 — Governance UI write paths
- Kill-switch toggle endpoints.
- Prompt rollback engine.
- Reward/penalty engine — actually compute Blueprint §10.2 from the event ledger.
- Approval matrix middleware blocking risky actions until CEO AI / Prarit approves.

### Phase 6 — Learning loop
- Recording upload → STT → speaker separation pipeline.
- QA scoring → Compliance review → CAIO audit workflow tables.
- Sandbox test infrastructure.
- Approved learning → playbook version update.

### Phase 7 — Multi-tenant SaaS
- Tenant model + middleware scoping every queryset.
- Per-tenant settings, integrations, claim vault.
- Billing.

---

## 12. Open clarifications (Master Blueprint §24)

These are blockers for Phase 2+. They need a decision from Prarit before code can ship:

1. **Product catalog** — exact names, categories, SKUs, pricing, quantity rules, approved usage instructions.
2. **Medical claims** — doctor-approved benefit claims and strictly banned claims per product (Claim Vault content).
3. **Discount rules** — exact authority for 10% / 20% / 30% and when AI may offer each.
4. **Advance payment policy** — minimum advance, mandatory vs optional, category-/risk-wise logic.
5. **Voice AI provider** — Vapi as final or compare alternatives first?
6. **CRM migration** — existing CRM fields, export format, legacy data import scope.
7. **Delhivery workflow** — account/API availability, AWB flow, pickup process, NDR rules.
8. **Razorpay/PayU setup** — gateway accounts, webhook events, refund permissions, reconciliation format.
9. **Confirmation timing** — fixed 24h or dynamic by product/source/risk?
10. **RTO risk model** — initial rule-based vs ML-based prediction timeline.
11. **Human team roles** — which roles stay human (doctor, refund approver, escalation, warehouse).
12. **Dashboard priority** — top 10–15 metrics for the first live dashboard cut.
13. **Governance approvals** — exact action → approver mapping (Prarit vs CEO AI vs admin).
14. **Call recording consent** — exact script + storage policy.
15. **Language support** — Hindi/Hinglish first; Punjabi/English/regional in which phase.
16. **WhatsApp integration** — Phase 1 or later?
17. **SaaS readiness** — multi-tenant from day one or kept future-ready?

---

## 13. Conventions for any agent working on this repo

### General
- **Don't break the contract.** If you rename a field, update both the Django serializer (with `source=` mapping) AND the TypeScript interface AND the test that asserts the key exists. Endpoint smoke tests are your safety net.
- **No business logic in the frontend.** If a calculation has business meaning, it belongs in a Django service, not a React component.
- **No real medical claims in code.** AI must only emit content from `apps.compliance.Claim`. Hard-coded medical strings = blocked.
- **Master Event Ledger first.** Before adding a new state-change-bearing model, add the matching `post_save` receiver in `apps/audit/signals.py`.

### Backend (Python / Django)
- Snake_case in Python and DB; camelCase only in serializer field names (`source=` does the mapping).
- DRF `ViewSet`s with `mixins.ListModelMixin` / `mixins.RetrieveModelMixin` for read endpoints. `pagination_class = None` while fixture sizes stay small.
- Pin `Django>=5.0,<5.2` and `Python>=3.10`.
- Tests: `pytest-django`, one smoke test per endpoint asserting status 200 + presence of camelCase keys.
- Seed deterministic — same indices, same names, same counts as `mockData.ts`.

### Frontend (TypeScript / React)
- No `any` in app code. Use generics + `unknown` at boundaries.
- Use `Zod` for schema validation at boundaries.
- Pages talk **only** to `import { api } from "@/services/api"`. Direct `mockData.ts` imports in pages are forbidden.
- Animate compositor-friendly properties only (`transform`, `opacity`).
- Prefer Vitest + React Testing Library; visual regression via Playwright is Phase 6+.

### Git
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- Commit at every checkpoint that leaves the repo green (build + lint + test).
- **Never** `git push --force` to `main`. Never skip hooks.

### Compliance (HARD STOPS)
- AI must not emit any of the blocked phrases listed in §2.
- Medical emergency / side-effect complaint / very angry customer / explicit human request / low confidence / legal threat → **immediate human handoff** per Blueprint §9.
- Reward/penalty must reflect **delivered profitable orders**, never punching count alone.

---

## 14. File-level pointers (for code agents diving in)

| When you need to… | Open this file |
| --- | --- |
| Understand the domain types | `frontend/src/types/domain.ts` |
| Add or modify a frontend → backend call | `frontend/src/services/api.ts` |
| See how mocks are generated | `frontend/src/services/mockData.ts` |
| Add a new Django app | `backend/config/settings.py` (INSTALLED_APPS) + `backend/config/urls.py` (mount) + new `backend/apps/<name>/` skeleton |
| Add a new endpoint | `backend/apps/<app>/{models,serializers,views,urls}.py` + `backend/tests/test_endpoints.py` (smoke) |
| Add a new audit-ledger event | `backend/apps/audit/signals.py` (add receiver + ICON_BY_KIND entry) |
| Re-seed the DB | `python manage.py seed_demo_data --reset` |
| Run all tests | `pytest -q` (backend) + `npm test` (frontend) |
| Run the full stack | `python manage.py runserver` + `npm run dev` |
| See approved API surface | `docs/BACKEND_API.md` |
| See run instructions | `docs/RUNBOOK.md` |
| See what's still open | `docs/FUTURE_BACKEND_PLAN.md` + §11 + §12 here |

---

## 15. Reference document

**Nirogidhara AI Command Center — Master Blueprint v1.0** (PDF in repo root).
- 31 pages. Owner: Prarit Sidana. Version: v1.0.
- Sections referenced throughout this doc: §3 business flow, §5 product modules, §6 agent hierarchy, §10 reward/penalty, §11 learning loop, §12 governance, §13 architecture, §14 entities, §15 app structure, §16 API-first rule, §18 security, §19 dashboard, §20 phased roadmap, §24 open clarifications, §25 build order, §26 locked non-negotiables.

When in doubt: **the blueprint wins.** Every decision in this codebase traces back to a section there.

---

## 16. Quick health check (run this before any large change)

```bash
# Backend healthy?
cd backend && python -m pytest -q && python manage.py check

# Frontend healthy?
cd frontend && npm run lint && npm test && npm run build

# Stack healthy end-to-end?
cd backend && python manage.py runserver 0.0.0.0:8000 &
cd frontend && npm run dev &
curl http://localhost:8000/api/healthz/
curl http://localhost:8080/
```

If all of the above pass: you have a green baseline to build on. Now go ship the next phase.

---

_End of `nd.md`. Last updated by the Phase 1 build session._
