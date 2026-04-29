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
frontend/src/pages/                 ← 21 pages, each maps to a route
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
backend/apps/rewards/models.py ← Phase 4B RewardPenaltyEvent (per-order, per-AI-agent) + RewardPenalty rollup
backend/apps/rewards/engine.py ← Phase 4B engine: AI-agents-only attribution, CEO AI net accountability, idempotent sweeps
backend/apps/rewards/tasks.py ← Phase 4B Celery task (run_reward_penalty_sweep_task; eager-mode safe)
backend/apps/rewards/management/commands/calculate_reward_penalties.py ← Phase 4B cron-friendly sweep command
backend/apps/rewards/views.py ← Phase 4B endpoints: /api/rewards/{events,summary,sweep}/
backend/apps/ai_governance/approval_engine.py ← Phase 4C middleware: evaluate_action / enforce_or_queue / approve_request / reject_request / request_approval_for_agent_run
backend/apps/ai_governance/models.py ← Phase 4C: ApprovalRequest + ApprovalDecisionLog
backend/apps/ai_governance/views.py ← Phase 4C/4D endpoints: /api/ai/approvals/{,id/,id/approve/,id/reject/,id/execute/,evaluate/} + /api/ai/agent-runs/{id}/request-approval/
backend/apps/ai_governance/approval_execution.py ← Phase 4D execution engine + 3-action allow-listed registry (payment.link.advance_499, payment.link.custom_amount, ai.prompt_version.activate)
backend/apps/ai_governance/models.py ← Phase 4D: ApprovalExecutionLog (status executed/failed/skipped, partial unique constraint enforcing one executed per ApprovalRequest)
backend/apps/orders/services.py ← Phase 4E: apply_order_discount (mutates only Order.discount_pct via validate_discount; writes discount.applied audit)
backend/apps/ai_governance/approval_execution.py ← Phase 4D + 4E: 6-action allow-listed registry — payment.link.advance_499, payment.link.custom_amount, ai.prompt_version.activate, discount.up_to_10, discount.11_to_20, ai.sandbox.disable
docs/WHATSAPP_INTEGRATION_PLAN.md ← Phase 5A-0 audit + integration plan; the single source for Phase 5A scoping (Meta Cloud is the production target; Baileys is dev/demo only; consent + Claim Vault + approval matrix gates are server-side)
backend/apps/audit/realtime.py ← Phase 4A: serialize_event + latest_events + publish_audit_event (transaction.on_commit, never blocks DB writes)
backend/apps/audit/consumers.py ← Phase 4A: AuditEventConsumer (read-only fanout to ws://<host>/ws/audit/events/)
backend/apps/audit/routing.py ← Phase 4A: WebSocket URL routes for the audit app
backend/config/routing.py ← Phase 4A: top-level WebSocket router consumed by config/asgi.py ProtocolTypeRouter
frontend/src/services/realtime.ts ← Phase 4A: buildWebSocketUrl + connectAuditEvents (snapshot + per-event push, exponential reconnect, dedupe by id, never throws)
backend/apps/whatsapp/                ← Phase 5A WhatsApp Live Sender Foundation
backend/apps/whatsapp/models.py       ← 8 tables (WhatsAppConnection / Template / Consent / Conversation / Message / MessageAttachment / MessageStatusEvent / WebhookEvent / SendLog)
backend/apps/whatsapp/services.py     ← queue_template_message, send_queued_message, handle_inbound_message_event, handle_status_event (consent + Claim Vault + matrix + CAIO gates)
backend/apps/whatsapp/integrations/whatsapp/ ← provider interface (base.py) + mock.py (default) + meta_cloud_client.py (Nirogidhara-built Graph client) + baileys_dev.py (dev-only stub, refuses on DEBUG=False)
backend/apps/whatsapp/tasks.py        ← Celery send_whatsapp_message (autoretry_for=ProviderError, retry_backoff=True, retry_jitter=True, max_retries=5)
backend/apps/whatsapp/webhooks.py     ← /api/webhooks/whatsapp/meta/ (HMAC-SHA256 + replay-window + idempotent on provider_event_id; Meta GET handshake)
backend/apps/whatsapp/template_registry.py ← Meta-mirrored templates + Claim-Vault flag
backend/apps/whatsapp/consent.py      ← granted / revoked / opted_out + STOP / UNSUBSCRIBE / BAND keywords
backend/apps/whatsapp/management/commands/sync_whatsapp_templates.py ← seeds defaults; --from-file accepts a Meta-style payload
backend/apps/whatsapp/models.py     ← Phase 5B adds `WhatsAppInternalNote` (operator-side notes, never sent to customer)
backend/apps/whatsapp/views.py      ← Phase 5B adds `WhatsAppInboxView` (inbox summary), `WhatsAppConversationNotesView` (GET/POST), `WhatsAppConversationMarkReadView`, `WhatsAppConversationSendTemplateView` (per-conversation manual template send), `WhatsAppCustomerTimelineView` (WhatsApp-only timeline) + `_patch_conversation` helper for safe-field PATCH at /api/whatsapp/conversations/{id}/
frontend/src/pages/WhatsAppInbox.tsx ← Phase 5B three-pane manual-only inbox (filters / list / thread + internal notes + AI-suggestions-disabled placeholder + manual template send modal); live refresh via Phase 4A connectAuditEvents filtered on whatsapp.*
frontend/src/pages/Customers.tsx    ← Phase 5B extends Customer 360 with a WhatsApp tab (timeline, AI-suggestions disabled placeholder, link to inbox)
docker-compose.prod.yml             ← Phase 5B-Deploy production stack (project name `nirogidhara-command`, six isolated containers, host port 18020 → 80)
backend/Dockerfile                  ← Phase 5B-Deploy backend image (Python 3.11 slim + tini + non-root user; reused by backend/worker/beat services)
frontend/Dockerfile                 ← Phase 5B-Deploy frontend image (multi-stage node → nginx alpine; build context = repo root)
deploy/backend/entrypoint.sh        ← waits for Postgres/Redis, runs migrate + collectstatic, then execs the role command
deploy/nginx/nirogidhara.conf       ← container Nginx — serves SPA + proxies /api/, /admin/, /ws/
.env.production.example             ← copy to .env.production on the VPS; never commit the populated copy
docs/DEPLOYMENT_VPS.md              ← end-to-end runbook for ai.nirogidhara.com
backend/apps/dashboards/management/commands/seed_demo_data.py  ← deterministic seed

docs/RUNBOOK.md                     ← how to run the stack
docs/BACKEND_API.md                 ← endpoint reference
docs/FUTURE_BACKEND_PLAN.md         ← Phase 2+ roadmap
nd.md                               ← full project handoff (read this if you need depth)
```

16 Django apps: `accounts`, `audit`, `crm`, `calls`, `orders`, `payments`, `shipments`, `agents`, `ai_governance`, `compliance`, `rewards`, `learning_engine`, `analytics`, `dashboards`, `catalog` (Phase 3E), `whatsapp` (Phase 5A).

21 frontend pages: Dashboard, Leads CRM, Customer 360, AI Calling, Orders Pipeline, Confirmation Queue, Payments, Delhivery Tracking, RTO Rescue, AI Agents Center, CEO AI Briefing, CAIO Audit, AI Scheduler & Cost (Phase 3C), AI Governance (Phase 3D), Reward & Penalty, Human Call Learning, Claim Vault, Analytics, WhatsApp Inbox (Phase 5B), WhatsApp Templates (Phase 5A), Settings.

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
python -m pytest -q                 # 434 tests today

# Frontend
cd frontend
npm install
npm run dev                         # http://localhost:8080
npm test                            # 13 tests today
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
- Don't move the reward/penalty formula into the frontend. Phase 4B engine (`apps/rewards/engine.py`) wires the Phase 3E pure formula into per-order, per-AI-agent `RewardPenaltyEvent` rows. Frontend renders API data only — no scoring math in React. CEO AI **always** receives a net accountability event for every delivered (reward) and every RTO / cancelled (penalty) order. CAIO is excluded from business reward / penalty.
- Don't duplicate approval rules in views. Phase 4C middleware (`apps/ai_governance/approval_engine.py`) is the single source. Risky write paths call `enforce_or_queue` and stop when `result.allowed` is False. `approve_request` flips status to `approved` and writes audits — it does **not** silently execute the underlying business write; that still flows through its existing tested service path. CAIO can never request an executable approval (refused at AgentRun bridge AND at the matrix evaluation step).
- Phase 4D ships an Approved Action Execution Layer at `POST /api/ai/approvals/{id}/execute/` over a strict allow-listed registry. The first pass wires only 3 actions: `payment.link.advance_499`, `payment.link.custom_amount`, `ai.prompt_version.activate`. Every other approved action — discount, sandbox-disable, ad-budget, refund, WhatsApp, escalations, production live-mode switch — returns HTTP 400 + `ai.approval.execution_skipped` audit. Don't expand the registry without explicit Prarit sign-off + matching tests. CAIO blocked at engine + AgentRun bridge + execute layer. Idempotent: a successful execution writes one log; re-running the endpoint returns the prior result without re-invoking the handler.
- Phase 4A wires Django Channels for live AuditEvent streaming at `ws://<host>/ws/audit/events/`. The frame carries the **full stored `AuditEvent.payload`** — never trim it, but never put secrets in audit payloads either (the existing rule). The publisher in `apps/audit/realtime.py` runs inside `transaction.on_commit` and swallows Channels failures, so a missing Redis must never break a service-layer write. Existing polling endpoints (`/api/dashboard/activity/`, `/api/ai/approvals/`) remain as fallback — don't remove them. The consumer is read-and-fanout only: never execute, never mutate. Local dev defaults to the in-memory channel layer; production sets `CHANNEL_LAYER_BACKEND=redis` + `CHANNEL_REDIS_URL=redis://...:6379/2` (Channels uses Redis index 2; Celery uses 0/1).
- Phase 4E grows the execution registry to 6 actions: `payment.link.advance_499`, `payment.link.custom_amount`, `ai.prompt_version.activate`, `discount.up_to_10`, `discount.11_to_20`, `ai.sandbox.disable`. Discount handlers route through `apps.orders.services.apply_order_discount` (only mutates `Order.discount_pct`, validates via the Phase 3E `validate_discount` policy, writes `discount.applied` audit). `ai.sandbox.disable` stays Director-only (matrix `director_override`) and is idempotent on already-off (`alreadyDisabled=true`). **`discount.above_20` + `ad.budget_change` + `payment.refund` + `whatsapp.*` + `ai.production.live_mode_switch` remain unmapped** — execute → HTTP 400 + `ai.approval.execution_skipped` audit. CAIO blocked at engine + bridge + execute layer. Don't expand the registry without explicit Prarit sign-off + matching tests.
- **WhatsApp** (Phase 5A-0 + 5A-1 audits complete; live sender is Phase 5A): production target is **Meta Cloud API**, called from a Nirogidhara-built client. The external [`prarit0097/Whatsapp-sales-dashboard`](https://github.com/prarit0097/Whatsapp-sales-dashboard) reference repo's Meta Cloud provider is **stubbed** (every method returns no-op dicts; zero `graph.facebook.com` calls) — Nirogidhara writes its own client; do not "port" that file. **Baileys is dev/demo only** (`baileys_dev` provider must refuse to load when `DEBUG=False` AND `WHATSAPP_DEV_PROVIDER_ENABLED!=true`). Every WhatsApp send must be **consent + approved-template + Claim-Vault gated** server-side; failed sends NEVER mutate `Order` / `Payment` / `Shipment`. Webhook is HMAC-verified (`X-Hub-Signature-256`) + replay-window-checked + idempotent on `provider_event_id`. **CAIO never sends customer messages** (refused at engine + bridge + execute layer, plus an explicit guard at the WhatsApp service entry). Live updates use the existing Phase 4A `/ws/audit/events/` channel — no separate WhatsApp WebSocket. Full integration plan with model specs, provider interface, allowed message types, audit kinds, env vars, test plan, and migration sequence: `docs/WHATSAPP_INTEGRATION_PLAN.md`.
- **WhatsApp AI Chat Sales Agent direction (Phase 5A-1, locked).** The WhatsApp module is **not only a reminder sender**. It must work as an inbound-first AI Chat Sales Agent with the same business objective as the AI Calling Agent (greet → category detection → Claim-Vault-grounded explanation → objection handling → address collection in chat → order booking → payment-link handoff → confirmation / delivery / RTO / reorder lifecycle → chat-to-call handoff). **Greeting rule (locked):** first reply to any generic intro must be the fixed Hindi UTILITY template `"Namaskar, Nirogidhara Ayurvedic Sanstha mai aapka swagat hai. Bataye mai aapki kya help kar sakta/sakti hu?"` — no freestyle on first reply. **First-phase mode = `auto-reply` with guardrails:** AI replies without operator click but every send still routes through `enforce_or_queue` + Claim Vault + sandbox + budget; CAIO never sends. **Category detection (locked):** before any product-specific text, identify a `apps.catalog.ProductCategory` slug; product explanation thereafter must use `apps.compliance.Claim.approved` only. **Chat-to-call handoff** triggers on explicit request, low confidence on two consecutive turns, address/payment/pincode failure, six existing handoff flags, or high-risk RTO rescue. Full plan: `docs/WHATSAPP_INTEGRATION_PLAN.md` §S–§GG.
- **Discount discipline (LOCKED, the most important business rule, applies to every AI agent — Chat / Calling / Confirmation / RTO / Customer Success / any future).** **AI must NEVER offer a discount upfront.** Lead with standard ₹3000/30-capsule price; do not mention discount unless the customer asks; on first ask, handle the underlying objection (value/trust/benefit/brand/doctor/ingredients/lifestyle); only after 2–3 customer pushes may the AI offer a discount within the Phase 3E `validate_discount` bands. **Refusal-based rescue is the only proactive offer path** — eligible at three stages: (A) order-booking refusal, (B) confirmation refusal, (C) delivery / RTO refusal. **50% total-discount hard cap across all stages combined.** Examples: 20+20+10=50% allowed; 20+20+20=60% blocked. Phase 5E will add `validate_total_discount_cap(order, additional_pct)` that runs before `apply_order_discount` in the Phase 4D execute layer; over-cap requests convert to a director-only `discount.above_50_director_override` `ApprovalRequest`. **Every discount or discount offer (accepted, rejected, blocked) must be audited** via the future `DiscountOfferLog` table and a `discount.offered` audit kind (planned for Phase 5C/5D).
- **WhatsApp learning loop scope (locked).** May improve tone / timing / objection handling / closing style / discount-offer timing / handoff timing / category-question phrasing / address-collection wording. **Must NOT create** new medical claims, product promises, cure statements, side-effect advice, refund/legal commitments, new outbound templates (Meta-pre-approved only — sync from WABA), or discount offers above the per-stage band or the 50% total cap. Promotion path mirrors `learned_memory.py`: raw → QA → Compliance → CAIO audit → CEO sandbox test run on next 100 conversations → live `PromptVersion` update. **No automatic promotion.**
- **Production deployment** (Phase 5B-Deploy): the Docker stack at `docker-compose.prod.yml` is **isolated** — project name `nirogidhara-command`, container names prefixed `nirogidhara-*`, network `nirogidhara_network`, host port `18020:80`. The VPS already runs Postzyo / OpenClaw — never run `docker system prune -a`, never reuse their container names, never point the new stack at their volumes, never share their Redis. `docs/DEPLOYMENT_VPS.md` is the only production runbook; keep it in sync. **Never commit `.env.production`** (gitignored at the repo root). All integration `*_MODE` env vars stay `mock` until Prarit confirms each integration's live credentials.
- Don't push to `main` without running tests + build + lint locally first.
- Don't `git push --force`. Don't skip hooks. Don't amend pushed commits.

---

## When in doubt

1. Read `nd.md` (the project handoff). Section index is at the top.
2. Read the relevant blueprint section (`Nirogidhara AI Command Center — Master Blueprint v1.0`, PDF in repo).
3. Run the health check above.
4. Ask Prarit before doing anything that touches: ad budgets, real medical claims, payment flows, customer messaging, kill-switch states, or production data.

The blueprint wins. Every decision in this codebase traces back to a section there.
