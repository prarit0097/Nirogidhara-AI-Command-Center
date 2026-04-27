# AGENTS.md — Nirogidhara AI Command Center

> Auto-loaded by Claude Code, Cursor, and other AI coding tools.
> If you are an AI agent working in this repo, **read this file first**, then
> see `nd.md` for full context and `docs/RUNBOOK.md` for run instructions.

---

## Working agreement (binding rule)

**Every meaningful change to this project MUST be followed by:**

1. **Update `nd.md`** — adjust the relevant section so the project handoff stays the source of truth.
2. **Update `AGENTS.md`** — if a convention, hard stop, or "where things live" pointer changed.
3. **Run the full verification suite** before committing:
   - `cd backend && python -m pytest -q && python manage.py check`
   - `cd frontend && npm run lint && npm test && npm run build`
4. **Commit with a Conventional Commit message** (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
5. **Push to `origin/main`** at https://github.com/prarit0097/Nirogidhara-AI-Command-Center.

The remote on GitHub must mirror local state at the end of every working session. Non-negotiable.

**Meaningful change** = any code edit, new endpoint/model/migration/service/page, env var, dependency, or onboarding-doc change.
**Not meaningful** = read-only exploration or reverted experiments.

**Never without explicit user authorization**: force-push to `main`, rewrite pushed history (`commit --amend`, `rebase -i`), skip hooks (`--no-verify`), commit secrets.

---

## Hard stops (compliance — never bypass)

This codebase serves an Ayurvedic medicine business. Some rules are non-negotiable:

1. **No free-style medical claims.** AI may only emit content from `apps.compliance.Claim` (the Approved Claim Vault). Hard-coded medical strings in code are forbidden.
2. **Blocked claim phrases — do not generate, hard-code, or seed:**
   - "Guaranteed cure"
   - "Permanent solution"
   - "No side effects for everyone"
   - "Works for all people universally"
   - "Doctor ki zarurat nahi"
   - Any "cures X disease" claim without doctor approval
   - Emergency medical advice
3. **CAIO Agent never executes business actions.** It monitors / audits / suggests only. If you find code wiring a CAIO endpoint to a write path, that's a bug — fix it.
4. **CEO AI is the execution approval layer.** Low/medium-risk actions go through it. High-risk actions go to **Prarit Sidana** (final authority).
5. **Every important state change writes an `AuditEvent`** (Master Event Ledger). Add a `post_save` receiver in `apps/audit/signals.py` for any new state-bearing model.
6. **Reward/penalty is based on delivered profitable orders**, not order-punching count.
7. **Human call recordings must not auto-train live AI.** They go through QA → Compliance → CAIO audit → Sandbox → CEO approval first.
8. **Frontend never holds business logic.** All calculations with business meaning live in Django services.
9. **AI Kill Switch, Sandbox Mode, Rollback System, Approval Matrix** are mandatory before any production rollout.
10. **Future Android/iOS apps must use the same backend APIs.** Don't fork business logic into mobile clients.
11. **AI provider keys live in `backend/.env` only** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROK_API_KEY`). Read them through `apps._ai_config.current_config()`. Never hard-code, never log them, never expose them to the frontend. When wiring Phase 3 LLM calls, every prompt MUST inject relevant `apps.compliance.Claim` entries before reaching the model — see rule #1.

---

## Architecture rule

```
React UI  ──/api/JSON──►  Django + DRF  ──ORM──►  SQLite (dev) / Postgres (prod)
   │                          │
   │                          │ post_save signals
   │                          ▼
   │                   audit.AuditEvent  ← Master Event Ledger
   │
   └── mock fallback ── frontend/src/services/mockData.ts
       (offline-safe; pages never break if backend is down)
```

- **Frontend → backend** flows through one file: `frontend/src/services/api.ts`. Never call `mockData.ts` directly from a page.
- **Backend → frontend** uses camelCase JSON keys (Django serializers map snake_case columns via `source=`).
- **Pages** (`frontend/src/pages/*.tsx`) consume `api` only. **Never** import `mockData.ts` from a page.
- **No `{success, data}` envelope** — endpoints return raw arrays/objects matching `frontend/src/types/domain.ts`.

---

## Repo layout (where things live)

```
frontend/src/services/api.ts        ← service layer (HTTP + mock fallback)
frontend/src/services/mockData.ts   ← deterministic fixtures (internal)
frontend/src/types/domain.ts        ← THE TypeScript contract
frontend/src/pages/                 ← 19 pages, each maps to a route
frontend/src/components/{ui,layout} ← shadcn UI + app shell

backend/config/settings.py          ← env-driven config
backend/config/urls.py              ← mounts every app under /api/
backend/apps/<app>/{models,serializers,views,urls}.py  ← per-app skeleton
backend/apps/<app>/services.py      ← workflow logic per app (writes happen here, not views)
backend/apps/audit/signals.py       ← Master Event Ledger receivers
backend/apps/accounts/permissions.py ← RoleBasedPermission + role-set constants
backend/apps/payments/integrations/razorpay_client.py ← Razorpay mock/test/live adapter
backend/apps/payments/webhooks.py   ← Razorpay webhook receiver (HMAC + idempotent)
backend/apps/shipments/integrations/delhivery_client.py ← Delhivery mock/test/live adapter
backend/apps/shipments/webhooks.py  ← Delhivery tracking webhook receiver (HMAC + idempotent)
backend/apps/calls/integrations/vapi_client.py ← Vapi mock/test/live adapter
backend/apps/calls/webhooks.py      ← Vapi voice webhook receiver (HMAC when secret set + idempotent)
backend/apps/calls/services.py      ← trigger_call_for_lead + persist_vapi_webhook
backend/apps/crm/integrations/meta_client.py ← Meta Lead Ads mock/test/live adapter + signature/handshake helpers
backend/apps/crm/webhooks.py        ← Meta Lead Ads webhook (GET handshake + POST ingest, idempotent on leadgen_id)
backend/apps/_ai_config.py          ← AI provider config helper
backend/apps/integrations/ai/       ← Phase 3A provider adapters: base.py, openai_client.py, anthropic_client.py, grok_client.py, dispatch.py
backend/apps/ai_governance/prompting.py ← System policy + Approved Claim Vault enforced prompt builder (raises ClaimVaultMissing when ungrounded)
backend/apps/ai_governance/services/__init__.py ← AgentRun lifecycle + CAIO hard stop (refuses execute/apply/create_order/transition intents)
backend/apps/ai_governance/services/agents/ ← Phase 3B per-agent runtime modules: ceo, caio, ads, rto, sales_growth, cfo, compliance
backend/apps/ai_governance/management/commands/run_daily_ai_briefing.py ← cron-friendly CEO + CAIO daily runner
backend/apps/ai_governance/tasks.py ← Phase 3C Celery task wrapping CEO + CAIO daily sweeps (eager-mode safe)
backend/apps/ai_governance/models.py ← AgentRun (id, agent, prompt_version, input/output payload, status, provider, latency_ms, cost_usd, prompt_tokens, completion_tokens, total_tokens, provider_attempts, fallback_used, pricing_snapshot)
backend/apps/integrations/ai/pricing.py ← Model-wise OpenAI + Anthropic per-1M-token rates (review periodically)
backend/config/celery.py            ← Celery app + 09:00 + 18:00 IST beat schedule (CELERY_TASK_ALWAYS_EAGER=true in dev)
docker-compose.dev.yml              ← Local Redis only — VPS Redis NEVER used in development
backend/apps/ai_governance/sandbox.py ← Phase 3D SandboxState singleton (skips CeoBriefing refresh when ON)
backend/apps/ai_governance/prompt_versions.py ← Phase 3D PromptVersion lifecycle (one active per agent + rollback)
backend/apps/ai_governance/budgets.py ← Phase 3D per-agent USD budget guard (warning + block, no provider fallback)
backend/apps/catalog/{models,serializers,views,urls,admin}.py ← Phase 3E product catalog (ProductCategory / Product / ProductSKU + admin)
backend/apps/orders/discounts.py ← Phase 3E discount policy (validate_discount: 10% auto / 20% approval / above-20 director-override)
backend/apps/payments/policies.py ← Phase 3E advance payment policy (FIXED_ADVANCE_AMOUNT_INR = 499)
backend/apps/rewards/scoring.py ← Phase 3E reward/penalty deterministic formula (caps: +100 / -100 per order)
backend/apps/ai_governance/approval_matrix.py ← Phase 3E approval-matrix policy table (22 actions); read at /api/ai/approval-matrix/
backend/apps/crm/whatsapp_design.py ← Phase 3E WhatsApp sales/support design scaffold (no live integration yet)
backend/apps/dashboards/management/commands/seed_demo_data.py  ← deterministic seed

docs/RUNBOOK.md                     ← how to run the stack
docs/BACKEND_API.md                 ← endpoint reference
docs/FUTURE_BACKEND_PLAN.md         ← Phase 2+ roadmap
nd.md                               ← full project handoff (read this if you need depth)
```

15 Django apps: `accounts`, `audit`, `crm`, `calls`, `orders`, `payments`, `shipments`, `agents`, `ai_governance`, `compliance`, `rewards`, `learning_engine`, `analytics`, `dashboards`, `catalog` (Phase 3E).

19 frontend pages: Dashboard, Leads CRM, Customer 360, AI Calling, Orders Pipeline, Confirmation Queue, Payments, Delhivery Tracking, RTO Rescue, AI Agents Center, CEO AI Briefing, CAIO Audit, AI Scheduler & Cost (Phase 3C), AI Governance (Phase 3D), Reward & Penalty, Human Call Learning, Claim Vault, Analytics, Settings.

---

## Conventions

### Python / Django

- Pin `Django>=5.0,<5.2`, `Python>=3.10`.
- Snake_case in Python and DB. Use `source=` mapping in serializers to expose camelCase keys.
- DRF `ViewSet`s with `mixins.ListModelMixin` / `mixins.RetrieveModelMixin` for read endpoints. `pagination_class = None` while fixture sizes stay small.
- Tests use `pytest-django`. Every endpoint gets a smoke test that asserts status 200 + camelCase key presence.
- Models with string PKs match the frontend's seeded IDs (`LD-NNNNN`, `NRG-NNNNN`, `CL-LIVE-NNN`, `PAY-NNNNN`, etc.) so the cutover from mock to backend is bit-identical.
- The seed command must remain deterministic and idempotent.

### TypeScript / React

- **No `any`** in app code. Use generics + `unknown` at boundaries.
- Use **Zod** for schema validation at boundaries.
- Define props with named `interface` / `type`. Don't use `React.FC`.
- Animate compositor-friendly properties only (`transform`, `opacity`).
- Prefer **Vitest + React Testing Library**. Visual regression is Phase 6+.
- Component files stay under ~400 lines (split when bigger).
- No `console.log` left in committed code (use proper warnings only).

### Style

- Tailwind tokens. Premium Ayurveda + AI SaaS theme: deep green / emerald / teal / saffron-gold / ivory / charcoal. Rounded cards, soft shadows, clean typography, strong hierarchy.
- Director should grok business health in 30 seconds. Not an admin template.

### Git

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- Commit at every checkpoint that leaves the repo green (build + lint + test).
- **Never** `git push --force` to `main`. Never skip hooks (`--no-verify` is forbidden unless the user explicitly authorizes).
- One feature per branch when working on Phase 2+.

---

## Common commands

```bash
# Backend
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py runserver 0.0.0.0:8000
python -m pytest -q                 # 219 tests today

# Frontend
cd frontend
npm install
npm run dev                         # http://localhost:8080
npm test                            # 8 tests today
npm run lint                        # 0 errors expected
npm run build                       # production build
```

Quick health check before any large change:
```bash
cd backend && python -m pytest -q && python manage.py check
cd frontend && npm run lint && npm test && npm run build
```

---

## When adding things

| Task | What to touch |
| --- | --- |
| New API endpoint | `backend/apps/<app>/{models,serializers,views,urls}.py` + smoke test in `backend/tests/test_endpoints.py` + matching call in `frontend/src/services/api.ts` |
| New Django app | Add to `INSTALLED_APPS` in `backend/config/settings.py` + mount URL in `backend/config/urls.py` + create `apps/<name>/{__init__,apps,models,serializers,views,urls,admin}.py` |
| New audit-ledger event | `backend/apps/audit/signals.py` (add `@receiver(post_save, sender=...)` + `ICON_BY_KIND` entry) |
| New frontend page | New file in `frontend/src/pages/` + add route in `App.tsx` + add nav item in `components/layout/Sidebar.tsx` + use `api` service only |
| New shared TS type | `frontend/src/types/domain.ts` + matching serializer with `source=` mapping |

---

## Don't do this

- Don't import `mockData.ts` from a page or component. Use `api`.
- Don't add `console.log` to production paths.
- Don't add `any` to TypeScript when `unknown` + a narrow would work.
- Don't add Supabase, Firebase, or any other backend service. Backend is Django + DRF, period.
- Don't hard-code medical claims in any file. They live in `apps.compliance.Claim`.
- Don't write to the database from CAIO endpoints. CAIO is read/audit only.
- Don't add a real third-party integration without confirming credentials & sandbox setup with Prarit first. **Razorpay (2B), Delhivery (2C), Vapi (2D), and Meta Lead Ads (2E) are shipped** — `RAZORPAY_MODE`, `DELHIVERY_MODE`, `VAPI_MODE`, and `META_MODE` each accept `mock|test|live` and flip to test/live once real credentials are in `backend/.env`. **WhatsApp** has a design scaffold only (`apps/crm/whatsapp_design.py`, Phase 3E) — no live sender; Phase 4+ wires it once Business API credentials + consent flow are confirmed. PayU still needs creds before any wiring lands.
- Don't bypass the Phase 3E policies: `apps/orders/discounts.py` is the discount source of truth (10% auto / 20% approval / above-20 director-override), `apps/payments/policies.py` defines the ₹499 fixed advance, `apps/rewards/scoring.py` is the reward/penalty formula (do not invent missing data), and `apps/ai_governance/approval_matrix.py` is the action → approver table. The Phase 4C middleware will enforce the matrix; until then, keep the policy modules as the single source.
- Don't push to `main` without running tests + build + lint locally first.
- Don't `git push --force`. Don't skip hooks. Don't amend pushed commits.

---

## When in doubt

1. Read `nd.md` (the project handoff). Section index is at the top.
2. Read the relevant blueprint section (`Nirogidhara AI Command Center — Master Blueprint v1.0`, PDF in repo).
3. Run the health check above.
4. Ask Prarit before doing anything that touches: ad budgets, real medical claims, payment flows, customer messaging, kill-switch states, or production data.

The blueprint wins. Every decision in this codebase traces back to a section there.
