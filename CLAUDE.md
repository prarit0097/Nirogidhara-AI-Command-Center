# CLAUDE.md — Nirogidhara AI Command Center

> Auto-loaded by Claude Code on every session in this repo.
> If you are an AI agent working here, **read this file first**, then `AGENTS.md` for guardrails and `nd.md` for the full project handoff.

---

## 0. Project context (60-second read)

Full-stack AI Business Operating System for Nirogidhara Private Limited (Ayurvedic medicine D2C). React 18 + Vite + TS frontend talks to Django 5 + DRF backend. Director: Prarit Sidana — final authority for high-risk decisions. Reference: *Nirogidhara AI Command Center — Master Blueprint v1.0* (PDF in repo).

Status: Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B + 3C + 3D + 3E complete (CRM data layer, write APIs, all four gateway integrations, AgentRun + 7 per-agent runtime services, Celery beat at 09:00 + 18:00 IST, OpenAI → Anthropic fallback, model-wise USD cost tracking, sandbox toggle + versioned prompts with rollback + per-agent USD budgets, Scheduler + Governance frontend pages, **Phase 3E business config: catalog admin app + discount policy (10/20% bands) + ₹499 fixed advance + reward/penalty deterministic scoring + approval matrix table + WhatsApp design scaffold**). **219 backend tests + 8 frontend tests**, all green. Next: Phase 4A WebSockets, Phase 4B reward/penalty engine wiring, Phase 4C approval-matrix middleware enforcement.

GitHub: https://github.com/prarit0097/Nirogidhara-AI-Command-Center

---

## 1. Working agreement (binding rule)

**Every meaningful change to this project MUST be followed by:**

1. **Update `nd.md`** — adjust the relevant section (TL;DR §0, what's done so far §8, phase roadmap §11, or whichever is impacted) so the project handoff stays the source of truth.
2. **Update `AGENTS.md`** — if a convention, hard stop, or "where things live" pointer changed, reflect it here so other AI tools that auto-load `AGENTS.md` pick it up.
3. **Run the full verification suite** before committing:
   - `cd backend && python -m pytest -q && python manage.py check`
   - `cd frontend && npm run lint && npm test && npm run build`
4. **Commit with a Conventional Commit message** (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
5. **Push to `origin/main` at GitHub** — `git push origin main` to https://github.com/prarit0097/Nirogidhara-AI-Command-Center.

This is non-negotiable. The repo on GitHub must mirror the local state at the end of every working session.

### What counts as a "meaningful change"?

- Any code edit (backend or frontend)
- Any new endpoint, model, migration, service, or page
- Any new env var, dependency, or configuration
- Any docs change that affects onboarding (RUNBOOK, BACKEND_API, README)
- Any rule or convention change

### What does NOT count?

- Reading-only exploration
- Failed/discarded edits that were reverted
- Local-only experiments outside the repo

If you're unsure, default to "yes, this is meaningful, update + push."

### Exceptions (still ask the user)

- **Force-push** to `main`: never without explicit user authorization.
- **Rewriting history** (`rebase -i`, `commit --amend` on already-pushed commits): never without explicit user authorization.
- **Pushing secrets**: never. The `.gitignore` covers `.env`, `db.sqlite3`, etc. — verify before staging.
- **Pushing during plan mode**: never. Plan mode means edits are gated.

---

## 2. Hard stops (compliance — never bypass)

Inherited from `AGENTS.md` and the Master Blueprint §26. Most important to keep in mind for AI agents:

1. **No free-style medical claims.** AI may only emit content from `apps.compliance.Claim`. Hard-coded medical strings are forbidden.
2. **CAIO Agent never executes business actions.** Monitor / audit / suggest only.
3. **CEO AI is the execution approval layer.** High-risk decisions go to Prarit.
4. **Every important state change writes an `AuditEvent`** (Master Event Ledger).
5. **Reward/penalty is based on delivered profitable orders**, not punching count.
6. **Frontend never holds business logic.**
7. **Razorpay/PayU/Delhivery/Vapi/Meta secrets stay server-side.** Frontend gets URLs and statuses only.

Full list in `AGENTS.md`.

---

## 3. Architecture rule (the contract)

```
React UI  ──/api/JSON──►  Django + DRF  ──ORM──►  SQLite (dev) / Postgres (prod)
   │                          │
   │                          │ post_save signals + service-layer writes
   │                          ▼
   │                   audit.AuditEvent  ← Master Event Ledger
   │                          ▲
   │                          │
   │                   Razorpay webhooks (HMAC-verified, idempotent)
   │
   └── mock fallback ── frontend/src/services/mockData.ts (offline-safe)
```

- **Frontend → backend** flows through `frontend/src/services/api.ts`.
- **Backend → frontend** uses camelCase JSON keys (Django serializers map snake_case columns via `source=`).
- **Pages** consume `api` only. **Never** import `mockData.ts` from a page.
- **No `{success, data}` envelope** — endpoints return raw arrays/objects matching `frontend/src/types/domain.ts`.
- **Workflow logic lives in `apps/<app>/services.py`** (services), not views. Views are parse → call service → respond.
- **Gateway integrations live in `apps/<app>/integrations/`** (e.g. `apps/payments/integrations/razorpay_client.py`) with a mock/test/live mode dispatch.

---

## 4. Common commands

```bash
# Backend
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py runserver 0.0.0.0:8000
python -m pytest -q                    # 219 tests today

# Frontend
cd frontend
npm install
npm run dev                            # http://localhost:8080
npm test                               # 8 tests today
npm run lint                           # 0 errors expected
npm run build                          # production build

# After any change
git add -A
git commit -m "<type>: <message>"
git push origin main
```

---

## 5. Where things live

| Task | File |
| --- | --- |
| Frontend → backend contract | `frontend/src/services/api.ts` |
| Shared TS types | `frontend/src/types/domain.ts` |
| Backend service layer per app | `backend/apps/<app>/services.py` |
| Razorpay adapter (mock/test/live) | `backend/apps/payments/integrations/razorpay_client.py` |
| Razorpay webhook receiver | `backend/apps/payments/webhooks.py` |
| Delhivery adapter (mock/test/live) | `backend/apps/shipments/integrations/delhivery_client.py` |
| Delhivery tracking webhook | `backend/apps/shipments/webhooks.py` |
| Vapi adapter (mock/test/live) | `backend/apps/calls/integrations/vapi_client.py` |
| Vapi voice trigger + webhook | `backend/apps/calls/services.py` + `backend/apps/calls/webhooks.py` |
| Meta Lead Ads adapter (mock/test/live) | `backend/apps/crm/integrations/meta_client.py` |
| Meta Lead Ads webhook | `backend/apps/crm/webhooks.py` (`apps/crm/services.ingest_meta_lead`) |
| AI provider adapters (Phase 3A) | `backend/apps/integrations/ai/{base,openai_client,anthropic_client,grok_client,dispatch}.py` |
| AI prompt builder (Claim Vault enforced) | `backend/apps/ai_governance/prompting.py` |
| AgentRun services (CAIO hard stop) | `backend/apps/ai_governance/services/__init__.py` |
| Per-agent runtime modules (Phase 3B) | `backend/apps/ai_governance/services/agents/{ceo,caio,ads,rto,sales_growth,cfo,compliance}.py` |
| Daily AI briefing management command | `backend/apps/ai_governance/management/commands/run_daily_ai_briefing.py` |
| Celery app + beat schedule (Phase 3C) | `backend/config/celery.py` |
| Celery task wrapping CEO + CAIO sweeps | `backend/apps/ai_governance/tasks.py` |
| Model-wise USD pricing (OpenAI + Anthropic) | `backend/apps/integrations/ai/pricing.py` |
| Local Redis (dev only) | `docker-compose.dev.yml` (root) |
| Frontend Scheduler Status page | `frontend/src/pages/Scheduler.tsx` (`/ai-scheduler`) |
| Sandbox state singleton (Phase 3D) | `backend/apps/ai_governance/sandbox.py` |
| PromptVersion lifecycle | `backend/apps/ai_governance/prompt_versions.py` |
| Per-agent budget guard | `backend/apps/ai_governance/budgets.py` |
| Frontend AI Governance page | `frontend/src/pages/Governance.tsx` (`/ai-governance`) |
| Product Catalog (Phase 3E) | `backend/apps/catalog/{models,serializers,views,urls,admin}.py` |
| Discount policy (Phase 3E) | `backend/apps/orders/discounts.py` (`validate_discount`) |
| Advance payment policy (Phase 3E, ₹499) | `backend/apps/payments/policies.py` (`FIXED_ADVANCE_AMOUNT_INR`) |
| Reward/Penalty scoring (Phase 3E) | `backend/apps/rewards/scoring.py` (`calculate_order_reward_penalty`) |
| Approval Matrix policy (Phase 3E) | `backend/apps/ai_governance/approval_matrix.py` (read at `/api/ai/approval-matrix/`) |
| WhatsApp design scaffold (Phase 3E) | `backend/apps/crm/whatsapp_design.py` |
| Master Event Ledger receivers | `backend/apps/audit/signals.py` |
| Permissions (role-based) | `backend/apps/accounts/permissions.py` |
| Order state machine | `backend/apps/orders/services.py` (`ALLOWED_TRANSITIONS`) |
| Seed deterministic data | `backend/apps/dashboards/management/commands/seed_demo_data.py` |
| Env config | `backend/config/settings.py` + `backend/.env.example` |
| Endpoint reference | `docs/BACKEND_API.md` |
| How to run | `docs/RUNBOOK.md` |
| Phased roadmap | `docs/FUTURE_BACKEND_PLAN.md` |
| Project handoff | `nd.md` |

---

## 6. When in doubt

1. Read `nd.md` (the full handoff). Section index is at the top.
2. Read the relevant Master Blueprint section (PDF in repo).
3. Run the health check: `pytest -q`, `npm test`, `npm run lint`, `npm run build`.
4. **Ask Prarit before doing anything that touches**: ad budgets, real medical claims, payment flows in live mode, customer messaging, kill-switch states, or production data.

The blueprint wins. Every decision in this codebase traces back to a section there.
