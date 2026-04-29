# WhatsApp Integration Plan — Phase 5A-0 Compatibility Audit

> **Status:** Planning / audit only. **No runtime code lands in this phase.**
> **Reference repo:** [`prarit0097/Whatsapp-sales-dashboard`](https://github.com/prarit0097/Whatsapp-sales-dashboard) — branch `main`, audited at SHA `273b57a3` (2026-04-28).
> **Source of truth:** Nirogidhara AI Command Center. The reference repo is a **foundation**, not a blueprint to merge.

---

## A. Executive summary

### What WhatsApp-sales-dashboard accelerates for Nirogidhara

- **Provider abstraction shape.** A clean 6-method `BaseWhatsAppProvider` ABC (`connect`, `get_qr`, `status`, `send_message`, `disconnect`, `reconnect`). Mirrors the mock/test/live pattern Nirogidhara already uses for Razorpay, Delhivery, Vapi, and Meta Lead Ads.
- **Domain model shapes.** `Message` (direction / status / type / `provider_message_id` / `ai_generated` / `error_message` / `metadata`), `Conversation` (`status` / `assigned_to` / `unread_count` / `ai_handled` / `last_message_*`), `MessageAttachment`, `WhatsAppConnection` + `ConnectionEvent`. The fields are exactly what Meta Cloud needs — porting these saves design time.
- **HMAC + idempotency test shapes.** `test_webhook_flow.py`, `test_send_outbound.py`, and `test_action_dispatcher.py` are the strongest part of the repo. Their shapes (signature pass/fail → 401, dedupe by `(org, provider_message_id)`, status-event mapping, dispatcher gating) port directly to Nirogidhara's existing `payments.WebhookEvent` / `crm.MetaLeadEvent` patterns.
- **Inbox UX.** Three-pane Inbox (filter list / conversation list / message thread + composer + notes) with TanStack Query hooks (`useConversations`, `useConversationMessages`, `useSendMessage`, `useAIReplyFeedback`). Best-in-class shape for the Customer 360 WhatsApp tab we'll add later.
- **Learned-memory loop with explicit human gate.** `learned_memory.py` only promotes replies to future prompts after an agent clicks "accept" (`feedback_type="accepted"`). Org facts require `confidence ≥ 0.70`. Caps: 15 customer facts, 8 org facts. **No automatic promotion.** This is the cleanest single file in the repo and aligns with Nirogidhara's "human-vetted before reuse" stance.

### What cannot be reused directly

- **Baileys provider.** ToS-risk to Nirogidhara's WhatsApp Business numbers. The reference repo's own `README.md` flags it: *"Baileys is unofficial and violates WhatsApp's ToS… For production, swap to Meta Cloud API."* **No path to production with Baileys.**
- **Meta Cloud provider.** Stubbed. Every method returns `{"provider":"meta_cloud","status":"not_implemented"}` or `{"queued": False}`. **Zero HTTP calls** to `graph.facebook.com`. No template rendering, no webhook signature verification, no GET-verify handshake. We rebuild this from scratch.
- **AI auto-reply (`AUTO` mode).** Once `confidence ≥ threshold`, the bot sends. **Violates Nirogidhara Hard Stops §1, §2, §3** — no Claim Vault enforcement, no approval queue, autonomous customer-facing AI execution.
- **Action dispatcher's `create_booking` path.** `allow_side_effects=True` boolean toggle is the only gate. No idempotency key, no rate limit, no per-action approval queue. Direct conflict with Nirogidhara's Phase 4C/4D approval-and-execution layers.
- **Templates UI as data source.** Lets users create arbitrary text templates. Meta WABA requires pre-approved templates for outbound-initiated business messages — UI must "fetch from Meta + sync state", not "create".
- **`whatsapp-service/` Node app.** Fastify + Baileys forwarder is irrelevant once we go Meta Cloud direct: Meta calls our Django webhook, we call Meta's Graph API. No Node hop.

### Why Nirogidhara remains source of truth

- Nirogidhara already owns the **Customer / Order / Payment / Shipment lifecycle**, the **Approval Matrix**, the **AuditEvent Master Ledger**, the **Reward / Penalty engine**, the **Claim Vault**, the **CEO AI / CAIO governance**, and the **Approved Execution Registry**. WhatsApp must plug into these — not replace or fork them.
- The reference repo's "Conversation owns assigned_to + ai_handled" model is fine; the reference repo's "Conversation is the source of truth for the customer" assumption is **wrong for Nirogidhara**. `apps.crm.Customer` (already loaded in 19 frontend pages) is the source of truth.
- Nirogidhara's audit / approval / execution model already encodes the safety bar Meta's WABA business policy expects. The reference repo's `agent.md` envelope (`{success, message, data, meta}`) and `OrgScopedModel` multi-tenancy are explicitly **rejected** by Nirogidhara's contracts (raw arrays, single-tenant Phase 1–4E).

### Why Meta Cloud API is required for production

1. **WhatsApp ToS.** Baileys is reverse-engineered; Meta can ban the underlying number with no warning, no SLA, no recourse. A single ban during a festival promo can cost a quarter's delivery revenue.
2. **Approved templates required.** Outbound-initiated business messages (payment reminders, delivery reminders, RTO rescue, reorder reminders) must use WABA-pre-approved templates. Baileys can send anything; this is exactly what Meta will ban for.
3. **Customer trust + verification.** A green-tick verified WABA business profile vs. an unbranded sender is the difference between 18% and 64% open rates on payment links (industry data).
4. **Compliance + observability.** Meta Cloud webhooks are signed (`X-Hub-Signature-256`), versioned, and rate-limited per-tier. We can audit every send/status; Baileys' bridge model loses delivery semantics.
5. **Phase 5A locked decision.** Production = Meta Cloud. Baileys allowed only as `dev/demo` provider behind a feature flag that defaults off in any non-development environment.

---

## B. Reference repo audit

| Module / file (real path) | What it does | Decision | Reason | Nirogidhara target |
| --- | --- | --- | --- | --- |
| `README.md` | Quick-start; states Baileys = ToS risk; recommends Meta Cloud swap. | **adapt** | Copy structure, drop Baileys recommendation. | `docs/whatsapp/README.md` |
| `Automation.md` | 74KB engineering changelog. Real history of JID whitelist churn, Baileys 405 disconnects, OpenAI wiring. | **avoid copy / mine for risk register** | Honest but historical. | risk register §12 below |
| `agent.md` | Operating contracts: response envelope `{success,message,data,meta}`, `OrgScopedModel`, AI calls only via single service file. | **avoid wholesale / adapt isolation pattern** | Envelope + multi-tenancy conflict with Nirogidhara. The "AI in one place" pattern is good. | `nd.md` already encodes isolation; no new doc |
| `backend/apps/whatsapp_connections/providers/base.py` | 6-method ABC: `connect / get_qr / status / send_message / disconnect / reconnect`. | **reuse** | Right shape; matches Nirogidhara mock/test/live pattern. | `apps/messaging/integrations/whatsapp/base.py` |
| `backend/apps/whatsapp_connections/providers/baileys.py` | `httpx.Client` proxy to `whatsapp-service` over `WHATSAPP_SERVICE_URL`. No outbound HMAC. | **avoid** | Nirogidhara has no Baileys path. | none |
| `backend/apps/whatsapp_connections/providers/meta_cloud.py` | **Stubbed.** Returns `{"provider":"meta_cloud","status":"not_implemented"}`. Zero `graph.facebook.com` calls. Silent failure mode. | **replace** | Production blocker. Build from scratch. | `apps/messaging/integrations/whatsapp/meta_cloud_client.py` |
| `backend/apps/whatsapp_connections/views.py` (webhook) | HMAC-SHA256 verify (`X-WA-Signature`), constant-time compare, 401 on mismatch, dedupes on `(org, provider_message_id)`, drops `is_from_me`, JID filter `@s.whatsapp.net`. **No replay-window check.** | **adapt** | HMAC + atomic + dedupe pattern is right. Rewrite for Meta's `X-Hub-Signature-256` shape + status-event dedupe + replay window. | `apps/whatsapp/webhooks.py` |
| `backend/apps/messages/tasks.py` (`send_outbound_message`) | `@shared_task` only. **No bind=True, no autoretry_for, no max_retries, no backoff.** Mutates `Message` + `Conversation`. | **adapt** | Port state machine; add `autoretry_for=(httpx.HTTPError,RateLimitError), retry_backoff=True, jitter=True, max_retries=5` + idempotency key. | `apps/whatsapp/tasks.py` |
| `backend/apps/messages/models.py` (`Message`) | `direction / status / type / provider_message_id / text / ai_generated / error_message / metadata`. Indexes `(org,conv,created_at)` + `(org,status,created_at)`. | **reuse** field set | Exactly what Meta Cloud needs. | `apps/whatsapp/models.WhatsAppMessage` |
| `backend/apps/messages/models.MessageAttachment` | `message FK, file_url, mime_type, size_bytes`. | **reuse** | Same shape. | `apps/whatsapp/models.WhatsAppMessageAttachment` |
| `backend/apps/conversations/models.Conversation` | `contact / assigned_to / status ∈ {open,pending,resolved} / unread_count / last_message_text / last_message_at / ai_handled (bool) / tags / resolved_at`. | **adapt** | Extend `ai_handled` boolean to `ai_status ∈ {disabled,suggest,pending_approval,auto_after_approval}` to fit Nirogidhara approval flow. | `apps/whatsapp/models.WhatsAppConversation` |
| `backend/apps/conversations/models.InternalNote` | Per-conversation note FK (author + body). | **reuse** | Internal handover comments — useful. | `apps/whatsapp/models.WhatsAppInternalNote` |
| `backend/apps/contacts/models.Contact` | `name, phone (indexed), email, source, city, interested_in, follow_up_at, notes, metadata, assigned_to, tags`. Unique `(org, phone)`. | **avoid model / reuse pattern** | Nirogidhara already has `apps.crm.Customer`. Borrow `metadata` + `(org,phone)` unique pattern only. | extend `apps.crm.Customer` |
| `backend/apps/whatsapp_connections/models.WhatsAppConnection` | `provider, display_name, phone_number, external_id, session_key, status, last_connected_at, last_error, metadata`. | **adapt** | Keep Connection + ConnectionEvent split for Meta Cloud (one row per WABA phone-number-id, `external_id=phone_number_id`). | `apps/whatsapp/models.WhatsAppConnection` |
| `backend/apps/ai_agents/services/openai_service.py` | Chat Completions wrap + soft-grounding system prompt + 75/25 vector+lexical retrieval. Soft "use only provided grounding" guard (no enforcement layer). Stub fallback on missing key returns `confidence=0.55`. | **avoid freestyle path / reuse retrieval** | Soft grounding ≠ Claim Vault. Reuse the cap-and-truncate retrieval; route through Nirogidhara's Claim-Vault-bound `prompting.build_messages`. | extend `apps/ai_governance/prompting.py` for WhatsApp orchestration |
| `backend/apps/ai_agents/services/orchestration_context.py` | Builds `{conversation, contact, recent_messages (cap 6, text 500c), business_memory, learned_memory, knowledge_candidates (cap 200, top 3, score≥0.25)}`. | **adapt** | Port cap-and-truncate; replace `business_memory` with Nirogidhara `Customer + Order` snapshot. | `apps/whatsapp/services/orchestration.py` |
| `backend/apps/ai_agents/services/learned_memory.py` | Stores `CustomerFact`, `LearningEvent (APPLIED only)`, `AIOrchestrationEvent (reply_feedback,accepted)`, accepted `AIReplyLog` texts. **No auto-promotion.** | **reuse** wholesale | Cleanest file in the repo. Aligns with Nirogidhara hard stops. | `apps/ai_governance/learned_memory.py` |
| `backend/apps/ai_agents/services/action_dispatcher.py` | 4 actions (`lookup_price`, `check_availability`, `create_booking`, `handoff_to_human`). `create_booking` gated by `allow_side_effects` boolean. **No idempotency key, no rate limit.** | **adapt shape only** | Allow-list pattern is right; route any state-mutating action through Nirogidhara `apps.ai_governance.approval_execution` registry, NOT a boolean flag. | route equivalent actions through existing approval engine |
| `backend/apps/ai_agents/tasks.py` (`trigger_ai_reply`) | Three modes: `DISABLED` / `SUGGEST` / `AUTO`. `AUTO` auto-sends if confidence ≥ threshold. | **avoid AUTO / reuse SUGGEST** | AUTO violates §1+§2+§3. Map AUTO → "queue ApprovalRequest" via approval engine. | `apps/whatsapp/services/ai_orchestration.py` |
| `Frontend/src/App.tsx` | 17 routes including `/inbox`, `/connect`, `/templates`, `/knowledge`, `/audit`. | **adapt** route names | Nirogidhara already has 19 pages; add `/whatsapp-inbox` only. | `frontend/src/App.tsx` route addition |
| `Frontend/src/pages/Inbox.tsx` | Three-pane (filter / list / thread + composer + notes). 11 TanStack Query hooks. WS topics `message.new`, `message.status`, `conversation.updated`. Filters `all/unread/ai/pending/resolved`. | **adapt** | Best-in-class WhatsApp inbox UX. Port the layout + `useAIReplyFeedback` hook into Nirogidhara. | `frontend/src/pages/WhatsAppInbox.tsx` |
| `Frontend/src/pages/Connect.tsx` | QR pairing with `useConnectionStatus` polling, `useConnectionQr` enabled on `qr_ready`. WS `wa.connection.status`. Inline 405 notice. | **avoid** | Meta Cloud has no QR pairing — paste `phone_number_id` + `access_token` in a settings form. | `frontend/src/pages/Settings.tsx` (extend with WABA section) |
| `Frontend/src/pages/Templates.tsx` | CRUD on freeform templates. Categories greeting/sales/billing/reminder/feedback. Live preview. | **adapt UI / replace data** | UI shape is good. Data must come from Meta WABA-pre-approved template list (`/v20.0/{waba_id}/message_templates`), not freeform input. | `frontend/src/pages/WhatsAppTemplates.tsx` |
| `Frontend/src/pages/Knowledge.tsx` | Three source types (`text|url|file`). Hooks for CRUD + search + reprocess (re-embed). | **adapt** | Port source-type tabs + re-embed UX into Claim Vault management. | extend Claims page |
| `Frontend/src/pages/Dashboard.tsx` | Stat tiles, AILearningSnapshot, recent conversations, lead funnel. | **avoid** | Nirogidhara's Director Dashboard is richer + different semantics. | none |
| `Frontend/src/pages/Audit.tsx` | Plain audit log list. Single hook. | **avoid** | Nirogidhara already has Phase 4A WebSocket-backed live audit feed. | none |
| `whatsapp-service/` (Fastify + Baileys forwarder) | Node 22 + Fastify 4 + Baileys 6.7.18 + ioredis. 11 env vars. Multi-strategy version selection. QR pairing. JID whitelist `@s.whatsapp.net`. **Webhook poster has no retries / no timeout.** 10 test cases. | **avoid wholesale** | Meta Cloud calls Nirogidhara directly — no Node forwarder needed. | none |
| `tests/test_webhook_flow.py` | ~10 cases: HMAC pass/fail (401), idempotency, self-message skip, AI mode branches. | **reuse test shapes** | The integration test patterns are the strongest part of the repo. | `backend/tests/test_phase5a.py` |
| `tests/test_send_outbound.py` | 6 cases: happy path, no connection, disconnected, provider raises, missing phone, JID preference. | **reuse test shapes** | Direct port. | `backend/tests/test_phase5a.py` |
| `tests/test_action_dispatcher.py` | 5 cases: unknown action skipped, `create_booking` gated, `lookup_price` matches catalog, `handoff_to_human` logged, dispatched count. | **reuse test shapes** | Validates the approval-execution mapping. | `backend/tests/test_phase5c.py` |
| `tests/test_ai_orchestration.py` | 5 cases: grounding, escalation on sensitive messages, business-memory injection, reply-feedback API, full action dispatch. | **reuse test shapes** | Validates Claim-Vault-wrapped path. | `backend/tests/test_phase5c.py` |
| `tests/test_learning_loop.py` | 6 cases: safe-type promotion, age cutoff, retriever surfacing, context injection. | **reuse test shapes** | Validates ported `learned_memory.py`. | `backend/tests/test_phase5c.py` |

---

## C. Nirogidhara target architecture

### Backend

```
backend/apps/whatsapp/
  __init__.py
  apps.py
  models.py                  # WhatsAppConversation / Message / Template / Consent / WebhookEvent / SendLog / Connection / MessageStatusEvent
  serializers.py             # camelCase via source= mapping
  views.py                   # ViewSets + APIView for send-template, retry, provider/status
  urls.py                    # /api/whatsapp/...
  webhook_urls.py            # /api/webhooks/whatsapp/meta/  (GET handshake + POST signed delivery)
  webhooks.py                # MetaCloudWebhookView (HMAC-SHA256 X-Hub-Signature-256, replay-window check, idempotent on event_id)
  services.py                # send_template / handle_inbound / mark_status / retry_send / consent helpers
  tasks.py                   # Celery: send_whatsapp_message, retry_failed_sends (autoretry_for + backoff + jitter + max_retries=5)
  template_registry.py       # ApprovedTemplate cache: synced from Meta /v20.0/{waba_id}/message_templates
  consent.py                 # WhatsApp consent rules (read Customer.consent.whatsapp + WhatsAppConsent.expires_at + opt-out flag)
  integrations/
    whatsapp/
      __init__.py
      base.py                # Provider ABC: send_template_message, send_text_message, verify_webhook, parse_webhook_event, get_message_status, health_check
      mock.py                # WHATSAPP_PROVIDER=mock — deterministic, no network (default for tests)
      meta_cloud_client.py   # Production target — graph.facebook.com/v20.0
      baileys_dev.py         # WHATSAPP_PROVIDER=baileys_dev — explicit dev-only, OFF by default in any non-DEBUG environment
  management/
    commands/
      sync_whatsapp_templates.py     # Pull Meta-approved template list into ApprovedTemplate cache
      send_dev_whatsapp_message.py   # Local smoke (mock + baileys_dev only)
  tests/
    test_provider_meta_cloud.py
    test_webhooks.py
    test_send_task.py
    test_consent.py
    test_template_enforcement.py
    test_approval_integration.py
    test_caio_blocked.py
    test_idempotency.py
```

### Frontend

```
frontend/src/
  pages/
    WhatsAppInbox.tsx        # Three-pane (filter / conv list / thread + composer + notes)
                             # Reuses Phase 4A realtime hook for message.new + message.status
    WhatsAppTemplates.tsx    # Read-only list of Meta-approved templates + "sync from Meta" button
    Settings.tsx             # Existing — extend with WABA Connection section
    Customers.tsx            # Existing — extend Customer 360 with WhatsApp timeline tab
    Orders.tsx               # Existing — add "Send delivery reminder template" / "Send payment reminder" CTA where allowed
    Confirmation.tsx         # Existing — add "Send confirmation reminder template" CTA
    Rto.tsx                  # Existing — add "Send rto rescue template" CTA (consent + approval gated)
  components/
    whatsapp/
      ConversationList.tsx
      MessageThread.tsx
      TemplateSendModal.tsx       # picker → preview with Customer/Order context → Submit (calls /api/whatsapp/send-template/)
      ConsentBanner.tsx           # "Customer has not opted in to WhatsApp" warning
      ProviderStatusPill.tsx      # Reads /api/whatsapp/provider/status/
      InternalNotePopover.tsx
      AISuggestionBox.tsx         # Reads pending ai-suggestion ApprovalRequest rows; admin/director can approve → execute
  services/
    api.ts                   # Add: getWhatsAppConversations, getWhatsAppMessages, sendWhatsAppTemplate, syncTemplates,
                             #      patchConsent, getProviderStatus, retryWhatsAppMessage
    realtime.ts              # No changes — existing /ws/audit/events/ already covers whatsapp.* audit kinds
  types/
    domain.ts                # Add WhatsAppConversation, WhatsAppMessage, WhatsAppTemplate, WhatsAppConsent, etc.
```

---

## D. Proposed Nirogidhara models

> All models are single-tenant for Phase 5A (no `OrgScopedModel`). All datetimes UTC. All audit-bearing writes pair with an `AuditEvent`.

### `WhatsAppConnection`
- `id: str (PK, "WAC-...")`
- `provider: str (choices: mock | meta_cloud | baileys_dev, default mock)`
- `display_name: str`
- `phone_number: str (E.164, indexed)`
- `phone_number_id: str (Meta WABA phone-number-id, unique when provider=meta_cloud)`
- `business_account_id: str (WABA id)`
- `status: str (choices: connected | disconnected | error)`
- `last_connected_at: dt (nullable)`
- `last_error: text (blank)`
- `metadata: JSON (default {})`
- `created_at, updated_at: auto`
- **Indexes:** `(provider, status)`, `(phone_number_id)` unique-when-not-empty.
- **Audit:** writes `whatsapp.connection.{configured,status_changed,error}` on changes.

### `WhatsAppTemplate`
- `id: str (PK, "WAT-...")`
- `connection: FK(WhatsAppConnection)`
- `name: str (Meta template name; unique per connection)`
- `language: str (e.g., "hi", "en", "en_US")`
- `category: str (choices: AUTHENTICATION | MARKETING | UTILITY)`
- `status: str (choices: PENDING | APPROVED | REJECTED | DISABLED)` — **mirrored from Meta**
- `body_components: JSON` — Meta's `components[]` array verbatim
- `variables_schema: JSON` — derived map of `{1: "customerName", 2: "orderId"}` for safe rendering
- `claim_vault_required: bool (default False)` — set True for `usage_explanation` and any product/medical text template
- `is_active: bool (default True)` — UI toggle that does NOT bypass Meta's `status`
- `last_synced_at: dt`
- `metadata: JSON (default {})`
- **Indexes:** unique `(connection, name, language)`, `(status, is_active)`.
- **Audit:** `whatsapp.template.{synced,activated,deactivated}`.

### `WhatsAppConsent`
- `id: BigAutoField`
- `customer: FK(crm.Customer)` — **single source of truth is `Customer.consent.whatsapp`**, this row carries the lifecycle history
- `consent_state: str (choices: unknown | granted | revoked | opted_out)`
- `granted_at: dt (nullable)`
- `revoked_at: dt (nullable)`
- `opt_out_keyword: str (blank)` — captured when customer texts STOP / UNSUBSCRIBE
- `expires_at: dt (nullable)` — for marketing-tier consent windows (24h transactional rule documented in §G below)
- `last_inbound_at: dt (nullable)` — used to compute "open service window" per Meta policy
- `source: str (free-form: "form", "ad_lead", "inbound_message", "support_call", "import")`
- `metadata: JSON (default {})`
- `created_at, updated_at: auto`
- **Indexes:** `(customer, consent_state)`, `(opt_out_keyword)` partial.
- **Audit:** `whatsapp.consent.updated`, `whatsapp.opt_out.received`.

### `WhatsAppConversation`
- `id: str (PK, "WCV-...")`
- `customer: FK(crm.Customer, on_delete=PROTECT)`
- `connection: FK(WhatsAppConnection)`
- `assigned_to: FK(accounts.User, nullable)`
- `status: str (choices: open | pending | resolved | escalated_to_human, default open)`
- `ai_status: str (choices: disabled | suggest | pending_approval | auto_after_approval, default suggest)`
- `unread_count: int (default 0)`
- `last_message_text: str (max 500)` — truncated for the inbox preview
- `last_message_at: dt (nullable)`
- `last_inbound_at: dt (nullable)` — drives Meta's 24h service-window calculation
- `subject: str (blank)`
- `tags: JSON (default [])`
- `resolved_at, resolved_by: dt + FK (nullable)`
- `metadata: JSON (default {})`
- `created_at, updated_at: auto`
- **Indexes:** `(customer, status, updated_at)`, `(assigned_to, status, updated_at)`, `(status, last_message_at)`.
- **Audit:** `whatsapp.conversation.{opened,assigned,resolved,reopened,escalated}`.

### `WhatsAppMessage`
- `id: str (PK, "WAM-...")`
- `conversation: FK(WhatsAppConversation, related_name=messages)`
- `customer: FK(crm.Customer)` — denormalized for efficient `Customer 360` queries
- `provider_message_id: str (indexed, blank)` — the Meta-side `wamid.HBgM...` value
- `direction: str (choices: inbound | outbound)`
- `status: str (choices: queued | sent | delivered | read | failed)`
- `type: str (choices: text | template | image | document | audio | location | interactive | system)`
- `body: text (blank)` — sanitized text body (max 4096; truncate logging to 80 chars per `agent.md` learning)
- `template: FK(WhatsAppTemplate, nullable)` — required when `type=template`
- `template_variables: JSON (default {})` — sanitized rendered context
- `media_url: URLField (blank)`
- `attachments: M2M-via-WhatsAppMessageAttachment` — see below
- `ai_generated: bool (default False)`
- `approval_request: FK(ai_governance.ApprovalRequest, nullable)` — set when AI-suggested send went through approval
- `error_message: text (blank)`
- `error_code: str (blank)` — Meta error code (e.g., `131051`, `131056`)
- `attempt_count: int (default 0)`
- `metadata: JSON (default {})`
- `idempotency_key: str (unique, blank)` — prevents Celery double-send
- `queued_at, sent_at, delivered_at, read_at: dt (nullable)`
- `created_at, updated_at: auto`
- **Indexes:** `(conversation, created_at)`, `(status, created_at)`, `(provider_message_id)` unique-when-not-empty, `(idempotency_key)` unique-when-not-empty.
- **Audit:** `whatsapp.message.{queued,sent,delivered,read,failed}` + `whatsapp.send.blocked` (consent / template / Claim Vault refusals) + `whatsapp.template.sent`.

### `WhatsAppMessageAttachment`
- `id: BigAutoField`
- `message: FK(WhatsAppMessage)`
- `file_url: URLField`
- `mime_type: str`
- `size_bytes: int`
- `media_id: str (Meta media id, blank)`
- `created_at: auto`

### `WhatsAppMessageStatusEvent`
- `id: BigAutoField`
- `message: FK(WhatsAppMessage)`
- `status: str (choices match WhatsAppMessage.status)`
- `event_at: dt`
- `provider_event_id: str (unique)` — Meta's per-status webhook event id
- `raw_payload: JSON`
- `received_at: auto`
- **Indexes:** unique `(provider_event_id)`, `(message, event_at)`.
- **Purpose:** lets us replay status history without polluting the message row's audit trail.

### `WhatsAppWebhookEvent`
- `id: BigAutoField`
- `provider: str` — usually `meta_cloud`
- `event_type: str` — `messages | statuses | message_template_status_update | account_alerts | …`
- `provider_event_id: str (unique)` — extracted from Meta's `entry[].id` + offset
- `signature_header: str (blank)` — `X-Hub-Signature-256` value as received
- `signature_verified: bool (default False)`
- `received_at: auto`
- `processed_at: dt (nullable)`
- `processing_status: str (choices: received | accepted | duplicate | rejected | error)`
- `raw_payload: JSON`
- `error_message: text (blank)`
- **Indexes:** unique `(provider_event_id)`, `(processing_status, received_at)`.
- **Purpose:** **idempotency + replay-safe audit** for every inbound. Required: replay-window check (≤5min skew) + nonce store via the unique constraint.

### `WhatsAppSendLog`
- `id: BigAutoField`
- `message: FK(WhatsAppMessage)`
- `attempt: int (default 1)`
- `provider: str`
- `request_payload: JSON` — what we sent to Meta
- `response_status: int (HTTP status)`
- `response_payload: JSON` — Meta response
- `latency_ms: int`
- `error_code: str (blank)`
- `started_at, completed_at: dt`
- **Purpose:** observability + retry-policy diagnostics. **Never carries secrets** (token-redacted by service helper).

---

## E. Provider strategy

### Provider interface (proposed)

```python
# apps/whatsapp/integrations/whatsapp/base.py

class WhatsAppProvider(Protocol):
    name: str  # "mock" | "meta_cloud" | "baileys_dev"

    def send_template_message(
        self,
        *,
        to_phone: str,                    # E.164
        template: WhatsAppTemplate,
        variables: Mapping[str, str],     # rendered context (post-sanitize)
        idempotency_key: str,             # per-message; provider may echo or ignore
    ) -> ProviderSendResult:
        ...

    def send_text_message(            # Phase 5B+ only; Phase 5A: NOT WIRED
        self,
        *,
        to_phone: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderSendResult:
        ...

    def verify_webhook(
        self,
        *,
        signature_header: str,        # "X-Hub-Signature-256"
        body: bytes,
        timestamp_header: str | None, # for replay-window check (where applicable)
    ) -> bool:
        ...

    def parse_webhook_event(
        self,
        *,
        body: dict,
    ) -> list[ProviderWebhookEvent]:  # 0..N parsed events per Meta's nested entry[].changes[].value
        ...

    def get_message_status(
        self,
        *,
        provider_message_id: str,
    ) -> ProviderStatusResult:
        ...

    def health_check(self) -> ProviderHealth:
        # Meta: GET /v20.0/{phone_number_id} — returns business profile + verified status
        ...
```

### Implementations

| Provider | Status | Default in env | Notes |
| --- | --- | --- | --- |
| `mock` | Phase 5A — **default for tests / dev** | `WHATSAPP_PROVIDER=mock` | Deterministic, no network. Mints `wamid.MOCK_<n>`. Used by 100% of CI tests. |
| `meta_cloud` | Phase 5A — **production target** | Set by ops in production `.env` | Calls `https://graph.facebook.com/v20.0/{phone_number_id}/messages`. HMAC-SHA256 webhook verification via app-secret. GET-verify handshake on `hub.mode=subscribe`. |
| `baileys_dev` | Optional dev-only (not built unless explicitly requested) | `WHATSAPP_DEV_PROVIDER_ENABLED=false` (locked default) | **OFF by default in any non-DEBUG environment.** Settings layer hard-rejects `baileys_dev` when `DJANGO_DEBUG=False` AND `WHATSAPP_DEV_PROVIDER_ENABLED!=true`. ToS risk documented in this plan §A and in the provider docstring. |

**Locked rule:** the `MetaCloudProvider` is the Phase 5A production target. The `BaileysDevProvider` (if ever built) is **disabled by default in production** and refuses to load when `DEBUG=False` unless `WHATSAPP_DEV_PROVIDER_ENABLED=true` is explicitly set.

---

## F. Phase 5A allowed message types

### Allowed (with templates Meta-pre-approved)

| Action key | Template purpose | Approval matrix mode | Notes |
| --- | --- | --- | --- |
| `whatsapp.payment_reminder` | Send Razorpay link + due-amount reminder | `auto_with_consent` | Already in Phase 3E approval matrix |
| `whatsapp.confirmation_reminder` | "We're confirming your order; reply YES" | `auto_with_consent` | Order in `Confirmation Pending` stage |
| `whatsapp.delivery_reminder` | "Your order arrives today" | `auto_with_consent` | Triggered by Delhivery `out_for_delivery` event |
| `whatsapp.rto_rescue` | Rescue contact when high RTO risk | `auto_with_consent` (low-risk) / `approval_required` (high-risk) | Driven by Phase 4B reward-penalty `rto_warning_was_raised` signal |
| `whatsapp.usage_explanation` | Post-delivery usage instructions | `approval_required` (Compliance approver) | **Claim Vault required** — see §H |
| `whatsapp.reorder_reminder` | "Time for refill" (locked **Day 20** cadence per Phase 5E `whatsapp.reorder_day20_reminder`; window 20–27 days post-delivery) | `auto_with_consent` | Daily Celery beat once `WHATSAPP_REORDER_DAY20_ENABLED=true` |
| `whatsapp.support_complaint_ack` | Auto-ack of inbound complaint, then handoff to human | `auto_with_consent` | Body is a fixed acknowledgement; complaint detail goes to human queue |

### Blocked in Phase 5A

| Action / scenario | Block reason |
| --- | --- |
| `whatsapp.broadcast_or_campaign` | Phase 5E only, gated by Director approval + Meta marketing-template tier |
| Freeform sales pitch | No Meta-pre-approved template = block |
| Refund promise | Director-only / human escalation per Phase 3E matrix |
| Legal reply | Human escalation only |
| Side-effect / medical advice | Human escalation only — Hard Stop §1 |
| Ad-budget action | Director-only via approval matrix |
| AI-generated medical claim | **Block at AI layer** — Claim Vault filter rejects |
| CAIO-originated customer message | **Block at engine + bridge + execute layer** (defense in depth from Phase 4D pre-checks) |

---

## G. Consent rules

### Source of truth

- **Single source:** `apps.crm.Customer.consent` JSON (existing). Phase 5A adds a structured `WhatsAppConsent` history row that tracks state transitions over time. The Customer.consent.whatsapp boolean stays the live gate; the history row enables audit + opt-out tracking.

### Lifecycle states

```
unknown → granted → revoked
                  → opted_out (customer texted STOP)
```

### Consent-gating rules (locked Phase 5A)

1. **No consent → no send.** All outbound (template or text) refuses with HTTP 403 + `whatsapp.send.blocked` audit when `Customer.consent.whatsapp ≠ True` OR `WhatsAppConsent.consent_state ∈ {revoked, opted_out}`.
2. **Marketing vs transactional distinction (Meta 2025 policy):**
   - **Transactional templates** (UTILITY category): payment_reminder, confirmation_reminder, delivery_reminder, rto_rescue, support_complaint_ack — allowed any time inside the 24h service window OR with explicit opt-in.
   - **Marketing templates** (MARKETING category): reorder_reminder, broadcast_campaign — require explicit opt-in AND a non-revoked WhatsAppConsent row.
3. **24h service window**: Meta allows freeform replies only within 24h of the customer's last inbound. Beyond that, only approved templates. Phase 5A only sends templates so this is automatic.
4. **Opt-out keywords** (case-insensitive substring match on inbound `body`): `STOP`, `UNSUBSCRIBE`, `BAND KARO`, `BAND`, `CANCEL`. On match: set `WhatsAppConsent.consent_state=opted_out` + `Customer.consent.whatsapp=False` + write `whatsapp.opt_out.received` audit + immediately stop scheduled outbound for this customer.
5. **Re-opt-in**: explicit form / call-center action only; never auto-flip from `opted_out` to `granted`.
6. **Withdrawal**: same path as opt-out plus a graceful confirmation send (one final transactional ack template only).

### Defaults (locked)

- `Customer.consent.whatsapp` defaults to **False** for all existing rows. New customer creation requires an explicit `consent.whatsapp` field.
- `WhatsAppConsent.consent_state` defaults to `unknown`.

---

## H. Claim Vault rules

### Scope

- All template bodies whose `category=UTILITY` and whose action key is in **`{whatsapp.usage_explanation}`** carry `claim_vault_required=True`.
- All AI-suggested replies (Phase 5C+) for product / medical content also enforce Claim Vault, regardless of template flag.

### Enforcement (locked, layered)

1. **Template registration time.** When a Meta template syncs in, if its body contains any product / medical keyword set, `claim_vault_required=True` is auto-set. Director / Compliance can flip it on manually via admin.
2. **Send time.** When `claim_vault_required=True`:
   - The rendered `template_variables` are checked against `apps.compliance.Claim.approved` for the matching product.
   - **No matching approved claim → block.** `whatsapp.send.blocked` audit + HTTP 403 + handoff suggestion.
   - **Block for human review** when Claim Vault has no row for the product, OR when variable rendering produces text not in `Claim.approved`.
3. **AI-suggested path (Phase 5C+).** The existing `apps.ai_governance.prompting.build_messages` Claim Vault enforcement applies. AI-generated text that fails the post-LLM Claim Vault filter is dropped; the conversation gets a human-handoff escalation instead.
4. **Human corrections** (per `learned_memory.py` shape): when an agent edits a suggestion before sending, the edit becomes a learning candidate, NOT a live claim. New approved claims still go through the existing Compliance + Director Claim Vault workflow; nothing in WhatsApp can shortcut it.

### Hard stops

- No freestyle medical claim ever reaches `whatsapp.tasks.send_whatsapp_message`. The send service refuses to construct a Meta API payload from text not derivable from a Claim Vault row when `claim_vault_required=True`.
- The post-LLM filter rejects any sentence containing strings NOT present in `Claim.approved` for the relevant product, when the message is product/medical-bound.

---

## I. Approval Matrix integration

The Phase 3E approval matrix (`apps/ai_governance/approval_matrix.py`) already has WhatsApp action keys in scaffold form. Phase 5A wires the message-send paths through `enforce_or_queue` exactly as Phase 4C wires payment-link / prompt-version / sandbox-disable today.

### Mapping (locked)

| Action key | Mode | Approver | Notes |
| --- | --- | --- | --- |
| `whatsapp.payment_reminder` | `auto_with_consent` | (auto) | Consent + approved-template gates; auto-approves when both pass |
| `whatsapp.confirmation_reminder` | `auto_with_consent` | (auto) | Same |
| `whatsapp.delivery_reminder` | `auto_with_consent` | (auto) | Same |
| `whatsapp.rto_rescue` (low/med risk) | `auto_with_consent` | (auto) | Risk-band gate: `Order.rto_risk ∈ {Low, Medium}` |
| `whatsapp.rto_rescue` (high risk) | `approval_required` | admin / CEO AI | Risk-band gate: `Order.rto_risk == High` |
| `whatsapp.usage_explanation` | `approval_required` | compliance | **Claim Vault still enforced** even on approval; approval doesn't bypass §H |
| `whatsapp.reorder_reminder` | `auto_with_consent` | (auto) | Marketing category — needs explicit opt-in |
| `whatsapp.support_complaint_ack` | `auto_with_consent` | (auto) | Auto-ack body is fixed; complaint detail → human escalation |
| `whatsapp.broadcast_or_campaign` | **`blocked`** | (none) | Phase 5E only |
| `whatsapp.handoff_to_human` | `auto` | (auto) | Conversation status flip; no customer message goes out |

### Execution registry expansion

Phase 5A does NOT add WhatsApp send to the Phase 4D execution registry yet. Instead:

- The send pipeline is its own service-layer function (`apps.whatsapp.services.send_whatsapp_message`) called by:
  1. **Direct API**: `POST /api/whatsapp/send-template/` (operations / admin / director with consent + template + Claim Vault gates).
  2. **Lifecycle triggers**: Order / Payment / Shipment state-change signals (Phase 5D, NOT 5A).
  3. **AI suggestion** (Phase 5C): an `ai_governance.ApprovalRequest` of action `whatsapp.<message_type>` is approved → executed via the existing approval-execution endpoint, calling the same service helper.
- This matches Phase 4D's "execute is the gateway, services own the write" rule.

---

## J. AuditEvent mapping

Add to `apps/audit/signals.py` `ICON_BY_KIND`:

```python
# Phase 5A — WhatsApp lifecycle audit kinds.
"whatsapp.message.queued":       "send",
"whatsapp.message.sent":         "send",
"whatsapp.message.delivered":    "check-check",
"whatsapp.message.read":         "eye",
"whatsapp.message.failed":       "alert-octagon",
"whatsapp.template.sent":        "file-text",
"whatsapp.send.blocked":         "ban",
"whatsapp.webhook.received":     "webhook",
"whatsapp.inbound.received":     "message-circle",
"whatsapp.inbound.escalated":    "alert-triangle",
"whatsapp.consent.updated":      "user-check",
"whatsapp.opt_out.received":     "user-x",
"whatsapp.connection.configured":   "plug",
"whatsapp.connection.status_changed": "activity",
"whatsapp.connection.error":     "x-circle",
"whatsapp.template.synced":      "refresh-cw",
"whatsapp.template.activated":   "play",
"whatsapp.template.deactivated": "pause",
```

Audit kinds **already exist** from Phase 3E's WhatsApp design scaffold and stay valid:
- `whatsapp.message_queued`
- `whatsapp.broadcast.requested`
- `whatsapp.escalation.requested`

**Rule:** every Phase 5A send / status / consent / webhook write **must** end in an `AuditEvent`. The Phase 4A WebSocket fan-out (`/ws/audit/events/`) automatically picks them up — no separate WhatsApp realtime channel.

---

## K. WebSocket behavior

### Locked rule

WhatsApp events flow through the existing Phase 4A `audit_events` Channels group. **No new WebSocket channels are created in Phase 5A.**

### How the Customer 360 / Inbox stays live

- Backend writes `whatsapp.message.received` / `.sent` / `.delivered` AuditEvents.
- Phase 4A `post_save(sender=AuditEvent)` publishes the row to `audit_events` group.
- Frontend WhatsAppInbox uses the same `connectAuditEvents(...)` helper from `services/realtime.ts`, with the `onEvent` callback filtering on `kind.startsWith("whatsapp.")`.
- On match, the page calls `api.getWhatsAppConversations()` / `api.getWhatsAppMessages(convId)` via the existing polling endpoints — keeping the **render path identical to Phase 4A Governance**.

### Why no separate channel?

- The Phase 4A consumer is read-and-fanout only; adding a WhatsApp-specific channel would duplicate auth, dedupe, and snapshot logic.
- Single channel = single audit trail, single test surface, single failure mode.
- Existing polling endpoints stay fallback when the WebSocket is unreachable.

---

## L. Backend API plan

### Endpoints (proposed)

| Method | Path | Auth / role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/whatsapp/conversations/` | `IsAuthenticatedOrReadOnly` (operations+) | List with filters: `status`, `assigned_to`, `customer_id`, `q` |
| GET | `/api/whatsapp/conversations/{id}/` | operations+ | Detail with last 50 messages + internal notes |
| GET | `/api/whatsapp/conversations/{id}/messages/` | operations+ | Paginated message history |
| POST | `/api/whatsapp/send-template/` | operations+ | Body `{ customerId, templateId, variables, conversationId? }`. Enforces consent + template `is_active` + Claim Vault. Calls service. |
| POST | `/api/whatsapp/messages/{id}/retry/` | operations+ | Re-enqueues a failed `WhatsAppMessage` if its idempotency key still applies; refuses on already-sent / already-retried-N |
| GET | `/api/whatsapp/templates/` | viewer+ | List Meta-approved templates filterable by `status`, `category`, `language` |
| POST | `/api/whatsapp/templates/sync/` | admin/director only | Pull from Meta `/v20.0/{waba_id}/message_templates`; UPSERT `WhatsAppTemplate` rows; write `whatsapp.template.synced` audit |
| PATCH | `/api/whatsapp/templates/{id}/` | admin/director only | Toggle `is_active` / `claim_vault_required` (UI manual override) |
| GET | `/api/whatsapp/consent/{customer_id}/` | operations+ | Read consent state + history |
| PATCH | `/api/whatsapp/consent/{customer_id}/` | operations+ (state grant); admin/director (override) | Body `{ consentState, source, note? }` |
| GET | `/api/whatsapp/provider/status/` | admin/director only | `{ provider, configured, last_health_check_at, account_id, phone_number_id, error? }`. Token + secret REDACTED. |
| GET | `/api/webhooks/whatsapp/meta/` | **public** | Meta GET-verify handshake. Echoes `hub.challenge` only when `hub.mode==subscribe` AND `hub.verify_token==META_WA_VERIFY_TOKEN`. |
| POST | `/api/webhooks/whatsapp/meta/` | **public** + signed | HMAC-SHA256 verify `X-Hub-Signature-256` against `META_WA_APP_SECRET`. Replay-window check (≤5min skew). Idempotent on `provider_event_id` via `WhatsAppWebhookEvent.unique`. |

### Permissions summary

- **Anonymous:** only the Meta webhook handshake + signed POST (signature-only auth). Everything else 401.
- **Viewer:** read templates only. Inbox + conversations are operations+.
- **Operations / Support:** read conversations, send allowed templates (consent + Claim Vault gated), patch consent state.
- **Admin / Director:** template sync, provider config, override consent (e.g., to honor a written consent proof), retry.
- **Director-only:** any future `broadcast_campaign` action (Phase 5E).
- **CAIO:** **always 403** at engine + bridge + execute layer. Cannot trigger sends, cannot promote AgentRuns to WhatsApp ApprovalRequests, cannot appear as `requested_by_agent` on a WhatsApp send.

---

## M. Frontend integration plan

### What to adapt from `Whatsapp-sales-dashboard`

| Reference UI | Adapt into Nirogidhara as | Notes |
| --- | --- | --- |
| `Inbox.tsx` three-pane layout (filter list / convo list / thread + composer + notes) | `pages/WhatsAppInbox.tsx` | Replace `OrgScopedModelViewSet` calls with Nirogidhara `api.getWhatsAppConversations()` etc. Use Phase 4A `connectAuditEvents` for live updates. |
| `Inbox` AI suggestion box (`useAIReplyLogs` + `useAIReplyFeedback`) | `components/whatsapp/AISuggestionBox.tsx` | **Suggestions become ApprovalRequests** in Phase 5C — admin/director approves → executes → sends. |
| `Connect.tsx` QR pairing | **Discard** | Meta Cloud has no QR. Replace with a plain Settings → WhatsApp section: paste `phone_number_id` + `access_token`. |
| `Templates.tsx` CRUD UI | `pages/WhatsAppTemplates.tsx` | UI shape only. Data comes from Meta sync — no inline create/edit. Show `status` (`PENDING / APPROVED / REJECTED / DISABLED`) + `claim_vault_required` flag + last sync time + a "Sync from Meta" button (admin/director only). |
| `Knowledge.tsx` source-type tabs + re-embed | extend Claims page | Keep the source-type pattern (`text | url | file`) for Compliance team imports. Re-embed UI is a future Phase 5C consideration. |
| `Audit.tsx` | **Discard** | Nirogidhara's existing audit page is richer + Phase 4A live. |
| `Dashboard.tsx` | **Discard** | Nirogidhara's Director Dashboard is richer + different semantics. |

### New Nirogidhara components

```
frontend/src/components/whatsapp/
  ConversationList.tsx       # left pane in Inbox
  MessageThread.tsx          # right pane
  TemplateSendModal.tsx      # picker → preview → submit
  ConsentBanner.tsx          # red banner when customer.consent.whatsapp !== true
  ProviderStatusPill.tsx     # green=connected / yellow=mock / red=error
  InternalNotePopover.tsx    # team handover notes
  AISuggestionBox.tsx        # Phase 5C — pending ApprovalRequests
```

### Customer 360 / Order / Confirmation / RTO touch points

- **Customers.tsx:** add a "WhatsApp" tab inside the existing Customer detail layout. Tab renders `MessageThread` for the most recent conversation + a "Send template" CTA gated by `customer.consent.whatsapp`.
- **Orders.tsx:** "Send delivery reminder" / "Send payment reminder" CTAs in the action menu — disabled when consent is missing or template is unavailable. Hover tooltip explains why.
- **Confirmation.tsx:** "Send confirmation reminder" in the queue row CTA.
- **Rto.tsx:** "Send rto rescue" CTA — visible always; disabled when `rto_risk == High` AND no admin approval is pending. The button calls the existing `POST /api/ai/approvals/evaluate/?persist=true` to mint the ApprovalRequest, then surfaces it on the Governance page.

### Hard frontend rules

- **No business logic in React.** Consent / template / Claim Vault checks happen on the backend; the UI just renders the result.
- **No direct Meta API calls.** Frontend never sees `META_WA_ACCESS_TOKEN`. `/api/whatsapp/provider/status/` is the only window into provider health.
- **No raw error message display from Meta.** Errors are translated server-side into operator-friendly text.

---

## N. Data mapping

| WhatsApp-sales-dashboard | Nirogidhara | Notes |
| --- | --- | --- |
| `Contact` | `apps.crm.Customer` | Customer is the source of truth; WhatsApp doesn't own contact identity. |
| `Conversation` | `apps.whatsapp.WhatsAppConversation` | New table; FK to Customer. |
| `Message` | `apps.whatsapp.WhatsAppMessage` | New table; FK to Conversation + Customer. |
| `MessageAttachment` | `apps.whatsapp.WhatsAppMessageAttachment` | New table. |
| `WhatsAppConnection` (per-org) | `apps.whatsapp.WhatsAppConnection` (single-tenant) | One row per WABA phone-number-id. |
| `Template` (free-form) | `apps.whatsapp.WhatsAppTemplate` (Meta-mirrored) | Read-only mirror of Meta-approved templates + Nirogidhara-only `claim_vault_required` flag. |
| `KnowledgeDocument` | `apps.compliance.Claim` (existing) + Compliance docs | Knowledge tabs feed Claim Vault, not a parallel table. |
| `AIAgentConfig` | folded into per-conversation `WhatsAppConversation.ai_status` + global `apps.ai_governance.PromptVersion` | Confidence threshold lives in PromptVersion metadata. |
| `AIReplyLog` | `apps.ai_governance.AgentRun` + new `WhatsAppSuggestion` join table | AgentRun owns the prompt + tokens + cost; WhatsAppSuggestion links it to a Conversation. |
| `LearningEvent` (APPLIED) | `apps.ai_governance.learned_memory.LearnedFact` (new) | Direct port of the human-vetted-only loop. |
| `AuditLog` | `apps.audit.AuditEvent` | Existing Master Event Ledger. |
| `ConnectionEvent` | `apps.whatsapp.WhatsAppConnectionEvent` | New table for connection-status history. |

---

## O. Phase 5A implementation checklist

> The following list is the order of operations for the **next** phase (5A). **Phase 5A-0 stops here** — no code lands until that phase is explicitly approved.

### Backend

- [ ] **Migrations / models** — create `apps/whatsapp/` app + 8 models (§D).
- [ ] **Provider interface** — `apps/whatsapp/integrations/whatsapp/base.py` + `mock.py` (default for tests).
- [ ] **Meta Cloud client** — full implementation: send_template_message, send_text_message (Phase 5B+ flag), verify_webhook (X-Hub-Signature-256 + replay window), parse_webhook_event (entry[].changes[].value{messages,statuses,errors,contacts}), get_message_status, health_check.
- [ ] **Settings + env** — `WHATSAPP_PROVIDER`, `META_WA_*`, `WHATSAPP_DEV_PROVIDER_ENABLED=false`. Add to `backend/.env.example`.
- [ ] **Service layer** — `apps/whatsapp/services.py` with `send_whatsapp_message()`, `handle_inbound_event()`, `mark_status()`, `record_consent()`. Service is the **only** path that touches the provider.
- [ ] **Tasks** — Celery `send_whatsapp_message_task` with `bind=True, autoretry_for=(httpx.HTTPError, RateLimitError), retry_backoff=True, retry_jitter=True, max_retries=5, retry_backoff_max=300`. Idempotency key check on entry.
- [ ] **Webhook receiver** — `apps/whatsapp/webhooks.py` with HMAC verify, replay-window, `WhatsAppWebhookEvent` insert (unique constraint = idempotency), atomic dispatch.
- [ ] **Consent enforcement** — `apps/whatsapp/consent.py` reads `Customer.consent.whatsapp` + `WhatsAppConsent.consent_state`. Service refuses send when consent missing.
- [ ] **Claim Vault enforcement** — for `claim_vault_required=True` templates, service rejects when no matching `Claim.approved` row exists.
- [ ] **Approval matrix integration** — service calls `approval_engine.enforce_or_queue` before send for all action keys; auto-approved gets executed inline, others queue.
- [ ] **Audit events** — every state-change call writes via `audit.signals.write_event`.
- [ ] **Template sync command** — `python manage.py sync_whatsapp_templates`.
- [ ] **Scheduler integration** — `WhatsAppMessage.status` periodic sweep for stuck queued/sent rows (every 60s) — same shape as `payments.tasks` recovery sweep.
- [ ] **Tests** — 9 test groups (§P).

### Frontend

- [ ] **Types** — add WhatsApp* to `types/domain.ts`.
- [ ] **API methods** — extend `services/api.ts` with new methods.
- [ ] **Realtime filter** — extend `pages/WhatsAppInbox.tsx` to filter `connectAuditEvents` for `kind.startsWith("whatsapp.")`.
- [ ] **Components** — `ConversationList`, `MessageThread`, `TemplateSendModal`, `ConsentBanner`, `ProviderStatusPill`, `InternalNotePopover`.
- [ ] **Pages** — `WhatsAppInbox.tsx`, `WhatsAppTemplates.tsx`. Extend `Settings.tsx` with WABA Connection section.
- [ ] **Customer 360 / Order / Confirmation / RTO touch points** — add CTAs.
- [ ] **Frontend tests** — 5 stable cases (§P).

### Docs

- [ ] **`docs/BACKEND_API.md`** — add WhatsApp endpoints.
- [ ] **`docs/RUNBOOK.md`** — add Meta WABA setup + template-sync section.
- [ ] **`docs/FUTURE_BACKEND_PLAN.md`** — mark Phase 5A done; write 5B plan.
- [ ] **`docs/FRONTEND_AUDIT.md`** — note new pages.
- [ ] **`nd.md`** + `CLAUDE.md` + `AGENTS.md` — file pointers.

---

## P. Test plan

### Backend (proposed — Phase 5A)

| Test group | Cases | Coverage |
| --- | --- | --- |
| `test_provider_meta_cloud.py` | ~10 | Mock provider always returns deterministic ids; meta_cloud build payload (template + interactive); `verify_webhook` happy / wrong-sig / replay-window-expired; `parse_webhook_event` for `messages` + `statuses`; `get_message_status` |
| `test_webhooks.py` | ~10 | GET handshake (correct verify_token; wrong; missing); POST signed (good HMAC; bad HMAC; missing header; replay window pass / fail); idempotency on `provider_event_id`; raw payload persisted; `whatsapp.webhook.received` audit fires |
| `test_send_task.py` | ~10 | Happy path through `mock` provider; consent missing → `whatsapp.send.blocked`; template not approved → blocked; Claim Vault required + no row → blocked; idempotency key dedupe; retry on `httpx.HTTPError`; max-retries → `failed` + audit; Order / Payment / Shipment NOT mutated on failure (regression) |
| `test_consent.py` | ~6 | `Customer.consent.whatsapp=False` + `WhatsAppConsent.unknown` → block; `granted` → allow; `revoked` → block; opt-out keyword (`STOP`, `BAND KARO`) flips state + writes audit + halts queued sends; re-grant must be explicit |
| `test_template_enforcement.py` | ~5 | `is_active=False` → block; Meta `status=DISABLED` → block; `claim_vault_required` toggle path; sync command upserts; manual-override audit |
| `test_approval_integration.py` | ~6 | `whatsapp.payment_reminder` auto-approves with consent; `whatsapp.usage_explanation` → ApprovalRequest pending; admin approves → executes via service; rejected → no send |
| `test_caio_blocked.py` | ~3 | CAIO actor → 403 at engine; CAIO actor in metadata → blocked at execute; CAIO AgentRun cannot mint WhatsApp ApprovalRequest |
| `test_idempotency.py` | ~4 | Send task with same idempotency key → no duplicate Meta call; webhook replay → no duplicate row; status webhook replay → no duplicate `WhatsAppMessageStatusEvent` |
| `test_audit_events.py` | ~5 | All `whatsapp.*` audit kinds emit on the right paths; payload contains required fields (no secrets) |
| **Regression** | (existing 351 tests stay green) | Hard requirement |

### Frontend (proposed — Phase 5A)

| Test | Scope |
| --- | --- |
| `WhatsAppInbox renders empty state` | render the page with mock-fallback API |
| `Send template modal calls api.sendWhatsAppTemplate` | render + click + assert mock fetch payload |
| `Consent banner visible when customer.consent.whatsapp is false` | render Customer detail with no consent + assert banner present |
| `Template list disables row when status=DISABLED` | render with mock data + assert disabled row state |
| `Provider status pill shows mock state in dev` | render Settings → WABA section + assert pill text |

**No flaky realtime tests.** WebSocket integration coverage stays at the `realtime.test.ts` `buildWebSocketUrl` level from Phase 4A.

---

## Q. Production env plan

### Locked Phase 5A env vars

| Env var | Default | Purpose |
| --- | --- | --- |
| `WHATSAPP_PROVIDER` | `mock` | One of `mock` (tests / dev), `meta_cloud` (production), `baileys_dev` (rejected when DEBUG=False) |
| `META_WA_PHONE_NUMBER_ID` | `""` | Meta WABA phone-number-id |
| `META_WA_BUSINESS_ACCOUNT_ID` | `""` | Meta WABA id |
| `META_WA_ACCESS_TOKEN` | `""` | Long-lived system-user access token. **NEVER log. NEVER expose.** |
| `META_WA_VERIFY_TOKEN` | `""` | GET-verify handshake secret |
| `META_WA_APP_SECRET` | `""` | HMAC-SHA256 signing secret for webhook verification |
| `META_WA_API_VERSION` | `v20.0` | Graph API version pin |
| `WHATSAPP_WEBHOOK_SECRET` | `""` | Reuse name for `META_WA_APP_SECRET` parity if a separate header is used |
| `WHATSAPP_DEV_PROVIDER_ENABLED` | `false` | Master kill switch for `baileys_dev`. Settings layer rejects `baileys_dev` provider when `DEBUG=False` AND this is `false`. |

### Production secret hygiene

- All five `META_WA_*` plus `WHATSAPP_WEBHOOK_SECRET` are **server-side only**. Frontend never sees them.
- Provider status endpoint redacts before returning: `{"provider":"meta_cloud","configured":true,"phoneNumberId":"…masked…","accessTokenSet":true}`.
- Webhook receiver never logs raw signatures; it logs only verification result + truncated body.

---

## R. Migration strategy

### Locked principle

> **Do not merge the reference repo.** Extract the patterns; build inside Nirogidhara.

### Sequence (locked)

1. **Phase 5A-0 (this doc):** audit + plan. Code: zero changes.
2. **Phase 5A — WhatsApp Live Sender Foundation:**
   - Models + migrations (8 new tables under `apps/whatsapp/`).
   - Provider interface + `MockProvider` (default for all CI).
   - Real Meta Cloud client.
   - Service layer + send task.
   - Webhook receiver (GET handshake + signed POST).
   - Consent + Claim Vault + approval-matrix gates.
   - Manual template send from Customer / Order detail (the **first milestone** — operator-triggered, lifecycle untouched).
   - Frontend Settings → WABA Connection section + WhatsAppTemplates page (read-only).
   - All 9 backend test groups + 5 frontend tests.
   - Existing 351 backend + 13 frontend tests stay green.
3. **Phase 5B — Inbound Inbox + Customer Timeline:**
   - WhatsAppInbox three-pane page.
   - Customer 360 WhatsApp tab.
   - Internal notes.
   - WebSocket-driven refresh via Phase 4A `connectAuditEvents`.
4. **Phase 5C — AI Suggestions + Learning Loop:**
   - Port `learned_memory.py` (the only "reuse" from the reference repo's AI subsystem).
   - AI suggestions become `ApprovalRequest` rows of action `whatsapp.<message_type>`; admin/director approves → executes.
   - Claim Vault filter wraps the AI path.
   - CAIO refused at engine + bridge + execute.
5. **Phase 5D — Lifecycle Automation:**
   - Order / Payment / Shipment state-change signals fire `enforce_or_queue` for the matching template.
   - Auto-approved (consent-gated) lifecycle messages flow without operator action.
   - Operations / admin can still manually pre-empt or send.
6. **Phase 5E — Campaign System (gated):**
   - Director-approved broadcast campaigns.
   - Meta MARKETING template tier.
   - Per-campaign rate limit + dry-run + audit.

### What stays Nirogidhara-shaped

- `Customer` is identity. Conversations attach to Customer.
- `Order` / `Payment` / `Shipment` lifecycle is the source of truth. WhatsApp messages are observers — they must not mutate any of these on send / receive failure.
- Approval Matrix + Approval Engine + Approved Execution Layer remain the single safety surface for any state-changing AI action.
- Claim Vault remains the single source of medical / product text.
- Master Event Ledger remains the single audit surface.
- Phase 4A WebSocket remains the single live channel.

### What we copy from the reference repo

- **Test shapes** (HMAC + idempotency + state machine + dispatcher gating) — direct port.
- **`learned_memory.py`** — port wholesale; it's the cleanest file in the repo.
- **Inbox UX layout** — adapt the three-pane shape and the AI-feedback hook idea.
- **Model field sets** for `Message` / `Conversation` / `Connection` / `MessageAttachment`.

### What we explicitly do NOT copy

- The whole `whatsapp-service/` Node app.
- `baileys.py` provider (Nirogidhara has no Baileys path).
- `meta_cloud.py` (it's a stub — we build from scratch).
- `agent.md` response envelope rule.
- `Audit.tsx`, `Dashboard.tsx`, `Connect.tsx` UI pages.
- `OpenAIService` AUTO-mode auto-send path.
- `ActionDispatcher` `allow_side_effects` boolean (we use the approval engine instead).

---

## Phase 5A-0 closing notes

- This document is the **single source for Phase 5A scoping**. Any deviation needs explicit Prarit sign-off + a revision of §F (allowed message types) or §I (approval mapping).
- The next implementer should start at §O (the implementation checklist), not at the reference repo.
- The reference repo is **frozen as of SHA `273b57a3` (audited 2026-04-28)**. Re-audit before adopting any new patterns from later commits.

---

# Phase 5A-1 Addendum — WhatsApp AI Chat Sales Agent + Discount Rescue Policy

> **Status:** Doc-only addendum. **No runtime code, models, migrations, APIs, or frontend pages land in this phase.**
> **Date locked:** 2026-04-28. **Source:** Prarit business decision after Phase 5A-0 audit.
> **Supersedes nothing.** Phase 5A-0 audit findings, Meta Cloud production target, Baileys dev/demo-only constraint, Claim Vault enforcement, and CAIO hard-stops in §A–R remain unchanged. This addendum **expands** the scope of the WhatsApp module from "lifecycle reminder sender" to "inbound-first AI Chat Sales + Support Agent that mirrors the AI Calling Agent's business objective".

---

## S. Product positioning shift

Phase 5A-0 framed WhatsApp as a **lifecycle reminder sender** (payment / confirmation / delivery / RTO / reorder templates with consent + Claim Vault gates).

Phase 5A-1 widens this to the locked product positioning:

> **WhatsApp AI Sales Agent + Lifecycle Messaging.**

The WhatsApp surface is **not only a sender**. It is the same business agent as the AI Calling Agent — only the channel differs. Both share:

- the same Customer / Order / Payment / Shipment lifecycle as the source of truth,
- the same Claim Vault for product / medical text,
- the same Approval Matrix,
- the same Reward / Penalty engine,
- the same CAIO hard stops (CAIO never sends customer messages),
- the same "delivered profitable orders" success metric.

**What changed:** the WhatsApp Chat Agent must be capable of running an inbound-first conversation through the full sales funnel — discovery → category detection → Claim-Vault-grounded explanation → objection handling → address collection → order booking → payment-link handoff → confirmation / delivery / RTO / reorder follow-through — escalating to the AI Calling Agent or a human whenever the chat surface is the wrong tool for the next step.

**What did NOT change:** Phase 5A still ships the **Live Sender Foundation** first (Meta Cloud client + send pipeline + 7 templates + consent + Claim Vault + approval matrix + webhook). Phase 5C wires the AI Chat Agent on top of that foundation. Phase 5A-1 only locks the **direction** so Phase 5A's models and provider interface don't paint Phase 5C into a corner.

---

## T. Customer journey (inbound-first)

When a previously-unknown number sends an inbound WhatsApp message:

```
Inbound WhatsApp message
  → Customer match-or-create (apps.crm.Customer)
  → WhatsAppConversation create-or-update (matched on Customer)
  → Intent detection (greeting / category / objection / address / call-request / opt-out)
  → Greeting reply (locked, see §U) if generic-intro detected
  → Category detection (see §X) if product not yet identified
  → Claim-Vault-grounded product explanation (see §H)
  → Objection handling (price / trust / fit / timing) — NO upfront discount (see §AA)
  → Address collection in chat (see §W)
  → Order draft (apps.orders.services.create_order — existing)
  → Payment-link handoff (existing apps.payments.services.create_payment_link with FIXED_ADVANCE_AMOUNT_INR)
  → Confirmation reminder template (existing 5A scope)
  → Delivery / RTO / reorder / support lifecycle (existing 5A scope + 5E automation)
  → Chat-to-call handoff (see §Y) when warranted at any step
```

**Key locked rule:** every step that mutates business state (`Customer`, `Order`, `Payment`, `Shipment`) flows through the **existing tested service layer** — exactly the same path the AI Calling Agent and the operator-triggered HTTP endpoints use. The Chat Agent never builds its own ORM writes.

---

## U. Greeting rule (locked)

When the inbound message matches a "generic intro" intent — `hi`, `hello`, `hii`, `namaste`, `namaskar`, `hey`, or any single-word greeting / single-emoji message in any language — the **first** outbound reply must be exactly:

> **"Namaskar, Nirogidhara Ayurvedic Sanstha mai aapka swagat hai. Bataye mai aapki kya help kar sakta/sakti hu?"**

The reply is sent through a Meta-pre-approved UTILITY template (Phase 5A registers it as `whatsapp.greeting`). The template body is the exact string above, with no variables.

After the greeting, the Chat Agent continues normal conversation (category detection / discovery / explanation).

**Why a fixed string and not a variable greeting:** consistency, brand voice, and Meta template approval rules. AI freestyle on the very first reply is the highest-risk surface for off-brand tone.

---

## V. First-phase mode — auto-reply with guardrails

Phase 5C ships the AI Chat Agent in **`auto-reply` mode**, but only because every reply is wrapped in the existing Nirogidhara guardrails:

| Guardrail | Where it fires | Effect on WhatsApp Chat Agent |
| --- | --- | --- |
| Claim Vault enforcement | `apps.ai_governance.prompting.build_messages` (existing) | LLM cannot speak medical / product text not in `apps.compliance.Claim.approved`. Post-LLM filter drops sentences containing strings outside the vault. |
| Approval Matrix | `apps.ai_governance.approval_engine.enforce_or_queue` (existing Phase 4C) | Every send goes through `enforce_or_queue` first. `auto_with_consent` actions auto-approve when consent + approved-template + Claim Vault all pass. `approval_required` actions queue an `ApprovalRequest`. |
| AuditEvent | `apps.audit.signals.write_event` (existing) | Every send / status / consent / handoff writes an `AuditEvent`. Phase 4A WebSocket fanout already covers the new `whatsapp.*` kinds. |
| CAIO hard stop | `apps.ai_governance.approval_execution._check_caio_block` (existing Phase 4D) | CAIO can never send a customer message — refused at engine + AgentRun bridge + execute layer + a fourth explicit check at the WhatsApp service entry. |
| Sandbox toggle | `apps.ai_governance.SandboxState` (existing Phase 3D) | Sandbox-on stamps `WhatsAppMessage.sandbox=True` and routes through the mock provider; no live Meta send. |
| Per-agent budget | `apps.ai_governance.budgets` (existing Phase 3D) | The Chat Agent has a USD budget; over-budget runs fail closed with `ai.budget.blocked` audit. |
| Reward / Penalty | `apps.rewards.engine` (existing Phase 4B) | Discount leakage / risky claims / unauthorised discount > 20% all penalize the Chat Agent. CEO AI gets net accountability. |
| 50% total-discount cap | NEW (see §AA) | Hard fail closed when the cumulative discount across stages would exceed 50%. |

**Locked rule:** "auto-reply mode" means **the AI replies without operator click**. It does NOT mean "the AI bypasses the matrix / Claim Vault / approval engine". The matrix path stays the same; auto-mode only changes who initiates the call (cron / signal / inbound webhook vs. operator click).

**What auto-reply mode never does:**

- No freestyle medical / product claims.
- No refund / legal / side-effect / medical-emergency replies.
- No broadcast / campaign sends.
- No unauthorized discount > 20% (still requires director_override per Phase 3E).
- No customer-facing message originated by CAIO.

---

## W. Address collection in chat

The Chat Agent collects shipping details directly in the WhatsApp thread. The collection flow is **stateful per `WhatsAppConversation`** (state stored in `WhatsAppConversation.metadata.address_collection`), not freestyle prompt engineering:

| Field | Required | Validation |
| --- | --- | --- |
| `name` | yes | non-empty |
| `phone` | yes | E.164; defaults to the WhatsApp `from` number, customer can override |
| `alternate_phone` | no | E.164 if provided |
| `address_line` | yes | non-empty, ≥ 8 chars |
| `pincode` | yes | 6 digits, validated against the pincode service used by Delhivery (Phase 2C adapter) |
| `city` | yes | non-empty |
| `state` | yes | non-empty (LLM auto-fills from pincode and asks customer to confirm) |
| `landmark` | no | free-form |
| `payment_preference` | yes | one of `advance_499` / `cod` / `full_advance` |
| `confirm_intent` | yes | explicit "haan / yes / confirm" before order is punched |

**Failure / unclear cases — escalate to AI Calling Agent (see §Y):**

- Pincode rejected by Delhivery service (out-of-deliverable area) → handoff for human address verification.
- Address line < 8 chars after two clarification attempts → handoff.
- Customer types "call me" / "phone karo" / "baat karni hai" at any step → immediate handoff.
- Customer goes silent for > 24h after reaching the address-collection state → re-engagement template (consent-gated), then handoff.

**Order creation is the existing service path:** `apps.orders.services.create_order(...)` exactly as the AI Calling Agent uses today. No parallel "WhatsApp order" model — the Order model is the single source of truth.

---

## X. Category detection (locked)

When the customer's first non-greeting message does not name a specific product, the Chat Agent **must** identify the **category** before any product-specific text leaves the system. Categories (locked, mirrors `apps.catalog.ProductCategory` slugs):

- `weight-management` (weight loss / weight management)
- `blood-purification` (blood purifier / skin wellness)
- `men-wellness`
- `women-wellness`
- `immunity`
- `lungs-detox`
- `body-detox`
- any other approved wellness category present in `apps.catalog.ProductCategory.is_active=True`

**Hard rules:**

1. The AI **must not** recommend a product unless its category has been confirmed by the customer.
2. Once the category is confirmed, product explanation **must** use `apps.compliance.Claim.approved` for that product. No claim outside the vault, ever.
3. If no `apps.catalog.Product` matches the confirmed category, the agent says "Thoda check karke bata sakti hu" and triggers a handoff (see §Y).
4. **The category-detection prompt is registered as a Meta UTILITY template** — not freestyle text — so the first product-bound reply is always template-shaped. Free-form chat starts only after the category template has been answered.

---

## Y. Chat-to-call handoff

The WhatsApp Chat Agent triggers an AI Calling Agent handoff (`apps.calls.services.trigger_call_for_lead` — existing Phase 2D adapter) in any of these cases:

- Customer text matches the call-request pattern: `call me`, `phone karo`, `phone kar do`, `baat karni hai`, `mujhe call karo`, etc.
- Confidence below the agent's threshold for two consecutive turns.
- High intent but no closing on chat after N attempts (configurable per `PromptVersion` metadata).
- Address / payment / pincode clarification needed and chat round-trip is failing.
- Inbound text matches any handoff flag from the existing six-flag list (medical_emergency / side_effect_complaint / very_angry_customer / human_requested / low_confidence / legal_or_refund_threat — already used by Vapi consumer in Phase 2D).
- High-risk Delivery / RTO rescue requires voice contact.
- Customer asks to talk to "someone" / "human" / "manager".

**Handoff contract:**

- The triggered call carries the same `Customer` + `Order` (if any) + `WhatsAppConversation` ids in its `metadata` so context is preserved.
- The chat thread is paused (no auto-reply) until the call ends or the operator marks the conversation `pending`.
- An `AuditEvent` of kind `whatsapp.handoff.call_triggered` is written.
- The `WhatsAppConversation.ai_status` flips to `pending_approval` — auto-replies do not resume until the call's transcript outcome is processed.

**Reverse handoff (Phase 5D):** the AI Calling Agent can "send remaining details on WhatsApp" — fires a single approved template back into the chat thread.

---

## Z. Allowed / Blocked AI chat flows (Phase 5A-1 lock)

### Allowed (with guardrails)

| Flow | Approval mode | Guardrail |
| --- | --- | --- |
| `whatsapp.greeting` | auto_with_consent | Fixed-string Meta UTILITY template (see §U) |
| Category detection question | auto_with_consent | Meta UTILITY template; no freestyle |
| Customer problem / lifestyle discovery | auto_with_consent | Generic Hindi/Hinglish discovery prompts; **no medical advice** |
| Claim Vault product explanation | auto_with_consent | **Strict Claim Vault** filter (post-LLM rejection) |
| Objection handling (price / trust / fit / timing) | auto_with_consent | Approved talk-track prompts only; **no upfront discount** (see §AA) |
| Order booking support / address collection | auto_with_consent | State machine in `WhatsAppConversation.metadata.address_collection` (see §W) |
| Payment-link handoff (₹499 advance) | auto_with_consent | Existing `apps.payments.services.create_payment_link` |
| Call handoff trigger | auto | Existing `apps.calls.services.trigger_call_for_lead` |
| Confirmation reminder | auto_with_consent | Existing 5A template |
| Delivery / RTO rescue messages | auto_with_consent (low/med) / approval_required (high) | Risk-band gate from Phase 4B engine |
| Reorder reminder | auto_with_consent | MARKETING template; explicit opt-in |
| Support / complaint acknowledgement | auto_with_consent | Auto-ack only; complaint detail → human |
| **Refusal-based rescue discount** (≤ 20% per stage, ≤ 50% total) | approval_required (admin / CEO AI) | New §AA / §BB rules |

### Blocked (hard stops, restated for the Chat Agent)

- Freestyle medical / product claims.
- "Guaranteed cure", "permanent solution", "no side effects for everyone", "doctor ki zarurat nahi", any disease-cure claim without doctor approval.
- Refund promises (director-only, human escalation).
- Legal replies (human escalation).
- Side-effect medical advice (human escalation).
- Emergency medical handling (immediate human escalation).
- Broadcast / campaign sends (Phase 5F only, director-approved).
- **Total discount > 50% across the customer lifecycle** (see §AA).
- Customer-facing messages originated by CAIO (engine + bridge + execute + WhatsApp service entry guard).

---

## AA. Discount discipline — the locked Prarit rule

This is the **most important business rule** in this addendum. Read it twice.

### Default behaviour

The AI Chat Agent and the AI Calling Agent **must never offer a discount upfront**. Standard sales conversation:

1. **Lead with standard price.** ₹3,000 for 30 capsules.
2. **Do not mention discount unless the customer asks.**
3. If the customer asks for a discount **once**, first handle the underlying objection — **value, trust, benefit, brand, doctor approval, ingredients, lifestyle fit**. Do **not** drop price.
4. Only if the customer pushes 2–3 times and the conversation is at clear risk of being lost, the agent may offer a discount **within the approved policy** (Phase 3E `validate_discount` bands: ≤10% auto, 11–20% approval, > 20% director-override).

**Reason this is locked:** if the AI agent offers a discount immediately, every customer learns to ask, and AI agents leak margin systemically. The discipline is a sales-design rule, not a code rule — but it must be reflected in prompt content, in Reward / Penalty signals (`discount_leakage_11_to_20_without_reason` already exists in Phase 3E), and in the audit trail.

### Refusal-based rescue discount (the only proactive offer path)

The AI may offer a discount **proactively** only when the customer is **refusing** and the order is **at risk of being lost**. Three eligible stages:

#### Stage A — Order booking refusal (Sales / Chat / Call)

Trigger phrases (any language; semantic match):

- `nahi chahiye` / "no" / "not interested" / "later"
- `price zyada hai` / "expensive" / "high price"
- `baad mein` / "next time" / "abhi nahi"
- explicit "do not book" / "cancel"

Action: after one round of objection handling, if the customer is still refusing, the AI may offer a rescue discount in the 0–20% band per `validate_discount`.

#### Stage B — Confirmation refusal (Confirmation AI)

Trigger phrases:

- "I did not order this"
- "cancel my order"
- "amount is too high"
- "I will not receive"

Action: the Confirmation AI may offer **additional** rescue discount on top of any sales-stage discount, subject to the per-stage band and the **50% total cap** (§BB).

#### Stage C — Delivery / RTO refusal (Delivery / RTO Agent)

Trigger phrases:

- "refuse parcel"
- "I have no money" / "paisa nahi hai"
- "return parcel" / "send back"
- "not needed" / "nahi chahiye"

Action: the Delivery / RTO Agent may offer a **final** rescue discount to save the delivery, subject to the per-stage band and the **50% total cap**.

---

## BB. 50% total discount hard cap (locked)

**Across all stages combined, the total discount on a single order must NEVER exceed 50%.**

### Worked examples

| Stage A (Sales) | Stage B (Confirmation) | Stage C (Delivery) | Total | Verdict |
| --- | --- | --- | --- | --- |
| 20% | 20% | 10% | 50% | ✅ allowed |
| 20% | 20% | 20% | 60% | ❌ blocked / escalate |
| 10% | 0% | 0% | 10% | ✅ allowed (auto band) |
| 25% (director override) | 10% | 10% | 45% | ✅ allowed |
| 25% (director override) | 25% (director override) | 5% | 55% | ❌ blocked / escalate |
| 0% | 30% (director override) | 25% (director override) | 55% | ❌ blocked / escalate |

### Scope of the cap

The 50% cap applies to **every AI workflow that can offer a discount**:

- WhatsApp AI Chat Agent (Phase 5C)
- AI Calling Agent (Phase 2D + future)
- Confirmation AI (Phase 3B)
- RTO / Delivery AI (Phase 3B)
- Customer Success AI (Phase 3B)
- Any future AI workflow that executes a discount via the Phase 4D approved-action layer.

### Enforcement (planned, doc-only)

When Phase 5C / 5D wires this in code, enforcement happens at **two layers**:

1. **Existing Phase 3E `validate_discount`** policy — keeps the per-band rules (auto / approval / director-override).
2. **NEW `validate_total_discount_cap(order, additional_pct)`** — sums the existing `Order.discount_pct` plus any in-flight rescue discount, refuses when the result exceeds 50%, writes `discount.blocked` AuditEvent, and escalates to a human approver.

The cap check runs **before** `apply_order_discount` in the Phase 4D execution layer. A rescue request that would push the total over 50% is converted into an `ApprovalRequest` of action `discount.above_50_director_override` (a new matrix row in Phase 5C — does NOT exist yet) which is **director-only + human escalation by default**.

---

## CC. Discount audit requirements

Every discount or discount **offer** (whether accepted, rejected, or auto-blocked) must record:

| Field | Source |
| --- | --- |
| `customer_id` | `Customer.id` |
| `order_id` | `Order.id` (if any) |
| `conversation_id` | `WhatsAppConversation.id` (or `Call.id` for calling agent) |
| `agent` | the AI agent token (`whatsapp_chat`, `calling_ai`, `confirmation_ai`, `rto_ai`, `success_ai`) |
| `channel` | `whatsapp` / `call` / `confirmation` / `delivery` |
| `stage` | `sales` / `confirmation` / `delivery` / `rto` / `reorder` |
| `trigger` | `asked_discount` / `refused_order` / `refused_confirmation` / `refused_delivery` |
| `customer_text_excerpt` | first 240 chars of the customer message that triggered the offer |
| `current_total_discount_pct` | sum of all prior approved discount events on this order |
| `proposed_additional_discount_pct` | the new offer (per-band) |
| `final_total_discount_pct` | proposed running total |
| `cap_checked_pass` | bool — did the 50% cap check pass? |
| `policy_band` | `auto` / `approval` / `director_override` / `blocked` (from `validate_discount`) |
| `approval_state` | `auto_approved` / `pending` / `approved` / `rejected` / `blocked` |
| `estimated_profit_impact_inr` | derived from `Order.amount` × `additional_discount_pct`/100 |
| `reason` | free-form (from agent's reasoning) |
| `audit_event_id` | the matching `AuditEvent.pk` |
| `reward_penalty_signal` | one of `discount_leakage_11_to_20_without_reason` / `unauthorized_discount_above_20` / `null` (from Phase 4B engine) |

The `AuditEvent` of kind `discount.offered` (NEW — to be added in Phase 5C) carries this record. The existing `discount.applied` (Phase 4E) keeps firing on the actual `Order.discount_pct` mutation.

---

## DD. Future model + API planning notes (NOT implemented yet)

> All names, fields, and endpoints in this section are **planning-only**. They are NOT created in Phase 5A-0, Phase 5A-1, or Phase 5A. The Phase 5C / 5D PR will revisit and finalize the schemas before any migration is generated.

### Future models (planning sketch)

| Model | Purpose |
| --- | --- |
| `WhatsAppAIReplySuggestion` | One row per LLM-generated reply candidate that did NOT auto-send (suggest mode / pending approval). Fields: `conversation`, `agent_run`, `prompt_version`, `suggested_text`, `confidence`, `claim_vault_pass`, `approval_request`, `accepted` (bool, set when operator clicks "send"), `created_at`. |
| `WhatsAppChatAgentRun` | Lightweight join between `apps.ai_governance.AgentRun` and a specific `WhatsAppConversation` turn. Useful for the Reward / Penalty engine to trace WhatsApp-specific outcomes. |
| `WhatsAppHandoffToCall` | One row per chat-to-call handoff (§Y). Fields: `conversation`, `customer`, `order` (nullable), `triggered_by` (text pattern / confidence / explicit-request / etc.), `call` (FK to `apps.calls.Call`), `outcome`. |
| `WhatsAppConversationOutcome` | Terminal-state record per conversation. Fields: `conversation`, `outcome` (`order_booked` / `lost_to_objection` / `lost_to_silence` / `handed_off_to_human` / `opted_out`), `closing_notes`, `closed_at`, `closed_by`. |
| `WhatsAppEscalation` | When the conversation triggers a human-only path (medical / legal / refund / opted-out). FK to a future `Escalation` table or to `WhatsAppHandoffToCall`. |
| `WhatsAppLearningCandidate` | Human-vetted-only learning loop seed (per `learned_memory.py` shape). Fields: `conversation`, `original_suggestion`, `agent_edit`, `compliance_review`, `caio_audit`, `ceo_approval`, `sandbox_test_run`, `promoted_at` (nullable; only non-null after the full QA → Compliance → CAIO → Sandbox → CEO chain). |
| `DiscountOfferLog` | The §CC audit record table. Fields: every column listed in §CC, plus `created_at`. **This is the table that enforces the 50% cap at the DB level via a `(order, final_total_discount_pct)` ordering check in the service layer.** |

### Future endpoints (planning sketch)

| Method + path | Permissions | Purpose |
| --- | --- | --- |
| `POST /api/whatsapp/conversations/{id}/ai-reply/` | admin/director (and operations in suggest mode) | Trigger the Chat Agent to draft a reply. In suggest mode returns the draft; in auto mode returns the `WhatsAppMessage` row. **CAIO 403.** |
| `POST /api/whatsapp/conversations/{id}/handoff-to-call/` | operations+ | Force a chat-to-call handoff from the operator UI. Calls `apps.calls.services.trigger_call_for_lead`. |
| `POST /api/whatsapp/orders/draft-from-chat/` | operations+ | Convert the address-collection state on a `WhatsAppConversation` into a draft `Order` via the existing `create_order` service. |
| `POST /api/whatsapp/discount-offers/` | admin/director | Mint a `DiscountOfferLog` row. Runs `validate_discount` + `validate_total_discount_cap`. Refuses when cap exceeded. |
| `GET /api/whatsapp/conversations/{id}/timeline/` | operations+ | Stitched timeline (messages, handoffs, orders, payments, discount offers, status events) for the Customer 360 tab. |

Each endpoint must:
- Live behind the same `RoleBasedPermission` Nirogidhara already uses.
- Refuse CAIO at every layer (engine + bridge + execute + endpoint).
- Write `AuditEvent`s on every state change.
- Stay idempotent on retry (idempotency key on conversation turn / discount offer).

**These endpoints are NOT part of the Phase 5A Live Sender Foundation unless Prarit explicitly approves expanding 5A scope.** They belong to Phase 5C (`POST /ai-reply/`, `POST /handoff-to-call/`) and Phase 5C / 5D (`POST /draft-from-chat/`, `POST /discount-offers/`, `GET /timeline/`).

---

## EE. Updated WhatsApp roadmap (Phase 5A-1 lock)

Phase numbering after this addendum:

| Phase | Status | Title |
| --- | --- | --- |
| 5A-0 | ✅ DONE | WhatsApp compatibility audit + integration plan |
| **5A-1** | ✅ DONE (this addendum, doc-only) | **WhatsApp AI Chat Agent + Discount Rescue Policy Addendum** |
| 5A | NEXT | Meta Cloud WhatsApp Live Sender Foundation (models, provider, send pipeline, signed webhook, 7 templates, manual operator-triggered send) |
| 5B | future | Inbound WhatsApp Inbox + Customer 360 Timeline |
| 5C | future | WhatsApp AI Chat Sales Agent (Claim-Vault-bound LLM, suggest + auto modes, learned memory, handoff) |
| 5D | future | Chat-to-Call Handoff + Lifecycle Automation (Order / Payment / Shipment signals → templated sends) |
| 5E | future | Confirmation / Delivery / RTO / Reorder automation (rescue discount flow + 50% cap enforcement in code) |
| 5F | future | Campaign system (strict approval-gated; director-only) |

The Phase 5A implementer **must** read §S–§DD of this addendum before designing models / provider / service contracts so:

- `WhatsAppConversation.metadata.address_collection` has somewhere to live.
- `WhatsAppMessage` stores enough context for the Chat Agent path (e.g. linking to `AgentRun`).
- The provider interface can serve both lifecycle templates (5A) and AI-driven chat (5C) without re-design.
- The discount audit table (`DiscountOfferLog`) is anticipated by the model name space.

---

## FF. Updated learning loop scope

The WhatsApp learning loop **may** improve:

- tone (Hindi / Hinglish / English)
- timing (when to reply / when to wait)
- objection handling phrasing
- closing style
- discount-offer timing (after which objection round)
- handoff timing (when to escalate to call / human)
- category-identification questions
- address-collection wording
- delivery rescue language

The WhatsApp learning loop **must NOT create**:

- new medical claims
- new product promises
- cure statements / "permanent solution" copy
- side-effect advice
- refund / legal commitments
- new outbound templates (Meta-pre-approved templates only — sync from WABA)
- discount offers above the per-stage band or the 50% total cap

### Promotion path (locked, mirrors `learned_memory.py`)

```
WhatsApp conversation + outcome
  → AIReplyLog / AgentRun / WhatsAppLearningCandidate (raw)
  → QA review (operator click "accept")
  → Compliance review (Claim Vault delta? doctor sign-off needed?)
  → CAIO audit (drift / hallucination / weak learning detection)
  → CEO approval (sandbox test run on next 100 conversations)
  → live PromptVersion / playbook update
```

**No automatic promotion.** The reference repo's `learned_memory.py` already enforces this exact gate; Phase 5C ports it wholesale.

---

## GG. Cross-document propagation summary

Phase 5A-1 updates the following documents in addition to this addendum:

- `nd.md` — TL;DR "What's next" + §8 Phase 5A-1 entry + closing line.
- `docs/FUTURE_BACKEND_PLAN.md` — Phase 5A-1 inserted between 5A-0 and 5A; phase numbering refreshed (5F is the campaign phase).
- `CLAUDE.md` — §2 hard stops gain the discount discipline + 50% cap rules; §5 file pointers unchanged (this file is the same).
- `AGENTS.md` — "Don't do this" gains the WhatsApp Chat Agent rules; hard-stop section adds the 50% cap; layout pointer entry already exists.
- `README.md` — short "Next" note adding the 5A-1 docs addendum.
- `docs/BACKEND_API.md`, `docs/RUNBOOK.md`, `docs/FRONTEND_AUDIT.md` — no change; Phase 5A-1 ships zero runtime / endpoint / page changes.

---

_End of Phase 5A-1 addendum._

---

## HH. Phase 5C — Implementation note (post-ship)

The full Phase 5A scope shipped (Meta Cloud client, send pipeline, 9 models, webhook, 8 templates).
Phase 5B shipped (Inbound Inbox + Customer 360 timeline).
**Phase 5C — WhatsApp AI Chat Sales Agent — shipped.** Implementation lives in:

- `backend/apps/whatsapp/ai_orchestration.py` — `run_whatsapp_ai_agent` end-to-end pipeline.
- `backend/apps/whatsapp/language.py` — deterministic Hindi/Hinglish/English detection.
- `backend/apps/whatsapp/ai_schema.py` — strict JSON schema + blocked-phrase filter.
- `backend/apps/whatsapp/discount_policy.py` — never-upfront + 50% total cap (§AA + §BB).
- `backend/apps/whatsapp/order_booking.py` — chat-to-order via existing service layer; never touches `apps.shipments`.
- `backend/apps/whatsapp/services.send_freeform_text_message` — TEXT replies through the same gates as templates.
- `backend/apps/whatsapp/tasks.run_whatsapp_ai_agent_for_conversation` — Celery task wired from inbound webhook.
- `backend/apps/whatsapp/views.py` — six new endpoints (`ai/status`, per-conversation `ai-mode / run-ai / ai-runs / handoff / resume-ai`).

Auto-reply is gated by `WHATSAPP_AI_AUTO_REPLY_ENABLED` (default off). The locked Hindi greeting (§U), category-detection-before-product-text rule (§X), discount discipline (§AA), and 50% total cap (§BB) are all enforced server-side.

Phase 5D — chat-to-call handoff + lifecycle automation — shipped (see CLAUDE.md / FUTURE_BACKEND_PLAN.md for the full audit). **Phase 5E** also shipped: rescue discount engine in `apps.orders.rescue_discount` with the locked 50% cumulative cap, per-stage ladder, automatic CEO AI / admin escalation via two new matrix rows (`discount.rescue.ceo_review`, `discount.above_safe_auto_band`), append-only `DiscountOfferLog`, plus four new WhatsApp lifecycle actions (`whatsapp.confirmation_rescue_discount`, `whatsapp.delivery_rescue_discount`, `whatsapp.rto_rescue_discount`, `whatsapp.reorder_day20_reminder`), Day-20 reorder cadence, and a default Claim Vault seed (`python manage.py seed_default_claims`). Defaults stay safe (`WHATSAPP_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_REORDER_DAY20_ENABLED=false`); production opts in only after the AI Calling Agent + WhatsApp AI flow has soaked on test numbers. Phase 5F adds approval-gated broadcast campaigns.

