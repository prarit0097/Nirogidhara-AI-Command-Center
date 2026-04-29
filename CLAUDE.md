# CLAUDE.md — Nirogidhara AI Command Center

> Auto-loaded by Claude Code on every session in this repo.
> If you are an AI agent working here, **read this file first**, then `AGENTS.md` for guardrails and `nd.md` for the full project handoff.

---

## 0. Project context (60-second read)

Full-stack AI Business Operating System for Nirogidhara Private Limited (Ayurvedic medicine D2C). React 18 + Vite + TS frontend talks to Django 5 + DRF backend. Director: Prarit Sidana — final authority for high-risk decisions. **Current strategic blueprint:** [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md) (Master Blueprint v2.0 — supersedes the v1.0 PDF, which is now historical reference only).

Status: Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B + 3C + 3D + 3E + 4A + 4B + 4C + 4D + 4E + 5A-0 + 5A-1 + 5A + 5B + 5C + 5D + 5E + 5E-Hotfix + 5E-Hotfix-2 + **5E-Smoke** + **5E-Smoke-Fix** + **5E-Smoke-Fix-2** complete. **Phase 5E-Smoke-Fix-3** ships the **false-positive safety classification fix**: the VPS OpenAI smoke run reported `overallPassed=false` because the orchestrator wrongly classified `Hi mujhe weight loss product ke baare me batana` as a `side_effect_complaint`. New `apps.whatsapp.safety_validation.validate_safety_flags(inbound_text, safety_flags)` runs server-side immediately before `_safety_block` in `apps.whatsapp.ai_orchestration` — for each blocker flag the LLM set to true (`sideEffectComplaint`, `medicalEmergency`, `legalThreat`), it checks whether the inbound text actually contains the corresponding signal vocabulary (English + Hindi + Hinglish). Flags with no matching vocabulary are flipped to false and a `whatsapp.ai.safety_downgraded` audit row is emitted; flags whose vocabulary IS present (`medicine khane ke baad ulta asar`, `chest pain`, `consumer forum`, `lawyer`) stay flagged exactly as the LLM said. `angryCustomer` and `claimVaultUsed` are never touched. The LLM prompt now carries an explicit `SAFETY FLAG DISCIPLINE` block listing required vocabulary for each flag and stating that a normal product / price / availability inquiry leaves all safety flags false. **28 new backend tests** prove false positives are scrubbed across all three flags in three languages, real safety phrases stay flagged, and the corrector never promotes false→true. **619 backend + 13 frontend tests, all green.** VPS rebuild required so the new orchestrator + prompt land in the container; after rebuild the OpenAI smoke run is expected to report `overallPassed=true`.

**Phase 5E-Smoke-Fix-2** ships the **OpenAI Chat Completions token-parameter compatibility hotfix**: extracts `apps.integrations.ai.openai_client.build_request_kwargs(messages, model, config)` so the SDK call shape is unit-testable. Modern OpenAI Chat models (gpt-4o, gpt-5, o1, o3, …) reject the legacy `max_tokens` parameter and require `max_completion_tokens`; the adapter now always sends `max_completion_tokens` and **never** sends `max_tokens` — the two are never sent together. Zero / unset `max_tokens` from `AIConfig` drops the key entirely so OpenAI doesn't reject an explicit null. **10 new backend tests** pin the kwargs shape, prove no `max_tokens` leaks, and confirm the smoke harness reports `safeFailure=true` when OpenAI rejects an unsupported parameter (the exact failure mode that triggered this hotfix). **591 backend + 13 frontend, all green.**

**Phase 5E-Smoke-Fix** ships the **OpenAI SDK dependency + provider-success semantics for the smoke harness**: `openai>=1.0,<2.0` added to `backend/requirements.txt` (the existing OpenAI adapter already targets the v1 SDK shape — `from openai import OpenAI; client.chat.completions.create(...)`). Smoke harness `ai-reply` scenario now sets four new detail fields when `--use-openai` is passed — `openaiAttempted`, `openaiSucceeded`, `providerPassed`, `safeFailure`. A safe-failure (adapter raised but the customer send stayed safely blocked) is still safety-correct but **does NOT count as a pass**: the scenario reports `passed=false`, `safeFailure=true`, and `overallPassed=false` so operators cannot miss "the SDK isn't installed" / "the API key is wrong" while everything else looks fine. Pre-seeds an outbound on the smoke conversation so the greeting fast-path never short-circuits LLM dispatch — the scripted Hindi/Hinglish/English inbounds (which all start with greeting words) now reliably exercise the adapter path. **6 new backend tests; 579 backend + 13 frontend, all green.**

**Phase 5E-Smoke** ships the **Controlled Mock + OpenAI Smoke Testing Harness**: new `apps.whatsapp.smoke_harness` module + `python manage.py run_controlled_ai_smoke_test` command exercise the WhatsApp AI orchestrator, Claim Vault gates, rescue discount cap math (50% absolute), Vapi handoff (mock mode), and Day-20 reorder sweep without sending any real customer message. Defaults are SAFE: `--dry-run`, `--mock-whatsapp`, `--mock-vapi`, OpenAI off (deterministic mocked LLM decision). Five scenarios — `ai-reply` / `claim-vault` / `rescue-discount` / `vapi-handoff` / `reorder-day20` / `all`. Four new audit kinds (`system.smoke_test.{started,completed,failed,warning}`). Refuses real Meta provider outright. Outputs `--json` for CI / log scraping. **23 new backend tests; 573 backend + 13 frontend, all green.** **Phase 5E-Hotfix-2** strengthens the demo Claim Vault seed so all eight categories report `risk=demo_ok` (not `weak`) on coverage. Adds four universal safe usage-guidance phrases (used as directed on the label / hydration + balanced diet / consult doctor for serious cases / discontinue on adverse reaction) merged into every demo entry; widens `USAGE_HINT_KEYWORDS` to recognize "directed", "label", "practitioner", "hydration", "balanced diet", "routine", "discontinue", "professional advice", "unusual reaction"; bumps the demo seed marker to `version="demo-v2"`. Idempotent — `--reset-demo` is required to upgrade demo-v1 rows in place; real admin / doctor-approved claims are still never overwritten. **550 backend tests + 13 frontend tests, all green.** Production still requires real doctor-approved final claims before full live rollout — automation flags remain OFF until controlled mock + OpenAI testing passes. **Phase 5E-Hotfix** adds two `RenameIndex` migrations (`apps/orders/migrations/0004_rename_orders_disc_order_i_dol_idx_orders_disc_order_i_e49f63_idx_and_more.py` + `apps/whatsapp/migrations/0004_rename_whatsapp_wh_convers_h0_idx_whatsapp_wh_convers_ae1708_idx_and_more.py`) to sync the index names from Phase 5D / 5E hand-rolled migrations to Django's auto-generated suffix names. Surfaced when the VPS reported "models in app(s) 'orders', 'whatsapp' have changes that are not yet reflected in a migration" after pulling commit `8374863`. Migrations are pure metadata renames — no schema rewrite, no data move. Working agreement now requires `python manage.py makemigrations --check --dry-run` to be clean before every commit. Phase 5E ships **Rescue Discount Flow + Day-20 Reorder + Default Claim Vault Seeds**: new `apps.orders.rescue_discount` is the single source of truth for AI rescue discount math — `get_current_total_discount_pct` / `get_discount_cap_remaining` / `validate_total_discount_cap` enforce a locked **50% cumulative cap** across confirmation / delivery / RTO / reorder stages, `calculate_rescue_discount_offer` walks a per-stage ladder (confirmation 5/10/15, delivery 5/10, RTO 10/15/20 with high-risk step-up, reorder 5), and `create_rescue_discount_offer` writes a new `apps.orders.DiscountOfferLog` row in every outcome (offered / accepted / rejected / blocked / skipped / `needs_ceo_review`). Over-cap or above-auto-band requests automatically mint a CEO AI / admin `ApprovalRequest` via two new matrix rows (`discount.rescue.ceo_review`, `discount.above_safe_auto_band`). Customer acceptance applies the discount through the existing `apps.orders.services.apply_order_discount` service path — Phase 4D / 4E discount handlers stay the only DB mutation point. Phase 5C orchestrator now also persists a `DiscountOfferLog` row on every WhatsApp AI discount proposal so the orders / analytics surfaces see the offer regardless of channel. New `apps.whatsapp.lifecycle` triggers — `whatsapp.confirmation_rescue_discount`, `whatsapp.delivery_rescue_discount`, `whatsapp.rto_rescue_discount`, `whatsapp.reorder_day20_reminder` — flow through the Phase 5A `queue_template_message` pipeline (consent + Claim Vault + matrix + CAIO + idempotency stays in force) and emit dedicated `whatsapp.lifecycle.rescue_discount_{queued,sent}` + `whatsapp.lifecycle.reorder_day20_{queued,sent}` audits. Day-20 reorder cadence: new `apps.whatsapp.reorder.run_day20_reorder_sweep` + `python manage.py run_reorder_day20_sweep` + `send_whatsapp_lifecycle_message_task` + `apps.whatsapp.tasks.run_reorder_day20_sweep_task` cover delivered orders 20–27 days old, idempotent on the lifecycle key. `python manage.py seed_default_claims` (idempotent, with `--reset-demo` flag) sows conservative non-cure / non-guarantee Claim Vault rows for the eight current categories (Weight Management, Blood Purification, Men/Women Wellness, Immunity, Lungs Detox, Body Detox, Joint Care); demo rows are flagged `version="demo-v1"` and surface in coverage reports as `risk=demo_ok` with a "replace before live rollout" note. Five new endpoints — `GET / POST /api/orders/{id}/discount-offers/{,rescue/,{offer_id}/accept/,{offer_id}/reject/}`, `GET /api/whatsapp/reorder/day20/status/`, `POST /api/whatsapp/reorder/day20/run/`. Twelve new audit kinds (`discount.offer.{created,sent,accepted,rejected,blocked,needs_ceo_review}`, `whatsapp.lifecycle.{rescue_discount_queued,rescue_discount_sent,reorder_day20_queued,reorder_day20_sent}`, `compliance.default_claims.seeded`). Four new env vars (all default safe — `WHATSAPP_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_REORDER_DAY20_ENABLED=false`, `DEFAULT_CLAIMS_SEED_DEMO_ONLY=true`). Frontend adds a Rescue Discount cap card to the AI Chat panel (current %, cap remaining, ask count) + new TS types (`DiscountOffer`, `DiscountOfferListResponse`, `CreateRescueOfferPayload`, `ReorderDay20StatusResponse`, `ReorderDay20RunResponse`) + six new api methods. Hard stops still in force: no medical-emergency replies, no freeform claims, no CAIO send, no shipment from chat, **no campaigns, no refunds, no ad-budget execution, never above 50% cumulative discount**. **38 new backend tests + 13 frontend tests, all green (536 backend total).**

Earlier (kept verbatim): Phase 5D shipped **Chat-to-Call Handoff + Lifecycle Automation**: new `apps.whatsapp.call_handoff` service routes the WhatsApp AI agent's handoff reasons (customer asked for a call / low-confidence / AI-handoff-requested) directly through the existing `apps.calls.services.trigger_call_for_lead` Vapi path — never the adapter — and writes a `WhatsAppHandoffToCall` row keyed on `(conversation, inbound_message, reason)` so the same inbound never fires two calls; safety reasons (medical_emergency / side_effect_complaint / legal_threat) record a `skipped` handoff row for human/doctor pickup instead of auto-dialing. AI-booked orders now move directly into the confirmation queue via `apps.orders.services.move_to_confirmation` (Phase 5C's `book_order_from_decision` does the move post-create; metadata records `confirmationMoveFailed` if it can't). New `apps.whatsapp.lifecycle` service + `apps.whatsapp.signals` listen on Order/Payment/Shipment `post_save` and route business events to approved templates (`whatsapp.confirmation_reminder`, `whatsapp.payment_reminder`, `whatsapp.delivery_reminder`, `whatsapp.usage_explanation`, `whatsapp.rto_rescue`) through Phase 5A's `queue_template_message` — every gate (consent + Claim Vault + approval matrix + CAIO + idempotency) stays in force, and a new `WhatsAppLifecycleEvent` table makes the dispatch idempotent on `lifecycle:{action}:{type}:{id}:{event}`. New Claim Vault coverage audit (`apps.compliance.coverage` + `check_claim_vault_coverage` mgmt cmd + `GET /api/compliance/claim-coverage/` admin endpoint) reports per-product `ok / weak / missing` risk and exits 1 in CI when products lack approved coverage; usage_explanation lifecycle template fails closed when coverage is missing. Three new endpoints: `POST /api/whatsapp/conversations/{id}/handoff-to-call/`, `GET /api/whatsapp/conversations/{id}/handoffs/`, `GET /api/whatsapp/lifecycle-events/`. Eleven new audit kinds (`whatsapp.handoff.{call_requested,call_triggered,call_failed,call_skipped,call_skipped_duplicate}`, `whatsapp.lifecycle.{queued,sent,blocked,skipped_duplicate,failed}`, `whatsapp.ai.order_moved_to_confirmation`, `compliance.claim_coverage.checked`). Four new env vars (`WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_LIVE_META_LIMITED_TEST_MODE`, `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`) — all default safe (handoff/lifecycle OFF, limited-test-mode ON). Frontend adds a "Call customer" button to the AI panel + new TS types (`WhatsAppHandoffToCall`, `WhatsAppLifecycleEvent`, `ClaimVaultCoverageReport`) + four new api methods. Hard stops still in force: no medical-emergency calls, no freeform claims, no CAIO send, no shipment from chat, no campaigns, no refunds, no ad-budget execution. **498 backend tests + 13 frontend tests, all green.**

Earlier (kept verbatim): Phase 5C shipped the WhatsApp AI Chat Sales Agent. Phase 5C ships the **WhatsApp AI Chat Sales Agent**: new `apps.whatsapp.ai_orchestration` runs on every inbound (Celery `run_whatsapp_ai_agent_for_conversation`) with deterministic language detection (Hindi / Hinglish / English in `apps.whatsapp.language`), locked Hindi greeting via approved UTILITY template, OpenAI dispatch through `apps.integrations.ai.dispatch`, strict JSON schema validator (`apps.whatsapp.ai_schema`), Claim Vault grounding, blocked-phrase filter, discount discipline + 50% total cap (`apps.whatsapp.discount_policy`), order booking from chat via `apps.orders.services.create_order` (+ ₹499 advance link via `apps.payments.services.create_payment_link` — uses `FIXED_ADVANCE_AMOUNT_INR` from Phase 3E), and auto-send rate gates (env-driven `WHATSAPP_AI_AUTO_REPLY_ENABLED` / `WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD` / `WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR` / `WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY`). Six endpoints — `GET /api/whatsapp/ai/status/`, `PATCH /api/whatsapp/conversations/{id}/ai-mode/`, `POST /api/whatsapp/conversations/{id}/{run-ai,handoff,resume-ai}/`, `GET /api/whatsapp/conversations/{id}/ai-runs/`. 18 audit kinds (`whatsapp.ai.run_started/completed/failed/reply_auto_sent/reply_blocked/suggestion_stored/greeting_sent/greeting_blocked/language_detected/category_detected/address_updated/order_draft_created/order_booked/payment_link_created/handoff_required/discount_objection_handled/discount_offered/discount_blocked`).

Earlier (kept verbatim): Phase 5B shipped the Inbound WhatsApp Inbox + Customer 360 Timeline. Phase 5B ships the **Inbound WhatsApp Inbox + Customer 360 Timeline**: new `WhatsAppInternalNote` model, six new endpoints (`GET /api/whatsapp/inbox/`, `PATCH /api/whatsapp/conversations/{id}/`, `POST /api/whatsapp/conversations/{id}/mark-read/`, `GET + POST /api/whatsapp/conversations/{id}/notes/`, `POST /api/whatsapp/conversations/{id}/send-template/` routing through Phase 5A's `queue_template_message`, `GET /api/whatsapp/customers/{customer_id}/timeline/`), six new audit kinds (`whatsapp.conversation.opened/updated/assigned/read`, `whatsapp.internal_note.created`, `whatsapp.template.manual_send_requested`), conversation list filters (`unread=true`, `assignedTo`, `q`), conversation serializer extended with `customerName / customerPhone / assignedToUsername` + message serializer with `templateName`. Frontend ships a three-pane `/whatsapp-inbox` page (filters / conversation list / thread + internal notes + manual template send modal + AI-suggestions-disabled placeholder) with live refresh via Phase 4A `connectAuditEvents` filtered on `whatsapp.*`, plus a Customer 360 WhatsApp tab. **Manual-only — AI auto-reply / chat-to-call handoff / rescue discount / order booking from chat are all deferred to Phase 5C–5F.** Operations users send only approved templates; backend gates (consent + approved template + Claim Vault + approval matrix + CAIO hard stop + idempotency) remain final. **434 backend tests + 13 frontend tests, all green.**

**Production is LIVE at <https://ai.nirogidhara.com>.** Operational reference: `nd.md` §17 + `docs/DEPLOYMENT_VPS.md`. VPS folder `/opt/nirogidhara-command`, host port `18020 → 80`, six namespaced containers, host Ubuntu Nginx + Certbot terminate TLS. The first VPS deploy surfaced four issues that were patched directly on the server and are now committed to `main` (Phase 5B-Deploy hotfix sync — see `nd.md` §17 closing block): repo-root build context for the backend image, explicit `deploy/backend/entrypoint.sh` copy + CRLF normalisation + `chmod +x` in the Dockerfile, no-args default in the entrypoint (`set -e` only, defaults to `daphne ...` on empty `$@`), and the duplicate-index `calls_calltranscriptline_call_id_*` recovery procedure documented in both `nd.md` §17 and `docs/DEPLOYMENT_VPS.md` §8.5. **Do not change container / volume / network names or the `18020` host port** — host Nginx + SSL cert paths assume that exact shape. **Never commit `.env.production`** (gitignored).

**Phase 5B-Deploy** added the production Docker scaffold for `ai.nirogidhara.com` on Hostinger VPS: `docker-compose.prod.yml` (six isolated containers — `nirogidhara-db` Postgres + `nirogidhara-redis` + `nirogidhara-backend` Daphne ASGI + `nirogidhara-worker` Celery + `nirogidhara-beat` Celery beat + `nirogidhara-nginx` serving the Vite SPA), `backend/Dockerfile` (slim Python 3.11 + tini + non-root user; entrypoint waits for Postgres/Redis, runs migrate + collectstatic, then exec's the supplied command), `frontend/Dockerfile` (multi-stage node 20 → nginx alpine; bakes `VITE_API_BASE_URL=/api` + `VITE_WS_BASE_URL=""` so production stays same-origin), `deploy/nginx/nirogidhara.conf` (proxies `/api/`, `/admin/`, `/ws/` with WebSocket upgrade headers; serves SPA with hashed-asset caching + `index.html` no-cache), `.env.production.example` covering every settings env var, `docs/DEPLOYMENT_VPS.md` runbook (DNS, TLS via Certbot, smoke tests, backups, security checklist, resource-safety notes for the shared VPS). Host port `18020 → 80` to avoid conflict with Postzyo / OpenClaw. CSRF_TRUSTED_ORIGINS is now env-driven. New runtime deps: `psycopg[binary]`, `requests`. **Mock-mode defaults stay locked** — all integrations (WhatsApp / Razorpay / Delhivery / Vapi / Meta / AI provider) ship with `*_MODE=mock` / `disabled` so the first deploy never sends a live message. Existing 434 backend + 13 frontend tests stay green.

Earlier phases unchanged: Phase 5A shipped the WhatsApp Live Sender Foundation (`apps.whatsapp` Django app with 8 models, three providers — `mock` default + `meta_cloud` Nirogidhara-built Graph client + `baileys_dev` dev-only stub, service layer gating consent + approved template + Claim Vault + approval matrix + CAIO + idempotency, Celery `send_whatsapp_message` task with autoretry/backoff/jitter/max_retries=5, signed webhook at `/api/webhooks/whatsapp/meta/`, 9 read + 4 write API endpoints under `/api/whatsapp/`, `sync_whatsapp_templates` management command, frontend Settings → WABA section + read-only `/whatsapp-templates` page). All earlier phases (CRM, write APIs, four gateway integrations, AgentRun + 7 per-agent runtimes, Celery beat at 09:00 + 18:00 IST, OpenAI → Anthropic fallback, model-wise USD cost tracking, sandbox + versioned prompts + per-agent USD budgets, Scheduler + Governance pages, Phase 3E business config — catalog + discount policy 10/20% bands + ₹499 fixed advance + reward/penalty scoring + approval matrix, Phase 4B reward/penalty engine + CEO AI net accountability, Phase 4C approval-matrix middleware, Phase 4D Approved Action Execution Layer, Phase 4A real-time AuditEvent WebSockets, Phase 4E expanded execution registry — discount.up_to_10 / discount.11_to_20 / ai.sandbox.disable) remain green. **Phase 5A-0 + 5A-1** are the doc-only WhatsApp design phases; the integration plan in `docs/WHATSAPP_INTEGRATION_PLAN.md` (sections A–R + S–GG) drove the Phase 5A + 5B implementations. Next: Phase 5C WhatsApp AI Chat Sales Agent.

GitHub: https://github.com/prarit0097/Nirogidhara-AI-Command-Center

---

## 1. Working agreement (binding rule)

**Every meaningful change to this project MUST be followed by:**

1. **Update `nd.md`** — adjust the relevant section (TL;DR §0, what's done so far §8, phase roadmap §11, or whichever is impacted) so the project handoff stays the source of truth.
2. **Update `AGENTS.md`** — if a convention, hard stop, or "where things live" pointer changed, reflect it here so other AI tools that auto-load `AGENTS.md` pick it up.
3. **Run the full verification suite** before committing:
   - `cd backend && python manage.py makemigrations --check --dry-run` — must report `No changes detected`. Fixed Phase 5E hotfix: hand-rolled migration index names produced auto-suffix drift; `makemigrations --check` now blocks the commit if any model field, index, or constraint diverges from the migration history.
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
python -m pytest -q                    # 619 tests today

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
| Production Docker compose | `docker-compose.prod.yml` (project name `nirogidhara-command`, six isolated containers, host port 18020) |
| Production backend image | `backend/Dockerfile` + `deploy/backend/entrypoint.sh` (waits for Postgres/Redis, runs migrate + collectstatic) |
| Production frontend image | `frontend/Dockerfile` (multi-stage node → nginx alpine; bakes same-origin VITE_*) |
| Production Nginx config | `deploy/nginx/nirogidhara.conf` (SPA + `/api/` + `/admin/` + `/ws/` with WebSocket upgrade) |
| Production env example | `.env.production.example` (mock-mode defaults locked) |
| Production deploy runbook | `docs/DEPLOYMENT_VPS.md` (DNS, TLS, smoke tests, backups, shared-VPS resource notes) |
| Phase 5C AI orchestration | `backend/apps/whatsapp/ai_orchestration.py` (`run_whatsapp_ai_agent`) |
| Phase 5C language detection | `backend/apps/whatsapp/language.py` |
| Phase 5C JSON schema + blocked phrases | `backend/apps/whatsapp/ai_schema.py` |
| Phase 5C discount cap | `backend/apps/whatsapp/discount_policy.py` (`evaluate_whatsapp_discount`, `validate_total_discount_cap`) |
| Phase 5C order booking from chat | `backend/apps/whatsapp/order_booking.py` (`book_order_from_decision`) |
| Phase 5C Celery task | `backend/apps/whatsapp/tasks.py` (`run_whatsapp_ai_agent_for_conversation`) |
| Phase 5C AI endpoints | `backend/apps/whatsapp/views.py` (`WhatsAppAiStatusView`, `WhatsAppConversationAiModeView`, `WhatsAppConversationRunAiView`, `WhatsAppConversationAiRunsView`, `WhatsAppConversationHandoffView`, `WhatsAppConversationResumeAiView`) |
| Phase 5C frontend AI panel | `frontend/src/pages/WhatsAppInbox.tsx` (`AiAgentPanel`) + `frontend/src/services/api.ts` (Phase 5C section) |
| Phase 5D Claim Vault coverage | `backend/apps/compliance/coverage.py` + `backend/apps/compliance/management/commands/check_claim_vault_coverage.py` |
| Phase 5D Claim coverage endpoint | `backend/apps/compliance/views.py` (`ClaimVaultCoverageView`) at `/api/compliance/claim-coverage/` |
| Phase 5D handoff model | `backend/apps/whatsapp/models.py` (`WhatsAppHandoffToCall`) |
| Phase 5D Vapi handoff service | `backend/apps/whatsapp/call_handoff.py` (`trigger_vapi_call_from_whatsapp`) |
| Phase 5D operator handoff endpoint | `backend/apps/whatsapp/views.py` (`WhatsAppConversationHandoffToCallView`) at `/api/whatsapp/conversations/{id}/handoff-to-call/` |
| Phase 5D lifecycle automation | `backend/apps/whatsapp/lifecycle.py` (`queue_lifecycle_message`, `LIFECYCLE_TRIGGERS`) |
| Phase 5D lifecycle event model | `backend/apps/whatsapp/models.py` (`WhatsAppLifecycleEvent`) |
| Phase 5D signal receivers | `backend/apps/whatsapp/signals.py` (Order/Payment/Shipment post_save) |
| Phase 5D lifecycle Celery task | `backend/apps/whatsapp/tasks.py` (`send_whatsapp_lifecycle_message_task`) |
| Phase 5D lifecycle list endpoint | `backend/apps/whatsapp/views.py` (`WhatsAppLifecycleEventsListView`) at `/api/whatsapp/lifecycle-events/` |
| Phase 5D AI booked → confirmation | `backend/apps/whatsapp/order_booking.py` (calls `apps.orders.services.move_to_confirmation` post-create) |
| Phase 5E rescue discount engine | `backend/apps/orders/rescue_discount.py` (`calculate_rescue_discount_offer`, `create_rescue_discount_offer`, `accept_rescue_discount_offer`, `reject_rescue_discount_offer`, `validate_total_discount_cap`) |
| Phase 5E DiscountOfferLog model | `backend/apps/orders/models.py` (`DiscountOfferLog`) + migration `0003_phase5e_discount_offer_log` |
| Phase 5E discount endpoints | `backend/apps/orders/views.py` (`OrderViewSet.list_discount_offers / create_rescue_offer / accept_discount_offer / reject_discount_offer`) at `/api/orders/{id}/discount-offers/...` |
| Phase 5E lifecycle rescue + Day-20 actions | `backend/apps/whatsapp/lifecycle.py` (`LIFECYCLE_TRIGGERS` extended, `RESCUE_DISCOUNT_ACTIONS`, `REORDER_DAY20_ACTION`) |
| Phase 5E Day-20 reorder sweep | `backend/apps/whatsapp/reorder.py` (`run_day20_reorder_sweep`) + `python manage.py run_reorder_day20_sweep` + `apps.whatsapp.tasks.run_reorder_day20_sweep_task` |
| Phase 5E Day-20 admin endpoints | `backend/apps/whatsapp/views.py` (`WhatsAppReorderDay20StatusView`, `WhatsAppReorderDay20RunView`) at `/api/whatsapp/reorder/day20/{status,run}/` |
| Phase 5E default Claim Vault seed | `python manage.py seed_default_claims [--reset-demo] [--json]` |
| Phase 5E rescue / reorder template names | `backend/apps/whatsapp/template_registry.py` (`whatsapp.{confirmation,delivery,rto}_rescue_discount`, `whatsapp.reorder_day20_reminder`) |
| Phase 5E approval matrix rows | `backend/apps/ai_governance/approval_matrix.py` (`discount.rescue.ceo_review`, `discount.above_safe_auto_band`, four rescue / Day-20 templates) |
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
2. Read the relevant section of [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md) — strategic mirror of `nd.md`. The v1.0 PDF is historical only.
3. Run the health check: `pytest -q`, `npm test`, `npm run lint`, `npm run build`.
4. **Ask Prarit before doing anything that touches**: ad budgets, real medical claims, payment flows in live mode, customer messaging, kill-switch states, or production data.

The blueprint wins. Every decision in this codebase traces back to a section there.
