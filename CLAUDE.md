# CLAUDE.md — Nirogidhara AI Command Center

> Auto-loaded by Claude Code on every session in this repo.
> If you are an AI agent working here, **read this file first**, then `AGENTS.md` for guardrails and `nd.md` for the full project handoff.

---

## 0. Project context (60-second read)

Full-stack AI Business Operating System for Nirogidhara Private Limited (Ayurvedic medicine D2C). React 18 + Vite + TS frontend talks to Django 5 + DRF backend. Director: Prarit Sidana — final authority for high-risk decisions. Reference: *Nirogidhara AI Command Center — Master Blueprint v1.0* (PDF in repo).

Status: Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B + 3C + 3D + 3E + 4A + 4B + 4C + 4D + 4E + 5A-0 + 5A-1 + 5A + **5B** complete. Phase 5B ships the **Inbound WhatsApp Inbox + Customer 360 Timeline**: new `WhatsAppInternalNote` model, six new endpoints (`GET /api/whatsapp/inbox/`, `PATCH /api/whatsapp/conversations/{id}/`, `POST /api/whatsapp/conversations/{id}/mark-read/`, `GET + POST /api/whatsapp/conversations/{id}/notes/`, `POST /api/whatsapp/conversations/{id}/send-template/` routing through Phase 5A's `queue_template_message`, `GET /api/whatsapp/customers/{customer_id}/timeline/`), six new audit kinds (`whatsapp.conversation.opened/updated/assigned/read`, `whatsapp.internal_note.created`, `whatsapp.template.manual_send_requested`), conversation list filters (`unread=true`, `assignedTo`, `q`), conversation serializer extended with `customerName / customerPhone / assignedToUsername` + message serializer with `templateName`. Frontend ships a three-pane `/whatsapp-inbox` page (filters / conversation list / thread + internal notes + manual template send modal + AI-suggestions-disabled placeholder) with live refresh via Phase 4A `connectAuditEvents` filtered on `whatsapp.*`, plus a Customer 360 WhatsApp tab. **Manual-only — AI auto-reply / chat-to-call handoff / rescue discount / order booking from chat are all deferred to Phase 5C–5F.** Operations users send only approved templates; backend gates (consent + approved template + Claim Vault + approval matrix + CAIO hard stop + idempotency) remain final. **434 backend tests + 13 frontend tests, all green.**

Earlier phases unchanged: Phase 5A shipped the WhatsApp Live Sender Foundation (`apps.whatsapp` Django app with 8 models, three providers — `mock` default + `meta_cloud` Nirogidhara-built Graph client + `baileys_dev` dev-only stub, service layer gating consent + approved template + Claim Vault + approval matrix + CAIO + idempotency, Celery `send_whatsapp_message` task with autoretry/backoff/jitter/max_retries=5, signed webhook at `/api/webhooks/whatsapp/meta/`, 9 read + 4 write API endpoints under `/api/whatsapp/`, `sync_whatsapp_templates` management command, frontend Settings → WABA section + read-only `/whatsapp-templates` page). All earlier phases (CRM, write APIs, four gateway integrations, AgentRun + 7 per-agent runtimes, Celery beat at 09:00 + 18:00 IST, OpenAI → Anthropic fallback, model-wise USD cost tracking, sandbox + versioned prompts + per-agent USD budgets, Scheduler + Governance pages, Phase 3E business config — catalog + discount policy 10/20% bands + ₹499 fixed advance + reward/penalty scoring + approval matrix, Phase 4B reward/penalty engine + CEO AI net accountability, Phase 4C approval-matrix middleware, Phase 4D Approved Action Execution Layer, Phase 4A real-time AuditEvent WebSockets, Phase 4E expanded execution registry — discount.up_to_10 / discount.11_to_20 / ai.sandbox.disable) remain green. **Phase 5A-0 + 5A-1** are the doc-only WhatsApp design phases; the integration plan in `docs/WHATSAPP_INTEGRATION_PLAN.md` (sections A–R + S–GG) drove the Phase 5A + 5B implementations. Next: Phase 5C WhatsApp AI Chat Sales Agent.

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
8. **WhatsApp** (Phase 5A-0 / 5A-1 / 5A): production target is **Meta Cloud API**; Baileys is **dev/demo only** (off by default in non-DEBUG environments). Every send is consent + approved-template + Claim-Vault gated server-side; failed sends never mutate Order / Payment / Shipment. CAIO never sends customer messages. Full plan: `docs/WHATSAPP_INTEGRATION_PLAN.md`.
9. **WhatsApp AI Chat Sales Agent** (Phase 5A-1 addendum, §S–§GG): the WhatsApp module must work as an inbound-first AI Chat Sales Agent mirroring the AI Calling Agent's business objective. Greeting rule locked (fixed Hindi UTILITY template on first reply). First-phase mode is `auto-reply` — meaning the AI replies without operator click, NOT that it bypasses the matrix / Claim Vault / approval engine / sandbox / budget. Address is collected in chat via a stateful `WhatsAppConversation.metadata.address_collection`. Category must be detected before any product-specific text. Chat-to-call handoff fires on explicit request, low confidence, address/payment failure, or any of the six existing handoff flags.
10. **Discount discipline (LOCKED, the most important business rule).** Any AI/Calling/Chat/Confirmation/RTO/Customer-Success agent **must NOT offer a discount upfront**. Lead with standard ₹3000/30-capsule price; do not mention discount unless the customer asks; on first ask, handle the underlying objection (value/trust/benefit/brand/doctor/ingredients/lifestyle); only after 2–3 customer pushes may the AI offer a discount within the Phase 3E `validate_discount` bands. **Refusal-based rescue is the only proactive offer path** — eligible at three stages: A) order-booking refusal, B) confirmation refusal, C) delivery / RTO refusal.
11. **50% total discount hard cap (LOCKED).** Across all stages combined, the total discount on a single order must NEVER exceed 50%. Examples: 20+20+10=50% allowed; 20+20+20=60% blocked. Scope: every AI workflow that can offer a discount. Phase 5E will add `validate_total_discount_cap(order, additional_pct)` that runs before `apply_order_discount`; over-cap requests convert to a director-only `discount.above_50_director_override` `ApprovalRequest`.

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
python -m pytest -q                    # 434 tests today

# Frontend
cd frontend
npm install
npm run dev                            # http://localhost:8080
npm test                               # 13 tests today
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
| WhatsApp app (Phase 5A) | `backend/apps/whatsapp/` |
| WhatsApp models | `backend/apps/whatsapp/models.py` (8 tables) |
| WhatsApp provider interface | `backend/apps/whatsapp/integrations/whatsapp/base.py` |
| WhatsApp mock provider | `backend/apps/whatsapp/integrations/whatsapp/mock.py` |
| WhatsApp Meta Cloud provider | `backend/apps/whatsapp/integrations/whatsapp/meta_cloud_client.py` |
| WhatsApp Baileys dev stub | `backend/apps/whatsapp/integrations/whatsapp/baileys_dev.py` |
| WhatsApp service layer | `backend/apps/whatsapp/services.py` (queue_template_message, send_queued_message, handle_inbound/status webhook events) |
| WhatsApp consent helpers | `backend/apps/whatsapp/consent.py` (granted / revoked / opted_out + STOP / UNSUBSCRIBE / BAND keywords) |
| WhatsApp template registry | `backend/apps/whatsapp/template_registry.py` (sync from Meta + Claim-Vault flag) |
| WhatsApp Celery task | `backend/apps/whatsapp/tasks.py` (autoretry_for=ProviderError, max_retries=5) |
| WhatsApp signed webhook | `backend/apps/whatsapp/webhooks.py` (`/api/webhooks/whatsapp/meta/`) |
| WhatsApp REST endpoints | `backend/apps/whatsapp/views.py` + `urls.py` (`/api/whatsapp/...`) |
| WhatsApp template-sync command | `backend/apps/whatsapp/management/commands/sync_whatsapp_templates.py` |
| Frontend WhatsApp Templates page | `frontend/src/pages/WhatsAppTemplates.tsx` (`/whatsapp-templates`) |
| Frontend WhatsApp api methods | `frontend/src/services/api.ts` (Phase 5A section) |
| Frontend WhatsApp types | `frontend/src/types/domain.ts` (`WhatsApp*` block) |
| Frontend Settings WABA section | `frontend/src/pages/Settings.tsx` (extended) |
| Phase 5B WhatsApp internal note model | `backend/apps/whatsapp/models.py` (`WhatsAppInternalNote`) |
| Phase 5B inbox / notes / mark-read / send-template / timeline views | `backend/apps/whatsapp/views.py` (`WhatsAppInboxView`, `WhatsAppConversationNotesView`, `WhatsAppConversationMarkReadView`, `WhatsAppConversationSendTemplateView`, `WhatsAppCustomerTimelineView`, `_patch_conversation`) |
| Phase 5B WhatsApp inbox page | `frontend/src/pages/WhatsAppInbox.tsx` (`/whatsapp-inbox`) |
| Phase 5B Customer 360 WhatsApp tab | `frontend/src/pages/Customers.tsx` (extended — `WhatsAppTab`) |
| Reward/Penalty engine (Phase 4B) | `backend/apps/rewards/engine.py` |
| RewardPenaltyEvent model | `backend/apps/rewards/models.py` |
| Reward/Penalty Celery task | `backend/apps/rewards/tasks.py` |
| `calculate_reward_penalties` command | `backend/apps/rewards/management/commands/calculate_reward_penalties.py` |
| Reward sweep / events / summary endpoints | `backend/apps/rewards/views.py` (`/api/rewards/{events,summary,sweep}/`) |
| Approval Matrix middleware (Phase 4C) | `backend/apps/ai_governance/approval_engine.py` |
| ApprovalRequest + ApprovalDecisionLog models | `backend/apps/ai_governance/models.py` |
| Approval endpoints | `backend/apps/ai_governance/views.py` (`/api/ai/approvals/{,id/,id/approve/,id/reject/,id/execute/,evaluate/}` + `/api/ai/agent-runs/{id}/request-approval/`) |
| Approved Action Execution (Phase 4D) | `backend/apps/ai_governance/approval_execution.py` |
| ApprovalExecutionLog model | `backend/apps/ai_governance/models.py` |
| Realtime AuditEvent serializer + publisher (Phase 4A) | `backend/apps/audit/realtime.py` |
| Audit WebSocket consumer (Phase 4A) | `backend/apps/audit/consumers.py` |
| Audit WebSocket route (Phase 4A) | `backend/apps/audit/routing.py` (`/ws/audit/events/`) |
| Top-level WebSocket router (Phase 4A) | `backend/config/routing.py` |
| Frontend realtime client | `frontend/src/services/realtime.ts` |
| Master Event Ledger receivers | `backend/apps/audit/signals.py` |
| Permissions (role-based) | `backend/apps/accounts/permissions.py` |
| Order state machine | `backend/apps/orders/services.py` (`ALLOWED_TRANSITIONS`) |
| Seed deterministic data | `backend/apps/dashboards/management/commands/seed_demo_data.py` |
| Env config | `backend/config/settings.py` + `backend/.env.example` |
| Endpoint reference | `docs/BACKEND_API.md` |
| How to run | `docs/RUNBOOK.md` |
| Phased roadmap | `docs/FUTURE_BACKEND_PLAN.md` |
| WhatsApp integration plan (Phase 5A-0) | `docs/WHATSAPP_INTEGRATION_PLAN.md` |
| Project handoff | `nd.md` |

---

## 6. When in doubt

1. Read `nd.md` (the full handoff). Section index is at the top.
2. Read the relevant Master Blueprint section (PDF in repo).
3. Run the health check: `pytest -q`, `npm test`, `npm run lint`, `npm run build`.
4. **Ask Prarit before doing anything that touches**: ad budgets, real medical claims, payment flows in live mode, customer messaging, kill-switch states, or production data.

The blueprint wins. Every decision in this codebase traces back to a section there.
