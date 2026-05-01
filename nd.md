# Nirogidhara AI Command Center — Project Handoff (`nd.md`)

> Read this file end-to-end before touching the repo.
> If you are a coding agent: this is your single source of truth.
> Strategic mirror: [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md) — Master Blueprint v2.0 (supersedes the v1.0 PDF, which is historical reference only). If `nd.md` and the blueprint disagree on any detail, **`nd.md` wins** and the blueprint must be updated to match.

---

## 0. TL;DR (60-second read)

- **What it is:** A full-stack AI Business Operating System for an Ayurvedic medicine D2C company (Nirogidhara Private Limited).
- **Owner / Director:** Prarit Sidana — final authority for high-risk decisions.
- **Stack:** React 18 + Vite + TypeScript (frontend) ↔ Django 5 + DRF (backend), JWT auth, SQLite (dev) / Postgres (prod-ready).
- **Repo layout:** monorepo — `frontend/`, `backend/`, `docs/`.
- **Status today (Phase 1 + 2A + 2B + 2C + 2D + 2E + 3A + 3B + 3C + 3D + 3E + 4A + 4B + 4C + 4D + 4E + 5A-0 + 5A-1 + 5A + 5B + 5C + 5D + 5E + 5E-Hotfix + 5E-Hotfix-2 + 5E-Smoke done):** **16 Django apps** scaffolded (Phase 5A adds `apps.whatsapp`, Phase 5B adds the `WhatsAppInternalNote` model + 6 inbox endpoints inside it), the full Phase 1–4E surface from earlier sessions, plus the **Phase 5A WhatsApp Live Sender Foundation**: 8 new models (`WhatsAppConnection` / `Template` / `Consent` / `Conversation` / `Message` / `MessageAttachment` / `MessageStatusEvent` / `WebhookEvent` / `SendLog`), three providers (`mock` default for tests, `meta_cloud` Nirogidhara-built Graph client, `baileys_dev` dev-only stub that refuses to load when `DEBUG=False AND WHATSAPP_DEV_PROVIDER_ENABLED!=true`), service layer (`queue_template_message` + `send_queued_message`) gating consent + approved-template + Claim Vault + approval matrix + CAIO hard stop + idempotency, Celery `send_whatsapp_message` task with `autoretry_for=ProviderError, retry_backoff=True, retry_jitter=True, max_retries=5`, signed Meta webhook at `/api/webhooks/whatsapp/meta/` (HMAC-SHA256 + replay-window + provider-event-id idempotency + GET handshake), 9 read + 4 write API endpoints under `/api/whatsapp/`, `python manage.py sync_whatsapp_templates` command, frontend Settings → WABA section + read-only `/whatsapp-templates` page + sidebar entry. **Failed sends never mutate Order/Payment/Shipment.** Earlier-phase surface unchanged: Master Event Ledger via signals + explicit service writes, JWT auth + role-based permissions, order state machine, all four gateway integrations with three-mode (mock/test/live) adapters + HMAC-verified webhooks + idempotency, AgentRun foundation + 7 per-agent runtime services + Celery beat at 09:00 + 18:00 IST + provider fallback (OpenAI → Anthropic) + model-wise USD cost tracking + Phase 3D sandbox toggle + versioned prompts (rollback) + per-agent USD budget guards + Governance page + Phase 3E product catalog admin + discount policy (10/20% bands) + ₹499 fixed advance + reward/penalty scoring formula + approval matrix policy + Phase 4B reward/penalty engine (AI agents only, CEO AI net accountability) + Rewards page agent leaderboard + Phase 4C approval-matrix middleware enforcement + Phase 4D Approved Action Execution Layer + Phase 4A Django Channels live `/ws/audit/events/` WebSocket + Phase 4E execution registry expansion (discount.up_to_10 / discount.11_to_20 / ai.sandbox.disable). Phase 5B added the **Inbound WhatsApp Inbox + Customer 360 Timeline**: new `WhatsAppInternalNote` model, six new endpoints (`GET /api/whatsapp/inbox/`, `PATCH /api/whatsapp/conversations/{id}/`, `POST /api/whatsapp/conversations/{id}/{mark-read,send-template}/`, `GET + POST /api/whatsapp/conversations/{id}/notes/`, `GET /api/whatsapp/customers/{customer_id}/timeline/`), six new audit kinds (`whatsapp.conversation.opened/updated/assigned/read`, `whatsapp.internal_note.created`, `whatsapp.template.manual_send_requested`), conversation list filters (`unread=true / assignedTo / q`), conversation serializer extended with `customerName / customerPhone / assignedToUsername` + message serializer with `templateName`. Per-conversation send-template routes through Phase 5A's `queue_template_message`, so consent + approved-template + Claim Vault + approval matrix + CAIO + idempotency gates all stay in force. Frontend wired with automatic mock fallback (21 pages now — WhatsApp Inbox + WhatsApp Templates). The new `/whatsapp-inbox` page is a three-pane layout (filters / conversation list / thread + internal notes + manual template send modal + AI-suggestions-disabled placeholder) with live refresh via Phase 4A `connectAuditEvents` filtered on `whatsapp.*`. Customer 360 grew a WhatsApp tab listing the customer's WhatsApp timeline + AI-disabled placeholder + a one-click link to the inbox. **434 backend tests + 13 frontend tests** all green.
- **Phase 5C — WhatsApp AI Chat Sales Agent shipped:** `apps.whatsapp.ai_orchestration.run_whatsapp_ai_agent` runs on every inbound (Celery `run_whatsapp_ai_agent_for_conversation`); deterministic Hindi/Hinglish/English language detection (`apps.whatsapp.language`); locked Hindi greeting via approved UTILITY template; OpenAI dispatch through `apps.integrations.ai.dispatch`; strict JSON schema validator (`apps.whatsapp.ai_schema`) with blocked-phrase filter; Claim Vault grounding; discount discipline (`apps.whatsapp.discount_policy`) — never upfront, 2–3 push minimum, 50% total cap; order booking from chat via `apps.orders.services.create_order` + ₹499 advance link via `apps.payments.services.create_payment_link`; auto-send rate gates (env-driven). Six new endpoints under `/api/whatsapp/ai/...` and per-conversation `ai-mode / run-ai / ai-runs / handoff / resume-ai`. 18 new audit kinds. Frontend AI Chat Agent panel inside the inbox (mode toggle / language + category / confidence / Run AI / Handoff / Resume) + AI Auto badge + Customer 360 status. **Auto-reply defaults to OFF** (`WHATSAPP_AI_AUTO_REPLY_ENABLED=false`); production flips it true after verification. **35 new tests; 469 backend + 13 frontend, all green.** Hard stops still in force: no medical-emergency replies, no freeform claims, no CAIO send, no shipment from chat.
- **Production deployment scaffold added (Phase 5B-Deploy):** `docker-compose.prod.yml` (six isolated containers — `nirogidhara-db` Postgres + `nirogidhara-redis` + `nirogidhara-backend` Daphne ASGI + `nirogidhara-worker` Celery + `nirogidhara-beat` + `nirogidhara-nginx` serving the Vite SPA), `backend/Dockerfile` + `frontend/Dockerfile`, `deploy/nginx/nirogidhara.conf` (proxies `/api/`, `/admin/`, `/ws/` with WebSocket upgrade), `.env.production.example`, full deploy runbook at `docs/DEPLOYMENT_VPS.md`. Target domain `ai.nirogidhara.com`, host port `18020:80` to avoid colliding with Postzyo / OpenClaw on the same VPS. All `*_MODE` env vars default to `mock` so the first deploy never sends a live message. CSRF_TRUSTED_ORIGINS now env-driven.
- **Phase 5D — Chat-to-Call Handoff + Lifecycle Automation shipped:** new `apps.whatsapp.call_handoff.trigger_vapi_call_from_whatsapp` is the SINGLE entry that may dial Vapi from a WhatsApp conversation; routes through the existing `apps.calls.services.trigger_call_for_lead` Vapi service (never the adapter directly). Idempotent on `(conversation, inbound_message, reason)` via the new `WhatsAppHandoffToCall` model. Safety reasons (medical_emergency / side_effect_complaint / legal_threat / refund_threat) record a `skipped` row for human/doctor pickup — never auto-dial a sales call. Phase 5C's AI orchestrator now opportunistically triggers Vapi for safe handoff reasons (`customer_requested_call`, `low_confidence_repeated`, `ai_handoff_requested`) when `WHATSAPP_CALL_HANDOFF_ENABLED=true`. Operator manual trigger at `POST /api/whatsapp/conversations/{id}/handoff-to-call/` (operations+). AI-booked orders now move directly to the confirmation queue from chat — `book_order_from_decision` calls `apps.orders.services.move_to_confirmation` after order create; failure flips `confirmationMoveFailed=true` in conversation metadata but never loses the order. New `apps.whatsapp.lifecycle.queue_lifecycle_message` + `apps.whatsapp.signals` listen on Order/Payment/Shipment `post_save` and dispatch approved templates (`whatsapp.confirmation_reminder`, `whatsapp.payment_reminder`, `whatsapp.delivery_reminder`, `whatsapp.usage_explanation`, `whatsapp.rto_rescue`) through Phase 5A's `queue_template_message`; idempotent on `lifecycle:{action}:{type}:{id}:{event}`; `usage_explanation` fails closed when Phase 5D Claim Vault coverage shows `missing` / `weak`. New Claim Vault coverage audit: `apps.compliance.coverage` + `python manage.py check_claim_vault_coverage` (exits 1 on missing) + admin-only `GET /api/compliance/claim-coverage/`. Three new endpoints (handoff-to-call, handoffs list, lifecycle-events list), eleven new audit kinds (`whatsapp.handoff.*` + `whatsapp.lifecycle.*` + `whatsapp.ai.order_moved_to_confirmation` + `compliance.claim_coverage.checked`), four new env vars (all default safe — handoff/lifecycle OFF, limited-test-mode ON). Frontend adds a "Call customer" button to the AI Chat panel + `WhatsAppHandoffToCall` / `WhatsAppLifecycleEvent` / `ClaimVaultCoverageReport` types + four new `api` methods. Hard stops still in force: no shipment from chat, no campaigns, no refunds, no ad-budget execution. **29 new backend tests; 498 backend + 13 frontend, all green.**
- **Phase 5E — Rescue Discount + Day-20 Reorder + Default Claims shipped:** new `apps.orders.rescue_discount` is the single source of truth for AI rescue discount math — locked **50% absolute cumulative cap**, per-stage ladder (confirmation 5/10/15, delivery 5/10, RTO 10/15/20 + high-risk step-up, reorder 5), conservative-first selection, automatic clamp to `cap_remaining`. Every offer attempt writes a `DiscountOfferLog` row (offered / accepted / rejected / blocked / skipped / `needs_ceo_review`). Anything above the 0–10 auto band, above the 50% cap, or with no headroom auto-mints an `ApprovalRequest` via two new matrix rows (`discount.rescue.ceo_review`, `discount.above_safe_auto_band`). Customer acceptance applies via `apps.orders.services.apply_order_discount` only; cap is re-validated at accept time, over-cap flips status to `needs_ceo_review` rather than mutating the order. Phase 5C orchestrator now also writes `DiscountOfferLog` rows when the WhatsApp AI proposes a discount, regardless of channel. New lifecycle triggers (`whatsapp.confirmation_rescue_discount`, `whatsapp.delivery_rescue_discount`, `whatsapp.rto_rescue_discount`, `whatsapp.reorder_day20_reminder`) flow through Phase 5A's `queue_template_message`; consent + Claim Vault + matrix + CAIO + idempotency unchanged. Day-20 reorder cadence: `apps.whatsapp.reorder.run_day20_reorder_sweep` covers delivered orders 20–27 days old via `python manage.py run_reorder_day20_sweep` + Celery `run_reorder_day20_sweep_task`. Default Claim Vault seed: `python manage.py seed_default_claims [--reset-demo] [--json]` (idempotent, demo-only) covers eight current categories with conservative non-cure / non-guarantee phrases; demo rows are flagged `version="demo-v1"` and surface in coverage as `risk=demo_ok`. **Defaults stay SAFE** — `WHATSAPP_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_REORDER_DAY20_ENABLED=false`, `DEFAULT_CLAIMS_SEED_DEMO_ONLY=true`. Five new endpoints. Twelve new audit kinds. Frontend adds a Rescue Discount cap card on the AI panel + six new TS types + six new `api` methods. **38 new backend tests; 536 backend + 13 frontend, all green.** Hard stops: never above 50% cumulative; never proactive on reorder Day 20; CAIO never originates an offer; no shipment from chat / no campaigns / no refunds / no ad-budget execution.
- **Phase 5E-Hotfix — migration drift sync shipped:** the VPS first-deploy after commit `8374863` reported "models in app(s) 'orders', 'whatsapp' have changes that are not yet reflected in a migration" because Phase 5D / 5E migrations hand-rolled short index names (`orders_disc_order_i_dol_idx`, `whatsapp_wh_convers_h0_idx`, …) but Django's auto-namer wants the suffix-hash form (`orders_disc_order_i_e49f63_idx`, `whatsapp_wh_convers_ae1708_idx`, …). Hotfix adds two `RenameIndex` migrations — `apps/orders/migrations/0004_rename_orders_disc_order_i_dol_idx_orders_disc_order_i_e49f63_idx_and_more.py` and `apps/whatsapp/migrations/0004_rename_whatsapp_wh_convers_h0_idx_whatsapp_wh_convers_ae1708_idx_and_more.py` — that rename four DiscountOfferLog indexes + five WhatsAppHandoffToCall / WhatsAppLifecycleEvent indexes to the auto-namer form. Pure metadata; no schema rewrite. **Working agreement now requires `python manage.py makemigrations --check --dry-run` to report "No changes detected" before every commit.** VPS deploy after pull must run `python manage.py migrate && python manage.py makemigrations --check --dry-run`. **536 backend tests stay green; 13 frontend stay green.**
- **Phase 5E-Hotfix-2 — Claim Vault seed strengthening shipped:** the prod VPS coverage report flagged Blood Purification (`approved=1, usage=no`) and Lungs Detox (`approved=2, usage=no`) as `weak` after the Phase 5E demo seed ran. Hotfix-2 merges four universal safe usage-guidance phrases (use as directed on the label / hydration + balanced diet / consult doctor for serious cases / discontinue on adverse reaction) into every demo entry; widens `USAGE_HINT_KEYWORDS` so the coverage detector recognises "directed", "label", "practitioner", "hydration", "balanced diet", "routine", "discontinue", "professional advice", "unusual reaction"; bumps the demo seed marker to `version="demo-v2"`. After running `python manage.py seed_default_claims --reset-demo` on the VPS, all eight categories report `risk=demo_ok` (not `weak`). Idempotent — running the seed twice does not duplicate phrases. Real admin / doctor-approved claims are still never overwritten. Production still needs real doctor-approved final claims before full live rollout; automation flags remain OFF (`WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`, `WHATSAPP_AI_AUTO_REPLY_ENABLED`, `WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`) until controlled mock + OpenAI testing passes. **14 new tests; 550 backend + 13 frontend, all green.**
- **Phase 5F-Gate Auto-Reply Monitoring Dashboard shipped:** the previous phase's fix landed on the VPS and the **Limited Auto-Reply Soak = FULL PASS** (real WhatsApp inbound from the allowed test number → orchestrator dispatched the deterministic Claim-Vault-grounded reply → phone received and read it; `replyAutoSentCount=1`, `autoReplyFlagPathUsedCount=1`, `deterministicBuilderUsedCount=1`, `unexpectedNonAllowedSendsCount=0`, `Order/Payment/Shipment/DiscountOfferLog` mutations = 0). After the soak Director rolled back to safe OFF state (`WHATSAPP_AI_AUTO_REPLY_ENABLED=false`); the gate inspector reports `nextAction=ready_to_enable_limited_auto_reply_flag` again. Scenario matrix passed across normal product info, discount objection, side-effect complaint blocked, legal/refund threat blocked, human-request handoff (correct typed reason), unknown category fail closed, cure/guarantee unsafe claim blocked. This phase ships the **read-only command-center surface** so Director can see all of that without running CLI commands. **New `apps.whatsapp.dashboard` selector module** is the single source of truth: seven composable read-only functions (`get_auto_reply_gate_summary`, `get_recent_auto_reply_activity(hours)`, `get_internal_cohort_summary`, `get_recent_whatsapp_audit_events(hours, limit)`, `get_whatsapp_mutation_safety_summary(hours)`, `get_unexpected_outbound_summary(hours)`, `get_whatsapp_monitoring_dashboard(hours)`). Every function is strictly read-only — no DB writes, no audit rows, no provider calls, no LLM dispatch — and phones are masked to last-4 (`+91*****99001` shape). Audit payloads run through `_safe_audit_payload` which drops `token` / `access_token` / `verify_token` / `app_secret` / `META_WA_*` keys before returning, defence-in-depth even though the orchestrator already masks. The two existing management commands (`inspect_whatsapp_auto_reply_gate`, `inspect_recent_whatsapp_auto_reply_activity`) now delegate to these selectors so the CLI and the dashboard share one source of truth — there is exactly ONE place the gate readiness / activity / cohort / mutation logic lives. **Seven new admin-only DRF endpoints** under `/api/whatsapp/monitoring/`: `overview/` returns the combined dashboard with a derived top-level `status` ∈ {`safe_off`, `limited_auto_reply_on`, `needs_attention`, `danger`}; `gate/`, `activity/?hours=N`, `cohort/`, `audit/?hours=N&limit=K`, `mutation-safety/?hours=N`, `unexpected-outbound/?hours=N` for finer-grained polling. Permission class `_AdminMonitoringPermission` in `apps.whatsapp.monitoring_views` is admin / director / superuser only — view-level even on GET, matching the existing `WhatsAppProviderStatusView` pattern. All endpoints are strictly read-only: POST/PATCH/DELETE return 405 (asserted in tests for all seven). The deployed app already exposes `/api/whatsapp/...`; the monitoring routes are scoped under `monitoring/` rather than introducing a parallel `/api/v1/` namespace so the existing api/url conventions stay clean. **New frontend page at `/whatsapp-monitoring`** (sidebar group "Messaging", icon `ShieldCheck`) renders: status badge ({Safe OFF / Limited Auto-Reply ON / Needs attention / Danger}), gate status cards (Provider / Limited test mode / Auto-reply enabled / Allowed list size / WABA active / Campaigns locked / Final-send guard / Consent + Claim Vault), broad-automation flag pills (call handoff / lifecycle / rescue / RTO / reorder / campaigns — all rendered as `OFF / locked` when healthy), activity metric cards (inbound / outbound / auto replies sent / deterministic builder / objection replies / blocked / delivered / read / guard blocks / unexpected non-allowed sends), mutation safety section (orders / payments / shipments / discount logs / lifecycle events / handoff events with a green confirmation when all zero), internal cohort table (masked phone / suffix / customer found / consent state / latest inbound + outbound / status / ready), recent audit timeline (kind / tone / text / IDs / phone suffix / fallback flag), backend `nextAction` panel rendered as a read-only string. Auto-refreshes every 30 seconds + an explicit Refresh button. **No send buttons. No automation enable/disable controls. No flag-flip controls. No business-data mutation hooks of any kind.** Six new TypeScript types (`WhatsAppMonitoringStatus / Gate / Activity / Cohort / MutationSafety / UnexpectedOutbound / AuditResponse / Overview`) and seven new `api` methods with deterministic mock fallback so the dashboard renders without a backend. **Hard rules preserved**: dashboard is read-only end-to-end (asserted via 405-on-POST checks for every endpoint); cohort selector NEVER exposes full E.164 (asserted in tests; the operator-only `--show-full-numbers` CLI flag is intentionally not exposed via the API surface); audit selector NEVER returns tokens / verify token / app secret (asserted in tests); unauthenticated access blocked; viewer / operations roles blocked; admin / director / superuser only; broad-automation flags (`callHandoff / lifecycle / rescue / RTO / reorder`) remain LOCKED OFF; campaigns remain LOCKED. **22 new backend tests + 6 new frontend tests; 869 backend + 19 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.** Rollback to `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` remains the default safe state between approved tests; the dashboard is what tells Director when the state has drifted.
- **Phase 5F-Gate Real Inbound Deterministic Fallback Fix shipped:** the previous phase (Limited Auto-Reply Flag Plan) handed the operator gate inspectors + soak monitors and Director flipped `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` for a controlled real-inbound test. The first real inbound from the allowed test number (suffix `9990`) — "Namaste. Mujhe weight management product ke price aur capsule quantity ke baare me bataye." stored as `WAM-100059` with a real Meta `provider_message_id` — was blocked safely with `claim_vault_not_used` even though backend grounding was fully present (`category=weight-management`, `normalized_claim_product=Weight Management`, `claim_row_count=1`, `approved_claim_count=3`, `confidence=0.9`, `replyAutoSentCount=0`, `autoReplyFlagPathUsedCount=0`, `unexpectedNonAllowedSendsCount=0`, `Order/Payment/Shipment/DiscountOfferLog` mutations = 0). Director rolled back the flag (`WHATSAPP_AI_AUTO_REPLY_ENABLED=false`) and asked for a fix. **Diagnosis confirmed:** (a) the deterministic Claim-Vault-grounded fallback existed only inside the controlled-CLI command (`run_controlled_ai_auto_reply_test`) — it ran AFTER the orchestrator returned. The real-inbound webhook path (`run_whatsapp_ai_agent_for_conversation` → `run_whatsapp_ai_agent`) never benefited; it just emitted `whatsapp.ai.handoff_required · claim_vault_not_used` and stored a suggestion. (b) The earlier failed-block audit referenced previous scenario-test context because the LLM was looking at conversation history that included synthetic side-effect / legal / unsafe scenario inbounds from earlier matrix tests — biasing its safety classification on a clean current query. **Fix shipped here:** (1) the deterministic grounded fallback is now extracted into a shared `apps.whatsapp.ai_orchestration._attempt_deterministic_grounded_fallback` helper and wired into the orchestrator at every soft non-safety blocker site (`claim_vault_not_used`, `low_confidence`, `ai_handoff_requested`, `no_action`). When auto-reply is enabled (env flag OR `force_auto_reply=True`) AND the inbound is a normal product-info inquiry AND the category maps to a `Claim.product` AND at least one approved phrase exists AND no live safety flag is set on the LATEST inbound, the orchestrator builds the deterministic Hinglish reply (literal approved phrase + ₹3000/30-capsules/₹499 advance + conservative usage + doctor escalation) and dispatches it through `services.send_freeform_text_message` — every existing gate (limited-mode allow-list, consent, CAIO, idempotency) stays in force. (2) Discount/price-objection inbounds get the existing `build_objection_aware_reply` ahead of the standard grounded reply (audit `whatsapp.ai.objection_reply_used` + `outcome.notes` carries `deterministic_objection_fallback_used`) so the real-inbound path mirrors the CLI's priority order. (3) The orchestrator flips `decision.safety["claimVaultUsed"]=True` after a successful fallback (truthful — the validator confirmed the reply text literally embeds an approved phrase) so downstream readers see the corrected flag. (4) **Latest-inbound safety isolation hardened:** the `whatsapp.ai.safety_downgraded` audit payload now carries `latest_inbound_message_id`, `latest_inbound_safety_flags`, `history_safety_flags`, `history_safety_ignored_for_current_safe_query=true`. Real safety phrases in the LATEST inbound (medicine khane ke baad ulta asar / chest pain / consumer forum / lawyer / refund) still block exactly as before; the safety stack runs first, the fallback never sees them. (5) Audit emits enriched: `whatsapp.ai.deterministic_grounded_reply_used` / `whatsapp.ai.objection_reply_used` carry `phone_suffix` last-4 only, `category`, `normalized_claim_product`, `claim_row_count`, `approved_claim_count`, `fallback_reason`, `final_reply_source`, `outbound_message_id`, `inbound_message_id`, `used_approved_phrases`, `triggered_by`, `force_auto_reply`, `trigger_path="real_inbound_webhook"`. `whatsapp.ai.auto_reply_flag_path_used` gains `deterministic_fallback_used` / `final_reply_source` / `inbound_message_id` / `outbound_message_id` / `normalized_claim_product` / `claim_vault_used`. (6) The CLI controlled-test command (`run_controlled_ai_auto_reply_test`) detects the orchestrator-driven fallback via `outcome.notes` (`deterministic_grounded_fallback_used` / `deterministic_objection_fallback_used`) and propagates `finalReplySource` / `deterministicFallbackUsed` / `claimVaultUsed=true` / `fallbackReason` into its JSON report; validation now runs against the actual outbound body (not just the LLM's `replyText`) so deterministic-fallback runs see truthful `containsApprovedClaim` / `blockedPhraseFree` results. **Hard rules preserved**: zero mutation of `Order` / `Payment` / `Shipment` / `DiscountOfferLog` from any fallback path (asserted with before/after counts in 13 new backend tests); the fallback NEVER fires when `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` and `force_auto_reply=False` (suggestion-only path preserved); the fallback NEVER bypasses the limited-mode allow-list guard (non-allowed numbers still emit `whatsapp.ai.auto_reply_guard_blocked` + `whatsapp.ai.deterministic_grounded_reply_blocked` and outcome.sent stays False); consent missing still blocks before LLM dispatch; medical-emergency / side-effect / legal-threat in the LATEST inbound still routes to handoff with no fallback; the broad-automation flags (`callHandoff / lifecycle / rescue / RTO / reorder`) remain LOCKED OFF; campaigns remain LOCKED. **13 new backend tests; 847 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.** Rollback to `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` is still required after every failed real-inbound test until the fix has been deployed and verified end-to-end on the VPS.
- **Phase 5F-Gate Limited Auto-Reply Flag Plan shipped:** the previous phase (Internal Allowed-Number Cohort Tooling) handed the operator the prep tooling. This phase ships **read-only inspector tooling + audit hardening** so Director can flip `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` on the global env safely and observe the soak without re-running anything. **No business logic is unlocked**: the final-send limited-mode allow-list guard, consent, Claim Vault grounding, blocked-phrase filter, medical-safety / objection / human-request handoff, CAIO, and audit ledger all stay exactly as they are; the six broad-automation flags (`WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`) remain LOCKED OFF; campaigns remain LOCKED. **Two new strictly read-only management commands.** (a) `python manage.py inspect_whatsapp_auto_reply_gate --json` reports every gate the real-inbound webhook auto-reply path depends on — `provider`, `limitedTestMode`, `autoReplyEnabled`, `allowedListSize`, `allowedNumbersMasked` (last-4 only — `+91*****99001`), `wabaSubscription` (active / count / warning / error), `finalSendGuardActive`, `consentRequired`, `claimVaultRequired`, `blockedPhraseFilterActive`, `medicalSafetyActive`, the six broad-automation flags, `campaignsLocked`, plus a `readyForLimitedAutoReply` boolean, a typed `blockers` list (each blocker names the env var or condition that must change — e.g. "WHATSAPP_PROVIDER must be 'meta_cloud'", "WHATSAPP_CALL_HANDOFF_ENABLED must remain false during the limited auto-reply gate"), `warnings`, and a typed `nextAction` ∈ {`ready_to_enable_limited_auto_reply_flag`, `keep_auto_reply_disabled_fix_blockers`, `limited_auto_reply_enabled_monitor_real_inbound`}. (b) `python manage.py inspect_recent_whatsapp_auto_reply_activity --hours N --json` is a soak monitor that counts AI activity audit kinds in the last `N` hours (`inboundAiRunStartedCount`, `replyAutoSentCount`, `replyBlockedCount`, `suggestionStoredCount`, `handoffRequiredCount`, `deterministicBuilderUsedCount`, `objectionReplyUsedCount`, `autoReplyFlagPathUsedCount`, `autoReplyGuardBlockedCount`, `messageDeliveredCount`, `messageReadCount`), runs a forensic outbound check against every `WhatsAppMessage.direction=OUTBOUND, sent_at >= since, provider_message_id != ""` and reports `unexpectedNonAllowedSendsCount` (any outbound that landed outside the allow-list — should always be 0 under limited mode), and counts `Order` / `Payment` / `Shipment` / `DiscountOfferLog` rows created in the window (mutation safety check — should remain 0 during the gate phase). `nextAction` ∈ {`rollback_auto_reply_flag` (any non-allowed leak), `limited_auto_reply_enabled_monitor_real_inbound` (healthy soak), `no_recent_ai_activity_in_window` (no inbound traffic to assess), `review_blocked_or_suggestion_paths` (AI runs happened but no auto-send fired)}. Both commands NEVER mutate the DB, NEVER write audit rows, NEVER print tokens / verify token / app secret; phones are masked to last-4 in JSON / latest-events / allowed-list output. **Two new audit kinds at the orchestrator level**, both inside `apps.whatsapp.ai_orchestration._send_freeform_reply`. `whatsapp.ai.auto_reply_flag_path_used` is emitted ONLY when `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` AND a real customer inbound triggered the auto-send (NEVER on `force_auto_reply=True` CLI runs — the orchestrator now stamps `ai_state.lastTriggeredBy` and `ai_state.lastForceAutoReply` on every run so this distinction is observable both at runtime and after-the-fact in the JSON snapshot). Payload carries `phone_suffix` (last-4), `category`, `confidence`, `claim_vault_used`, `limited_test_mode`. `whatsapp.ai.auto_reply_guard_blocked` is emitted whenever the final-send limited-mode allow-list guard refuses an outbound (`WhatsAppServiceError(block_reason="limited_test_number_not_allowed")` or any other guard-driven `WhatsAppServiceError`). Payload carries `phone_suffix`, `block_reason`, `provider`, `limited_test_mode`. **Hard rules preserved**: zero mutation of `Order` / `Payment` / `Shipment` / `DiscountOfferLog` from any inspector path (asserted with before/after counts in tests); campaigns / broadcasts / lifecycle automation / call handoff / rescue / RTO / reorder remain LOCKED OFF; final-send limited-mode allow-list guard still blocks every send that targets a phone outside `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`; CAIO never executes; orchestrator stays strict for webhook-driven runs (the existing strict gates run unchanged). Inspector commands gracefully handle missing Meta credentials. **16 new backend tests; 834 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.**
- **Phase 5F-Gate Internal Allowed-Number Cohort Tooling shipped:** the Phase 5F-Gate Scenario Matrix Test = FULL PASS, the Objection & Handoff Reason Refinement = FULL PASS, and the live one-number gate (Director's allowed test number) is delivering Claim-Vault-grounded AI replies safely (`WAM-100010` first deterministic grounded reply; `WAM-100012` normal product info; `WAM-100014` discount scenario; latest discount-objection retest succeeded with `finalReplySource=deterministic_objection_reply` and the WhatsApp message received). Zero unexpected outbound sends, zero mutation of `Order` / `Payment` / `Shipment` / `DiscountOfferLog` / `Lifecycle` / `Handoff` rows — confirmed via the existing controlled test + audit ledger spot-checks. This phase ships **management-command tooling** to safely expand from one allowed number to a tiny internal cohort of 2–3 staff numbers without unlocking any broad automation. **Three new commands:** (a) `python manage.py inspect_whatsapp_internal_cohort --json` reads `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` and reports per-number readiness for the controlled scenario tests — `customerFound`, `consentState`, `conversationFound`, `latestInbound/Outbound`, `latestAuditAt`, `readyForControlledTest`, `missingSetup` list — plus a global flag snapshot (`autoReplyEnabled`, `callHandoffEnabled`, `lifecycleEnabled`, `rescueDiscountEnabled`, `rtoRescueEnabled`, `reorderEnabled`) and the WABA subscription summary (`checked`, `active`, `subscribedAppCount`). Phone numbers masked to last-4 by default; `--show-full-numbers` is an operator-only flag with a "do not paste publicly" warning. Strictly read-only (asserted with before/after counts on `Customer` / `WhatsAppConsent` / `WhatsAppMessage` / `AuditEvent`). `nextAction` ∈ {`cohort_ready_for_manual_scenario_tests`, `add_numbers_to_allowed_list`, `register_missing_customers_or_consent`, `fix_waba_subscription`, `keep_global_auto_reply_off`}. (b) `python manage.py prepare_whatsapp_internal_test_number --phone +91XXXXXXXXXX --name "Internal Staff Name" --source internal_cohort_test --json` registers a number that the operator has ALREADY added to `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` in `.env.production`. Refuses outright if the phone is not on the allow-list (`nextAction=add_number_to_allowed_list`). Creates / reuses a `Customer` row, sets `customer.consent_whatsapp=True`, grants `WhatsAppConsent.consent_state="granted"` with `revoked_at=None`, source `internal_cohort_test`, and metadata `{reason: "Internal allowed-number WhatsApp AI cohort test", approved_by: "Prarit", limited_test_mode: true, phone_suffix}` — full phone number NEVER stored in the consent metadata. Writes one new `whatsapp.internal_cohort.number_prepared` audit row carrying `phone_suffix` only. NEVER sends a WhatsApp message; NEVER creates / mutates `Order` / `Payment` / `Shipment` / `DiscountOfferLog`. JSON output masks the phone to last-4; full E.164 NEVER appears in JSON or audit payload. (c) `python manage.py run_whatsapp_internal_cohort_dry_run --json` loops the allow-list and reports per-number scenario readiness (`normal_product_info_ready`, `discount_objection_ready`, `safety_block_ready`, `legal_block_ready`, `human_request_ready`) without sending or mutating; useful between deploys to confirm the cohort is wired up before running per-number scenarios. **Workflow:** edit `.env.production` to add staff numbers to `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` (keep `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`, every automation flag default OFF) → recreate `backend worker beat nginx` containers → `inspect_whatsapp_internal_cohort` to confirm the readiness map → `prepare_whatsapp_internal_test_number` per number → run the existing `run_controlled_ai_auto_reply_test --phone +91… --message "…" --send --json` per number through the seven scenario matrix. The existing safety stack, intent classifier, deterministic grounded / objection-aware fallbacks, final-send limited-mode guard, and audit ledger all stay in force. **One new audit kind** (`whatsapp.internal_cohort.number_prepared`); audit payloads carry phone last-4 only, never tokens / verify token / app secret. Hard rules preserved: zero broad auto-reply unlock; zero campaigns / broadcasts / lifecycle / call-handoff / rescue / RTO / reorder enabled; full phone numbers never committed to docs / git / audit payloads; the cohort starts with 2–3 numbers only and is gated by `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`. **19 new backend tests; 818 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.**
- **Phase 5F-Gate Objection & Handoff Reason Refinement shipped:** the Phase 5F-Gate Controlled AI Auto-Reply Soak Review reported FULL PASS (`WAM-100010` first successful deterministic grounded AI reply on the allowed test number; zero unexpected outbound sends; zero Order / Payment / Shipment / Lifecycle / Handoff events in the last 24h / 2h). The Phase 5F-Gate Scenario Matrix Test then passed with two refinements: (a) **Discount Objection** — safety-correct (no discount mutation, no >50% issue, no upfront discount) but the reply was a generic product-info-style response instead of an objection-aware one; (b) **Human Call Request** — safety-correct (no automation triggered) but the `blockedReason` came back as `claim_vault_not_used` instead of the desired `human_advisor_requested`. This phase fixes both. New `apps.whatsapp.grounded_reply_builder` helpers: `classify_inbound_intent(text) → IntentResult(primary ∈ {unsafe, human_request, discount_objection, product_info, unknown}, discount_objection, objection_type ∈ {discount, price, ""}, purchase_intent, human_request, unsafe, matched)`; `detect_discount_objection`, `detect_human_request`, `detect_purchase_intent`, `detect_unsafe_signal` deterministic detectors covering Hinglish + Hindi + English vocabulary (`discount`, `kuch kam`, `mehenga`, `budget`, `costly`, `kuch kar do` for objections; `mujhe call karwa do`, `AI se baat nahi`, `advisor se baat`, `callback`, `agent se baat`, `talk to a human` for human requests); `can_build_objection_reply(...)` eligibility gate (requires discount-objection signal AND fails closed on unsafe vocabulary inside the same message); `build_objection_aware_reply(normalized_product, approved_claims, inbound_text, purchase_intent)` composes a Hinglish reply that opens with a short price-concern acknowledgement, embeds the first approved Claim Vault phrase + ₹3000/30-capsules/₹499 advance facts, then explicitly states no upfront concession is promised and product is supported per approved process — followed by remaining approved phrases, a soft next-step invitation (with purchase-intent-aware wording), conservative usage guidance, and doctor-escalation; `validate_objection_reply(...)` extends the grounded validator with `objectionPromisedDiscount` / `objectionPromisedDiscountTerm` flags that reject `discount confirmed` / `guaranteed discount` / `50% discount` / `100% discount` framing. Controlled-test command priority order: (1) safety blockers (handled by orchestrator); (2) human request — short-circuits the orchestrator with `blockedReason="human_advisor_requested"`, `handoffReason="human_advisor_requested"`, `nextAction="human_handoff_requested"`, `safetyBlocked=false`, and a clean `whatsapp.ai.handoff_required` audit row carrying `reason=human_advisor_requested` (NEVER `claim_vault_not_used`); Vapi handoff stays gated by `WHATSAPP_CALL_HANDOFF_ENABLED=false`; (3) unknown category / no Claim Vault → fail closed unchanged; (4) discount/price objection with grounding → objection-aware fallback; (5) normal product-info → existing grounded fallback; (6) else → fail closed. Four new audit kinds (`whatsapp.ai.objection_detected`, `whatsapp.ai.objection_reply_used`, `whatsapp.ai.objection_reply_blocked`, `whatsapp.ai.human_request_detected`); audit payloads NEVER carry tokens / verify token / app secret; phone is masked to last 4 digits. Controlled-test JSON gains `detectedIntent`, `objectionDetected`, `objectionType`, `purchaseIntentDetected`, `humanRequestDetected`, `handoffReason`, `safetyReason`, and a `replyPolicy` block (`upfrontDiscountOffered=false`, `discountMutationCreated=false`, `businessMutationCreated=false`); `finalReplySource` extends to include `"deterministic_objection_reply"` and `"blocked_handoff"`. Hard rules preserved: NO mutation of `Order` / `Payment` / `Shipment` / `DiscountOfferLog` from any controlled-test path (asserted in tests); objection reply NEVER mentions a confirmed / guaranteed discount; cure / guarantee / unsafe-claim demand inside an objection sentence still routes to the safety stack (unsafe wins); side-effect / legal / refund / unknown-category still fail closed unchanged; final-send limited-mode guard still refuses non-allowed numbers; CAIO never executes; orchestrator stays strict for webhook-driven runs. **52 new backend tests; 799 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.**
- **Phase 5F-Gate Deterministic Grounded Reply Builder shipped:** even after the Controlled Reply Confidence Fix (`BUSINESS FACTS` + `ACTION SELECTION DECISION TREE` + `FINAL CHECK` in the prompt) landed on the VPS, the live `--send` against the allowed test number STILL failed: `WAM-100008` came back with `detectedCategory=weight-management`, `normalizedClaimProduct=Weight Management`, `claimRowCount=1`, `approvedClaimCount=3`, `groundingStatus.claimProductFound=true`, `groundingStatus.promptGroundingInjected=true`, `groundingStatus.businessFactsInjected=true`, every safety flag false — yet the LLM still returned `safety.claimVaultUsed=false`, `action=handoff`, `confidence=0.7`, `actionReason="No approved Claim Vault entries available for weight-management; cannot give product details safely."` That is a contradiction — the backend proves Claim Vault entries exist and were injected, but the LLM falsely claims none exist. Root cause: relying only on the LLM's self-reported `claimVaultUsed` flag is insufficient when the backend already has full grounding. Fix is a **backend-only deterministic Claim-Vault-grounded reply fallback**. New `apps.whatsapp.grounded_reply_builder` module: (a) `is_normal_product_info_inquiry(inbound_text)` — deterministic intent detector with explicit keyword + disqualifier lists; (b) `can_build_grounded_product_reply(...)` — eligibility gate (category mapped, approved claims present, no safety flag set, intent qualified); (c) `build_grounded_product_reply(...)` — composes a Hinglish reply that literally embeds the first approved phrase + ₹3000/30-capsules/₹499 advance + conservative usage guidance + doctor escalation; (d) `validate_reply_uses_claim_vault(...)` — re-checks the final text contains at least one approved phrase, no `BLOCKED_CLAIM_PHRASES` entry, no discount vocabulary. The controlled-test command (`run_controlled_ai_auto_reply_test`) now invokes this fallback **only** when the LLM blocked with one of the soft non-safety reasons (`claim_vault_not_used` / `low_confidence` / `ai_handoff_requested` / `auto_reply_disabled` / `no_action`) AND backend grounding is valid AND the inbound is a normal product-info inquiry; safety blockers (`medical_emergency` / `side_effect_complaint` / `legal_threat` / `blocked_phrase` / `limited_test_number_not_allowed`) NEVER trigger fallback. The fallback dispatches via `services.send_freeform_text_message` so the limited-mode allow-list guard, consent, CAIO, and idempotency gates all stay in force. Two new audit kinds (`whatsapp.ai.deterministic_grounded_reply_used`, `whatsapp.ai.deterministic_grounded_reply_blocked`); audit payloads NEVER carry tokens. Controlled-test JSON gains `deterministicFallbackUsed`, `fallbackReason`, `deterministicReplyPreview`, `finalReplySource` (`"llm"` or `"deterministic_grounded_builder"`), and `finalReplyValidation` (`containsApprovedClaim` / `blockedPhraseFree` / `discountOffered` / `safeBusinessFactsOnly` / `passed`). Hard rules preserved: `claimVaultUsed=true` flips ONLY because the validator confirmed the reply text literally embeds an approved phrase; the global `WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD` is unchanged; the orchestrator stays strict for webhook-driven runs (this fallback is controlled-test-only); never sends discount, cure, guarantee, "no side effects", or "doctor not needed" content. **24 new backend tests; 747 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.**
- **Phase 5F-Gate Controlled Reply Confidence Fix shipped:** the deployed Claim Vault Grounding Fix correctly mapped `weight-management → Weight Management` and surfaced the Weight Management Claim row in the prompt, but the live `--send` against the allowed test number still failed: `WAM-100007` came back with `blockedReason=low_confidence`, `confidence=0.7`, `action=handoff`. The audit showed Claim Vault product was correctly detected, yet the AI still chose handoff. Root cause: the prompt did not tell the LLM explicitly that a normal grounded inquiry must use `action=send_reply` with `confidence ≥ 0.85`; the LLM defaulted to handoff out of caution. Three pieces ship in this hotfix. (a) **Business facts injected explicitly**: the system prompt now carries an explicit `BUSINESS FACTS YOU MAY STATE FREELY` section listing standard price ₹3000 / 30 capsules, ₹499 fixed advance, conservative usage guidance ("use as directed on label / qualified practitioner"), and the doctor-escalation rule for pregnancy / serious illness / allergies / existing medication / adverse reaction. The prompt-context `settings` block also gains `standardCapsuleCount=30`, `currency=INR`, `discountDiscipline` description, and a `businessFactsAllowed` whitelist. Business facts are routing labels and price/quantity facts — they are NOT medical claims. Medical / product-benefit content still comes only from `Claim.approved`. (b) **Action discipline**: the system prompt now carries an explicit `ACTION SELECTION DECISION TREE` (cases A–E mapping grounded-inquiry, no-claim-vault, unknown-category, confirmed-booking, and safety-vocabulary inbounds to the canonical action) AND a `FINAL CHECK` paragraph at the end of the schema instructions stating: "if the claims block has at least one APPROVED phrase AND every safety flag is false AND the inbound is a normal product/price/quantity/use-guidance question, then action MUST be 'send_reply' with confidence ≥ 0.85, safety.claimVaultUsed=true, and replyText must literally include one of the APPROVED phrases — defaulting to action='handoff' on a grounded inquiry is a defect." Confidence threshold env (`WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.75`) is **unchanged** — we fix the prompt first, never lower the global threshold blindly. (c) **Diagnostics cleanup**: the ambiguous `claim_count` (which inconsistently meant rows vs phrases — the controlled_test.blocked audit said `claim_count=3` while category_detected/reply_blocked said `claim_count=1`) is split into three explicit fields across all four orchestrator audit kinds AND the controlled-test JSON: `claim_row_count` (number of `Claim` rows), `approved_claim_count` (sum of approved phrases — the count operators care about), `disallowed_phrase_count` (sum of disallowed phrases). `claim_count` is preserved as a backward-compat alias for `approved_claim_count`. New diagnostics fields on the controlled-test JSON: `confidenceThreshold`, `actionReason`, `sendEligibilitySummary`, `groundingStatus.{claimRowCount, businessFactsInjected}`. Hard rules preserved: `claimVaultUsed=false` still blocks the send; "guaranteed cure" / "100% cure" replies still blocked by the blocked-phrase filter even with grounding; side-effect / medical-emergency / legal-threat inbounds still route to handoff; the final-send limited-mode guard still refuses non-allowed numbers; CAIO never executes; no campaigns / broadcasts. **12 new backend tests; 723 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.**
- **Phase 5F-Gate Claim Vault Grounding Fix shipped:** the deployed Controlled AI Auto-Reply Test Harness produced two safety-correct blocks against the allowed test number on the VPS — first `WAM-100005` blocked by `low_confidence` (`confidence=0.7`, threshold higher), then `WAM-100006` blocked by `claim_vault_not_used` with audit reason "No Claim Vault entries available for weight management; cannot safely describe product, price details, or usage as per policy" → `nextAction=blocked_for_unapproved_claim`. Root cause confirmed by VPS Claim inspection: the Weight Management claim **did exist** (`product="Weight Management"`, `approved=["Supports healthy metabolism", "Ayurvedic blend used traditionally", "Best with diet & activity"]`, `version="v3.2"`, `doctor=Approved`, `compliance=Approved`). The orchestrator's `_claims_for_category("weight-management", customer)` was running `Claim.objects.filter(product__icontains="weight-management")` against `Claim(product="Weight Management")` — hyphen vs space — and silently fell through to `product__icontains=customer.product_interest or ""` which **returned every claim row** when `product_interest` was blank. The LLM then either had zero relevant grounding (incoherent prompt → `claimVaultUsed=false`) or a kitchen-sink prompt (still `claimVaultUsed=false` because the routing was incoherent). Fix: new deterministic helper `apps.whatsapp.claim_mapping.category_to_claim_product` (eight canonical slugs `weight-management → Weight Management`, `blood-purification → Blood Purification`, `men-wellness → Men Wellness`, `women-wellness → Women Wellness`, `immunity → Immunity`, `lungs-detox → Lungs Detox`, `body-detox → Body Detox`, `joint-care → Joint Care` plus ~25 aliases including `weight-loss / weight loss / weight management / blood purify / male wellness / female wellness / lungs detox / body detox / joint pain / joint care / detox / immune`). `_claims_for_category` is rewritten to use `Claim.product__iexact=normalized_product`; the empty-string-matches-everything fallback is removed; unknown / empty category fails closed (returns `[]`). Disallowed phrases stay attached to the prompt avoid list — the LLM continues to see them. The controlled-test command's `--json` output now carries a full diagnostics block (`detectedCategory / normalizedClaimProduct / claimCount / confidence / action / replyPreview / safetyFlags / groundingStatus.{claimProductFound, approvedClaimCount, disallowedPhraseCount, promptGroundingInjected}`). The `whatsapp.ai.category_detected`, `whatsapp.ai.reply_blocked`, `whatsapp.ai.handoff_required`, and `whatsapp.ai.controlled_test.blocked` audits gain `category / normalized_claim_product / claim_count / confidence` fields so the operator can diagnose without re-running. Hard rules preserved: `claimVaultUsed=false` still blocks the send; no free-style medical claims; no slug-to-product fuzzy guessing (every alias entry is explicit). **40 new backend tests; 711 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns) remains LOCKED.**
- **Phase 5F-Gate Controlled AI Auto-Reply Test Harness shipped:** the Hardening Hotfix landed on the VPS and the inspector confirmed a clean state (provider `meta_cloud`, limited mode `true`, allow-list size `2`, customer `NRG-CUST-5025` with granted consent, conversation `WCV-3`, outbound `WAM-100003`, inbound `WAM-100004`, webhook events accepted with `signature_verified=true`, WABA subscription active, `errors=[]`). After the inbound `WAM-100004` arrived, the existing AI orchestration ran but stored a suggestion (`whatsapp.ai.suggestion_stored`) and emitted `whatsapp.ai.reply_blocked · auto_reply_disabled` because `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` — exactly as designed. This phase ships the safe scoped path so Director can run a real one-shot live AI reply without flipping the global env. Two pieces: (a) **final-send limited-mode guard** inside `apps.whatsapp.services._limited_test_mode_blocks_send` runs both inside `send_freeform_text_message` (AI auto-reply path) and `queue_template_message` (template path) — when `WHATSAPP_PROVIDER=meta_cloud` AND `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`, every customer-facing send must target a phone on `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` or it raises `WhatsAppServiceError(block_reason="limited_test_number_not_allowed")` + writes `whatsapp.send.blocked` audit. This is the LAST-LINE defence and runs even when the caller has somehow bypassed every other gate. (b) `apps.whatsapp.ai_orchestration.run_whatsapp_ai_agent(..., force_auto_reply=True)` — new kwarg lets the new CLI flip the auto-reply gate ON for one orchestrator call only; webhook-driven runs never set it. The new `python manage.py run_controlled_ai_auto_reply_test --phone +91XXXXXXXXXX --message "…" [--dry-run|--send] [--json]` is the **only** sanctioned path that may produce a real AI auto-reply during the gate phase. Default `--dry-run` (returns `nextAction=dry_run_passed_ready_for_send` without persisting an inbound or hitting the LLM); `--send` runs the full orchestrator + AI dispatch + provider call. Refuses if any of the six automation flags (`WHATSAPP_AI_AUTO_REPLY_ENABLED`, `WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`) is on, if the destination is not on the allow-list, if consent is missing, if the customer doesn't exist, if WABA is inactive, or if the provider is not `meta_cloud`. Returns a typed `nextAction` for every amber path (`add_number_to_allowed_list / grant_consent_on_test_number / enable_meta_cloud_provider / enable_limited_test_mode / disable_automation_flags / fix_waba_subscription / fix_claim_vault_coverage / blocked_for_medical_safety / blocked_for_unapproved_claim / blocked_by_limited_mode_guard / inspect_live_test`). Five new audit kinds (`whatsapp.ai.controlled_test.{started,dry_run_passed,sent,blocked,completed}`); payloads carry phone last-4 only, body 120-char preview, no tokens. **15 new backend tests; 671 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns / growth automation) remains LOCKED.**
- **Phase 5F-Gate Hardening Hotfix shipped (post-live-pass diagnostics layer):** the limited live Meta WhatsApp one-number gate passed end-to-end on the VPS (`nrg_greeting_intro / hi / UTILITY / APPROVED`, outbound `WAM-100003` delivered to phone, then inbound `WAM-100004` "Namaste webhook test" stored after fixing the empty `GET /{WABA_ID}/subscribed_apps` by `POST` to subscribe + `POST` with `override_callback_uri=https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/&verify_token=…`). One invalid-signature test event was correctly rejected; one real Meta `messages` event was accepted with `signature_verified=True`. `WhatsAppMessageStatusEvent.count` is still 0 — diagnostics added, not blocking the gate yet. Three gaps surfaced during the run, all fixed in this hotfix: (1) the second allowed-number send hit a duplicate `idempotency_key` IntegrityError that crashed the CLI with a traceback — now trapped, returns clean JSON with `passed=false / duplicateIdempotencyKey=true / alreadyQueued|alreadySent / existingMessageId / nextAction=inspect_existing_message` and a new `whatsapp.meta_test.duplicate_idempotency` audit row (audit payload only carries the last 12 chars of the key, never the raw key, never any token); (2) `--check-webhook-config` now also runs `GET /{WABA}/subscribed_apps` against Meta Graph and reports `wabaSubscriptionChecked / wabaSubscriptionActive / wabaSubscribedAppCount / wabaSubscriptionWarning / wabaSubscriptionError / overrideCallbackExpected / recommendedSubscribeCommandHint / recommendedOverrideCallbackHint` + emits a new `whatsapp.meta_test.webhook_subscription_checked` audit row, with `nextAction=subscribe_waba_to_app_webhooks` when `data=[]`. Token / verify-token / app-secret are NEVER printed in hints; the helpers print `{api}/{WABA_ID}/...` shapes only. (3) new strictly-read-only `python manage.py inspect_whatsapp_live_test --phone +91XXXXXXXXXX --json` command surfaces customer / `WhatsAppConsent` / `WhatsAppConversation` / latest 5 outbound + 5 inbound messages / latest 5 webhook envelopes (with `signature_verified` + `processing_status`) / latest 5 status events / latest 25 `whatsapp.*` audit rows / WABA subscription / `latestProviderMessageId` + a typed `nextAction` (`run_one_number_send` / `verify_inbound_webhook_callback` / `subscribe_waba_to_app_webhooks` / `observe_status_events_optional` / `gate_hardened_ready_for_limited_ai_auto_reply_plan`). Inspector NEVER writes audit rows, sends messages, or mutates the DB; gracefully handles missing Meta credentials; never prints tokens / verify token / app secret. **13 new backend tests; 656 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns / growth automation) remains LOCKED** until the inspector reports `gate_hardened_ready_for_limited_ai_auto_reply_plan` on a real VPS run; next safe step is then a controlled AI auto-reply test against the same allowed test number only.
- **Phase 5F-Gate — Limited Live Meta WhatsApp One-Number Test harness shipped:** new `apps.whatsapp.meta_one_number_test` module + `python manage.py run_meta_one_number_test` command verify real Meta Cloud sends against exactly one approved test number, without enabling AI auto-reply, broadcasts, lifecycle automation, rescue / RTO / reorder automation, or freeform sends. Hard stops are stacked at the function level AND command level — provider must be `meta_cloud`, `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`, destination must be in `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` (allow-list normalised to digits, empty list blocks every number), template must be `APPROVED + active + UTILITY/AUTHENTICATION` (MARKETING tier refused), every automation flag must remain off, freeform refused outright. Eight new audit kinds (`whatsapp.meta_test.{started,config_ok,config_failed,blocked_number,template_missing,sent,failed,completed}`); audit payloads NEVER carry tokens (any `token`-keyed entry is stripped before persistence). Default `--dry-run`; `--send` required for a real dispatch and refuses if any safety gate is amber. `--check-webhook-config` prints the expected callback URL (`https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/`) + verify-token / app-secret presence + the subscribed-fields list. **24 new backend tests; 643 backend + 13 frontend, all green.** **Phase 5F (broadcast campaigns / growth automation) remains LOCKED until this gate passes on a live test number.**
- **Phase 5E-Smoke-Fix-3 — false-positive safety classification fix shipped:** the VPS OpenAI smoke run (`python manage.py run_controlled_ai_smoke_test --scenario ai-reply --use-openai --json`) reported `overallPassed=false` because the orchestrator wrongly classified `Hi mujhe weight loss product ke baare me batana` as a `side_effect_complaint` and routed the conversation to handoff. Hotfix-3 adds `apps.whatsapp.safety_validation.validate_safety_flags(inbound_text, safety_flags)` — a deterministic post-LLM corrector that runs server-side just before `_safety_block` in `apps.whatsapp.ai_orchestration`. For each blocker flag the LLM set true (`sideEffectComplaint`, `medicalEmergency`, `legalThreat`), it checks whether the inbound text contains the corresponding signal vocabulary (English + Hindi + Hinglish — e.g. `side effect`, `ulta asar`, `medicine khane ke baad`, `chest pain`, `saans nahi`, `consumer forum`, `lawyer`). Flags whose vocabulary is absent get flipped to false and emit a new `whatsapp.ai.safety_downgraded` audit row so every correction is observable; flags whose vocabulary IS present (real complaints) stay flagged exactly as the LLM said. `angryCustomer` (tone signal) and `claimVaultUsed` (reply property, not inbound) are **never** touched. The corrector is purely additive — it can only flip true→false, never false→true. The LLM prompt now carries an explicit `SAFETY FLAG DISCIPLINE` block listing required vocabulary per flag with the rule: "A normal product / price / availability inquiry leaves all safety flags false." **VPS rebuild required** so the new orchestrator + prompt land in the container; after rebuild the `ai-reply --use-openai` smoke run is expected to report `overallPassed=true`. **28 new backend tests; 619 backend + 13 frontend, all green.**
- **Phase 5E-Smoke-Fix-2 — OpenAI Chat Completions token-parameter hotfix shipped:** the VPS smoke run with the rebuilt image hit the OpenAI API but failed with *"Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."*. Modern OpenAI Chat models (gpt-4o, gpt-5, o1, o3, …) reject the legacy `max_tokens` and require `max_completion_tokens`. Hotfix extracts `apps.integrations.ai.openai_client.build_request_kwargs(messages, model, config)` so the SDK call shape is unit-testable; adapter now always sends `max_completion_tokens` and never `max_tokens`. Zero / unset `max_tokens` drops the key entirely. The smoke harness's `safeFailure=true` path correctly fired during the failure run, proving the safety semantics work; the new tests pin the kwargs shape so this regression cannot recur silently. **VPS rebuild required** so the new adapter code lands in the backend container. **10 new backend tests; 591 backend + 13 frontend, all green.**
- **Phase 5E-Smoke-Fix — OpenAI SDK + provider-success semantics shipped:** `openai>=1.0,<2.0` added to `backend/requirements.txt` (the OpenAI adapter already targets the v1 SDK API). Smoke harness `ai-reply` scenario now reports four new detail fields when `--use-openai` is passed — `openaiAttempted`, `openaiSucceeded`, `providerPassed`, `safeFailure`. A "safe failure" (adapter raised but the customer send stayed blocked because of the mock provider + auto-reply OFF lock) is still safety-correct but **does NOT count as a pass** — `scenario.passed=false`, `overallPassed=false`, with a clear warning telling the operator the OpenAI integration must be fixed before any flag flip. Pre-seeds an outbound on the smoke conversation so the greeting fast-path no longer short-circuits LLM dispatch. **VPS rebuild required** after the requirements.txt change so the openai package lands inside the backend container. **6 new backend tests; 579 backend + 13 frontend, all green.**
- **Phase 5E-Smoke — Controlled Mock + OpenAI Smoke Testing Harness shipped:** new `apps.whatsapp.smoke_harness` module + `python manage.py run_controlled_ai_smoke_test` command exercise the WhatsApp AI orchestrator (`ai-reply` scenario with Hindi / Hinglish / English scripted inbounds + a deterministic mocked LLM decision), Claim Vault gate (`claim-vault` scenario seeds + reports coverage), rescue discount cap math (`rescue-discount` scenario hits 0% / 40% / 50% existing-discount cases + CAIO refusal), WhatsApp → Vapi handoff (`vapi-handoff` scenario — safe trigger / idempotent re-fire / safety-reason skip in mock mode), and Day-20 reorder eligibility (`reorder-day20` scenario — dry-run + idempotency). Defaults are SAFE: dry-run, mock WhatsApp, mock Vapi, OpenAI off (deterministic mocked LLM decision). Pass `--use-openai` to hit the real OpenAI provider for the `ai-reply` scenario only — WhatsApp stays mock so no real customer is messaged. Refuses real Meta provider outright; refuses live Vapi outright in default mode. Four new audit kinds (`system.smoke_test.{started,completed,failed,warning}`). `--json` flag emits CI / log-scrape friendly output. **23 new backend tests; 573 backend + 13 frontend, all green.**
- **What's next (locked sequence):** **VPS rebuild for the Internal Cohort Tooling → operator adds 1–2 additional staff numbers to `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` in `.env.production` → recreate `backend worker beat nginx` → `inspect_whatsapp_internal_cohort --json` → `prepare_whatsapp_internal_test_number` per number → run the 7-scenario matrix per number with the existing `run_controlled_ai_auto_reply_test` → 24-hour soak → Phase 5F-Gate Controlled AI Auto-Reply Soak (extended) phase.** Required outcomes after rebuild: inspector reports `allowedListSize=2` or `3` with every entry's `readyForControlledTest=true` + `consentState="granted"`, `autoReplyEnabled=false` (and every other automation flag `false`), `wabaSubscription.active=true`, `nextAction=cohort_ready_for_manual_scenario_tests`. Per-number scenario matrix mirrors the verified one-number gate: normal product info → `passed=true / replySent=true / finalReplySource=deterministic_grounded_builder|llm`; discount objection → `finalReplySource=deterministic_objection_reply / objectionType ∈ {discount, price} / replyPolicy.upfrontDiscountOffered=false`; safety / legal / human → typed handoff reasons (NOT `claim_vault_not_used`); mutation safety check → `Order` / `Payment` / `Shipment` / `DiscountOfferLog` counts unchanged. Then observe `/ws/audit/events/` filtered on `whatsapp.ai.*` + `whatsapp.internal_cohort.*` for 24 hours. Phase 5F (broadcast campaigns) remains LOCKED throughout. **Earlier next-step history (kept verbatim for traceability):** VPS rebuild for the Objection & Handoff Reason Refinement → re-run the scenario matrix subset (discount objection / human call request / side-effect complaint / legal-refund threat / mutation safety check) → confirm the typed reasons in the audit ledger → 24-hour soak → Phase 5F-Gate Controlled AI Auto-Reply Soak (extended) phase.** Required outcomes per scenario after rebuild: discount objection → `passed=true`, `replySent=true`, `finalReplySource=deterministic_objection_reply`, `objectionDetected=true`, `objectionType ∈ {discount, price}`, `replyPolicy.upfrontDiscountOffered=false`, `replyPolicy.discountMutationCreated=false`, `replyPolicy.businessMutationCreated=false`. Human call request → `passed=false`, `replySent=false`, `blockedReason=human_advisor_requested`, `handoffReason=human_advisor_requested`, `finalReplySource=blocked_handoff`, `nextAction=human_handoff_requested`, the `whatsapp.ai.handoff_required` audit row payload `reason=human_advisor_requested` (NOT `claim_vault_not_used`), and NO Vapi call fires (gated by `WHATSAPP_CALL_HANDOFF_ENABLED=false`). Side-effect complaint → `safetyBlocked=true`, `nextAction=blocked_for_medical_safety`. Legal/refund threat → block + handoff, no sales reply. Mutation safety check via `python manage.py shell -c "from apps.orders.models import DiscountOfferLog, Order; from apps.payments.models import Payment; from apps.shipments.models import Shipment; print(DiscountOfferLog.objects.count(), Order.objects.count(), Payment.objects.count(), Shipment.objects.count())"` — counts unchanged from pre-test snapshot. Then observe `/ws/audit/events/` filtered on `whatsapp.ai.*` for 24 hours. **Earlier next-step history (kept verbatim for traceability):** VPS rebuild for the Deterministic Grounded Reply Builder → re-run dry-run with the explicit weight-management prompt → live `--send` against the existing allowed test number → verify the phone receives the deterministic Claim-Vault-grounded reply (`finalReplySource=deterministic_grounded_builder`, `deterministicFallbackUsed=true`, `claimVaultUsed=true`, reply preview embeds an approved phrase + ₹3000 / 30 capsules + ₹499 advance) → 24-hour soak → Phase 5F-Gate Controlled AI Auto-Reply Soak phase.** Concretely: rebuild the backend image so the new builder module + the controlled-command fallback wiring + the two new audit icons land in the container. Then run `python manage.py inspect_whatsapp_live_test --phone +918949879990 --json` (require `errors=[]`). Then `python manage.py run_controlled_ai_auto_reply_test --phone +918949879990 --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." --dry-run --json` (require `passed=true`, `nextAction=dry_run_passed_ready_for_send`). Then the same command with `--send` and require `passed=true`, `replySent=true`, `claimVaultUsed=true`, `action=send_reply`, `finalReplyValidation.passed=true`, `finalReplyValidation.containsApprovedClaim=true`. The reply may come from the LLM (`finalReplySource=llm`) — accept that. If the LLM still blocks, the fallback should now dispatch (`finalReplySource=deterministic_grounded_builder`, `deterministicFallbackUsed=true`). Verify the phone actually receives the AI reply on WhatsApp. Then observe the audit ledger for 24 hours under the same allowed-number-only configuration. Only after that clean soak does **Phase 5F-Gate Controlled AI Auto-Reply Soak** open. Phase 5F (broadcast campaigns) remains LOCKED throughout. Concretely: rebuild the backend image so the new prompt + diagnostics land in the container. Then run `python manage.py inspect_whatsapp_live_test --phone +918949879990 --json` (require `errors=[]`). Then `python manage.py run_controlled_ai_auto_reply_test --phone +918949879990 --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." --dry-run --json` (require `passed=true`, `nextAction=dry_run_passed_ready_for_send`, `groundingStatus.businessFactsInjected=true`). Then the same command with `--send` and require `passed=true`, `replySent=true`, `action=send_reply`, `claimVaultUsed=true`, `confidence>=confidenceThreshold`, `replyPreview` literally contains one of `Claim.approved` phrases plus `₹3000` / `30 capsules` when relevant, `nextAction=live_ai_reply_sent_verify_phone`. Verify the phone actually receives the AI reply on WhatsApp. Then observe the audit ledger for 24 hours under the same allowed-number-only configuration. Only after that clean soak does **Phase 5F-Gate Controlled AI Auto-Reply Soak** open. Phase 5F (broadcast campaigns) remains LOCKED throughout. Concretely: rebuild the backend image, then run `python manage.py inspect_whatsapp_live_test --phone +918949879990 --json` (require `errors=[]`), then `python manage.py run_controlled_ai_auto_reply_test --phone +918949879990 --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." --dry-run --json` (require `passed=true`, `groundingStatus.claimProductFound=true`, `groundingStatus.approvedClaimCount>=1`, `groundingStatus.promptGroundingInjected=true`). Then the same command with `--send` and require `passed=true`, `replySent=true`, `auditEvents` includes `whatsapp.ai.controlled_test.sent`, `nextAction=live_ai_reply_sent_verify_phone`, and the test phone receives a Claim-Vault-grounded WhatsApp reply. Then observe the audit ledger for 24 hours under the same allowed-number-only configuration. Only after that clean soak does **Phase 5F-Gate Controlled AI Auto-Reply Soak** open. Phase 5F (broadcast campaigns) remains LOCKED throughout. Concretely: rebuild the backend image so the new orchestrator kwarg + the `run_controlled_ai_auto_reply_test` command land in the container. Then `docker compose ... exec backend python manage.py run_controlled_ai_auto_reply_test --phone +918949879990 --message "Namaste mujhe weight loss product ke baare me bataye" --dry-run --json` and require `passed=true` + `nextAction=dry_run_passed_ready_for_send`. Then run the same command with `--send` and require `passed=true` + `auditEvents` includes `whatsapp.ai.controlled_test.sent` + `nextAction=live_ai_reply_sent_verify_phone`. Verify the phone receives the reply on WhatsApp. Then observe the audit ledger / Live Activity stream for 24 hours under the same allowed-number-only configuration. Only after that clean soak does the next phase open: **Phase 5F-Gate Controlled AI Auto-Reply Soak** (allowed test number only, 24-hour observation). Phase 5F (broadcast campaigns) remains LOCKED throughout. Concretely: rebuild the backend image, then `docker compose ... exec backend python manage.py inspect_whatsapp_live_test --phone +918949879990 --json`. Require `nextAction=gate_hardened_ready_for_limited_ai_auto_reply_plan` (or `observe_status_events_optional` if status events still trail). Only after a clean inspector run, plan a controlled `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` test scoped to the allowed number with the customer-facing send still gated by every other safety check (Claim Vault + matrix + CAIO + idempotency). Then enable the rest of the six automation flags one at a time with 24+ hours of soak between flips. Only then start **Phase 5F** (approval-gated broadcast campaigns, MARKETING template tier, director sign-off). Phase 6 (learning loop pipeline) and Phase 7 (multi-tenant SaaS) follow. Concretely: rebuild the backend image on the VPS so the new orchestrator + the `run_meta_one_number_test` command land in the container. Then on the VPS run `python manage.py run_meta_one_number_test --check-webhook-config --json` to confirm the callback URL + verify-token presence; wire the Meta Developer Console webhook (callback URL `https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/`, verify token = `META_WA_VERIFY_TOKEN`, subscribe `messages`); add exactly one approved test MSISDN to `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`; run `python manage.py run_meta_one_number_test --to +91XXXXXXXXXX --template nrg_greeting_intro --verify-only --json` and require `passed=true`; finally `python manage.py run_meta_one_number_test --to +91XXXXXXXXXX --template nrg_greeting_intro --send --json` and require `auditEvents` includes `whatsapp.meta_test.sent` + `nextAction=verify_inbound_webhook_callback`. After the live one-number send is confirmed end-to-end (delivery receipt + inbound webhook), enable the six automation flags (`WHATSAPP_AI_AUTO_REPLY_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`) one at a time with 24+ hours of soak between flips. Only then start **Phase 5F** (approval-gated broadcast campaigns, MARKETING template tier, director sign-off). Phase 6 (learning loop pipeline) and Phase 7 (multi-tenant SaaS) follow.
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

Nirogidhara sells Ayurvedic medicines across categories like **Weight Management, Blood Purification, Men/Women Wellness, Immunity, Lungs Detox, Body Detox, Joint Care**. Standard product is **₹3000 for 30 capsules** with a **₹499 fixed advance** payment. **AI never offers a discount upfront**; refusal-based rescue discounts may surface at the confirmation / delivery / RTO stages within the Phase 3E policy bands and the locked **50% cumulative cap** (see Phase 5E rescue discount engine in §11 of [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md)).

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
│       ├── App.tsx                # Router + 21 routes
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
│       ├── pages/                 # 21 pages — see §6 below
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
│   ├── apps/                      # 16 Django apps — see §5 below (catalog added in Phase 3E, whatsapp added in Phase 5A)
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
| `catalog` (Phase 3E) | Product catalog admin (categories / products / SKUs) | `ProductCategory`, `Product`, `ProductSKU` | `/api/catalog/categories/`, `/api/catalog/products/`, `/api/catalog/skus/` |
| `whatsapp` (Phase 5A) | WhatsApp Live Sender Foundation (Meta Cloud) | `WhatsAppConnection`, `WhatsAppTemplate`, `WhatsAppConsent`, `WhatsAppConversation`, `WhatsAppMessage`, `WhatsAppMessageAttachment`, `WhatsAppMessageStatusEvent`, `WhatsAppWebhookEvent`, `WhatsAppSendLog` | `/api/whatsapp/{provider/status,connections,templates,conversations,messages,send-template,messages/{id}/retry,consent/{customer_id},templates/sync}/`, signed webhook at `/api/webhooks/whatsapp/meta/` |

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

## 6. Frontend pages (21)

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
| 13 | AI Scheduler & Cost (Phase 3C) | `/ai-scheduler` | `getSchedulerStatus` |
| 14 | AI Governance (Phase 3D) | `/ai-governance` | sandbox + prompt-version + budget endpoints |
| 15 | Reward & Penalty Engine | `/rewards` | `getRewardPenaltyScores` |
| 16 | Human Call Learning Studio | `/learning` | `getHumanCallLearningItems` |
| 17 | Claim Vault & Compliance | `/claims` | `getClaimVault` |
| 18 | Analytics | `/analytics` | `getAnalyticsData` |
| 19 | Settings & Control Center | `/settings` | `getSettingsMock` |

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

## 8. What's done so far — Phase 1 to Phase 3D — every checkpoint we shipped

### ✅ Frontend (was already in place when we started; we wired it to the backend)
- 21 pages, all routing through `src/services/api.ts`. **No page imports `mockData.ts` directly.** Phase 3C added the Scheduler Status page; Phase 3D added the AI Governance page; Phase 5A added the read-only WhatsApp Templates page; Phase 5B added the three-pane WhatsApp Inbox page + Customer 360 WhatsApp tab.
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

### ✅ Phase 4E — Expanded Approved Execution Registry (built this session)

- **Three new handlers** added to `apps/ai_governance/approval_execution.py`:
  1. `discount.up_to_10` — applies 0–10% discounts. Accepts ApprovalRequest status `approved` OR `auto_approved` (the matrix lets this band auto-approve; the engine still trusts only backend-created status — frontend / AI cannot fake `auto_approved`).
  2. `discount.11_to_20` — applies 11–20% discounts. Same approve / auto_approve gate; same trust rule.
  3. `ai.sandbox.disable` — flips the SandboxState singleton off. **Director-only** (matrix mode `director_override`). Idempotent: returns `alreadyDisabled=true` when sandbox is already off.
- **`discount.above_20` stays intentionally unmapped** — even when an approved (e.g. director_override) ApprovalRequest exists, `POST /api/ai/approvals/{id}/execute/` returns HTTP 400 + `ai.approval.execution_skipped` audit. The director_override → execute path is reserved for `ai.sandbox.disable` today; expanding it needs explicit Prarit sign-off + matching tests.
- **New `apply_order_discount` service** in `apps/orders/services.py`. Validates via the locked Phase 3E `validate_discount` policy, mutates ONLY `Order.discount_pct`, never touches customer / payment / shipment / stage data, writes a `discount.applied` audit row, returns `{ orderId, oldDiscountPct, newDiscountPct, policyBand, reason, source }`. New `DiscountValidationError` exception bubbles policy refusals to the handler as `ExecutionRefused`.
- **New audit kind** `discount.applied` registered in `ICON_BY_KIND`. Successful execution still writes the existing `ai.approval.executed` row; failed / skipped executions still write `ai.approval.execution_failed` / `ai.approval.execution_skipped`.
- **Handler band-edge guards** are belt-and-braces on top of `validate_discount`:
  - `discount.up_to_10`: rejects `discount_pct > 10`, rejects negative, rejects missing field.
  - `discount.11_to_20`: rejects `discount_pct <= 10` AND `discount_pct > 20`, rejects negative, rejects missing field.
  - Both: missing `orderId` → `ExecutionRefused`, unknown order → 404.
- **`ai.sandbox.disable` handler safety**: requires `note` or `overrideReason` in `proposed_payload` (or via `approval.reason` / `approval.decision_note`); otherwise refuses. Calls the existing `apps.ai_governance.sandbox.set_sandbox_enabled` helper rather than mutating the singleton directly. Director-only enforcement is inherited from the existing `_check_role` pre-check on the matrix `director_override` mode — Phase 4E adds no new role logic, just the handler.
- **Pre-checks unchanged from Phase 4D** — idempotency (already-executed → prior result, no rerun), CAIO refusal (engine + bridge + execute layer; both `requested_by_agent='caio'` and `metadata.actor_agent='caio'` blocked), `_check_role` (admin/director only; director-only on `director_override`), `_check_status_allows_execution` (must be `approved` or `auto_approved`), unknown action → skipped + 400. Phase 4E inherits all of it.
- **Phase 4D unmapped-action tests trimmed** — `tests/test_phase4d.py` parametrized "unmapped" lists no longer include `discount.11_to_20` or `ai.sandbox.disable` (Phase 4E maps them); they're now tested in `tests/test_phase4e.py` with full handler-side coverage. Other unmapped actions (`payment.refund`, `whatsapp.broadcast_or_campaign`, `complaint.medical_emergency`, `ad.budget_change`, `ai.production.live_mode_switch`) continue to be tested as skipped.
- **31 new pytest tests** (`tests/test_phase4e.py`): discount.up_to_10 happy paths (auto_approved + approved), band-above + negative refusals; discount.11_to_20 happy paths (approved + auto_approved), >20 + ≤10 + missing-pct + negative refusals; discount.above_20 stays unmapped → 400 + skipped + order unchanged; idempotency on discount (prior result returned, no second `discount.applied` audit); discount-only side-effect scope (only `discount_pct` mutated; `amount`, `stage`, `advance_amount` untouched); audit firing on discount + sandbox paths; sandbox.disable executes for Director, blocks Admin / Operations / anonymous, requires note or overrideReason, idempotent on already-off, CAIO requested + CAIO metadata blocked on both surfaces; remaining-unmapped parametric on the 4 still-blocked actions; HTTP endpoint smoke for discount.up_to_10 / discount.11_to_20 / sandbox.disable (director) / sandbox.disable (admin → 403).

**Locked Phase 4E decisions (Prarit, Apr 2026):**
1. `discount.up_to_20` execution can run when `ApprovalRequest.status` is `approved` OR `auto_approved`.
2. The execution layer trusts ONLY backend-created `ApprovalRequest.status` — the approval_engine creates `auto_approved` rows; the frontend cannot.
3. `ai.sandbox.disable` execution stays **Director-only**.
4. No ad-budget execution. No refunds. No live WhatsApp. No production live-mode switch.
5. CAIO blocked at engine + bridge + execute layer (carry-through Phase 4D rule).

**Compliance hard stop preserved (Master Blueprint §26):** the discount handlers never speak medical / claim text. The sandbox handler never affects Claim Vault grounding (sandbox is a runtime gate; Approved Claim Vault enforcement at the AgentRun layer is independent and unchanged). CAIO never executes. Live WhatsApp sender + production live-mode switch + ad-budget execution + refund execution all remain pending.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **351 passed** (322 phase4d-baseline + 31 phase4e − 2 phase4d unmapped-list trims) |
| `python manage.py check` | 0 issues |

### ✅ Phase 4A — Real-time AuditEvent WebSockets (built this session)

- **Django Channels + channels_redis + daphne** added to `requirements.txt`. `daphne` registered first in `INSTALLED_APPS` so the runserver picks up the ASGI router; `channels` added below the third-party block. New env vars in `backend/.env.example`: `CHANNEL_LAYER_BACKEND` (default `memory` for tests / dev) and `CHANNEL_REDIS_URL` (default `redis://localhost:6379/2` — index 2 reserved for Channels; Celery still uses 0/1).
- **`config/asgi.py`** rewired as a `ProtocolTypeRouter`: HTTP requests still flow through Django's standard ASGI app; WebSocket requests go through a `URLRouter` mounted from `config/routing.py`, which itself imports per-app `websocket_urlpatterns` (only `apps.audit.routing` today).
- **`apps/audit/realtime.py`** — single source of truth for the WebSocket payload: `serialize_event(event)` returns the camelCase shape the frontend `ActivityEvent` type expects (`id`, `kind`, `text`, `tone`, `icon`, `payload`, `createdAt`, `time`) and **carries the full stored `AuditEvent.payload`** verbatim. Every audit caller across the codebase keeps API keys / tokens out of the payload, so streaming as-is is safe and matches the locked Phase 4A rule. `latest_events()` returns the freshest 25 rows for the connect snapshot. `publish_audit_event(event)` schedules a `transaction.on_commit` fan-out to the `audit_events` Channels group; both the publish and the schedule call are wrapped in broad `try / except` so a missing Redis / broken Channels layer never breaks the originating DB write.
- **`apps/audit/consumers.py`** — `AuditEventConsumer` (subclass of `AsyncJsonWebsocketConsumer`). On connect it: optionally validates a `?token=<jwt>` query param via the existing simplejwt authenticator (best-effort — connection still accepts on validation failure to keep the dashboard's read-only stream working in dev), joins the `audit_events` group, and pushes an initial `{ "type": "audit.snapshot", "events": [...] }` frame with the latest 25 rows. On every group broadcast it forwards `{ "type": "audit.event", "event": ... }`. Receive is read-only — it only answers a lightweight `{ "type": "ping" }` with `pong`. Disconnect is best-effort group cleanup.
- **`apps/audit/routing.py`** mounts the consumer at `ws://<host>/ws/audit/events/`.
- **Auto-publish on every new AuditEvent** — added a `post_save(sender=AuditEvent)` receiver to `apps/audit/signals.py` that calls `publish_audit_event(instance)` on creation only. Updates are intentionally not streamed.
- **Frontend `services/realtime.ts`** — pure helper module. `buildWebSocketUrl(path?, options?)` derives the WebSocket origin from `VITE_WS_BASE_URL` if set, otherwise from `VITE_API_BASE_URL` (`http`→`ws`, `https`→`wss`, `/api` suffix stripped). `connectAuditEvents({ onSnapshot, onEvent, onStatusChange, onError, token?, path? })` opens the socket, deduplicates events by `id`, exposes a `RealtimeStatus` of `connecting | live | reconnecting | offline`, reconnects with exponential backoff, and never throws to the caller — the Dashboard / Governance pages keep working from the existing polling endpoints when the socket is unreachable.
- **Dashboard activity feed (`/`) — live updates wired**: snapshot replaces the polling-fetched feed; new events prepend with id-deduplication and the list is capped at 25 rows. The "Live Activity" header shows a tone-mapped status pill (`connecting` / `realtime` / `reconnecting` / `polling fallback`).
- **Governance page (`/ai-governance`) — live refresh wired**: when a WebSocket frame arrives whose `kind` starts with `ai.approval.`, `ai.agent_run.approval_requested`, `ai.prompt_version.`, `ai.sandbox.`, or `ai.budget.`, the page re-runs `refresh()` so the approval queue, sandbox state, prompt versions, and budgets stay in sync without polling. The Approval queue header shows the same realtime status pill. **No business logic landed in React** — every Approve / Reject / Execute / activate / sandbox action still goes through the typed API.
- **Backend tests** — 8 new pytest tests in `tests/test_phase4a.py`: serializer carries full payload + camelCase shape, `latest_events()` returns the freshest 25 rows, `publish_audit_event` swallows a broken channel layer, `AuditEvent.objects.create` keeps working when the channel layer raises, the consumer accepts a connection and sends an `audit.snapshot` frame, the consumer forwards `audit.event.broadcast` group messages as `audit.event` frames, `ping` → `pong`, and the existing `GET /api/dashboard/activity/` polling endpoint is unchanged.
- **Frontend tests** — 5 new vitest cases in `src/test/realtime.test.ts` covering `buildWebSocketUrl` for `http→ws`, `https→wss + /api stripping`, `VITE_WS_BASE_URL` override, empty-base fallback, and `?token=…` appending.

**Locked Phase 4A decisions (Prarit, Apr 2026):**
1. WebSocket live updates support both the Dashboard activity feed and the Governance approval queue.
2. Channel layer is Redis-based in production (`CHANNEL_LAYER_BACKEND=redis`) and falls back to the in-memory layer for tests / dev.
3. The WebSocket frame carries the **full stored** `AuditEvent.payload` — no trimming. Existing rule still applies: AuditEvent payloads must never carry secrets.
4. Backend remains the final source of truth.
5. Existing polling endpoints (`/api/dashboard/activity/`, `/api/ai/approvals/`) remain as fallback. The frontend keeps fetching them on initial load and continues to render even when the WebSocket is offline.

**Compliance hard stop preserved (Master Blueprint §26):** the consumer is read-and-fanout only — it never executes business actions, never alters AuditEvent rows, and never bypasses the AgentRun / approval / execution gates already in place. CAIO continues to be blocked at engine + AgentRun bridge + execute layer. Live WhatsApp sender remains pending. Expanded execution registry (discount + sandbox-disable + ad-budget execution) remains pending.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **322 passed** (314 + 8 phase4a) |
| `python manage.py check` | 0 issues |
| `npm test` | **13 passed** (8 + 5 phase4a) |

### ✅ Phase 4D — Approved Action Execution Layer (built this session)

- **New `ApprovalExecutionLog` model** in `apps.ai_governance.models` (separate from `ApprovalDecisionLog` on purpose — decisions log status transitions, executions log execute attempts on top of an already-approved request). Fields: id, approval_request FK, action, status (`executed` / `failed` / `skipped`), executed_by, executed_at, result JSON, error_message, metadata, created_at, updated_at. Partial unique constraint enforces **one `status=executed` row per ApprovalRequest** so re-runs return the prior result without re-invoking the handler. Migration `0006_phase4d_approval_execution_log`.
- **`apps/ai_governance/approval_execution.py`** — the engine. `execute_approval_request` runs a strict pre-check chain (idempotency → CAIO refusal → role gate → status gate) before reaching the **allow-listed registry**. `mark_execution_success` / `mark_execution_failed` / `mark_execution_skipped` each persist a row + write the matching audit. `ExecutionOutcome` dataclass carries the right `http_status` so the view returns 200 / 400 / 403 / 404 / 409 without re-deriving it.
- **Phase 4D execution registry (locked initial set)** — exactly **3 actions** are wired to handlers:
  1. `payment.link.advance_499` → `apps.payments.services.create_payment_link` with the amount **always** resolved to `FIXED_ADVANCE_AMOUNT_INR` (₹499). Tampering with `proposed_payload.amount` is ignored — defense against payload mutation.
  2. `payment.link.custom_amount` → same service path, but executes only after admin approval and requires `amount > 0`.
  3. `ai.prompt_version.activate` → `apps.ai_governance.prompt_versions.activate_prompt_version`. Idempotent: if the version is already active, returns `{ alreadyActive: true }` without re-flipping. Claim Vault grounding remains untouched.
- **Everything else is intentionally unmapped** — `discount.up_to_10`, `discount.11_to_20`, `discount.above_20`, `ai.sandbox.disable`, `ad.budget_change`, `payment.refund`, all `whatsapp.*` actions, all `complaint.*` escalations, `ai.production.live_mode_switch`, etc. Even when an admin / director **approves** these, the execute endpoint returns HTTP 400, persists `status=skipped`, and writes an `ai.approval.execution_skipped` audit row. The registry is an allow-list, not a guess-list.
- **Pre-checks (defense in depth)** — execute will refuse before touching the registry when:
  - Already executed → 200 + prior result, no handler call.
  - `requested_by_agent == "caio"` → 403 + failed log + audit.
  - `metadata.actor_agent == "caio"` → 403 + failed log + audit.
  - Caller is not admin / director → 403.
  - Caller is admin while policy mode is `director_override` → 403.
  - ApprovalRequest status not in `{approved, auto_approved}` → 409.
- **New endpoint** `POST /api/ai/approvals/{id}/execute/`:
  - Anonymous → 401, viewer / operations → 403.
  - Admin / director → allowed for normal modes; director-only on `director_override`.
  - Body: `{ payloadOverride?, note? }`. Caller overrides win over `proposed_payload` for that one execute call (the stored payload itself is not mutated).
  - Response: `{ approvalRequestId, action, executionStatus, executedAt, executedBy, result, errorMessage, message, alreadyExecuted }`.
- **3 new audit kinds** — `ai.approval.executed`, `ai.approval.execution_failed`, `ai.approval.execution_skipped`. Every attempt — success, failure, or skipped — writes both an `ApprovalExecutionLog` row and a Master Event Ledger audit row.
- **`ApprovalRequestSerializer` extended** with `executionLogs[]`, `latestExecutionStatus`, `latestExecutionAt`, `latestExecutionResult`, `latestExecutionError` so the operator UI sees the latest outcome without an extra round-trip. New `ApprovalExecutionLogSerializer` for the nested rows.
- **Frontend Governance page enhanced** — new "Execution" column in the Approval queue table showing the latest execution status pill (executed / failed / skipped) + relative time + error/skip reason. An **Execute** button appears for rows whose `status ∈ {approved, auto_approved}` AND `latestExecutionStatus !== "executed"` (idempotency baked into the UI). Pending / rejected / blocked / escalated / expired / already-executed rows do not show the Execute button. Backend remains the final permission enforcer — the UI just hides the affordance to keep the operator path clean.
- **Frontend types + api.ts** — `ApprovalExecutionLog`, `ApprovalExecutionStatus`, `ExecuteApprovalPayload`, `ExecuteApprovalResponse`. New `api.executeApprovalRequest(id, payload?)` with deterministic mock fallback so dev never crashes when backend is offline.
- **39 new pytest tests** (`tests/test_phase4d.py`) covering: model creation + idempotency constraint, already-executed returns prior result without rerun, every non-approved status → 409, CAIO requested_by_agent → 403, CAIO actor in metadata → 403, advance_499 happy path with `amount=499`, advance_499 ignores tampered amount in payload, advance_499 missing orderId → failed, custom_amount happy path with `amount=1500`, custom_amount pending → 409, custom_amount zero/negative → failed, custom_amount missing amount → failed, prompt_version.activate happy path, prompt_version.activate idempotent on already-active, prompt activation does not drop Claim Vault rows, 4 unmapped admin-eligible actions → skipped, 2 unmapped director_override actions → skipped (with director user), audit kinds emitted on each path, full endpoint role gating (anonymous / viewer / operations all blocked, admin allowed, director allowed), 404 on missing request, 409 on pending, already-executed endpoint returns `alreadyExecuted: true`, director_override blocks admin at the execute layer, ApprovalRequestSerializer surfaces `latestExecutionStatus`.

**Locked Phase 4D decisions (Prarit, Apr 2026):**
1. Initial executable registry has **only 3 actions**: payment.link.advance_499, payment.link.custom_amount, ai.prompt_version.activate.
2. **Discount execution + sandbox-disable execution are NOT in the first 4D pass**. They stay approval-only.
3. **No ad-budget changes**, **no refunds**, **no live WhatsApp** executes from Phase 4D.
4. Backend remains the final permission and policy enforcement layer — the frontend Execute button is a UX affordance, not an authorization mechanism.
5. CAIO can **never** execute. Refused at engine + AgentRun bridge + Phase 4D execute layer.
6. Unmapped approved actions return HTTP 400 + `ai.approval.execution_skipped` audit. The registry is an explicit allow-list.

**Compliance hard stop preserved (Master Blueprint §26):** None of the 3 in-scope handlers generate medical / claim text, so they don't trigger Claim Vault enforcement at the execute layer; the existing AgentRun-layer Claim Vault grounding remains the source of truth for prompt-bound actions. CAIO never executes (triple-guarded). The execute endpoint never silently runs complex business writes — every action is allow-listed by name. Phase 4A WebSockets and live WhatsApp sender remain pending.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **314 passed** (275 + 39 phase4d) |
| `python manage.py check` | 0 issues |

### ✅ Phase 4C — Approval Matrix Middleware enforcement (built this session)

- **Two new models in `apps.ai_governance`** — `ApprovalRequest` (one row per gated business action: id, action, mode, approver, status, requested_by user / agent, target app/model/id, proposed_payload JSON, policy_snapshot JSON, reason, decision_note, decided_by, decided_at, expires_at, created_at, updated_at, metadata) and `ApprovalDecisionLog` (one row per status transition: old_status → new_status with note + decided_by + metadata). Migration `0005_phase4c_approval_matrix`.
- **`apps/ai_governance/approval_engine.py`** — the middleware. `evaluate_action` is pure (no DB, used for previews). `create_approval_request`, `mark_auto_approved`, `enforce_or_queue`, `approve_request`, `reject_request`, `request_approval_for_agent_run`. Mode handling:
  - **auto** → allowed; logged as `auto_approved` for the queue.
  - **auto_with_consent** → allowed only when `payload.customer_consent` or any value in `target.consent` is `True`; otherwise queued.
  - **approval_required** → caller blocked, `pending` ApprovalRequest created.
  - **director_override** → blocked unless `actor_role='director'` AND `payload.director_override=True` AND `payload.override_reason` is non-empty.
  - **human_escalation** → blocked, status `escalated`, no automated path.
  - Unknown action / unknown mode → fail closed.
  - **CAIO actor** → always blocked (`caio_no_execute` note); belt-and-braces on top of the AgentRun layer guard.
- **AgentRun → ApprovalRequest bridge** (`request_approval_for_agent_run`): only succeeds for non-CAIO, `success`-status AgentRuns whose `output_payload` contains `action` (matrix key) and `proposedPayload`. CAIO is refused outright; failed / skipped / unknown-action runs raise `ValueError`. The new ApprovalRequest links back via `metadata.agent_run_id` and writes a `ai.agent_run.approval_requested` audit row.
- **5 new endpoints** under `/api/ai/`:
  - `GET /api/ai/approvals/` — admin/director only. Filters: `status`, `action`, `limit`.
  - `GET /api/ai/approvals/{id}/` — admin/director only. Includes `decisionLogs[]`.
  - `POST /api/ai/approvals/{id}/approve/` — admin/director only. Director-only when policy `mode=director_override`.
  - `POST /api/ai/approvals/{id}/reject/` — admin/director only.
  - `POST /api/ai/approvals/evaluate/` — admin/director only. `persist=False` (default) returns the pure evaluation; `persist=True` runs `enforce_or_queue` and returns the persisted `approvalRequestId`.
  - `POST /api/ai/agent-runs/{id}/request-approval/` — admin/director only. CAIO blocked; failed / skipped runs blocked.
- **Live enforcement wired into 3 high-value paths** (the rest stays auto, intentionally):
  - `POST /api/payments/links/` — routes to `payment.link.advance_499` (auto) when type is Advance and amount is `0` or `₹499`; otherwise to `payment.link.custom_amount` (admin approval). Operations role + custom amount → 403 + queued ApprovalRequest.
  - `POST /api/ai/prompt-versions/{id}/activate/` — calls `mark_auto_approved` for `ai.prompt_version.activate` so the activation appears in the approval queue. (Endpoint is already admin/director-only.)
  - `PATCH /api/ai/sandbox/status/` with `isEnabled=false` — gated through `ai.sandbox.disable` (`director_override`). Admin → 403; director with `director_override=True` and a `note` → allowed.
- **8 new audit kinds** — `ai.approval.requested`, `ai.approval.auto_approved`, `ai.approval.approved`, `ai.approval.rejected`, `ai.approval.blocked`, `ai.approval.escalated`, `ai.approval.expired`, `ai.agent_run.approval_requested`. Every status transition writes an `ApprovalDecisionLog` + a Master Event Ledger audit row.
- **Frontend Governance page enhanced** — new "Approval queue · Phase 4C" table at the bottom of `/ai-governance`: Action / Mode / Approver / Target / Status / Proposed payload preview / Decision controls. Per-row decision-note input + Approve / Reject buttons. Premium Ayurveda + AI SaaS theme. **No business logic in React** — every approve / reject goes through `api.approveApprovalRequest()` / `api.rejectApprovalRequest()`; the backend enforces the role gate.
- **Frontend types + api.ts** — `ApprovalRequest`, `ApprovalDecisionLog`, `ApprovalEvaluationResult`, `ApprovalEvaluatePayload`, `ApprovalRequestStatus`, `ApprovalRequestMode`. New `api.getApprovals()`, `api.getApprovalById()`, `api.approveApprovalRequest()`, `api.rejectApprovalRequest()`, `api.evaluateApprovalAction()`, `api.requestAgentRunApproval()` with deterministic mock fallback so dev never crashes when backend is offline.
- **31 new pytest tests** (`tests/test_phase4c.py`) covering all 5 matrix modes (auto / auto_with_consent / approval_required / director_override / human_escalation / unknown / caio_actor), persistence + policy snapshot, approve / reject transitions + audit, director-only override, can't-approve-already-decided, AgentRun bridge happy path + CAIO blocked + failed / skipped / missing-action / unknown-action all rejected, full role gating across the 5 endpoints, and live enforcement smoke for payment-link advance / custom-amount + sandbox-disable. The Phase 3D sandbox-disable test was tightened to match the new enforcement (admin can no longer flip sandbox off without director_override).

**Locked Phase 4C decisions:**
1. The approval matrix is the **single source of truth**. Views / services call `enforce_or_queue` instead of duplicating policy.
2. Approval **never silently executes** the underlying business write. `approve_request` flips status to `approved` and writes audits; the actual write still flows through its existing tested service path (Phase 4D will add explicit safe execution paths action-by-action).
3. CAIO can never request an executable approval — refused at the AgentRun bridge AND at the matrix evaluation step.
4. Phase 4C ships only enforcement on 3 controlled high-value paths (custom-amount payment link, prompt activation, sandbox disable). Other normal workflows (lead create / call trigger / ₹499 advance / Delhivery dispatch / RTO rescue / 0–10% discount) stay auto per matrix.

**Compliance hard stop preserved (Master Blueprint §26):** The Approved Claim Vault check still runs at the AgentRun layer — failed / skipped runs cannot be promoted. CAIO never executes (double-guarded at engine + bridge). The middleware fails closed on unknown actions / modes. No business logic landed in React. Live WhatsApp sender + Phase 4A WebSockets remain pending.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **275 passed** (244 + 31 phase4c) |
| `python manage.py check` | 0 issues |

### ✅ Phase 4B — Reward / Penalty Engine wiring (built this session)

- **`apps.rewards` extended**: new `RewardPenaltyEvent` model (per-order, per-AI-agent scoring event with `unique_key` for idempotency, `components` / `missing_data` / `attribution` JSON, `event_type` reward/penalty/mixed). `RewardPenalty` rollup row gains Phase 4B fields (`agent_id`, `agent_type`, `rewarded_orders`, `penalized_orders`, `last_calculated_at`). Migration `0002_phase4b_reward_events`.
- **`apps/rewards/engine.py`** — the wiring layer. `build_reward_context(order)` derives only signals provable from the DB (no inventions); `calculate_for_order(order, ...)` calls the Phase 3E pure scoring formula then **fans the result across the 10 in-scope AI agents** (CEO AI / Ads / Marketing / Sales Growth / Calling AI / Confirmation AI / RTO / Customer Success / Data Quality / Compliance). Sweep helpers: `calculate_for_delivered_orders`, `calculate_for_failed_orders`, `calculate_for_all_eligible_orders` (delivered + RTO + cancelled), `rebuild_agent_leaderboard`. Eligible stages: `Delivered` (rewards), `RTO` + `Cancelled` (penalties). Other stages skipped.
- **CEO AI net accountability rule (locked)** — every delivered order generates a CEO AI **reward** event mirroring the order's reward total; every RTO / cancelled order generates a CEO AI **penalty** event mirroring the order's penalty total. Always present, every sweep.
- **CAIO excluded** — `EXCLUDED_AGENTS = {"caio"}` and CAIO is intentionally absent from `AI_AGENT_BY_ID`. CAIO never receives a business reward / penalty.
- **Idempotency** — `unique_key` `phase4b_engine:{order_id}:{agent_id}:{event_type}` is enforced as a unique DB constraint. Re-running the sweep updates rows in place; the response surfaces `createdEvents` vs `updatedEvents`.
- **3 backend endpoints** (under `/api/rewards/`):
  - `GET /api/rewards/events/` — admin/director only. Filters: `agent`, `orderId`, `eventType`, `limit`.
  - `GET /api/rewards/summary/` — admin/director only. Returns `evaluatedOrders`, `totalReward`, `totalPenalty`, `netScore`, `lastSweepAt`, `agentLeaderboard`, `missingDataWarnings`.
  - `POST /api/rewards/sweep/` — admin/director only. Body `{ startDate?, endDate?, orderId?, dryRun? }`. Anonymous → 401, viewer / operations → 403.
  - `GET /api/rewards/` is unchanged in shape (the legacy leaderboard list); new fields ride alongside as optional camelCase keys for forward compat.
- **Management command** `python manage.py calculate_reward_penalties` with `--start-date`, `--end-date`, `--order-id`, `--dry-run`, `--rebuild-leaderboard` flags. No Redis required.
- **Celery task** `apps.rewards.tasks.run_reward_penalty_sweep_task` runs the all-eligible sweep + leaderboard rebuild. Eager-mode safe; production Celery worker / beat will pick it up unchanged.
- **6 new audit kinds** — `ai.reward.calculated`, `ai.penalty.applied`, `ai.reward_penalty.sweep_started` / `.sweep_completed` / `.sweep_failed` / `.leaderboard_updated`. The engine never spams the ledger: per-order events are persisted on the `RewardPenaltyEvent` table, while sweep lifecycle + leaderboard rebuild are summarized as audit rows.
- **Frontend Rewards page enhanced** — agent-wise leaderboard table (Agent / Type / Reward / Penalty / Net / +Orders / −Orders / Last calculated), order-wise scoring events table (Order / Agent / Type / Reward / Penalty / Net / Components / Missing / Calculated), 4 sweep summary cards (Reward total / Penalty total / Net AI score / Last sweep time + Run sweep + Dry run buttons), missing-data warnings strip. **No business logic in React** — every value comes from the API; the Run Sweep button calls `POST /api/rewards/sweep/` and refreshes the three derived views.
- **Frontend types + api.ts** — `RewardPenaltyEvent`, `RewardPenaltySummary`, `RewardPenaltySweepPayload`, `RewardPenaltySweepResult` typed; new methods `api.getRewardPenaltyEvents()`, `api.getRewardPenaltySummary()`, `api.runRewardPenaltySweep()` with deterministic mock fallback so dev never crashes when backend is offline.
- **25 new pytest tests** (`tests/test_phase4b.py`) covering: per-order event creation, idempotent re-runs, delivered → CEO reward, RTO → CEO penalty, cancelled → CEO penalty, CAIO excluded, AI-agents-only scope, missing data recorded (not invented), reward / penalty caps respected, full sweep idempotency, audit firing, dry-run no-persistence, leaderboard rebuild, management command (incl. `--dry-run` + `--order-id`), Celery task in eager mode, public list endpoint camelCase, admin-only events / summary endpoints, sweep endpoint role gating (anonymous / viewer / operations all blocked, admin / director allowed), sweep with `orderId`, sweep dry-run no-persist.

**Locked Phase 4B decisions (Prarit, Apr 2026):**
1. Reward / penalty scoring is **AI-agents only** in this phase — no human staff scoring.
2. Every RTO / cancelled order penalty **always** routes a CEO AI net accountability event.
3. The Rewards page must show **both** the agent-wise leaderboard **and** the order-wise scoring events.

**Compliance hard stop preserved (Master Blueprint §26):** The engine is read-and-derive only. It NEVER writes to Lead / Order / Payment / Shipment / Call rows. Reward / penalty is based on **delivered profitable quality orders**, never on order-punching count alone. Missing signals are recorded explicitly in `missing_data`; nothing is invented. CAIO remains audit-only. Phase 4A WebSockets, Phase 4C approval middleware, and live WhatsApp sender are still pending.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **244 passed** (219 + 25 phase4b) |
| `python manage.py check` | 0 issues |

### ✅ Phase 3E — Business Configuration Foundation (built this session)

- **New `apps.catalog` Django app** — `ProductCategory`, `Product`, `ProductSKU` models with admin/director-managed CRUD via Django admin (`ProductSKUInline` under Product), public read endpoints + admin/director-gated write endpoints under `/api/catalog/`. Migration `0001_initial`.
- **Read endpoints**: `GET /api/catalog/categories/`, `GET /api/catalog/products/` (with nested `skus`), `GET /api/catalog/products/{id}/`, `GET /api/catalog/skus/?productId=...`. Reads stay public; writes are admin/director-only via `RoleBasedPermission` (anonymous → 401, viewer/operations → 403).
- **Write endpoints**: `POST/PATCH/PUT/DELETE` on the same routes. Each successful write fires a `catalog.{category,product,sku}.{created,updated}` audit event.
- **Discount policy** at `apps/orders/discounts.py`: `validate_discount(discount_pct, actor_role, approval_context=None) → DiscountValidationResult`. **Locked bands**: 0–10% auto, 11–20% requires CEO AI / admin / director approval, > 20% blocked unless director override (`actor_role='director'` + `approval_context['director_override']=True`). Director ceiling 50%. Negative / unknown role / over-100% → blocked.
- **Advance payment policy** at `apps/payments/policies.py`: `FIXED_ADVANCE_AMOUNT_INR = 499` + `resolve_advance_amount()`. The `Advance` payment type now defaults to ₹499 when the caller omits `amount` (or sends 0). Non-Advance types still require an explicit positive value. The `PaymentLinkSerializer` was widened to accept missing `amount`.
- **Reward / Penalty deterministic scoring** at `apps/rewards/scoring.py`: `calculate_order_reward_penalty(order, context=None)` returns an `OrderRewardPenaltyResult` dataclass with capped totals (+100 reward / -100 penalty). 7 reward components (delivered, healthy_net_profit, advance_paid, customer_satisfaction_positive, reorder_potential_high, clean_data, compliance_safe) and 10 penalty components (rto_after_dispatch, cancelled_after_punch, wrong_or_incomplete_address, no_advance_high_risk_cod, discount_leakage_11_to_20_without_reason, unauthorized_discount_above_20, risky_claim, side_effect_legal_refund_mishandled, ignored_rto_warning, bad_fake_lead_quality). Missing data is recorded explicitly — never invented. Phase 4B will wire this into the engine + leaderboard rollup.
- **Approval matrix** at `apps/ai_governance/approval_matrix.py`: 22-row policy table mapping every action (lead create, payment-link advance, order punch, every discount band, dispatch, RTO rescue, all WhatsApp message types, refund, ad budget change, prompt activation, sandbox disable, production live-mode switch, medical / side-effect / legal escalations) to its `approver` + `mode` (`auto`, `auto_with_consent`, `approval_required`, `director_override`, `human_escalation`). Public read endpoint `GET /api/ai/approval-matrix/`. Phase 4C middleware will enforce the table.
- **WhatsApp design scaffold** at `apps/crm/whatsapp_design.py`: 9 supported message types (follow-up / payment_reminder / confirmation_reminder / delivery_reminder / rto_rescue / usage_explanation / support_complaint / reorder_reminder / broadcast_campaign), consent + admin-approval flags, audit kinds. Live integration intentionally NOT implemented in Phase 3E — Phase 4+ wires the actual sender / receiver. The scaffold encodes the policy reminders: consent required, no medical claims outside the Approved Claim Vault, mandatory human escalation for refund / legal / side-effect threats, every send writes an `AuditEvent`.
- **12 new audit kinds**: `catalog.category.{created,updated}`, `catalog.product.{created,updated}`, `catalog.sku.{created,updated}`, `discount.{requested,approved,blocked}`, `approval.required`, `whatsapp.{message_queued,broadcast.requested,escalation.requested}`.
- **29 new pytest tests** (`tests/test_phase3e.py`) cover catalog read endpoints (camelCase) + admin/director write gate (anonymous 401, viewer 403, operations 403, admin 201) + audit firing on every catalog write, discount policy across all bands (auto / approval / director-override / blocked / negative / over-100 / unknown role), the `₹499 default` resolved by `POST /api/payments/links/` when amount is omitted, reward/penalty cap math (sum > 100 capped at 100 for both), missing-data recording, simple delivered-order success path, approval matrix endpoint shape, director-override mapping for above-20 discount, WhatsApp scaffold contracts, and **the compliance hard stops still hold** (CAIO `intent: execute` → `failed`, ClaimVaultMissing for medical agents → `failed` before any LLM dispatch).

**Compliance hard stop (Master Blueprint §26 #4):** Phase 3E adds policy and config — it never relaxes the §26 hard stops. Catalog rows are metadata only; AI medical content still flows from `apps.compliance.Claim`. The discount policy never speaks medical claims. The reward/penalty scoring never invents missing data. The approval matrix encodes who can do what but does NOT execute anything (Phase 4C middleware will). The WhatsApp scaffold is design-only — no live sends. CAIO is still hard-stopped.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **219 passed** (190 + 29 phase3e) |
| `python manage.py check` | 0 issues |

### ✅ Phase 3D — Sandbox + Prompt Rollback + Budget Guards (built this session)

- **PromptVersion model** (`apps.ai_governance.models.PromptVersion`) — versioned prompt content per agent: `id`, `agent`, `version`, `title`, `system_policy`, `role_prompt`, `instruction_payload`, `is_active`, `status` (draft/sandbox/active/rolled_back/archived), `created_by`, `metadata`, `created_at`, `activated_at`, `rolled_back_at`, `rollback_reason`. DB partial-unique constraint enforces "one active per agent".
- **AgentBudget model** — per-agent daily + monthly USD caps with `is_enforced` flag and `alert_threshold_pct`. Spend is computed at runtime by summing successful `AgentRun.cost_usd`.
- **SandboxState singleton** (`apps.ai_governance.models.SandboxState`) — DB-backed toggle seeded from `settings.AI_SANDBOX_MODE`. PATCH endpoint flips the row and writes audit. While ON: every successful AgentRun is stamped `sandbox_mode=True` and the CEO success path skips `CeoBriefing` refresh — no business-state mutation.
- **AgentRun extended** (migration `0004_phase3d_sandbox_prompts_budgets`): `sandbox_mode`, `prompt_version_ref` FK to PromptVersion, `budget_status`, `budget_snapshot`.
- **Prompt builder integration** — `build_messages` accepts an optional active PromptVersion. When supplied, its `system_policy` and `role_prompt` blocks override the defaults. The Approved Claim Vault block is **always** appended on top — a custom PromptVersion CANNOT skip it.
- **Budget guard** (`apps.ai_governance.budgets`) runs in `run_readonly_agent_analysis` BEFORE prompt building and dispatch:
  1. Block when daily / monthly cap is exceeded → write `ai.budget.blocked` audit, persist a `failed` AgentRun, **never trigger provider fallback**.
  2. Warning at `alert_threshold_pct` → write `ai.budget.warning` audit; run still proceeds.
  3. Snapshot stamped on every `AgentRun.budget_snapshot`.
- **9 new endpoints** under `/api/ai/{sandbox,prompt-versions,budgets}/*` (admin/director only): GET/PATCH sandbox status, list/create/retrieve/activate/rollback prompt versions, list/upsert/patch agent budgets. Budget list/upsert decorate the response with `dailySpendUsd` + `monthlySpendUsd`.
- **7 new audit kinds**: `ai.prompt_version.{created,activated,rolled_back}`, `ai.sandbox.{enabled,disabled}`, `ai.budget.{warning,blocked}`.
- **Frontend Governance page** at `/ai-governance` (under "AI Layer" in the sidebar). Shows the sandbox toggle, per-agent prompt version list with one-click Activate / Rollback, and per-agent daily/monthly budget editor showing live spend. No business logic in the frontend — every state change goes through the typed `api.ts` calls. Frontend never receives provider keys.
- **CAIO is still hard-stopped** — the existing `CAIO_FORBIDDEN_INTENTS` guard runs before any of the new code paths and still refuses execution intents.
- **15 new pytest tests** cover PromptVersion CRUD + activation flip + rollback (with audit reason + audit event), sandbox endpoint perms + audit, sandbox-mode CeoBriefing skip on a successful CEO run, active prompt version injection (with custom system_policy / role_prompt + Claim Vault still appended), budget block path (no provider fallback), budget warning path with allowed run, ClaimVaultMissing still failing closed before any adapter is called, CAIO refusal under the new guards, and AgentBudget upsert + admin-only perms.

**Compliance hard stop (Master Blueprint §26 #4):** PromptVersion content cannot bypass the Approved Claim Vault — every prompt still attaches the relevant Claim entries on top of any custom system policy. CAIO remains read-only in every sandbox / budget / prompt state. Budget blocks fail closed and never trigger the provider fallback chain. ClaimVaultMissing still fails before any adapter dispatch. Phase 3D remains dry-run by construction; the only path that will turn an AgentRun suggestion into a business write is the future approval-matrix middleware.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **190 passed** (175 + 15 phase3d) |
| `python manage.py check` | 0 issues |

### ✅ Phase 3C — Celery Scheduler + Cost Tracking + Fallback (built earlier this session)

- **Celery app** at `backend/config/celery.py` autoloads via `config/__init__.py`. Local dev runs in eager mode (`CELERY_TASK_ALWAYS_EAGER=true`) — Redis is not required for `pytest` / `manage.py check` / day-to-day development. Production cron starts `celery -A config worker -B`.
- **Beat schedule** fires `apps.ai_governance.tasks.run_daily_ai_briefing_task` at **09:00 IST** (morning) and **18:00 IST** (evening). Hours / minutes are env-driven (`AI_DAILY_BRIEFING_*`). The task wraps the existing Phase 3B `ceo.run` + `caio.run` services, so the scheduler shares the same compliance and CAIO hard-stops.
- **Local Redis** via `docker-compose.dev.yml` (Redis 7 alpine on 6379). VPS Redis is **never** used in development.
- **Model-wise pricing table** at `backend/apps/integrations/ai/pricing.py` covering OpenAI (gpt-5.2 / 5.1 / 5 / 5-mini / 5-nano / 4.1 family) and Anthropic (Claude Sonnet 4.5/4.6 + Opus 4.5/4.6). Costs are computed in `Decimal` (per-1M-token rates) and the rate sheet used at the time of the call is stored on every AgentRun in `pricing_snapshot`. Pricing must be reviewed periodically against the official provider pages — the file documents this and the source.
- **Provider fallback chain** in `apps/integrations/ai/dispatch.py`. The dispatcher walks `AI_PROVIDER_FALLBACKS` (default `openai → anthropic`) left → right; the first provider whose adapter returns `success` wins. Adapters are looked up at call time so `mock.patch` continues to work for tests. Every attempt — successful, failed, or skipped — is recorded in `provider_attempts` (provider / model / status / error / latency / tokens / cost). `fallback_used=True` whenever a non-first provider answered.
- **AgentRun model** extended (migration `0003_agentrun_cost_tracking`) with `prompt_tokens`, `completion_tokens`, `total_tokens`, `provider_attempts`, `fallback_used`, `pricing_snapshot`. The Phase 3A `cost_usd` decimal column is preserved.
- **OpenAI + Anthropic adapters** extract token usage (including OpenAI cached-input + Anthropic cache-creation/cache-read variants) and compute `cost_usd` via the pricing table. Lazy SDK imports kept; disabled / no-key path still returns `skipped` without any network.
- **`GET /api/ai/scheduler/status/`** (admin/director only) returns the Celery / Redis / schedule / fallback / last-cost snapshot. Broker credentials are redacted (`redis://***@host`) before the response leaves the server.
- **5 new audit kinds**: `ai.scheduler.daily_briefing.started` / `.completed` / `.failed`, `ai.provider.fallback_used`, `ai.cost_tracked`. The fallback + cost events fire from `complete_agent_run` so every dispatched run leaves a paper trail.
- **Frontend Scheduler Status page** at `/ai-scheduler` (under "AI Layer" in the sidebar). Premium Ayurveda + AI SaaS theme. Pure read; no business logic. Surfaces Celery + Redis state, both schedule slots, primary provider + model, fallback order, last CEO briefing run, last CAIO sweep, last cost in USD, last fallback flag. The frontend never receives any provider API key.
- **`AgentRun` TypeScript type widened** with `promptTokens`, `completionTokens`, `totalTokens`, `providerAttempts`, `fallbackUsed`, `pricingSnapshot` (all optional for backward compat).
- **17 new pytest tests** cover Celery eager mode (task runs synchronously and writes the started/completed audit events), beat schedule env-var parsing, scheduler-status perms (admin allowed; viewer / operations / anonymous all blocked), broker URL credential redaction, the disabled-provider no-network path, cost tracking persistence on AgentRun, OpenAI + Anthropic pricing math (including cached-input / cache-write / cache-read variants and unknown-model `None` cost), the fallback path triggered when OpenAI fails, the no-fallback path when first provider succeeds, ClaimVaultMissing **not** triggering a fallback (failure logged before any adapter is called), and the CAIO hard stop surviving the dispatcher refactor.

**Compliance hard stop (Master Blueprint §26 #4):** ClaimVaultMissing fails closed before any adapter is invoked — fallback chains do **not** mask compliance refusals. CAIO never executes; the runtime payload contains no execution intents and the existing `CAIO_FORBIDDEN_INTENTS` guard refuses any leaked intent before the LLM is called. Phase 3C remains dry-run by construction; the only path that will ever turn an AgentRun suggestion into a business write is the Phase 5 approval-matrix middleware.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **175 passed** (158 + 17 phase3c) |
| `python manage.py check` | 0 issues |

### ✅ Phase 3B — Per-agent Runtime Services (built earlier this session)

- **Per-agent service modules** under `apps/ai_governance/services/agents/`: `ceo.py`, `caio.py`, `ads.py`, `rto.py`, `sales_growth.py`, `cfo.py`, `compliance.py`. Each exposes `build_input_payload()` (safe read-only DB slice — counts, aggregations, recent rows) and `run(triggered_by="")` that dispatches through the existing `run_readonly_agent_analysis`.
- **Package conversion**: `apps/ai_governance/services.py` → `apps/ai_governance/services/__init__.py` to host the new `services/agents/` subpackage. Existing imports (`from apps.ai_governance.services import run_readonly_agent_analysis`) keep working.
- **CEO success path** updates the `CeoBriefing` row only when the LLM returns a non-empty `summary` — skipped/failed runs leave the existing briefing untouched. Recommendations array is also persisted into `CeoRecommendation` rows. Writes a wrapping `ai.ceo_brief.generated` audit row.
- **CAIO** stays read-only by construction. Its payload is pulled from the AgentRun ledger + handoff flags + Claim Vault status — none of those keys overlap with `CAIO_FORBIDDEN_INTENTS`, so the existing Phase 3A guardrail keeps the LLM call from being asked to write anywhere.
- **Compliance** runtime fails closed when the Claim Vault is empty (the prompt builder raises `ClaimVaultMissing` → `failed` AgentRun + danger-tone audit row).
- **8 new endpoints** under `/api/ai/agent-runtime/*` (admin/director only via the same `_AdminAndUpAlways` permission used by `/api/ai/agent-runs/`):
  - `GET /api/ai/agent-runtime/status/` — phase + dry-run flag + last `AgentRun` per agent.
  - `POST /api/ai/agent-runtime/{ceo|caio|ads|rto|sales-growth|cfo|compliance}/...` — each runs its agent and returns the persisted `AgentRun`.
- **Management command** `python manage.py run_daily_ai_briefing` calls CEO + CAIO in one shot (`--skip-ceo` / `--skip-caio` to run just one). No Redis / Celery dependency — wires straight to cron / Windows Task Scheduler. Phase 3C upgrades to Celery beat once Redis is available.
- **Audit kinds** added: `ai.ceo_brief.generated` (success), `ai.caio_sweep.completed` (info), `ai.agent_runtime.completed` (success/info), `ai.agent_runtime.failed` (danger).
- **Frontend** `AgentRuntimeStatus` type + 8 `api.*` methods (one per endpoint) with offline-safe optimistic stubs. No page changes needed — Phase 3C can wire a UI on top.
- **26 new pytest tests** cover each agent's payload shape (Meta attribution, RTO data, calls/orders/payments, Claim Vault grounding), the CEO success path refreshing `CeoBriefing`, the CEO skipped path leaving the existing briefing untouched, the compliance fail-closed when the vault is empty, the permission gates (anonymous / viewer / operations all blocked across all 7 endpoints, admin / director allowed), the status endpoint surfacing the last run per agent, the management command (with `--skip-caio` variant), and the wrapping `ai.agent_runtime.completed` / `ai.agent_runtime.failed` audit events firing on the right paths.

**Compliance hard stop (Master Blueprint §26 #4):** CAIO never executes — the runtime payload contains no execution intents, the prompt builder reminds the model, and `services.run_readonly_agent_analysis` would refuse one anyway. Compliance runtime never generates new medical claims; it only summarises Claim Vault coverage. Phase 3B is dry-run by construction; the only path that will ever turn an AgentRun suggestion into a business write is the Phase 5 approval-matrix middleware.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **158 passed** (132 + 26 phase3b) |
| `python manage.py check` | 0 issues |

### ✅ Phase 3A — AgentRun Foundation + AI Provider Adapters (built earlier this session)

- **AgentRun model** (`apps/ai_governance/models.py`) — every LLM dispatch is logged: `id`, `agent`, `prompt_version`, `input_payload`, `output_payload`, `status` (`pending`/`success`/`failed`/`skipped`), `provider`, `model`, `latency_ms`, `cost_usd`, `error_message`, `dry_run`, `triggered_by`, `created_at`, `completed_at`. Migration `0002_agentrun`.
- **Provider adapters** under `apps/integrations/ai/`: `base.py` (Adapter protocol + `AdapterResult` dataclass + `skipped_result` helper), `openai_client.py`, `anthropic_client.py`, `grok_client.py` (Grok reuses the OpenAI SDK pointed at `https://api.x.ai/v1`). Every adapter lazy-imports its SDK and short-circuits with `skipped` when `current_config().enabled` is False — disabled / no-key path never touches the network. `dispatch.py` is the single seam the agent service calls.
- **Prompt builder** (`apps/ai_governance/prompting.py`) — assembles a fixed system policy block (the §26 hard stops verbatim, blocked phrases enumerated), agent role block, **Approved Claim Vault grounding** (relevant `apps.compliance.Claim` rows), and the JSON-coerced input payload. Raises `ClaimVaultMissing` when a medical/product run has no approved claims, so the call site logs a `failed` AgentRun rather than dispatching a hallucinated answer. Heuristic `needs_claim_vault` covers both agent type (compliance/ceo/caio/marketing/sales_growth always need it) and payload-text triggers (`product`, `claim`, `medicine`, `script`, `creative`, etc.).
- **Services** (`apps/ai_governance/services.py`): `create_agent_run`, `complete_agent_run`, `fail_agent_run`, and the high-level `run_readonly_agent_analysis` which builds prompt → dispatches → persists. **CAIO hard stop** — payloads carrying `execute`, `apply`, `create_order`, `transition`, `assign_lead`, `approve` (etc.) are refused before any LLM call, with a `failed` AgentRun + danger-tone audit row.
- **New endpoint** `POST /api/ai/agent-runs/` — admin/director only via a tightened `_AdminAndUpAlways` permission (reads also gated). Body `{ agent, input, dryRun? }`. Phase 3A coerces `dryRun` to `true` server-side; non-dry-run requests at the service level fail with a row pointing at the Phase 5 approval-matrix milestone. `GET /api/ai/agent-runs/` list + `/{id}/` detail.
- **Audit kinds** added: `ai.agent_run.created` (info), `ai.agent_run.completed` (success or info), `ai.agent_run.failed` (danger).
- **Frontend** `AgentRun` + `AgentRunCreatePayload` types and `api.listAgentRuns()` / `getAgentRun()` / `createAgentRun()` with offline-safe optimistic stub returning a `skipped` draft so dev never crashes when the backend is offline. No page changes needed.
- **25 new pytest tests** cover provider routing (disabled/openai/anthropic/grok with patched adapters — real SDKs never imported), missing-key skip path, list/detail endpoints, anonymous/viewer/operations/admin gates, CAIO no-execute refusals (`intent: execute` and `create_order: {...}` payloads), Claim Vault enforcement (vault attached when seeded, refused when empty, skipped for non-medical agents, blocked when payload mentions products and vault is empty), audit firing for create/complete/fail, dry-run guard, and unit-level adapter skips.

**Compliance hard stop (Master Blueprint §26 #4):** No prompt is dispatched without Approved Claim Vault grounding for medical/product content. CAIO is wired so even the call signature refuses execution intents — the LLM never sees them. Phase 3A is read-only by construction; even if a model suggests an action, the runtime won't execute it until the Phase 5 approval-matrix middleware is built.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **132 passed** (107 + 25 phase3a) — pre-Phase-3B snapshot |
| `python manage.py check` | 0 issues |

### ✅ Phase 2E — Meta Lead Ads Webhook (built earlier this session)

- Three-mode adapter at `backend/apps/crm/integrations/meta_client.py` (`mock` | `test` | `live`). Mock parses the inbound payload as-is (no network); `test` / `live` lazy-import `requests` and call Meta's Graph API to expand each `leadgen_id`.
- New endpoint `GET /api/webhooks/meta/leads/` answers Meta's subscription handshake when `hub.mode == "subscribe"` and `hub.verify_token == META_VERIFY_TOKEN`. Mismatch / missing token → 403.
- New endpoint `POST /api/webhooks/meta/leads/` verifies `X-Hub-Signature-256` (HMAC-SHA256 of the raw body) against `META_WEBHOOK_SECRET` (or `META_APP_SECRET` as fallback). Empty secret → signature check skipped so dev fixtures stay simple. Each delivered leadgen upserts a `Lead` row, writes a `lead.meta_ingested` AuditEvent, and inserts a `crm.MetaLeadEvent` row keyed on `leadgen_id` for idempotency. Re-deliveries of the same `leadgen_id` return 200 with `action: duplicate` and never duplicate the Lead.
- `Lead` model gains optional `meta_leadgen_id` (db_indexed), `meta_page_id`, `meta_form_id`, `meta_ad_id`, `meta_campaign_id`, `source_detail`, `raw_source_payload` via migration `0002_phase2e_meta_fields`. New `MetaLeadEvent` model holds the per-leadgen idempotency log + raw payload + status (ok / error).
- LeadSerializer now exposes the camelCase Meta fields (read-only) so the frontend can show attribution. Frontend `Lead` type widened with the same optional fields; no page changes needed.
- 13 new pytest tests cover GET handshake (correct token / wrong token / unset token), POST mock create with full Meta-shaped payload, idempotency on `leadgen_id`, signature verification (good / bad / missing / app-secret fallback / no-secret-skipped), AuditEvent firing, test-mode Graph API expansion (`_fetch_lead_via_graph` patched), refresh-not-duplicate, signature helper round-trip, empty payload.
- New env vars: `META_MODE`, `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_PAGE_ACCESS_TOKEN`, `META_GRAPH_API_VERSION` (default `v20.0`), `META_WEBHOOK_SECRET`. All secrets stay server-side.
- `audit.signals.ICON_BY_KIND` extended with `lead.meta_ingested`.

**Compliance hard stop (Master Blueprint §26 #4):** the Meta payload is persisted verbatim into `Lead.raw_source_payload` for attribution but never injected into AI prompts. Any future prompt-builder MUST pull medical content only from `apps.compliance.Claim`. CAIO never executes business actions; nothing in this pipeline routes through CAIO.

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **107 passed** (93 + 14 meta) |
| `python manage.py check` | 0 issues |

### ✅ Phase 2D — Vapi Voice Trigger + Transcript Ingest (built earlier this session)

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
cd backend && python -m pytest -q   # 434 tests (Phase 1 → 5B inclusive — see test_phaseNN.py files)

# Frontend
cd frontend && npm test             # 13 tests
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

### ✅ Phase 1 — Foundation (DONE)
14 apps · 25 endpoints · seed · audit ledger · auth · CORS · tests. See §8.

### ✅ Phase 2A — Core Write APIs + Workflow State Machine (DONE)
13 write endpoints · service layer · order state machine · `RoleBasedPermission` · 18 new tests · mock payment + shipment + RTO rescue. See §8.

### ✅ Phase 2B — Razorpay payment-link integration (DONE)
Three-mode adapter, HMAC-verified webhook, idempotency, 13 new tests. See §8.

### ✅ Phase 2C — Delhivery courier integration (DONE)
Three-mode adapter, HMAC-verified tracking webhook, NDR / RTO risk handling, 13 new tests. See §8.

### ✅ Phase 2D — Vapi voice trigger + transcript ingest (DONE)
Three-mode adapter, `POST /api/calls/trigger/`, HMAC-verified webhook, six handoff flags, keyword fallback, 14 new tests. See §8.

### ✅ Phase 2E — Meta Lead Ads webhook (DONE)
Three-mode adapter, GET subscription handshake, signed POST webhook, idempotent leadgen ingest, 13 new tests. See §8.

### ✅ Phase 3A — AgentRun foundation + AI provider adapters (DONE)
AgentRun model + 4 provider adapters (OpenAI / Anthropic / Grok / disabled) + Claim-Vault-enforced prompt builder + CAIO hard stop + admin/director-only `/api/ai/agent-runs/` endpoint, 25 new tests. See §8.

### ✅ Phase 3B — Per-agent runtime services (DONE)
7 agent modules (CEO / CAIO / Ads / RTO / Sales Growth / CFO / Compliance) + 8 admin-only runtime endpoints + `run_daily_ai_briefing` management command + `CeoBriefing` refresh on CEO success, 26 new tests. See §8.

### ✅ Phase 3C — Celery scheduler + cost tracking + fallback (DONE)
Celery beat at 09:00 + 18:00 IST + provider fallback chain (OpenAI → Anthropic) + model-wise USD cost tracking + frontend Scheduler Status page, 17 new tests. See §8.

### ✅ Phase 3D — Sandbox + prompt rollback + budget guards (DONE)
SandboxState singleton + versioned PromptVersion (one active per agent + rollback) + per-agent USD budget caps with warning + block + Governance page, 15 new tests. See §8.

### ✅ Phase 3E — Business configuration foundation (DONE)
Product Catalog admin (`apps.catalog`) + discount policy (10/20% bands) + ₹499 fixed advance + reward/penalty deterministic scoring (capped at +100/-100) + approval matrix policy table + WhatsApp sales/support design scaffold + production infra targets documented, 29 new tests. See §8.

### ✅ Phase 4B — Reward / Penalty Engine wiring (DONE)
`RewardPenaltyEvent` model + `apps.rewards.engine` (AI-agents-only attribution, CEO AI net accountability rule) + `/api/rewards/{events,summary,sweep}/` endpoints + `calculate_reward_penalties` management command + `run_reward_penalty_sweep_task` Celery task + Rewards page upgraded with leaderboard / events / sweep button, 25 new tests. See §8.

### ✅ Phase 4C — Approval Matrix Middleware enforcement (DONE)
`ApprovalRequest` + `ApprovalDecisionLog` models + `apps.ai_governance.approval_engine` (`evaluate_action` / `enforce_or_queue` / `approve_request` / `reject_request` / AgentRun bridge) + 5 new admin/director endpoints + live enforcement on payment-link custom-amount, prompt activation, and sandbox-disable + Governance page approval queue with Approve / Reject buttons, 31 new tests. See §8.

### ✅ Phase 4D — Approved Action Execution Layer (DONE)
`ApprovalExecutionLog` model + `apps/ai_governance/approval_execution.py` with allow-listed registry of 3 handlers (payment.link.advance_499, payment.link.custom_amount, ai.prompt_version.activate) + `POST /api/ai/approvals/{id}/execute/` endpoint + `executionLogs` / `latestExecutionStatus` on the `ApprovalRequestSerializer` + Governance page Execute button + 39 new tests. CAIO blocked at engine + bridge + execute layer; unmapped actions return 400 + `ai.approval.execution_skipped`. See §8.

### ✅ Phase 4A — Real-time AuditEvent WebSockets (DONE)
Django Channels + channels_redis + daphne wired with `ProtocolTypeRouter`. New WebSocket endpoint `/ws/audit/events/` carries the **full stored AuditEvent.payload** verbatim. `apps/audit/realtime.py` publishes via `transaction.on_commit` (publish failures swallowed — never breaks underlying DB writes). `apps/audit/consumers.py` sends an initial `audit.snapshot` frame (latest 25 rows) on connect and forwards every new AuditEvent as `audit.event`. Dashboard "Live Activity" feed and Governance "Approval queue" both auto-refresh on relevant events. Existing polling endpoints (`/api/dashboard/activity/`, `/api/ai/approvals/`) remain as fallback. Frontend `services/realtime.ts` derives the WebSocket origin from `VITE_API_BASE_URL` (or `VITE_WS_BASE_URL` override), reconnects with exponential backoff, deduplicates by id, and never throws. 8 new backend tests + 5 new frontend tests.

### ✅ Phase 4E — Expanded Approved Execution Registry (DONE)
Three new handlers wired into `apps/ai_governance/approval_execution.py`: `discount.up_to_10` and `discount.11_to_20` apply through a new `apps.orders.services.apply_order_discount` (mutates only `Order.discount_pct`, validates via `validate_discount`, writes `discount.applied` audit), `ai.sandbox.disable` flips the SandboxState singleton via the existing helper (Director-only via matrix `director_override`, idempotent on already-off). `discount.above_20` + ad-budget + refund + WhatsApp + production live-mode-switch remain unmapped → HTTP 400 + `ai.approval.execution_skipped` audit. CAIO blocked at engine + bridge + execute layer. 31 new tests; previous Phase 4D unmapped-list parametrizations trimmed by 2 to reflect the new mapping.

### Pending
- Live WhatsApp Business Cloud API sender (consent-gated, Claim-Vault-grounded) is still pending; Phase 3E ships only the design scaffold.
- Ad-budget execution, refund execution, production live-mode switch, and discount.above_20 execution intentionally remain unmapped — expansion needs explicit Prarit sign-off + matching tests.

### Phase 2 — Other gateways / credentials (slot when needed)
- **PayU payment links** — same shape as Razorpay; only the adapter is missing.
- **Delhivery test/live credentials** — code path is wired; flip `DELHIVERY_MODE=test` once a real test API token + a pickup location registered with Delhivery are available.
- **Meta test/live credentials** — code path is wired; flip `META_MODE=test` once a real Meta app + page access token are available.
- **WhatsApp Business outbound + consent** — design first per blueprint §24, build later.
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

**Active strategic blueprint:** [`docs/MASTER_BLUEPRINT_V2.md`](docs/MASTER_BLUEPRINT_V2.md) — Master Blueprint v2.0. Owner: Prarit Sidana. Reflects production reality through Phase 5E-Hotfix-2 (Phase 1 → 5E-Hotfix-2 done, 550 backend tests + 13 frontend tests, live at https://ai.nirogidhara.com).

**Historical reference only:** the original *Master Blueprint v1.0* (PDF, pre-Phase 5 design draft) is superseded and kept solely for context. v2.0 supersedes its discount bands (now 50% cumulative cap), reorder cadence (now Day 20), Phase 0–7 roadmap (now Phase 1 → 5E-Hotfix-2 done + controlled rollout + 5F next), and "WhatsApp future" framing (WhatsApp AI Sales engine is shipped and live). Sections of v1.0 that remain valid (CEO AI / CAIO hierarchy, reward / penalty philosophy, learning loop philosophy, KPI definition, locked non-negotiables) have been carried forward into v2.0 in updated language.

When in doubt: **`nd.md` wins** on operational truth, **`docs/MASTER_BLUEPRINT_V2.md` wins** on strategic framing. Every decision in this codebase traces back to a section in one of those two documents.

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

## 17. Production Deployment — Hostinger VPS

> **Operational truth.** Anything below this line describes the live
> production stack at `https://ai.nirogidhara.com`. If you change the
> deployment shape, also update this section, `docs/DEPLOYMENT_VPS.md`,
> `AGENTS.md`, and `CLAUDE.md`. The repo on GitHub is the source of
> truth — never hand-edit files on the VPS without committing the same
> change here.

### Production URL

- **App:** `https://ai.nirogidhara.com`
- **Health:** `https://ai.nirogidhara.com/api/healthz/`

### VPS

- **Host:** Hostinger VPS
- **SSH:** `ssh root@187.127.132.106`
- **Project folder:** `/opt/nirogidhara-command`
- **GitHub repo:** `https://github.com/prarit0097/Nirogidhara-AI-Command-Center`
- **Other Docker projects on the same VPS:** `postzyo`, `openclaw`. **Never touch their containers, networks, or volumes.** Never run `docker system prune -a`.

### Deployment method

- Docker Compose production deployment.
- Compose file: `docker-compose.prod.yml`.
- Env file (live, gitignored): `.env.production`.
- Env example (committed): `.env.production.example`.
- **Compose project name:** `nirogidhara-command` (namespaced; will not collide with `postzyo` / `openclaw`).

### Containers

| Container | Image | Role |
| --- | --- | --- |
| `nirogidhara-db` | `postgres:16-alpine` | Database — only siblings reach it |
| `nirogidhara-redis` | `redis:7-alpine` (AOF on) | Celery broker + Channels group layer |
| `nirogidhara-backend` | `nirogidhara/backend:latest` (built from `backend/Dockerfile` with **repo-root context**) | Daphne ASGI on internal `:8000`, runs migrate + collectstatic on boot |
| `nirogidhara-worker` | same image | `celery -A config worker --concurrency=1` |
| `nirogidhara-beat` | same image | `celery -A config beat` |
| `nirogidhara-nginx` | `nirogidhara/nginx:latest` (built from `frontend/Dockerfile` with **repo-root context**) | Serves the Vite SPA, proxies `/api/`, `/admin/`, `/ws/` to `backend:8000` |

### Network + volumes

- Network: `nirogidhara_network` (isolated bridge).
- Volumes: `nirogidhara_postgres_data`, `nirogidhara_redis_data`, `nirogidhara_static_volume`, `nirogidhara_media_volume`.

### Host port + reverse proxy

- Container Nginx publishes **`18020:80`**. Avoids conflict with Postzyo / OpenClaw.
- Host-level Ubuntu Nginx (or Hostinger Traefik) terminates TLS and proxies `ai.nirogidhara.com → 127.0.0.1:18020`.
- Host Nginx config (recommended path): `/etc/nginx/sites-available/ai.nirogidhara.com` symlinked into `/etc/nginx/sites-enabled/ai.nirogidhara.com`.

### SSL

- Issued by **Certbot / Let's Encrypt** (`sudo certbot --nginx -d ai.nirogidhara.com`).
- Certificate paths:
  - `/etc/letsencrypt/live/ai.nirogidhara.com/fullchain.pem`
  - `/etc/letsencrypt/live/ai.nirogidhara.com/privkey.pem`
- Auto-renewal handled by Certbot's default systemd timer.

### Health checks

```bash
curl http://127.0.0.1:18020/api/healthz/
curl http://ai.nirogidhara.com/api/healthz/
curl https://ai.nirogidhara.com/api/healthz/
```

All three must return `{"status":"ok","service":"nirogidhara-backend"}`.

### Common VPS commands

```bash
# SSH
ssh root@187.127.132.106

# Switch to project
cd /opt/nirogidhara-command

# Status
docker compose -f docker-compose.prod.yml --env-file .env.production ps

# Logs
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f beat
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f nginx

# Pull latest code
cd /opt/nirogidhara-command
git pull origin main

# Rebuild + restart (--pull never keeps the local image cache; the
# images are not published to a registry).
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --pull never

# Run migrations explicitly (entrypoint also does this, but explicit is
# easier to scan for warnings).
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm --entrypoint sh backend -lc "python manage.py migrate --no-input"

# Create superuser
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend python manage.py createsuperuser

# Seed demo data (NOT on a live customer DB)
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend python manage.py seed_demo_data --reset

# Django check
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm --entrypoint sh backend -lc "python manage.py check"

# Restart
docker compose -f docker-compose.prod.yml --env-file .env.production restart

# Stop (keeps volumes + data)
docker compose -f docker-compose.prod.yml --env-file .env.production down

# Resource monitoring
docker stats
docker system df

# Host Nginx checks
nginx -t
systemctl reload nginx

# Certbot renewal check
certbot certificates
certbot renew --dry-run
```

### Troubleshooting — duplicate Postgres index on first migrate

If the **first** `migrate` against a fresh Postgres errors out with
`relation "calls_calltranscriptline_call_id_5bc33dc3" already exists`
(or the `_like` variant), drop the stale indexes and re-run migrate.

```bash
cd /opt/nirogidhara-command

docker compose -f docker-compose.prod.yml --env-file .env.production stop backend worker beat nginx
docker compose -f docker-compose.prod.yml --env-file .env.production up -d postgres redis

docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c \
    'DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3; DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3_like;'

docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
    --entrypoint sh backend -lc "python manage.py migrate --no-input"

docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --pull never
```

If multiple variants accumulated across retries, sweep them all in one
shot:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c "DO \$\$ DECLARE r RECORD; BEGIN FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'calls_calltranscriptline_call_id_%' LOOP EXECUTE format('DROP INDEX IF EXISTS %I', r.indexname); END LOOP; END \$\$;"
```

> **Do not** edit `apps/calls/migrations/0002_phase2d_vapi_fields.py`
> in the repo. Migration files are append-only history; a patch that
> works for one customer's DB will silently desync from another. The
> recovery is documented here and in `docs/DEPLOYMENT_VPS.md` §8.5.

### Manual VPS fixes that are now in the repo (Phase 5B-Deploy hotfix)

These were applied directly on the VPS during the first deploy and are
now committed to `main` so the next `git pull && docker compose up -d
--build` reproduces them automatically:

1. `docker-compose.prod.yml` — backend service uses **repo-root build context** (`context: .` + `dockerfile: backend/Dockerfile`). Without this the image cannot copy `deploy/backend/entrypoint.sh` and tini exits with `exec ... entrypoint.sh failed: No such file or directory`.
2. `backend/Dockerfile` — copies `backend/requirements.txt` and `backend/` separately, then explicitly copies `deploy/backend/entrypoint.sh`, runs `sed -i 's/\r$//'` (drops Windows CRLF that breaks tini) and `chmod +x`.
3. `deploy/backend/entrypoint.sh` — runs under `set -e` only (no `set -u`), defaults `daphne -b 0.0.0.0 -p 8000 config.asgi:application` when invoked with zero positional args, and runs `migrate` + `collectstatic` only for the backend / python role (worker + beat skip both).
4. `docs/DEPLOYMENT_VPS.md` §8.5 + this section — the duplicate Postgres index workaround for `calls.0002_phase2d_vapi_fields`.

### Security — what stays mock-mode in production

These integrations stay in `mock` until Prarit confirms each integration's live credentials. **Never change them without authorisation:**

- `WHATSAPP_PROVIDER=mock`
- `RAZORPAY_MODE=mock`
- `DELHIVERY_MODE=mock`
- `VAPI_MODE=mock`
- `META_MODE=mock`
- `AI_PROVIDER=disabled` (or live OpenAI when key is set)
- `WHATSAPP_DEV_PROVIDER_ENABLED=false` (Baileys must never load in production)

Other warnings:

- **Never commit `.env.production`** — it is gitignored at the repo root.
- **Never paste `docker compose config` output publicly** — the rendered config interpolates the env file and prints secrets.
- Existing VPS apps `postzyo` / `openclaw` must not be touched.
- Do not run `docker system prune -a` on a shared VPS without explicit user approval.

---

### ✅ Phase 5A — WhatsApp Live Sender Foundation (DONE, this session)

The first runtime WhatsApp phase. New `apps.whatsapp` Django app added to `INSTALLED_APPS`. **No AI Chat Agent in this phase** — that's 5C. **No lifecycle automation** — that's 5D. **No campaigns** — that's 5F. Phase 5A is the safe foundation: manual operator-triggered sends through a fully-gated pipeline.

**What shipped:**

- 8 new models in `apps/whatsapp/models.py`: `WhatsAppConnection` (one row per WABA phone-number-id), `WhatsAppTemplate` (Meta-mirrored, `claim_vault_required` flag), `WhatsAppConsent` (lifecycle history on top of `Customer.consent_whatsapp` live gate), `WhatsAppConversation`, `WhatsAppMessage` (unique constraint on both `provider_message_id` and `idempotency_key` when non-empty), `WhatsAppMessageAttachment`, `WhatsAppMessageStatusEvent` (idempotent on `provider_event_id`), `WhatsAppWebhookEvent` (envelope idempotency log), `WhatsAppSendLog` (one row per provider send attempt). Migration `0001_initial`.
- Provider interface `apps/whatsapp/integrations/whatsapp/base.py` with `ProviderSendResult`, `ProviderWebhookEvent`, `ProviderStatusResult`, `ProviderHealth` dataclasses + `ProviderError` exception.
- **`MockProvider`** (default for tests / dev) — deterministic `wamid.MOCK_<sha1(idempotency_key)[:16]>`, no network. Webhook signature verification accepts any non-empty header so tests don't need to compute HMAC.
- **`MetaCloudProvider`** (Nirogidhara-built — the reference repo's was stubbed) — posts to `https://graph.facebook.com/{version}/{phone_number_id}/messages`, lazy `requests` import, **never logs the access token** (the send log only persists request_payload after a `_redact` pass that strips `Authorization`/`token`/`secret` keys), `verify_webhook` HMAC-SHA256 against `META_WA_APP_SECRET` (or `WHATSAPP_WEBHOOK_SECRET` override) + `X-Hub-Signature-256` constant-time compare + optional replay-window check via `X-Hub-Timestamp` (default 300 s window), `parse_webhook_event` walks Meta's `entry[].changes[].value.{messages,statuses}` shape, `health_check` against `GET /v20.0/{phone_number_id}`. Missing credentials return `ProviderError(retryable=False)` so the Celery task does not retry forever.
- **`BaileysDevProvider`** dev-only stub — refuses to instantiate when `DEBUG=False AND WHATSAPP_DEV_PROVIDER_ENABLED!=true`. Send methods raise `ProviderError(retryable=False)` — there is no production transport.
- Consent helpers in `apps/whatsapp/consent.py` — `has_whatsapp_consent` (both `Customer.consent_whatsapp=True` AND `WhatsAppConsent.consent_state=granted`), `grant_whatsapp_consent`, `revoke_whatsapp_consent`, `record_opt_out` (cancels every queued send for the customer), `detect_opt_out_keyword` (case-insensitive substring match on `STOP / UNSUBSCRIBE / BAND KARO / BAND / CANCEL`).
- Template registry in `apps/whatsapp/template_registry.py` — `sync_templates_from_provider` (seeds 8 default lifecycle templates when no payload supplied; otherwise upserts from a Meta WABA `{"data": [...]}` payload), `get_template_for_action`, `render_template_components`, `validate_template_variables` (enforces declared `required` keys when present in `variables_schema`).
- Service layer in `apps/whatsapp/services.py` — `queue_template_message` runs the full safety stack: refuses CAIO actor → no consent → block; opted-out → block; template not approved/inactive → block; Claim Vault required + no approved Claim row → block; `enforce_or_queue` matrix gate; idempotency-key dedupe via the model unique constraint. Audit blocks (`whatsapp.send.blocked`) are written **before** the atomic transaction wrapping the row insert, so a rollback inside `transaction.atomic` cannot drop them. `send_queued_message` drives the queued row through the provider once, writes a `WhatsAppSendLog`, marks `sent` on success, marks `failed` on `ProviderError`. **Failed sends never mutate `Order` / `Payment` / `Shipment`** (verified by a regression test that creates an order + payment, monkeypatches the provider to raise, asserts no field changed). Webhook handlers `handle_inbound_message_event` + `handle_status_event` are also single-tenant + idempotent.
- Celery task `apps.whatsapp.tasks.send_whatsapp_message` with `bind=True, autoretry_for=(ProviderError,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True, max_retries=5`. Eager-mode safe.
- Webhook view at `/api/webhooks/whatsapp/meta/`. GET: Meta verification handshake (`hub.mode == "subscribe"` AND `hub.verify_token == META_WA_VERIFY_TOKEN`). POST: signature verify → JSON parse → idempotent envelope insert into `WhatsAppWebhookEvent.provider_event_id` (SHA1 of body + entry id) → parse events → dispatch inbound + status. Failed-signature attempts still persist as `processing_status=rejected` for audit.
- 9 read + 4 write API endpoints under `/api/whatsapp/`: `provider/status/` (admin-only, redacts ids and never exposes tokens), `connections/`, `templates/` + `templates/sync/` (admin-only), `conversations/` + `conversations/{id}/messages/`, `messages/` + `messages/{id}/retry/` (operations+), `consent/{customer_id}/` (GET authenticated, PATCH operations+), `send-template/` (operations+).
- 9 new approval-matrix entries: `whatsapp.payment_reminder` / `confirmation_reminder` / `delivery_reminder` / `rto_rescue` / `reorder_reminder` / `support_complaint_ack` / `greeting` (all `auto_with_consent`), `whatsapp.usage_explanation` (compliance `approval_required` — Claim Vault still enforced even after approval), plus the existing `whatsapp.broadcast_or_campaign` (admin `approval_required`) and `whatsapp.support_handover_to_human` (`human_escalation`).
- 18 new audit kinds in `apps/audit/signals.py` `ICON_BY_KIND`. The Phase 4A WebSocket fanout picks them up automatically — no separate WhatsApp WebSocket channel.
- Management command `python manage.py sync_whatsapp_templates` (with optional `--from-file <meta-payload.json>`).
- Frontend: 16 new types in `frontend/src/types/domain.ts` (`WhatsApp*` block), 9 new API methods in `frontend/src/services/api.ts` with mock-fallback + optimistic responses, mock fixtures in `frontend/src/services/mockData.ts`, new read-only `/whatsapp-templates` page (`frontend/src/pages/WhatsAppTemplates.tsx`), Settings page extended with a WABA section showing provider / health / phone number / token-set flags, sidebar entry under a new "Messaging" group.
- New env vars in `backend/.env.example` + `backend/.env`: `WHATSAPP_PROVIDER`, `META_WA_PHONE_NUMBER_ID`, `META_WA_BUSINESS_ACCOUNT_ID`, `META_WA_ACCESS_TOKEN`, `META_WA_VERIFY_TOKEN`, `META_WA_APP_SECRET`, `META_WA_API_VERSION` (default `v20.0`), `WHATSAPP_WEBHOOK_SECRET`, `WHATSAPP_DEV_PROVIDER_ENABLED` (default `false`), `WHATSAPP_WEBHOOK_REPLAY_WINDOW_SECONDS` (default 300).

**Tests:** 50 new pytest cases in `backend/tests/test_phase5a.py` covering all 9 test groups (provider mock + Meta Cloud, webhook GET + POST + signatures + replay window + idempotency, consent live gate + opt-out keywords + cancel-queued-on-opt-out, template enforcement, send pipeline + Order-untouched-on-failure regression, idempotency on idempotency-key + provider-message-id + provider-event-id, approval matrix integration + CAIO blocked at service entry + at dispatch, API permissions for anonymous / viewer / operations / admin / director, audit-kind emission, management command, dev-provider refusal). Existing 351 backend tests stay green. **Total: 401 passed.** Frontend: 13 / 13 still green; lint 0 errors / 8 pre-existing warnings; build OK.

**Deferred to later phases (explicitly out of scope here):** WhatsApp AI Chat Sales Agent (Phase 5C), inbound auto-reply, chat-to-call handoff, Order booking from chat, lifecycle automation triggers, rescue discount, broadcast/campaigns. Phase 5A is the safe foundation — no AI freestyle, no automatic outbound on lifecycle events, manual operator-triggered sends only.

### Phase 5A-1 — WhatsApp AI Chat Agent + Discount Rescue Policy Addendum (DONE, doc-only)

Locked addendum to `docs/WHATSAPP_INTEGRATION_PLAN.md` (sections S–GG). **No runtime code changes.** Key product decisions captured:

- **Direction shift.** WhatsApp is no longer just a lifecycle reminder sender. It must run an **inbound-first AI Chat Sales Agent** with the same business objective as the AI Calling Agent — discovery → category detection → Claim-Vault-grounded explanation → objection handling → address collection in chat → order booking → payment-link handoff → confirmation / delivery / RTO / reorder lifecycle → chat-to-call handoff when warranted.
- **Greeting rule (locked).** First reply to a generic intro (`hi` / `hello` / `namaste` / single-emoji) must be the exact Hindi string: *"Namaskar, Nirogidhara Ayurvedic Sanstha mai aapka swagat hai. Bataye mai aapki kya help kar sakta/sakti hu?"* delivered via a Meta-pre-approved UTILITY template, not freestyle.
- **First-phase mode = `auto-reply` with guardrails.** Auto-reply means the AI replies without operator click — it does NOT mean bypassing the matrix / Claim Vault / approval engine. Every send still flows through `apps.ai_governance.approval_engine.enforce_or_queue` first; CAIO never sends; sandbox stamps live; budgets gate; Reward / Penalty signals fire.
- **Address collection in chat.** Stateful per `WhatsAppConversation.metadata.address_collection`. Required fields: name, phone, alt_phone, address_line, pincode (Delhivery-validated), city, state (auto-fill from pincode + customer confirmation), landmark, payment_preference, confirm_intent. Failure → handoff.
- **Category detection (locked).** Before any product-specific text, the agent must identify the category (mirrors `apps.catalog.ProductCategory` slugs). The category-detection prompt is itself a Meta UTILITY template, not freestyle. Once confirmed, product explanation **must** use `apps.compliance.Claim.approved` only.
- **Chat-to-call handoff (locked).** Triggers: explicit call request, low confidence on two consecutive turns, address / payment / pincode clarification failure, six existing handoff flags (medical_emergency / side_effect / very_angry / human_requested / low_confidence / legal_or_refund), high-risk RTO rescue. Handoff carries `Customer + Order + WhatsAppConversation` ids; auto-reply pauses until call outcome processed; writes `whatsapp.handoff.call_triggered` audit.
- **Discount discipline (LOCKED, the most important rule in this addendum):**
  - **AI never offers a discount upfront.** Lead with standard ₹3000/30-capsule price; do not mention discount unless customer asks; on first ask, handle the underlying objection (value / trust / benefit / brand / doctor / ingredients / lifestyle); only after 2–3 customer pushes may the AI offer a discount within the Phase 3E `validate_discount` bands.
  - **Refusal-based rescue is the only proactive offer path** — eligible at three stages: A) order-booking refusal (Sales/Chat/Call), B) confirmation refusal (Confirmation AI), C) delivery / RTO refusal (Delivery / RTO AI).
- **50% total discount hard cap (LOCKED).** Across all stages combined, the total discount on a single order must NEVER exceed 50%. Examples: 20+20+10=50% allowed; 20+20+20=60% blocked. Scope: every AI workflow that can offer a discount (Chat / Calling / Confirmation / RTO / Customer Success / any future). Enforcement (Phase 5C/5D code work) layered on top of existing `validate_discount` plus a new `validate_total_discount_cap(order, additional_pct)` check that runs before `apply_order_discount` in the Phase 4D execute layer; over-cap requests convert to a director-only `discount.above_50_director_override` `ApprovalRequest`.
- **Discount audit (planned).** Every offer (accepted, rejected, blocked) records customer / order / conversation / agent / channel / stage / trigger / current+proposed+final pct / cap-check pass / policy band / approval state / estimated profit impact / Reward-Penalty signal / `AuditEvent` id. Future `DiscountOfferLog` model (Phase 5C/5D) holds the table.
- **Future model + API planning** (NOT implemented in 5A-1 or 5A): `WhatsAppAIReplySuggestion`, `WhatsAppChatAgentRun`, `WhatsAppHandoffToCall`, `WhatsAppConversationOutcome`, `WhatsAppEscalation`, `WhatsAppLearningCandidate`, `DiscountOfferLog`. Future endpoints `POST /api/whatsapp/conversations/{id}/ai-reply/`, `POST /handoff-to-call/`, `POST /orders/draft-from-chat/`, `POST /discount-offers/`, `GET /timeline/`. All belong to Phase 5C / 5D.
- **Learning loop scope.** May improve tone / timing / objection handling / closing style / discount-offer timing / handoff timing / category-question phrasing / address-collection wording. Must NOT create new medical claims, product promises, cure statements, side-effect advice, refund / legal commitments, new outbound templates, or discount offers above the per-stage band or the 50% cap. Promotion path mirrors `learned_memory.py`: raw → QA → Compliance → CAIO audit → CEO sandbox test → live `PromptVersion` update. No automatic promotion.
- **Updated phase numbering.** 5A-0 (audit, DONE) → 5A-1 (this addendum, DONE) → 5A (Live Sender Foundation, NEXT) → 5B (Inbox + Customer 360 timeline) → 5C (AI Chat Sales Agent) → 5D (Chat-to-Call Handoff + Lifecycle Automation) → 5E (Confirmation / Delivery / RTO / Reorder automation with rescue-discount flow + 50% cap enforcement in code) → 5F (Campaign system, strict approval-gated).

Phase 5A implementation must read sections S–DD of the integration plan before designing models, provider interface, and service contracts so the foundation does not paint Phase 5C into a corner.

### Phase 5A-0 — WhatsApp compatibility audit (DONE, doc-only)

The external [`prarit0097/Whatsapp-sales-dashboard`](https://github.com/prarit0097/Whatsapp-sales-dashboard) reference repo was audited in detail (SHA `273b57a3`, 2026-04-28). Findings recorded in `docs/WHATSAPP_INTEGRATION_PLAN.md`. Locked decisions:

- The reference repo is **a foundation, not a blueprint to merge**. Nirogidhara remains source of truth.
- **Production target is Meta Cloud API.** The reference repo's Meta Cloud provider is **stubbed** (every method returns a no-op dict; zero `graph.facebook.com` calls) — Nirogidhara builds its own client from scratch in Phase 5A.
- **Baileys is dev/demo only.** Any `baileys_dev` provider would refuse to load when `DJANGO_DEBUG=False` unless `WHATSAPP_DEV_PROVIDER_ENABLED=true` is explicitly set. ToS risk is documented; production never runs Baileys.
- **What we reuse from the reference repo:** the 6-method `BaseWhatsAppProvider` ABC shape, the `Message` / `Conversation` / `MessageAttachment` / `Connection` model field sets, `learned_memory.py` (human-vetted-only retrieval — the cleanest file in the repo), HMAC + idempotency test shapes, and the three-pane Inbox UX layout.
- **What we explicitly do NOT copy:** the whole Node `whatsapp-service/`, `baileys.py`, `meta_cloud.py` stub, `agent.md`'s `{success,data,meta}` envelope rule, `Audit.tsx` / `Dashboard.tsx` / `Connect.tsx` (Nirogidhara already richer), and the `OpenAIService` AUTO-mode auto-send path (incompatible with Hard Stops §1, §2, §3 — no Claim Vault enforcement, no approval queue).
- **Locked Phase 5A scope** (per `WHATSAPP_INTEGRATION_PLAN.md`): allowed message types are `payment_reminder`, `confirmation_reminder`, `delivery_reminder`, `rto_rescue` (low/med risk auto, high risk approval-required), `usage_explanation` (Compliance approval + Claim Vault required), `reorder_reminder`, `support_complaint_ack`. Blocked: broadcast campaigns, freestyle sales, refund / legal / side-effect / medical AI replies, ad-budget actions, customer-facing CAIO messages.
- **Hard rules carried over:** every send writes `AuditEvent`; consent + approved template + Claim Vault gates are enforced server-side; webhook is HMAC-verified + replay-window-checked + idempotent on `provider_event_id`; failed sends never mutate Order / Payment / Shipment; CAIO blocked at engine + bridge + execute layer.

The plan is the single source for Phase 5A scoping. Next: Phase 5A WhatsApp Live Sender Foundation.

### ✅ Phase 5B-Deploy — Production Docker scaffold for ai.nirogidhara.com (DONE, this session)

Pure deploy scaffold. **No business logic changed.** Production target is
`ai.nirogidhara.com` on a Hostinger VPS that already runs Postzyo and
OpenClaw, so everything is namespaced (project `nirogidhara-command`,
containers `nirogidhara-*`, network `nirogidhara_network`, host port
`18020 → 80`).

**What shipped:**

- `docker-compose.prod.yml` — six isolated services: `nirogidhara-db` (Postgres 16-alpine), `nirogidhara-redis` (Redis 7-alpine, AOF on), `nirogidhara-backend` (Daphne ASGI on :8000), `nirogidhara-worker` (Celery worker, concurrency=1 initially), `nirogidhara-beat` (Celery beat), `nirogidhara-nginx` (Vite SPA + reverse proxy). Healthchecks on Postgres / Redis / backend. Volumes: `nirogidhara_postgres_data / _redis_data / _static_volume / _media_volume`.
- `backend/Dockerfile` — Python 3.11 slim + tini + libpq + non-root user (uid 10001). Single image is reused by backend / worker / beat services; the runtime command comes from compose.
- `deploy/backend/entrypoint.sh` — role-aware. Daphne role waits for Postgres + Redis, runs `migrate --noinput` and `collectstatic --noinput`, then `exec`s Daphne. Worker / beat skip migrate (the backend container owns schema) but still wait for DB + Redis.
- `frontend/Dockerfile` — multi-stage build: node 20 alpine builds the Vite SPA (build context is repo root so it can also read `deploy/nginx/...`); nginx 1.27 alpine serves the dist + the project nginx config. Build args: `VITE_API_BASE_URL=/api`, `VITE_WS_BASE_URL=` (empty so `realtime.ts` derives the WS URL from the page origin).
- `deploy/nginx/nirogidhara.conf` — serves the SPA from `/usr/share/nginx/html`, proxies `/api/` + `/admin/` + `/ws/` to `backend:8000`, sets WebSocket upgrade headers + Forwarded-* headers, gzip + 25 MB upload cap, hashed-asset caching + `index.html` no-cache.
- `.env.production.example` — full coverage of every env var read by `backend/config/settings.py`. All integration `*_MODE` and `WHATSAPP_PROVIDER` default to `mock`; `AI_PROVIDER=disabled`. `CSRF_TRUSTED_ORIGINS` documented (the env var is now consumed by `settings.py`). Production-flavored `RAZORPAY_CALLBACK_URL` and `VAPI_CALLBACK_URL` already point at `https://ai.nirogidhara.com/...` placeholders.
- `backend/config/settings.py` extended: `CSRF_TRUSTED_ORIGINS` now env-driven (defaults to the dev CORS list when unset).
- `backend/requirements.txt` adds `psycopg[binary]` + `requests` (both required for production; the existing lazy imports keep dev/CI lean).
- `.gitignore` extended: `.env.production`, `*.pem / *.key / *.crt`, `certbot/`, `deploy/secrets/`. Allow-list keeps `.env.production.example` tracked.
- `.dockerignore` (repo root + backend) — keeps secrets, sqlite, dev artifacts, git history out of every image.
- `docs/DEPLOYMENT_VPS.md` — end-to-end runbook: prerequisites, `git clone /opt/nirogidhara-command`, `.env.production` template, first boot, migrate + createsuperuser + sync_whatsapp_templates, smoke tests, DNS A-record, host Nginx + Certbot OR Hostinger Traefik, daily logs / restart / update flow, Postgres backup commands, security checklist before going live, resource-safety notes for the shared VPS, and an explicit "intentionally NOT here" list (Phase 5C+).

**Locked safety:**

- Existing Postzyo / OpenClaw containers must not be touched. Project name + container prefixes + network + volumes + host port are all namespaced.
- `.env.production` is gitignored. The repo only carries `.env.production.example` with placeholders.
- Mock-mode defaults are the safe rollout: WhatsApp / Razorpay / Delhivery / Vapi / Meta Lead Ads / AI provider all stay `mock` / `disabled` until each integration's live credentials are confirmed by Prarit.
- Worker concurrency = 1 initially. Bump only after `docker stats` confirms memory headroom on the shared VPS.
- No application-level changes. Phase 5C is still locked out at the matrix + service-entry level (CAIO refusal, AI auto-reply not wired, etc.).

### ✅ Phase 5C — WhatsApp AI Chat Sales Agent (DONE, this session)

The first runtime AI customer-facing phase. Phase 5C wires an OpenAI-backed chat agent on top of Phase 5A's send pipeline + Phase 5B's inbox. The agent runs in **auto mode** (Prarit-locked decision §1) but every customer-facing send still flows through the existing safety stack: consent → approved template (greeting) / Claim Vault check (freeform) → blocked-phrase filter → discount discipline → 50% total cap → matrix → CAIO refusal → idempotency → rate limits.

**What shipped:**

- `backend/apps/whatsapp/ai_orchestration.py` — `run_whatsapp_ai_agent(conversation_id, inbound_message_id)`. Pipeline: idempotency check → language detection → greeting fast-path on first inbound → AI provider gate → context builder (Customer 360 + recent history + last order + Claim Vault relevant to detected category) → prompt assembly with strict JSON instructions → `apps.integrations.ai.dispatch.dispatch_messages` → JSON parse + schema validation → safety gates → discount discipline → rate limits → `services.send_freeform_text_message` (TEXT) OR `order_booking.book_order_from_decision` OR handoff. Every state-change writes an audit row.
- `backend/apps/whatsapp/language.py` — deterministic Hindi/Hinglish/English detector. ≥30% devanagari → Hindi; Hinglish marker words OR mixed devanagari → Hinglish; Latin-only → English; empty → unknown (fallback Hinglish for the Indian-customer default Prarit picked). The detector stamps `WhatsAppConversation.metadata.detectedLanguage` so the AI prompt + UI both read the same source.
- `backend/apps/whatsapp/ai_schema.py` — strict `ChatAgentDecision` dataclass + `parse_decision()` validator. Anything that fails the schema becomes a `handoff` outcome, never a customer send. Exposes `BLOCKED_CLAIM_PHRASES` (`100% cure`, `permanent solution`, `doctor ki zarurat nahi`, `no side effects for everyone`, `cures X disease`, …) and `reply_contains_blocked_phrase()` for defence in depth on top of the Claim Vault gate.
- `backend/apps/whatsapp/discount_policy.py` — `evaluate_whatsapp_discount()` wraps Phase 3E `validate_discount` with two extra rules: (1) cannot offer until customer has pushed at least `MIN_OBJECTION_TURNS_BEFORE_OFFER=2` times unless this is a refusal-rescue path; (2) `validate_total_discount_cap()` enforces the locked 50% total cap (sum of prior approved + proposed ≤ 50%). Anything over → `handoff_required=True`.
- `backend/apps/whatsapp/order_booking.py` — `book_order_from_decision()` validates the order draft is complete (name, phone, address, pincode, city, state), checks the discount cap, calls `apps.orders.services.create_order` (existing service path — never writes the model directly), optionally calls `apps.payments.services.create_payment_link` for the ₹499 advance. **Never touches `apps.shipments`** — Phase 5C deliberately stops at order-punched + payment link. Failed payment-link creation does NOT roll back the order; it just stamps `paymentLinkPending=True` in metadata.
- `backend/apps/whatsapp/services.py` — new `send_freeform_text_message()` for TEXT replies (Phase 5A's `queue_template_message` was template-only). Same gates: CAIO refusal, consent, idempotency-key dedupe. Returns the `WhatsAppMessage` row; raises `WhatsAppServiceError` on any blocker.
- `backend/apps/whatsapp/tasks.py` — new Celery task `run_whatsapp_ai_agent_for_conversation`. The inbound webhook now fires it via `_enqueue_ai_run` in `services.handle_inbound_message_event`; eager mode dispatches synchronously, real-broker production uses `transaction.on_commit`.
- Six new HTTP endpoints — `GET /api/whatsapp/ai/status/`, `PATCH /api/whatsapp/conversations/{id}/ai-mode/`, `POST /api/whatsapp/conversations/{id}/run-ai/`, `GET /api/whatsapp/conversations/{id}/ai-runs/`, `POST /api/whatsapp/conversations/{id}/handoff/`, `POST /api/whatsapp/conversations/{id}/resume-ai/`. Reads are auth-only; writes are operations+. Anonymous blocked. Viewer cannot toggle / handoff / run.
- 18 new audit kinds — `whatsapp.ai.run_started/completed/failed/reply_auto_sent/reply_blocked/suggestion_stored/greeting_sent/greeting_blocked/language_detected/category_detected/address_updated/order_draft_created/order_booked/payment_link_created/handoff_required/discount_objection_handled/discount_offered/discount_blocked`. Phase 4A WebSocket fanout picks them up automatically — no new channel.
- New env vars (defaults SAFE / off): `WHATSAPP_AI_AUTO_REPLY_ENABLED=false`, `WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.75`, `WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR=10`, `WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY=30`. Flipping `WHATSAPP_AI_AUTO_REPLY_ENABLED=true` is the production opt-in.
- Frontend: 11 new types in `frontend/src/types/domain.ts` (`WhatsAppAiMode`, `WhatsAppAiStage`, `WhatsAppAiLanguage`, `WhatsAppConversationAiState`, `WhatsAppAiGlobalStatus`, `WhatsAppAiRunSummary`, `WhatsAppAiRunsResponse`, …). Six new API methods (`getWhatsAppAiStatus`, `updateWhatsAppConversationAiMode`, `runWhatsAppConversationAi`, `getWhatsAppConversationAiRuns`, `handoffWhatsAppConversation`, `resumeWhatsAppConversationAi`). New `AiAgentPanel` inside the inbox right pane — mode toggle / language pill / category pill / confidence pill / handoff banner / order-booked card / Run AI / Handoff / Resume buttons. Outbound messages now show an "AI Auto" badge when `aiGenerated=true`. Customer 360 WhatsApp tab status pill reflects the new vocabulary (`auto / auto_reply_off / provider_disabled`).

**Hard stops (still enforced; defence in depth):**

- No medical-emergency replies — `safety.medicalEmergency=true` flips conversation to `escalated_to_human` immediately.
- No freeform claims outside `apps.compliance.Claim.approved` — `claim_vault_not_used` blocker forces handoff.
- Blocked-phrase substring match on the LLM reply text → `blocked_phrase:<phrase>` blocker forces handoff.
- No discount on first ask — `discipline_too_early` notes; agent must objection-handle first.
- 50% total cap is non-negotiable — `over_total_cap_50` forces handoff regardless of LLM confidence.
- Order booking demands an explicit customer "yes / haan / confirm / book" word in the latest inbound — otherwise `missing_explicit_confirmation` blocker, no order created.
- Order booking refuses incomplete addresses — `incomplete_address` blocker.
- CAIO can never originate a customer-facing send — refused at `services.send_freeform_text_message` and `services.queue_template_message` and the matrix engine (triple gate).
- No shipment / no campaign / no refund path from chat — Phase 5C stops at order-punched + payment-link.

**Tests:** 35 new pytest cases in `backend/tests/test_phase5c.py` covering language detection, schema validation, blocked-phrase detector, discount discipline + 50% cap + rescue path, greeting fast-path (template present / missing), provider-disabled fail-closed, auto-send happy / disabled / low-confidence / blocked-phrase / medical-emergency, CAIO refusal, order booking happy / no confirmation / incomplete address (no shipment), payment-link ₹499 created via service, idempotency, API permissions for ai-status / ai-mode / run-ai / ai-runs / handoff / resume-ai (viewer / operations / anonymous), inbound webhook → Celery task. Existing 434 stay green; total **469**.

### ✅ Phase 5B-Deploy hotfix sync (DONE, after first VPS deploy)

The first VPS deploy surfaced four issues that were patched directly on
the server. They are now committed back to `main` so future
`git pull && docker compose up -d --build` runs reproduce them:

1. **Compose backend build context.** `docker-compose.prod.yml` now uses `context: .` + `dockerfile: backend/Dockerfile` (was `context: ./backend`). The repo-root context is required so the image can copy `deploy/backend/entrypoint.sh`. Without it tini exits with `exec /app/deploy/backend/entrypoint.sh failed: No such file or directory`.
2. **Backend Dockerfile path layout.** `backend/Dockerfile` now does `COPY backend/requirements.txt /app/requirements.txt`, `COPY backend/ /app/`, then explicitly `COPY deploy/backend/entrypoint.sh /app/deploy/backend/entrypoint.sh` followed by `sed -i 's/\r$//' ... && chmod +x ...` to normalise CRLF + ensure the executable bit even when the repo was checked out on Windows. Adds `netcat-openbsd` for shell-based DB / Redis polling fallbacks.
3. **Entrypoint default command.** `deploy/backend/entrypoint.sh` runs under `set -e` only (not `set -eu`) and defaults to `daphne -b 0.0.0.0 -p 8000 config.asgi:application` when invoked with zero positional args. The previous `set -u` + `case "$1"` shape crashed the backend container with `parameter not set`.
4. **Migration duplicate-index workaround.** Documented in §17 of this file and `docs/DEPLOYMENT_VPS.md` §8.5 — drop the stale `calls_calltranscriptline_call_id_*` indexes via `psql`, then re-run `migrate`. Migration files stay append-only in the repo.

These four fixes are required for any greenfield deploy to succeed
without manual intervention. Anyone running `docker compose -f
docker-compose.prod.yml --env-file .env.production up -d --build` from
a fresh clone of `main` will get a clean stack.

Tests stay at 434 backend / 13 frontend. The deploy scaffold doesn't add code paths — every change is config / Docker / docs.

### ✅ Phase 5B — Inbound WhatsApp Inbox + Customer 360 Timeline (DONE, this session)

The first runtime inbox phase. Phase 5B is **manual-only** — no AI auto-reply, no chat-to-call handoff, no order booking from chat, no rescue discount, no campaigns. Operations users can read inbound conversations, leave internal notes, mark conversations read, change status / assignment / tags / subject, and click a button to queue an approved-template send (which still flows through Phase 5A's gates).

**What shipped:**

- New `WhatsAppInternalNote` model (`apps/whatsapp/models.py`) + migration `0002_whatsappinternalnote`. Notes carry `conversation FK`, `author FK (User)`, `body`, `metadata`, timestamps. They are NEVER sent to the customer.
- Six new endpoints under `/api/whatsapp/`:
  - `GET /api/whatsapp/inbox/` — returns `{ conversations, counts: { all, unread, open, pending, resolved, escalatedToHuman }, aiSuggestions: { enabled: false, status: "disabled", message: "Phase 5C pending" } }`. The `aiSuggestions` block is the explicit machine-readable contract that the inbox stays manual; the frontend never invents AI behavior.
  - `PATCH /api/whatsapp/conversations/{id}/` — operations+ safe-field update (`status / assignedToId / tags / subject`). Anything else in the body is ignored by the serializer; an empty payload returns 400. Status transition to `resolved` stamps `resolved_at + resolved_by`. Writes `whatsapp.conversation.updated` audit and (when assignment changes) `whatsapp.conversation.assigned`.
  - `POST /api/whatsapp/conversations/{id}/mark-read/` — operations+ resets `unread_count` to 0; idempotent when already 0; writes `whatsapp.conversation.read`.
  - `GET + POST /api/whatsapp/conversations/{id}/notes/` — list (auth+) and create (operations+). Note create writes `whatsapp.internal_note.created`.
  - `POST /api/whatsapp/conversations/{id}/send-template/` — operations+ manual template send. The customer is resolved from the conversation (operators can't accidentally pick the wrong one); the call routes through Phase 5A's `services.queue_template_message` so the consent + approved-template + Claim Vault + approval matrix + CAIO + idempotency gates all stay in force. Writes `whatsapp.template.manual_send_requested` audit before queuing.
  - `GET /api/whatsapp/customers/{customer_id}/timeline/` — WhatsApp-only timeline (messages + status events + internal notes interleaved by `occurredAt`). Phase 5B intentionally does NOT merge calls / payments / orders into the timeline — that's a Phase 5C/5D concern.
- Six new audit kinds added to `apps/audit/signals.py` ICON_BY_KIND: `whatsapp.conversation.opened/updated/assigned/read`, `whatsapp.internal_note.created`, `whatsapp.template.manual_send_requested`. The Phase 4A WebSocket fanout picks them up automatically — no separate inbox channel.
- Conversation list filters extended: `?unread=true`, `?assignedTo=<user_id>`, `?q=<search>` (name / phone / last_message_text / subject icontains). Slicing only happens on the `list` action so retrieve / partial_update keep working.
- Conversation serializer now exposes `customerName / customerPhone / assignedToUsername`. Message serializer now exposes `templateName`. New `WhatsAppInternalNoteSerializer`.
- Frontend types: `WhatsAppInternalNote`, `WhatsAppInboxSummary`, `WhatsAppInboxCounts`, `WhatsAppCustomerTimeline`, `WhatsAppCustomerTimelineItem`, `WhatsAppAiSuggestionStatus`, `CreateInternalNotePayload`, `UpdateWhatsAppConversationPayload`, `SendConversationTemplatePayload`. Conversation type extended with `customerName / customerPhone / assignedToUsername`; Message type with `templateName`.
- Frontend API methods (mock-fallback safe): `getWhatsAppInbox`, `getWhatsAppConversation`, `getWhatsAppConversationNotes`, `createWhatsAppConversationNote`, `updateWhatsAppConversation`, `markWhatsAppConversationRead`, `sendWhatsAppConversationTemplate`, `getCustomerWhatsAppTimeline`.
- New `/whatsapp-inbox` page (three-pane). Left pane: filter chips (`All / Unread / Open / Pending / Resolved`) with count badges + name/phone/text search + AI-suggestions placeholder card. Middle pane: conversation cards with avatar / name / unread badge / last-message preview / status pill / relative time. Right pane: thread (inbound = bordered card, outbound = gradient bubble) with template label + status pill + relative time, plus the internal-notes panel (list + textarea + save button), plus the AI-suggestions disabled callout, plus a `Send template` modal that posts to the per-conversation send endpoint. Live refresh via `connectAuditEvents` filtered on `whatsapp.*`. New sidebar entry under Messaging.
- Customer 360 (`/customers`) gained a WhatsApp tab — separate from the existing Calls / Orders / Payments / Delivery / Consent tabs (the brief explicitly avoided a unified timeline). Loads `getCustomerWhatsAppTimeline`. When no conversation exists, shows the empty-state copy "No WhatsApp conversation yet. Inbound messages or manual templates will appear here." Otherwise renders message bubbles + internal notes + a one-click `Open in Inbox` button + AI-suggestions disabled placeholder.
- 33 new pytest cases in `backend/tests/test_phase5b.py` covering: inbox summary counts + AI placeholder; conversation filters (unread / status / search); conversation serializer (customer name / phone / assigned-to username); internal note create + list (operations / viewer / anonymous); empty-body rejection; mark-read + idempotent no-op; PATCH safe fields + assignment audit + unsafe-field rejection; viewer + anonymous PATCH refusal; inbound webhook unread + last-message updates; inbound message no-auto-reply; inbound message does-not-mutate-Order/Payment; opt-out keyword still revokes consent; per-conversation send-template happy path; consent missing → 403 + `consent_missing`; inactive template → 400 + `template_inactive`; CAIO actor → service-entry refusal; viewer + anonymous send refusal; customer timeline returns WhatsApp-only items (kinds ⊆ {message, internal_note, status_event}); 404 for unknown customer; full audit-emission lifecycle (`whatsapp.inbound.received / conversation.read / internal_note.created / template.manual_send_requested / message.queued / message.sent`).
- Phase 5A's 50 tests stay green; full backend suite 434 passed.

**Hard stops still enforced:** No AI auto-reply. No freeform outbound text. No chat-to-call handoff. No order booking from chat. No discount automation. No campaigns. CAIO can never originate a customer-facing send (refused at engine + bridge + execute layer + service entry guard). Failed sends never mutate Order / Payment / Shipment.

### ✅ Phase 5A-Fix — Env + Docs Consistency Audit (DONE, no runtime change)

Small cleanup phase that ran after Phase 5A. **No runtime code changed.**

- Diffed `backend/config/settings.py` against `backend/.env.example`. Two
  vars were read by the code but missing from the documented env template:
  `DJANGO_TIME_ZONE` (defaults to `Asia/Kolkata` when unset) and
  `GROK_MODEL` (defaults to `""`). Both are now documented in `.env.example`
  and the local `.env` got safe blank defaults.
- Frontend uses `VITE_API_BASE_URL` (already documented) and
  `VITE_WS_BASE_URL` (Phase 4A WebSocket origin override — was undocumented).
  Added both to `frontend/.env.example` with comments explaining the
  derivation rule.
- Verified `backend/.env` and `frontend/.env` are correctly gitignored
  and not tracked (`git ls-files | grep -E '\.env$'` returns nothing).
  No secrets were exposed during the audit.
- Fixed stale counts in `README.md` ("15 apps" → "16 apps", "19 pages" →
  "20 pages"), `AGENTS.md` ("19 pages" → "20 pages"), and `nd.md` §3
  tree comments + §5 (added the `whatsapp` row) + §6 (`Frontend pages
  (19)` → `Frontend pages (20)`) + §8 page-count line.
- `docs/RUNBOOK.md` already shipped a "Phase 5A — WhatsApp (Meta Cloud)
  live sender" section with the env, sync, send, and webhook smoke tests
  (added in the Phase 5A commit). Verified complete; no edits needed.
- Existing 401 backend + 13 frontend tests stay green; lint 0 errors;
  build OK.

The audit found no runtime bugs — the missing env vars all had safe
in-code defaults, so the gap was purely documentation drift. Phase 5B
implementation can start from a clean baseline.

_End of `nd.md`. Last updated after **Phase 5C — WhatsApp AI Chat Sales
Agent** (`apps.whatsapp.ai_orchestration` runs on every inbound;
deterministic Hindi/Hinglish/English detection; locked greeting
template; OpenAI dispatch with strict JSON schema + Claim Vault gate +
blocked-phrase filter + discount discipline + 50% total cap + auto-send
rate gates; six new endpoints + 18 audit kinds + frontend AI Chat Agent
panel). Auto-reply defaults to OFF; production flips
`WHATSAPP_AI_AUTO_REPLY_ENABLED=true` after verification. **35 new
tests; 469 backend + 13 frontend, all green.** Live at
**`https://ai.nirogidhara.com`**. Operational runbook lives in `nd.md`
§17 + `docs/DEPLOYMENT_VPS.md`._
