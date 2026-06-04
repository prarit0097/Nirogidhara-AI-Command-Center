# Backend API Reference

Django REST Framework endpoints exposed by `backend/`. Every entry is consumed
by `frontend/src/services/api.ts`. Response shapes match the TypeScript
interfaces in `frontend/src/types/domain.ts`.

All paths are prefixed by `/api/`. JSON in, JSON out. CORS allows
`http://localhost:8080` by default.

> **Operational baseline (Phase 16K — PRODUCTION VERIFIED on the VPS and CLOSED at commit `efea751`).** Current operational baseline is **Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer** (internal/DB-only; extends `apps.ai_copilot` — `AiApprovedAction` gains 8 additive workboard fields [`department`, `assignee_user`, `work_status`, `due_at`, `blocker_reason`, `completed_by`, `completed_at`, `last_activity_at`] + a new `AiActionWorkEvent` model; 12 new endpoints — `workboard/`, `workboard/summary/`, `workboard/director-attention/`, `actions/<id>/{assign,claim,start,block,unblock,complete-internal,reassign,notes}/`; `sla_status` computed at read time; every transition is DB-only and never calls a provider, `providerAction*` / `externalAction*` stay false; all workboard mutations require director/admin/superuser, reads = auth; backend 23 Phase 16K + 102 regression = 125 passed targeted, frontend 385/385, lint 0, build green, `makemigrations --check` + `manage.py check` clean; VPS browser-validated at `/operations/ai-copilot` — Department action workboard + summary cards; Assign / Claim / Block [Director attention updated] / Unblock / Complete internal / Add note all PASSED; external/provider action flags false; `pytest tests/test_phase16k_action_workboard.py` → 23 passed; healthz OK; ADDS migration `ai_copilot.0003_phase16k_action_workboard` → a fresh VPS deploy requires `migrate`, already applied on the VPS), on top of **Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge** (PRODUCTION VERIFIED at `aa8cf13`). See the Phase 16K + Phase 16J sections below.
>
> **Phase 16J baseline (PRODUCTION VERIFIED on the VPS and CLOSED at commit `aa8cf13`).** **Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge** (internal/DB-only; extends `apps.ai_copilot` with `AiApprovedAction` / `AiApprovedActionEvent` + 7 endpoints under `/api/v1/ai-copilot/actions...`; converts an approved Phase 16I suggestion into an internal-only work item a human applies — only an approved suggestion can become an action [else `409`]; applying is DB-only [may create an internal `PilotTask` via the Phase 16H safe service, else records a `result_payload`] and never calls a provider; locked `providerActionAttempted` / `providerActionTaken` / `externalActionAllowed` / `externalActionTaken` = false; backend 16 new + regression 102 passed targeted, frontend 374/374, lint 0, build green; `makemigrations --check` + `manage.py check` clean; VPS browser-validated at `/operations/ai-copilot` — an approved suggestion created an internal action [PENDING INTERNAL ACTION → Apply → APPLIED INTERNAL; Reject → REJECTED], safety flags stayed false, no live provider action, `pytest tests/test_phase16j_ai_action_queue.py` → 16 passed, healthz OK), on top of **Phase 16I — AI Copilot Enablement + Human Approval Workflow** (PRODUCTION VERIFIED at `0f91f6b`). **It ADDS migration `ai_copilot.0002_phase16j_ai_action_queue`, so a fresh VPS deploy requires `migrate` (already applied on the VPS). Phase 16J is CLOSED (Phase 16K has since shipped on top — PRODUCTION VERIFIED + CLOSED at `efea751`; the current next-planned work is Phase 16L).** See the Phase 16K + Phase 16J + Phase 16I sections below.
>
> **Phase 16I baseline (PRODUCTION VERIFIED on the VPS and CLOSED at `0f91f6b`; previous verified baseline beneath Phase 16J).** **Phase 16I — AI Copilot Enablement + Human Approval Workflow** (internal/DB-only; new app `apps.ai_copilot` with `AiCopilotSuggestion` / `AiCopilotReviewEvent` + 5 endpoints under `/api/v1/ai-copilot/`; deterministic "mock"/"sandbox" generation, no live AI/LLM provider call, human approval before any business action, locked `provider_call_made` / `external_action_allowed` / `external_action_taken` = false; VPS browser-validated at `/operations/ai-copilot` — suggestion generated → pending review → approved + rejected internally, external-action flags false; targeted suite 19 passed `[100%]`, regression 67 passed `[100%]`, healthz OK), on top of **Phase 16H — Internal Pilot Execution Workbench + Role-Based Task Queues** (PRODUCTION VERIFIED at `d733cf0`). See the Phase 16I section below.
>
> **Phase 16H baseline (PRODUCTION VERIFIED on the VPS and CLOSED at `d733cf0`).** Current operational baseline is **Phase 16H — Internal Pilot Execution Workbench + Role-Based Task Queues** (internal/DB-only; extends `apps.pilot` with `PilotTask` / `PilotTaskEvent` + 7 endpoints under `/api/v1/pilot/`; converts an approved pilot plan into role-based internal task queues + tracks per-team execution; no live provider action; provider actions stay locked at every task status including `in_progress`/`done`; VPS browser-validated at `/operations/pilot-workbench` — pilot plan created/approved, 14 tasks generated, full task lifecycle exercised, targeted suite 19 passed `[100%]`, `makemigrations --check` + `manage.py check` clean, healthz OK), on top of **Phase 16G — Internal Pilot Control Center / Pilot Execution Dashboard** (PRODUCTION VERIFIED at `38e8dc8`). Next planned work: **Phase 16I** (NOT started; separate Director directive required). See the Phase 16H section below.
>
> **Phase 16G baseline (PRODUCTION VERIFIED on the VPS and CLOSED at `38e8dc8`).** Current operational baseline is **Phase 16G — Internal Pilot Control Center / Pilot Execution Dashboard** (internal/DB-only; extends `apps.pilot` with `PilotPlan` / `PilotPlanEvent` / `PilotPlanReview` + 6 endpoints under `/api/v1/pilot/`; no live provider action; provider actions stay locked at every plan state including `running_internal`; VPS browser-validated at `/operations/pilot-control`, targeted suite 19 passed `[100%]`, `makemigrations --check` + `manage.py check` clean, healthz OK), on top of **Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run** (PRODUCTION VERIFIED at `967ed3d`). Next planned work: **Phase 16H** (NOT started; separate Director directive required). See the Phase 16G section below.
>
> **Phase 16F baseline (PRODUCTION VERIFIED on the VPS and CLOSED at `967ed3d`).** Current operational baseline is **Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run** (internal/DB-only; pilot readiness surface + DB-only dry-run engine reusing Phase 16E readiness; no live provider action; VPS browser-validated — `/operations/pilot-readiness` opened with the Controlled Internal Pilot Readiness title, safety shell AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked, gate matrix with Payment/Shipment/Vapi-AI gates BLOCKED and data/calling/order/confirmation/safety gates PASS, an internal dry-run recorded with status BLOCKED, no live side effect; `migrate --noinput` → "No migrations to apply."; targeted + regression suites `[100%]`; healthz OK), on top of **Phase 16E — Payment / Logistics Integration Hardening** (PRODUCTION VERIFIED at `36395f6`), **Phase 16D — Uploaded Customer Data Campaigns + Calling Lifecycle** (PRODUCTION VERIFIED at `c0be74a`), **Phase 16C — Director Daily Briefing + Team Roles UI** (verified at `687ef41`), **Phase 16B — Customer Lifecycle UI Backbone** (verified at `00c3295`), and the Phase 15M Foundation Release Freeze (safety shell frozen at `eefd8b3`). Next planned work: **Phase 16G** (NOT started; separate Director directive required). This API reference catalogues endpoints through the Phase 12D-era surfaces (read-only) plus Phase 15B (`/api/v1/ceo-orchestration/snapshots/sidebar-status/`), Phase 15C (`/api/v1/audit/timeline/`), Phase 16B (`POST /api/leads/import-csv/`, `GET /api/customers/{id}/timeline/`, consent/email/notes/disease_category on `POST /api/leads/`), **Phase 16C's four `/api/v1/director-ops/` endpoints**, **Phase 16D's eleven `/api/v1/imports/` endpoints**, **Phase 16E's two read-only `/api/v1/integrations/payment-logistics/` endpoints**, and **Phase 16F's four `/api/v1/pilot/` readiness + dry-run endpoints** (see the sections below). **Lead uniqueness is PHONE-ONLY (normalized) per Hotfix-2** — a duplicate normalized phone returns a typed `409 Conflict` "Duplicate phone blocked — existing lead found."; same email + different phone is allowed; email is metadata, NOT a uniqueness key. Test-count strings inside this file (e.g. "2730 backend tests + 82 frontend tests") describe the **historical Phase 12D snapshot** and are no longer current; current verification baseline lives in [`../nd.md`](../nd.md). Phase 8F live execute, Phase 7E-Live-B, and Phase 7G-Live remain **NOT approved**. Phase 8F state changes and execute remain CLI-only; HTTP endpoints are read-only. **Next planned work: Phase 16G (separate Director directive required).**

## Phase 16I — AI Copilot Enablement + Human Approval (`/api/v1/ai-copilot/`) — PRODUCTION VERIFIED at `0f91f6b`

Internal/DB-only AI copilot surface (**production-verified** — VPS browser validation of `/operations/ai-copilot` + targeted backend tests 19 passed `[100%]`, regression 67 passed `[100%]`). **Deterministic generation only — no live AI/LLM provider call this phase.** The `suggestions/generate/` and `suggestions/<id>/review/` endpoints are **DB-only** — they write `AiCopilotSuggestion` / `AiCopilotReviewEvent` rows and trigger **no WhatsApp / payment / courier / Vapi / AI-provider call**, no order/payment/customer mutation, and never change `RuntimeKillSwitch` / `SandboxState` (asserted by a defensive backend test). Every suggestion's `providerCallMade` / `externalActionAllowed` / `externalActionTaken` stay `false`. Reads require authentication (viewers may read); generate + review require director / admin / superuser. Response shapes are camelCase and match the `AiCopilot*` interfaces in `frontend/src/types/domain.ts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/ai-copilot/status/` | AI mode + safety status: `aiPaused`, `sandboxOn`, `providerLiveActionsLocked`, `liveAutonomousExecutionLocked:true`, `aiMode` (mock\|sandbox), `liveProviderStatus` (live_gated\|unavailable; never invoked), `aiProvider`, `humanApprovalRequired:true`, `noProviderCallMade:true`. |
| `GET` | `/api/v1/ai-copilot/suggestions/` | List suggestions (`{ items, total }`); filters `?type=&status=&source=&limit=`. |
| `POST` | `/api/v1/ai-copilot/suggestions/generate/` | Generate (deterministically) + persist a suggestion. Body: `{ suggestionType ∈ lead_summary\|call_priority\|call_script\|objection_handling\|compliance_risk\|pilot_recommendation\|task_recommendation\|director_briefing\|whatsapp_draft\|payment_followup_draft\|rto_rescue_draft, sourceType ∈ lead\|customer\|order\|imported_queue_item\|pilot_plan\|pilot_task\|manual, sourceId?, text? }`. Stores sanitized output (`status=pending_review`, locked contract). Writes `ai_copilot.suggestion.generated` audit. **Director/Admin only.** Unknown type/source → `400`. |
| `GET` | `/api/v1/ai-copilot/suggestions/{id}/` | Suggestion detail + `detail` JSON + review events. |
| `POST` | `/api/v1/ai-copilot/suggestions/{id}/review/` | Record an internal human review. Body: `{ action ∈ approve\|reject\|comment\|apply_internal, note? }`. Sets status; `apply_internal` is an internal acknowledgement only and NEVER authorises an external action; re-asserts the locked contract. Writes `ai_copilot.suggestion.reviewed` audit. **Director/Admin only.** Unknown action → `400`. |

**Validation:** unknown `suggestionType` / `sourceType` / review `action` → `400`. POST without director/admin/superuser → `403`. No endpoint calls a live AI/LLM provider, touches a real provider, mutates a real `Order` / `Payment` / `Shipment` / `Customer` / `Lead`, or changes the Phase 15 safety shell.

## Phase 16K — Department Action Workboard (`/api/v1/ai-copilot/workboard...`) — PRODUCTION VERIFIED at `efea751`

Internal/DB-only **department execution layer** over the Phase 16J AI-approved internal actions. Extends `apps.ai_copilot` (`AiApprovedAction` workboard fields + `AiActionWorkEvent`; migration `ai_copilot.0003_phase16k_action_workboard`). **Calls no external provider.** Every transition re-asserts `providerActionAttempted` / `providerActionTaken` / `externalActionAllowed` / `externalActionTaken` = `false`, writes an `AiActionWorkEvent`, and triggers **no WhatsApp / payment / courier / Vapi / AI-provider call**, no order/payment/customer/discount mutation, no business Celery enqueue, and never changes `RuntimeKillSwitch` / `SandboxState` (asserted by a defensive backend test). Reads require authentication; **all workboard mutations require director / admin / superuser**. `sla_status` is computed at read time (`no_due_date` / `on_track` / `due_soon` / `overdue`). Response shapes are camelCase and extend the `AiApprovedAction` interface in `frontend/src/types/domain.ts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/ai-copilot/workboard/` | Department workboard list (`{ items, total, departments, workStatuses }`); filters `?department=&workStatus=&priority=&slaStatus=&assignee=&search=&limit=`. |
| `GET` | `/api/v1/ai-copilot/workboard/summary/` | Counts: `total`, `unassigned`, `assigned`, `inProgress`, `blocked`, `completedInternal`, `overdue`, `directorAttention`, `byWorkStatus`, `byDepartment`, plus locked safety flags + `phase:"16K"`. |
| `GET` | `/api/v1/ai-copilot/workboard/director-attention/` | Actions needing Director attention (blocked + overdue + unassigned high/urgent), each with an `attentionReason`. |
| `POST` | `/api/v1/ai-copilot/actions/{id}/assign/` | Assign to a department (+ optional `assigneeUserId` / `dueAt`). Body: `{ department, assigneeUserId?, dueAt?, note? }`. Department required (else `409 department_required`). → `work_status=assigned`. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/claim/` | Claim an unassigned action for the current user → `assigned`. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/start/` | Assigned → `in_progress`. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/block/` | Assigned/in-progress → `blocked` (requires `{ reason }`, else `409 blocker_reason_required`). **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/unblock/` | Blocked → `in_progress`. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/complete-internal/` | Assigned/in-progress/blocked → `completed_internal` (internal-only; never calls a provider). **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/reassign/` | Reassign to another `department` / `assigneeUserId` → `assigned`. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/notes/` | Add an internal note (`{ note }`), or flag for Director review (`{ directorReview: true }`). **Director/Admin only.** |

**Validation:** a queue-terminal action (Phase 16J `status` rejected/cancelled) cannot be worked (`409 action_queue_terminal`); a closed work item (completed/rejected/cancelled) or an invalid source state → `409 invalid_work_status`; block without a reason → `409 blocker_reason_required`; assign without a department → `409 department_required`. POST without director/admin/superuser → `403`. No endpoint calls a live AI/LLM provider, touches a real provider, mutates a real `Order` / `Payment` / `Shipment` / `Customer` / `Lead`, or changes the Phase 15 safety shell.

## Phase 16J — AI-Approved Internal Action Queue (`/api/v1/ai-copilot/actions...`) — PRODUCTION VERIFIED at `aa8cf13`

Internal/DB-only **work execution bridge** that converts an **approved** Phase 16I suggestion into a tracked internal-only work item a human applies. Extends `apps.ai_copilot` (`AiApprovedAction` / `AiApprovedActionEvent`; migration `ai_copilot.0002_phase16j_ai_action_queue`). **Calls no external provider.** `from-suggestion/`, `apply/`, `reject/`, `cancel/` are **DB-only** — they write `AiApprovedAction` / `AiApprovedActionEvent` rows (apply may also create an internal `PilotTask` via the Phase 16H safe service when the source is a resolvable pilot plan) and trigger **no WhatsApp / payment / courier / Vapi / AI-provider call**, no order/payment/customer/discount mutation, no business Celery enqueue, and never change `RuntimeKillSwitch` / `SandboxState` (asserted by a defensive backend test across create → apply over 9 safe action types). Every action's `providerActionAttempted` / `providerActionTaken` / `externalActionAllowed` / `externalActionTaken` stay `false`. Reads require authentication; create + apply + reject + cancel require director / admin / superuser. Response shapes are camelCase and match the `AiApprovedAction*` interfaces in `frontend/src/types/domain.ts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/ai-copilot/actions/` | List the action queue (`{ items, total }`); filters `?type=&status=&limit=`. |
| `GET` | `/api/v1/ai-copilot/actions/summary/` | Status counts + `total`, `providerActionsLocked:true`, `noProviderActionTaken:true`, `phase:"16J"`. Registered before the dynamic `actions/<id>/`. |
| `POST` | `/api/v1/ai-copilot/actions/from-suggestion/` | Create an internal action from an **approved** suggestion. Body: `{ suggestionId, actionType ∈ create_calling_followup_task\|create_qa_review_task\|create_pilot_task\|create_customer_note\|create_order_note\|create_callback_item\|create_rto_review_task\|create_payment_followup_task\|create_dispatch_review_task\|create_director_review_item, title?, description?, priority? }`. Suggestion not approved → `409 suggestion_not_approved`; unknown action type → `400`. Status starts `pending_internal_action`; locked contract intact. Writes `ai_copilot.action.created` audit. **Director/Admin only.** |
| `GET` | `/api/v1/ai-copilot/actions/{id}/` | Action detail + `resultPayload` + `safetySnapshot` + events. |
| `POST` | `/api/v1/ai-copilot/actions/{id}/apply/` | Apply (internal). DB-only — materialises an internal `PilotTask` (pilot-plan source) or records a `result_payload`; status → `applied_internal`; re-asserts the locked contract. Only from `pending_internal_action` (else `409`). Writes `ai_copilot.action.applied` audit. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/reject/` | Reject the action (→ `rejected`). Body: `{ note? }`. Writes `ai_copilot.action.rejected` audit. **Director/Admin only.** |
| `POST` | `/api/v1/ai-copilot/actions/{id}/cancel/` | Cancel the action (→ `cancelled`). Body: `{ note? }`. Writes `ai_copilot.action.cancelled` audit. **Director/Admin only.** |

**Validation:** an action can only be created from an **approved** suggestion (else `409 suggestion_not_approved`); unknown `actionType` → `400`; apply is only valid from `pending_internal_action` (else `409`). POST without director/admin/superuser → `403`. No endpoint calls a live AI/LLM provider, touches a real provider, mutates a real `Order` / `Payment` / `Shipment` / `Customer` / `Lead`, or changes the Phase 15 safety shell.

## Phase 16H — Internal Pilot Execution Workbench (`/api/v1/pilot/`) — PRODUCTION VERIFIED at `d733cf0`

Internal/DB-only pilot-execution surface (**production-verified** — VPS browser validation of `/operations/pilot-workbench` + targeted backend tests 19 passed `[100%]`). Extends `apps.pilot`; **calls no external provider**. The `tasks/` create, `tasks/<id>/` PATCH, `tasks/<id>/transition/`, `tasks/<id>/assign/`, and `plans/<id>/tasks/` POST (generate) endpoints are **DB-only** — they write `PilotTask` / `PilotTaskEvent` rows and trigger **no WhatsApp / payment / courier / Vapi / AI-provider call** and never mutate `RuntimeKillSwitch` / `SandboxState` (asserted by a defensive backend test). A task's `providerActionsAllowed` stays `false` and `providerActionsBlocked` stays `true` at every status — **including `in_progress` and `done`**. Reads require authentication (viewers may read); generate / create / update / transition / assign require director / admin / superuser. Response shapes are camelCase and match the `Pilot*` interfaces in `frontend/src/types/domain.ts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/pilot/execution/summary/[?plan=<id>]` | Execution progress dashboard: `byTeam[]` breakdown (todo/in_progress/blocked/done/skipped/cancelled + progressPct), `overall`, `teamPerformance[]`, `blockedLiveActions[]`, `safety`, `noSideEffect:true`, `generatedByProvider:false`. |
| `GET` | `/api/v1/pilot/plans/{id}/tasks/` | List a plan's tasks (`{ items }`); filters `?team=&status=`. |
| `POST` | `/api/v1/pilot/plans/{id}/tasks/` | **Generate** default role-based task queues for the plan. Body: `{ teams?: string[] }`. Refuses with `409` unless the plan is `approved_internal`/`running_internal`; idempotent per team. Writes `pilot.tasks.generated` audit. **Director/Admin only.** |
| `GET` | `/api/v1/pilot/tasks/` | Global task list (`{ items, total }`); filters `?plan=&team=&status=&limit=`. |
| `POST` | `/api/v1/pilot/tasks/` | Create a single task. Body: `{ pilotPlanId (required), teamRole ∈ calling_agent\|confirmation_team\|warehouse_dispatch\|delivery_rto\|qa_compliance\|finance_accounts\|director_admin, title (required), description?, priority?, sequence?, assignedTeamLabel? }`. Writes `pilot.task.created` audit. **Director/Admin only.** |
| `GET` | `/api/v1/pilot/tasks/{id}/` | Task detail + checklist + events. |
| `PATCH` | `/api/v1/pilot/tasks/{id}/` | Update config fields and/or replace the internal `checklist`. **Director/Admin only.** |
| `POST` | `/api/v1/pilot/tasks/{id}/transition/` | Internal task status transition. Body: `{ action ∈ start\|block\|unblock\|complete\|skip\|cancel, note? }`. Valid flow `todo → in_progress → done`; `in_progress → blocked` (block requires `note` — else `400 block_requires_reason`); `blocked → in_progress`; skip/cancel from any non-terminal. Invalid → `409`; unknown action → `400`. Writes a typed event + `pilot.task.transitioned` audit. **Director/Admin only.** No provider call. |
| `POST` | `/api/v1/pilot/tasks/{id}/assign/` | Assign to a user and/or team label. Body: `{ assigneeId?, teamLabel? }`. Writes `pilot.task.assigned` audit. **Director/Admin only.** |
| `GET` | `/api/v1/pilot/tasks/{id}/events/` | The task's internal event log (`{ items }`). |

**Validation:** generate on a non-approved plan → `409`; missing `title` / unknown `teamRole` / unknown `action` → `400`; block without reason → `400`; invalid transition → `409`; non-existent plan reference → `400`. POST/PATCH without director/admin/superuser → `403`. No endpoint touches a real provider, mutates a real `Order` / `Payment` / `Shipment`, or changes the Phase 15 safety shell.

## Phase 16G — Internal Pilot Control Center (`/api/v1/pilot/`) — PRODUCTION VERIFIED at `38e8dc8`

Internal/DB-only pilot-management surface (**production-verified** — VPS browser validation of `/operations/pilot-control` + targeted backend tests 19 passed `[100%]`). Extends `apps.pilot`; **calls no external provider**. The `plans/` create, `plans/<id>/` PATCH, `plans/<id>/transition/`, and `plans/<id>/review/` endpoints are **DB-only** — they write `PilotPlan` / `PilotPlanEvent` / `PilotPlanReview` rows and trigger **no WhatsApp / payment / courier / Vapi / AI-provider call** and never mutate `RuntimeKillSwitch` / `SandboxState` (asserted by a defensive backend test). A plan's `providerActionsAllowed` stays `false` and `providerActionsBlocked` stays `true` at every status — **including `running_internal`**. Reads require authentication (viewers may read); create / update / transition / review require director / admin / superuser. Response shapes are camelCase and match the `Pilot*` interfaces in `frontend/src/types/domain.ts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/pilot/control/summary/` | Control-center summary: `statusCounts`, `totalPlans`, `activePlans`, reused readiness `gates` + `safety` snapshot, `blockedLiveActions`, `noSideEffect:true`, `generatedByProvider:false`. |
| `GET` | `/api/v1/pilot/plans/` | List pilot plans (`{ items, total }`); filters `?status=&type=&limit=`. |
| `POST` | `/api/v1/pilot/plans/` | Create a pilot plan (status `draft`). Body: `{ name (required), pilotType ∈ imported_campaign\|fresh_leads\|existing_orders\|payment_logistics\|full_lifecycle, ownerTeam?, problemCategory?, productCategory?, objective?, riskNote?, allowedListNote?, maxContacts?, safetyAcknowledged?, linkedImportCampaignId?, linkedDatasetId?, linkedOrderId?, linkedDryRunId? }`. Writes a `created` event + `pilot.plan.created` audit. **Director/Admin only.** |
| `GET` | `/api/v1/pilot/plans/{id}/` | Plan detail + `events` + `reviews` + derived `gateStatus` checklist + `metrics`. |
| `PATCH` | `/api/v1/pilot/plans/{id}/` | Update editable config fields; re-asserts the provider-lock contract. **Director/Admin only.** |
| `POST` | `/api/v1/pilot/plans/{id}/transition/` | Internal status transition. Body: `{ action ∈ mark_ready\|approve_internal\|start_internal\|pause\|resume_internal\|complete\|cancel, note? }`. Valid flow `draft → ready_for_review → approved_internal → running_internal → paused → completed`; cancel from any non-terminal state. Invalid transition → `409`; unknown action → `400`. Writes a typed event + `pilot.plan.transitioned` audit. **Director/Admin only.** No provider call. |
| `POST` | `/api/v1/pilot/plans/{id}/review/` | Record an internal Director review. Body: `{ decision ∈ reviewed\|approved_internal\|deferred\|blocked, note? }`. Record-only (`PilotPlanReview`); does not change status. Writes a `note_added` event + `pilot.plan.reviewed` audit. **Director/Admin only.** |
| `GET` | `/api/v1/pilot/plans/{id}/events/` | The plan's internal event log (`{ items }`). |

**Validation:** missing `name` → `400`; unknown `pilotType` / `decision` / `action` → `400`; invalid transition → `409`; non-existent FK reference is dropped to `null`. POST/PATCH without director/admin/superuser → `403`. No endpoint touches a real provider, mutates a real `Order` / `Payment` / `Shipment`, or changes the Phase 15 safety shell.

## Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run (`/api/v1/pilot/`) — PRODUCTION VERIFIED at `967ed3d`

Internal/DB-only pilot rehearsal surface (**production-verified** — VPS browser validation + targeted tests `[100%]`). Reuses Phase 16E readiness + Claim Vault coverage; **calls no external provider**. The `dry-runs/` create and `dry-runs/{id}/review/` endpoints are **DB-only** — they evaluate readiness and write `PilotDryRun` / `PilotDecision` rows but trigger **no WhatsApp / payment / courier / Vapi / AI-provider call** and never mutate `RuntimeKillSwitch` / `SandboxState` (asserted by a defensive backend test). All four endpoints live under `/api/v1/pilot/`. Reads require authentication (viewers may read); create + review require director / admin / superuser. Response shapes are camelCase and match the `Pilot*` interfaces in `frontend/src/types/domain.ts`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/pilot/readiness/` | Read-only readiness: `safety` snapshot, `automationFlags`, payment/payu/logistics readiness, `claimVault`, `teamRoles`, `dataCounts`, a 12-gate `gates[]` matrix, `blockedLiveActions[]`, `signoffChecklistKeys[]`, `noSideEffect:true`, `generatedByProvider:false`. |
| `GET` | `/api/v1/pilot/dry-runs/` | List recent dry-runs (`{ items, total }`). |
| `POST` | `/api/v1/pilot/dry-runs/` | Create + evaluate an internal dry-run. Body: `{ name (required), scenarioType ∈ fresh_lead\|imported_campaign\|existing_order\|payment_logistics\|full_lifecycle, selectedLeadId?, selectedCustomerId?, selectedOrderId?, selectedImportCampaignId?, selectedQueueItemId? }`. Evaluates DB-only; stores verdict (`passed`/`warning`/`blocked`/`failed`), `gateResults`, `blockedReasons`, `safetySnapshot`; always `providerActionsAttempted=false` + `providerActionsBlocked=true`. Writes `pilot.dry_run.created` audit. **Director/Admin only.** |
| `GET` | `/api/v1/pilot/dry-runs/{id}/` | Dry-run detail (adds `gateResults`, `blockedReasons`, `safetySnapshot`, `decisions[]`). |
| `POST` | `/api/v1/pilot/dry-runs/{id}/review/` | Record a Director review. Body: `{ decision ∈ reviewed\|approved_for_next_phase\|deferred\|blocked, note?, signoffChecklist? }`. Force-locks `signoff_checklist["live_provider_gate_not_approved"]=true` on every review. Writes `pilot.dry_run.reviewed` audit. **Director/Admin only.** |

**Validation:** missing `name` → `400`; unknown `scenarioType` → `400`; unknown `decision` → `400`; non-existent FK reference → `400`. POST without director/admin/superuser → `403`. No mutation endpoint touches a real `Order` / `Payment` / `Shipment` or any provider — the dry-run is a DB-only `PilotDryRun` row.

## Phase 16E — Payment / Logistics Integration Hardening (`/api/v1/integrations/`)

Read-only readiness surfaces. **No endpoint creates a live Razorpay/PayU payment link, captures/refunds, calls PayU live, books a live Delhivery AWB, sends WhatsApp/Meta Cloud, places a Vapi call, calls any AI/LLM provider, enqueues a business Celery job, or mutates `RuntimeKillSwitch` / `SandboxState`.** Secrets are surfaced as presence booleans only (never values). Both endpoints require authentication.

| Method | Path | Auth | Purpose & side-effect guarantee |
| --- | --- | --- | --- |
| GET | `/api/v1/integrations/payment-logistics/readiness/` | authenticated | Composite readiness: `safety` (aiPaused / sandboxOn / providerLiveActionsLocked / hardeningMode / phase), `payments` [Razorpay, PayU], `logistics` [Delhivery], `orderWorkflowGates` (paymentGate, shipmentGate), `noSideEffect:true`, `generatedByProvider:false`. Each provider row: `mode` (mock/test/live-gated/unavailable), `configured`, `secretRefsPresent` (booleans), `liveEnabled`, `liveGateRequired`, `liveGatePresent`, `status` (ready/blocked/unavailable/misconfigured), `blockedReasons`, `safeActions`. Live is always blocked (no HTTP live gate in Phase 16E). |
| GET | `/api/v1/integrations/payment-logistics/recent-events/?limit=N` | authenticated | Recent Payment + Shipment records for safe display: payment id / orderId / gateway / status / amount / hasPaymentUrl / gatewayRefLast6; shipment awbLast6 / orderId / courier / status / delhiveryStatus. AWB + gateway ref masked to last-6; no full PII. Read-only. |

**Phase 16E hardening of `POST /api/shipments/` (`ShipmentViewSet.create`):** explicit `DELHIVERY_MODE` dispatch — `mock` → deterministic AWB (no network, 201, unchanged); `test` → Delhivery staging adapter (201, existing Phase 2C behaviour preserved); `live` → **HTTP 409** `{"detail":"live_delhivery_booking_blocked","message":"Live Delhivery booking blocked — Director live gate required."}` (no live production AWB from the API); unknown mode → HTTP 400. The controlled CLI-only Phase 7G-Live gate remains the only live booking path and is unchanged.

> **Historical Phase 12D baseline note (preserved for context):** endpoint body documented
> through Phase 8F read-only surfaces. Historical verification baseline:
> **2730 backend tests + 82 frontend tests**, green on local SQLite
> and VPS Postgres at that snapshot. Phase 8F gate id=1 was recovered/approved on
> the VPS on 2026-05-14 and attempt id=1 was minted, but **Phase 8F
> execute was NOT run**.
>
## Health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/healthz/` | Liveness probe |

## Auth

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/auth/token/` | none | JWT login (`{username, password}`) |
| POST | `/api/auth/refresh/` | refresh token | Rotate access token |

## Phase 16C — Director Operations (`/api/v1/director-ops/`)

Internal-only / review-only. **No endpoint here calls any AI/LLM/WhatsApp/Razorpay/PayU/Delhivery/Vapi provider, generates an AI briefing, enqueues a business Celery job, or mutates `RuntimeKillSwitch` / `SandboxState`.** Writes touch only `DirectorBriefingReview` / `TeamRoleAssignment` rows plus a non-PII `AuditEvent`.

| Method | Path | Auth | Purpose & side-effect guarantee |
| --- | --- | --- | --- |
| GET | `/api/v1/director-ops/briefing-overview/` | director/admin | Read-only composite: latest CEO/Director snapshot status (`fresh`/`stale`/`missing`/`unavailable`, read from the existing Phase 9F snapshot — never regenerated), static business-readiness facts, latest review, `reviewCount`, `generatedByProvider:false`. |
| GET | `/api/v1/director-ops/briefing-reviews/` | director/admin | List recent internal `DirectorBriefingReview` rows (`{items,total}`). |
| POST | `/api/v1/director-ops/briefing-reviews/` | director/admin | Create an internal review/note. Body `{note, decisionStatus∈reviewed/needs_action/deferred, snapshotRef?}`. `needs_action` requires a note (400 otherwise). Stores a row + `directorops.briefing_review.created` audit (no note text / no PII in payload). NEVER triggers WhatsApp/payment/shipment/call/AI generation. |
| GET | `/api/v1/director-ops/team-roles/` | any authenticated | List users with masked email, account `User.role`, internal operational-role label, active flag, plus the 8 `operationalRoleOptions`. |
| POST | `/api/v1/director-ops/team-roles/assign/` | director/admin | Upsert one user's operational-role label. Body `{userId, operationalRole, isActive?, notes?}`. Invalid role → 400; unknown user → 404; non-admin → 403. Stores a `TeamRoleAssignment` row + `directorops.team_role.assigned` audit (ids + role only, no email/name). Grants NO provider access, activates NO automation. |

## Phase 16D — Uploaded Data Campaigns + Calling Lifecycle (`/api/v1/imports/`)

Internal-only. **No endpoint here places a Vapi/AI call, sends WhatsApp/Meta Cloud, creates a Razorpay/PayU link/charge, books a Delhivery shipment, calls any AI/LLM provider, enqueues a business Celery job, or mutates `RuntimeKillSwitch` / `SandboxState`.** Phone numbers are stored to enable calling but are NEVER returned in full (last-4 masked) or written to logs/audit. Order creation reuses `apps.orders.services.create_order` (pure DB insert). Auth required on every endpoint.

| Method | Path | Auth | Purpose & side-effect guarantee |
| --- | --- | --- | --- |
| GET | `/api/v1/imports/overview/` | director/admin | KPI dashboard (datasetCount, validContacts, duplicateCount, invalidCount, activeCampaigns, pendingCalls, interestedRate, orderCreatedCount). |
| GET | `/api/v1/imports/datasets/` | director/admin | List uploaded datasets (`{items,total}`). |
| POST | `/api/v1/imports/datasets/upload/` | director/admin | Upload + validate a CSV. Body `{name, csv, sourceLabel?, problemCategory?, originalFilename?}` (~5MB / 5000-row cap). Auto-detects columns; creates `ImportedDataset` + `ImportedDataRow` rows with per-row `validation_status` (valid / duplicate_in_file / duplicate_existing / invalid_phone / missing_required). **Creates NO Lead/Customer/Order.** Returns dataset + masked error samples + problem breakdown. |
| GET | `/api/v1/imports/datasets/<id>/` | director/admin | Dataset detail + error samples + problem breakdown + campaign ids. |
| GET | `/api/v1/imports/datasets/<id>/rows/?status=&limit=` | director/admin | Dataset rows (phones masked to last-4). |
| POST | `/api/v1/imports/datasets/<id>/create-campaign/` | director/admin | Create `ImportedCallingCampaign` + one `ImportedCallQueueItem` (pending) per VALID row. `no_valid_rows` → 400. |
| GET | `/api/v1/imports/campaigns/?status=&limit=` | director/admin | List campaigns with denormalized counters. |
| GET | `/api/v1/imports/campaigns/<id>/` | director/admin | Campaign detail. |
| GET | `/api/v1/imports/campaigns/<id>/queue/?status=&limit=` | director/admin | Queue items (phones masked). |
| POST | `/api/v1/imports/queue/<id>/outcome/` | director/admin/operations | Record a manual call outcome. Body `{outcome, notes?, nextFollowUpAt?}`. `outcome ∈ interested / not_interested / callback / wrong_number / no_answer / already_ordered / angry_escalation / medical_emergency`. `medical_emergency` → `escalationFlag="medical_emergency"`; `angry_escalation` → `senior_review`. Invalid → 400. No provider contacted. |
| POST | `/api/v1/imports/queue/<id>/create-order/` | director/admin/operations | Create an **internal** Order from an `interested` item via `create_order` (stage Order Punched); links order + best-effort Lead; flips item to `order_created`. Non-interested → 400. No payment/courier/WhatsApp side effect. |

| GET | `/api/auth/me/` | bearer access | Current user + role |
| GET | `/api/settings/` | none | Approval matrix + integration flags + kill-switch state |

## Dashboard

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/dashboard/metrics/` | `Record<string, DashboardMetric>` |
| GET | `/api/dashboard/activity/` | `ActivityEvent[]` (last 25 audit-ledger rows) |
| GET | `/api/audit/timeline/` | **Phase 15C** — read-only sanitised window into the full Master Event Ledger. Admin/director/owner/superuser only (viewer + anonymous → 403/401). Query params: `kind` (exact match), `tone` (one of `success` / `info` / `warning` / `danger`; invalid → 400), `category` (one of `safety` / `rollback` / `ai_governance` / `whatsapp` / `payments` / `orders` / `delivery` / `auth_system` / `other`; invalid → 400; mapping is prefix-derived in pure Python), `q` (case-insensitive substring against `text` only — payload bodies are NEVER substring-searched), `date_from` / `date_to` (ISO 8601), `limit` (default 50, hard-capped at 200, zero / garbage falls back to 50), `offset`. Response: `{items: [{id, occurredAt, kind, tone, icon, text, category, payload}], count, limit, offset, categoriesAvailable, categoryFiltered}`. **`payload` is a sanitised allow-list slice** (70 stable keys: phase / source / actor / agent / IDs / stage / status / counts / tier / labels / boolean flags / SHA-256 hashes). NEVER returns tokens, secrets, API keys, verify tokens, full phone numbers, full emails, addresses, raw bodies, prompt bodies, instruction payloads, provider payloads, transcripts, reply text, customer names, director sign-off text, metadata blobs, or evidence JSON. String values truncated defensively at 200 chars. Non-dict payloads → `{}`. POST/PUT/PATCH/DELETE return 405. NEVER mutates state; NEVER writes a new AuditEvent; NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi / OpenAI / Anthropic / NVIDIA / NIM / OpenRouter; NEVER enqueues a Celery task; NEVER changes RuntimeKillSwitch / SandboxState; NEVER edits any `.env*` file. |

## CRM

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/leads/` | `Lead[]` (now exposes optional `metaLeadgenId`, `metaPageId`, `metaFormId`, `metaAdId`, `metaCampaignId`, `sourceDetail` — all populated when ingested via the Meta webhook; Phase 16B adds `consentCall`, `consentWhatsapp`, `consentMarketing`, `email`, `notes`, `diseaseCategory`) |
| GET | `/api/leads/{id}/` | `Lead` |
| POST | `/api/leads/` | `Lead` (201). **Phase 16B:** payload accepts `consentCall` / `consentWhatsapp` / `consentMarketing` (all default `false`), `email`, `notes`, `diseaseCategory`. **Phase 16B-Hotfix-2:** lead uniqueness is **phone-only** (normalized — `+91…` / `91…` / `0…` / bare-10-digit all collapse to one key). Same email + different phone creates successfully; same normalized phone is blocked. Returns **409** with `{detail: "Duplicate phone blocked — existing lead found.", duplicate: true, field: "phone", duplicate_field: "phone", existingLeadId, existing_lead_id}` on a phone duplicate (no full PII). Operations role and above. |
| POST | `/api/leads/import-csv/` | **Phase 16B — NEW.** CSV lead import. Payload `{csv: string, source?: string}`. Returns summary `{totalRows, createdCount, duplicateCount, errorCount, createdLeadIds[], rowErrors[{rowNumber, reason, phoneLast4}], truncatedErrorList}`. Required CSV columns: `name`, `phone`. Optional aliases: `email`, `source`, `disease/category`, `state`, `city`, `notes`, `consent_call`, `consent_whatsapp`, `consent_marketing`. **Phase 16B-Hotfix-2:** duplicate detection is **phone-only** (normalized) both within the CSV and against existing Leads — duplicates are **skipped, never overwritten**; the same email on two rows with different phones both create. Phone digits in error rows masked to last-4. Max 1000 rows / 50 row-errors per import. Operations role and above. **No WhatsApp / call / payment side-effect.** |
| GET | `/api/customers/` | `Customer[]` |
| GET | `/api/customers/{id}/` | `Customer` |
| GET | `/api/customers/{id}/timeline/` | **Phase 16B — NEW.** Customer 360 unified timeline. Returns `{customerId, calls[], orders[], payments[], shipments[]}` — up to 50 rows per bucket sorted by recency. Calls / Orders matched via `phone`; Payments via `customer_phone` ∪ `customer` name; Shipments via `order_id` from the matched orders. **Distinct from the WhatsApp-only `/api/whatsapp/customers/{id}/timeline/`** which surfaces conversations / messages / internal notes only. Operations role and above. |

## Orders

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/orders/` | `Order[]` |
| GET | `/api/orders/pipeline/` | `Order[]` (sorted by stage) |
| GET | `/api/confirmation/queue/` | `(Order & {hoursWaiting, addressConfidence, checklist})[]` |

## Calls

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/calls/` | `Call[]` (now exposes `provider`, `providerCallId`, `summary`, `recordingUrl`, `handoffFlags`) |
| GET | `/api/calls/active/` | `ActiveCall` (latest) |
| GET | `/api/calls/active/transcript/` | `CallTranscriptLine[]` |

## Payments / Shipments / RTO

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/payments/` | `Payment[]` |
| GET | `/api/shipments/` | `Shipment[]` (with `timeline`, `trackingUrl`, `riskFlag`) |
| GET | `/api/rto/risk/` | `(Order & {riskReasons, rescueStatus})[]` |

## Agents & AI Governance

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/agents/` | `Agent[]` |
| GET | `/api/agents/hierarchy/` | `{root, ceo, caio, departments}` |
| GET | `/api/ai/ceo-briefing/` | `CeoBriefing` (latest) |
| GET | `/api/ai/caio-audits/` | `CaioAudit[]` |
| GET | `/api/ai/agent-runs/` | `AgentRun[]` (Phase 3A — admin/director only) |
| GET | `/api/ai/agent-runs/{id}/` | `AgentRun` (admin/director only) |
| GET | `/api/ai/agent-runtime/status/` | `{phase, dryRunOnly, agents, lastRuns}` (Phase 3B — admin/director only) |
| GET | `/api/ai/scheduler/status/` | `{celeryConfigured, celeryEagerMode, redisConfigured, brokerUrl (redacted), timezone, morningSchedule, eveningSchedule, lastDailyBriefingRun, lastCaioSweepRun, aiProvider, primaryModel, fallbacks, lastCostUsd, lastFallbackUsed}` (Phase 3C — admin/director only) |
| GET | `/api/ai/sandbox/status/` | Sandbox singleton: `{isEnabled, note, updatedBy, updatedAt}` (Phase 3D — admin/director only). Phase 14E adds `sandboxEnabled`, `statusLabel`, `reason`, `confirmationPhrases`. POST verb added Phase 14E for UI-driven typed-phrase toggle. |
| GET | `/api/ai/prompt-versions/` (`?agent=`) | List prompt versions (Phase 3D — admin/director only) |
| GET | `/api/ai/prompt-versions/{id}/` | Single prompt version |
| GET | `/api/ai/budgets/` | Per-agent budgets with current daily/monthly spend decoration |

## Compliance / Rewards / Learning

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/compliance/claims/` | `Claim[]` (Approved Claim Vault) |
| GET | `/api/rewards/` | `RewardPenalty[]` |
| GET | `/api/learning/recordings/` | `LearningRecording[]` |

## SaaS Runtime Live Audit Gate

Phase 6G Controlled Runtime Routing Dry Run is **FULL PASS**. Phase 6H adds
the live audit gate only, and Phase 6I adds the single internal simulation
layer on top of that gate. Default dry-run stays on, live execution stays
blocked, the global runtime kill switch defaults enabled, and approval/run in
Phase 6I never executes external calls. Runtime providers still use
env/config, not DB integration settings. Responses never expose raw secrets,
raw payloads, full phone numbers, or real customer data.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/runtime-live-gate/` | authenticated | Summary/readiness for the live gate, kill-switch state, recent requests, recent gate audit events, blockers, warnings, and next action. |
| GET | `/api/v1/saas/runtime-live-gate/requests/` | authenticated | Recent sanitized `RuntimeLiveExecutionRequest` rows. |
| POST | `/api/v1/saas/runtime-live-gate/requests/` | admin/staff | Create an audit-only live execution approval request. Does not call a provider. |
| GET | `/api/v1/saas/runtime-live-gate/policies/` | authenticated | Phase 6H operation policy registry. All operations have `allowedInPhase6H=false`. |
| GET | `/api/v1/saas/runtime-live-gate/kill-switch/` | admin/director/superuser (Phase 14D tightened from `authenticated`) | Current global kill-switch state. `enabled=true` means live external side effects are blocked. Phase 14D extends the response with `runtimeKillSwitchEnabled`, `aiExecutionBlocked`, `statusLabel: "running" \| "paused"`, `updatedAt`, `updatedBy`, and `confirmationPhrases.{activateEmergencyStop, resumeAiOperations}`. |
| POST | `/api/v1/saas/runtime-live-gate/kill-switch/` | admin/director/superuser | **Phase 14D** — flip the canonical `RuntimeKillSwitch` global row from the UI. Body: `{action: "activate_emergency_stop" \| "resume_ai_operations", reason: string (>= 10 chars), confirmationPhrase: string}`. The `confirmationPhrase` must equal `"ACTIVATE KILL SWITCH"` (for activate) or `"RESUME AI OPERATIONS"` (for resume); mismatch → HTTP 400. Writes a `runtime.kill_switch.ui_changed` audit row with `phase="14D"` + actor + previous/new state + reason, alongside the legacy `runtime.kill_switch.enabled` / `.disabled` rows that `set_runtime_kill_switch` already fires. NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi / WhatsApp / OpenAI / NVIDIA; NEVER mutates any business row. |
| POST | `/api/v1/saas/runtime-live-gate/preview/` | admin/staff | Preview and audit a gate decision for an operation. Does not call a provider. |
| POST | `/api/v1/saas/runtime-live-gate/requests/{id}/approve/` | admin/staff | Mark a request approved for audit/readiness only. Phase 6H still returns `externalCallWillBeMade=false`. |
| POST | `/api/v1/saas/runtime-live-gate/requests/{id}/reject/` | admin/staff | Mark a request rejected. Does not call a provider. |
| GET | `/api/v1/saas/runtime-live-gate/simulations/` | authenticated | List sanitized Phase 6I `RuntimeLiveGateSimulation` rows plus summary. |
| GET | `/api/v1/saas/runtime-live-gate/simulations/{id}/` | authenticated | Fetch one sanitized simulation row. |
| POST | `/api/v1/saas/runtime-live-gate/simulations/prepare/` | admin/staff | Prepare a simulation for `razorpay.create_order` (default), `whatsapp.send_text`, or `ai.smoke_test`. No provider call. |
| POST | `/api/v1/saas/runtime-live-gate/simulations/{id}/request-approval/` | admin/staff | Link an audit-only `RuntimeLiveExecutionRequest`; no provider call. |
| POST | `/api/v1/saas/runtime-live-gate/simulations/{id}/approve/` | admin/staff | Mark simulation approved for rehearsal only. Does not execute. |
| POST | `/api/v1/saas/runtime-live-gate/simulations/{id}/reject/` | admin/staff | Mark simulation rejected. Does not execute. |
| POST | `/api/v1/saas/runtime-live-gate/simulations/{id}/run/` | admin/staff | Run the internal simulation marker only. Always returns `externalCallWasMade=false` and `providerCallAttempted=false`. |
| POST | `/api/v1/saas/runtime-live-gate/simulations/{id}/rollback/` | admin/staff | Mark simulation rolled back. No business-state rollback is needed because no business state was mutated. |

Protected Phase 6H operations: `whatsapp.send_text`,
`whatsapp.send_template`, `razorpay.create_order`,
`razorpay.create_payment_link`, `payu.create_payment`,
`delhivery.create_shipment`, `vapi.place_call`,
`ai.customer_hinglish_chat`, `ai.caio_compliance`, `ai.ceo_planning`,
`ai.reports_summary`, `ai.critical_fallback`, and `ai.smoke_test`.

Protected Phase 6I simulation operations: `razorpay.create_order`
(default), `whatsapp.send_text`, and `ai.smoke_test`. Every simulation
response preserves `dryRun=true`, `liveExecutionAllowed=false`,
`externalCallWillBeMade=false`, `externalCallWasMade=false`, and
`providerCallAttempted=false`.

## Phase 6J — Single Internal Provider Test Plan (planning-only)

Plan-only paper trail for a future Razorpay test-mode call. **No provider
call is ever made from these endpoints.** Synthetic payload is locked:
`{amount: 100, currency: "INR", receipt: "phase6j_internal_test_plan_<plan_id>"}`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/provider-test-plans/` | admin/staff | List sanitized plans (status / provider / operation / approver / safety invariants). |
| GET | `/api/v1/saas/provider-test-plans/{id}/` | admin/staff | Detail. Includes locked safety booleans and the synthetic-payload preview. |
| POST | `/api/v1/saas/provider-test-plans/prepare/` | admin/staff | Prepare a draft plan. No provider call. |
| POST | `/api/v1/saas/provider-test-plans/{id}/validate/` | admin/staff | Validate the snapshot recorded at prepare time (env presence, amount lock, payload lock). |
| POST | `/api/v1/saas/provider-test-plans/{id}/approve/` | admin/staff | Approve **for future Phase 6K execution only**. Never authorises a provider call in Phase 6J. |
| POST | `/api/v1/saas/provider-test-plans/{id}/reject/` | admin/staff | Reject. Audit-only. |
| POST | `/api/v1/saas/provider-test-plans/{id}/archive/` | admin/staff | Archive. Audit-only. |

Every plan response keeps `dry_run=true`, `provider_call_allowed=false`,
`external_call_will_be_made=false`, `external_call_was_made=false`,
`provider_call_attempted=false`, `real_money=false`,
`real_customer_data_allowed=false`. Asserted by
`assert_provider_test_plan_has_no_side_effects`.

## Phase 6K — Single Internal Razorpay Test-Mode Execution Gate

Read-only gate readiness + sanitized attempt records. **Execution itself
is exclusively CLI** (`python manage.py execute_single_razorpay_test_order`)
behind `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=true` +
`--confirm-test-execution` + `RAZORPAY_KEY_ID` starts with `rzp_test`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/provider-execution-attempts/` | admin/staff | List sanitized `RuntimeProviderExecutionAttempt` rows. Status / rollback_status / locked safety booleans / masked env_readiness / safe_request_summary / safe_response_summary. |
| GET | `/api/v1/saas/provider-execution-attempts/{id}/` | admin/staff | Detail. Includes `provider_object_id` once execution succeeds (Phase 6K-B artefact: `pex_8f309650e9644cfaae4418f9` → `order_Sks3KPf0vntKhf`). |
| POST | `/api/v1/saas/provider-execution-attempts/prepare/` | admin/staff | Prepare an attempt against an approved Phase 6J plan. No provider call. |
| POST | `/api/v1/saas/provider-execution-attempts/{id}/rollback/` | admin/staff | Mark attempt rolled back. No business-state rollback is required because no business state was mutated. |
| POST | `/api/v1/saas/provider-execution-attempts/{id}/archive/` | admin/staff | Archive. Audit-only. |

There is intentionally **no `POST execute` endpoint**. Every attempt
preserves `business_mutation_was_made=false`, `payment_link_created=false`,
`payment_captured=false`, `customer_notification_sent=false` regardless
of execution status.

## Phase 6L — Razorpay Test Execution Audit Review + Webhook Readiness Plan (read-only / planning-only)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/execution-audit/?execution_id=<id>` | authenticated | Replay the 10 Phase 6K invariants for the given execution; scan every linked AuditEvent for raw-key leak. FAILs on flipped safety booleans / missing rollback / missing provider object id / leaked secret. |
| GET | `/api/v1/saas/razorpay/webhook-readiness/` | authenticated | Env presence-only readiness check (masked Razorpay key id + webhook secret presence boolean — never raw values). |
| GET | `/api/v1/saas/razorpay/webhook-plan/` | authenticated | Canonical webhook handler policy doc — endpoint design (`POST /api/webhooks/razorpay/test/`), HMAC-SHA256 signature, constant-time compare, idempotency on `x_razorpay_event_id`, 300-second replay window, 9-event allowlist + 9-event denylist, 8 future audit kinds, 13-key sensitive-payload scrub list, `businessMutationPolicy` all-False. |

POST/PATCH/DELETE return 405 on every Phase 6L endpoint. Phase 6L never
calls Razorpay, never creates a payment link, never captures, never sends
a customer notification, never mutates business records, and never
returns the raw Razorpay response (whitelisted summary only).

## Phase 6M-0 — MCP Gateway Foundation (dormant)

Admin-only readiness APIs for the dormant MCP scaffolding. **Do not flip
any `MCP_*` env flag.** Defaults: `MCP_ENABLED=false`,
`MCP_READ_ONLY_MODE=true`, `MCP_WRITE_TOOLS_ENABLED=false`,
`MCP_PROVIDER_TOOLS_ENABLED=false`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/mcp/readiness/` | admin/staff | Gateway readiness summary — feature flags, registry counts, forbidden-tool list size (13), sensitive-key scrub state. |
| GET | `/api/v1/mcp/client-apps/` | admin/staff | List `McpClientApp` rows (no secrets). |
| GET | `/api/v1/mcp/access-policies/` | admin/staff | List `McpAccessPolicy` rows. |
| GET | `/api/v1/mcp/tool-definitions/` | admin/staff | List `McpToolDefinition` rows. |
| GET | `/api/v1/mcp/resource-definitions/` | admin/staff | List `McpResourceDefinition` rows. |
| GET | `/api/v1/mcp/prompt-definitions/` | admin/staff | List `McpPromptDefinition` rows. |
| GET | `/api/v1/mcp/invocations/` | admin/staff | Recent `McpToolInvocationLog` rows (expect zero in Phase 6M-0). |

Detection helpers (`detect_raw_secret`, `detect_full_pii`) use a
`\b\d{10,}\b` word-boundary digit match so ISO timestamps like
`2026-05-04T10:00:00.000000` are not flagged as PII.

## Phase 6M — Razorpay Webhook Handler (test-mode, dormant by default)

Admin-only readiness / event-list / simulate / readiness APIs for the
test-mode webhook handler. The handler endpoint itself is public (signed
HMAC) and lives at `POST /api/webhooks/razorpay/test/` (see Webhooks
section). Defaults: `RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false`,
`RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED=false`,
`RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED=false`,
`RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD=false`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/webhook-handler-readiness/` | authenticated | Returns dormant flag, allowlist + denylist, scrub-key count, idempotency / replay-window settings, locked safety summary. |
| GET | `/api/v1/saas/razorpay/webhook-events/` | authenticated | List sanitized `RazorpayWebhookEvent` rows (safe summary only — never the raw payload). |
| GET | `/api/v1/saas/razorpay/webhook-events/{id}/` | authenticated | Detail (sanitized). |
| POST | `/api/v1/saas/razorpay/webhook-events/simulate/` | admin/staff | Synthetic event simulation. Builds a fake payload through the same scrub + classify pipeline. Never delivers to Razorpay. |

Every response preserves `business_mutation_was_made=false`,
`customer_notification_sent=false`, `raw_secret_exposed=false`,
`full_pii_exposed=false`. Production webhook secret is **never** consumed
by this handler.

## Phase 7B - Controlled Pilot Execution Gate (gate-only, CLI-only review state changes)

Read-only HTTP layer over the Phase 7B controlled pilot gate. Review state
changes are deliberately CLI-only; there is no POST prepare / dry-run /
rollback-dry-run / approve / reject / archive endpoint and **no execute_*
endpoint**.

| Method | Endpoint | Auth | Returns |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/controlled-pilot-gate-readiness/` | admin/staff | Phase 7B readiness, `PHASE7_CONTROLLED_PILOT_GATE_ENABLED` flag state, gate counters, Phase 6T locked-record count, gate contract, internal-staff cohort checklist, kill-switch requirements, approval requirements, rollback rehearsal steps, abort criteria, env posture, forbidden actions, blockers/warnings, `safeToStartPhase7CExecutionReviewFlow`, `nextAction`. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-gates/?limit=N` | admin/staff | Sanitized recent `RazorpayControlledPilotExecutionGate` rows + counts + locked safety booleans (`controlledPilotExecutionAllowedInPhase7B=false`, `liveExecutionAllowedInPhase7B=false`, `providerCallAllowedInPhase7B=false`, etc). |
| GET | `/api/v1/saas/razorpay/controlled-pilot-gates/<id>/` | admin/staff | Sanitized detail for one gate row. No raw secret, no raw signature, no full phone/email/address, no provider response. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-gate-preview/?phase6t_lock_id=<PHASE6T_LOCK_ID>` | admin/staff | Read-only preview of Phase 7B eligibility from a locked Phase 6T audit lock. Never creates rows. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-gate-dry-runs/<gate_id>/` | admin/staff | List of dry-run records for a Phase 7B gate. Read-only. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-gate-rollback-dry-runs/<gate_id>/` | admin/staff | List of rollback-dry-run rehearsal records for a Phase 7B gate. Read-only. |

POST/PATCH/PUT/DELETE on every Phase 7B endpoint return 405. Phase 7B never
calls Razorpay / Meta Cloud / Delhivery / Vapi, never sends or queues
WhatsApp, never creates a shipment / AWB, never mutates real `Order` /
`Payment` / `Shipment` / `Customer` / `Lead` / `WhatsAppMessage` /
`WhatsAppLifecycleEvent` rows, never validates the live `RAZORPAY_KEY_ID`
(provider-execution key validation is deferred to Phase 7C+), never edits
`.env.production`. Approval flips status to
`approved_for_future_phase7c_execution_review` only — Phase 7C / live
execution is **not approved**.

## Phase 6T - Final Phase 6 Audit + Lock (audit-lock-only, CLI-only review state changes)

Read-only HTTP layer over the Phase 6T final audit-lock selector. Review
state changes are deliberately CLI-only; there is no POST prepare/lock/
reject/archive endpoint and no execution endpoint.

| Method | Endpoint | Auth | Returns |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/phase6-final-audit-lock-readiness/` | admin/staff | Phase 6T readiness, flag state, final audit lock counters, Phase 6N -> 6S audit chain, Director signoff contract, kill-switch contract, rollback contract, abort criteria, operator checklist, safety invariants, blockers/warnings, `safeToStartFutureControlledPilot`, `safeToStartPhase7A=false`, and `nextAction`. |
| GET | `/api/v1/saas/razorpay/phase6-final-audit-locks/?limit=N` | admin/staff | Sanitized recent `RazorpayPhase6FinalAuditLock` rows + counts + locked safety booleans. |
| GET | `/api/v1/saas/razorpay/phase6-final-audit-locks/<id>/` | admin/staff | Sanitized detail for one final audit-lock row. No raw payload, raw signature, secrets, full PII, or provider response is returned. |
| GET | `/api/v1/saas/razorpay/phase6-final-audit-lock-preview/?plan_id=<PHASE6S_PLAN_ID>` | admin/staff | Read-only preview of Phase 6T eligibility and final audit contract. Never creates rows. |

POST/PATCH/DELETE on every Phase 6T endpoint return 405. Phase 6T never
executes a pilot, never sends or queues WhatsApp, never calls Meta Cloud
/ Delhivery / Razorpay, never creates shipment / AWB rows, never sends a
customer notification, and never mutates real business tables.

## Phase 6S — Limited Internal Dispatch Pilot Plan (planning-only, CLI-only review state changes)

Read-only HTTP layer over the Phase 6S Limited Internal Dispatch
Pilot Plan review records. **There is no POST endpoint that prepares,
approves, rejects, or archives a pilot plan** — review state changes
are exclusively dispatched via CLI. **Phase 6S never executes a
pilot, never sends a WhatsApp message, never calls Meta Cloud, never
calls Delhivery, never creates a shipment / AWB, never mutates real
``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` /
``Customer`` / ``Lead`` / ``WhatsAppMessage`` /
``WhatsAppConversation`` rows, never calls Razorpay, never flips an
env flag.**

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/payment-dispatch-pilot-plan-readiness/` | admin/staff | Phase 6S readiness composition: 16 locked-False safety invariants, env flag state, pilot plan counters (`pendingManualReview` / `approvedForFuturePhase6T` / `rejected` / `archived` / `blocked` / `pilotExecutionAllowedInPhase6S` / `whatsAppMessageCreated` / `whatsAppMessageQueued` / `metaCloudCallAttempted` / `delhiveryCallAttempted` / `shipmentCreated` / `awbCreated` / etc), Phase 6R approved-readiness count, 9-row Limited Internal Dispatch Pilot contract, four readiness checklists (internal staff cohort / WhatsApp / courier / dispatch), abort criteria, kill-switch + approval + rollback requirements, verification checklist, forbidden-action list, blockers, warnings, `safeToStartPhase6T`, `nextAction`. |
| GET | `/api/v1/saas/razorpay/payment-dispatch-pilot-plans/?limit=N` | admin/staff | List recent `RazorpayPaymentDispatchPilotPlan` rows (sanitized — no raw payload, no PII) + counts + locked safety booleans. Response carries `frontendCanExecute=false`, `apiEndpointCanExecute=false`, `apiEndpointCanApprove=false`, `pilotExecutionAllowedInPhase6S=false`, plus every Phase 6S safety boolean (`realOrderMutationWasMade=false`, `whatsAppMessageCreated=false`, `whatsAppMessageQueued=false`, `metaCloudCallAttempted=false`, `delhiveryCallAttempted=false`, `shipmentCreated=false`, `awbCreated=false`, `customerNotificationSent=false`, `providerCallAttempted=false`). |
| GET | `/api/v1/saas/razorpay/payment-dispatch-pilot-plans/<id>/` | admin/staff | Detail (sanitized). |
| GET | `/api/v1/saas/razorpay/payment-dispatch-pilot-plan-preview/?readiness_id=<PHASE6R_READINESS_ID>` | admin/staff | Read-only preview of how a Phase 6S pilot plan would map from an approved Phase 6R readiness gate. Never creates rows. Returns `proposedContract` (`pilotExecutionAllowedInPhase6S` / `whatsappSendAllowedInPhase6S` / `courierBookingAllowedInPhase6S` / `providerCallAllowedInPhase6S` all `false`). |

Every response preserves the 16 locked-False safety booleans:
`pilotExecutionAllowedInPhase6S=false`,
`liveSendAllowedInPhase6S=false`,
`courierBookingAllowedInPhase6S=false`,
`providerCallAllowedInPhase6S=false`, plus
`realOrderMutationWasMade=false`, `realPaymentMutationWasMade=false`,
`shipmentMutationWasMade=false`, `shipmentCreated=false`,
`awbCreated=false`, `whatsAppMessageCreated=false`,
`whatsAppMessageQueued=false`, `customerNotificationSent=false`,
`metaCloudCallAttempted=false`, `delhiveryCallAttempted=false`,
`razorpayCallAttempted=false`, `providerCallAttempted=false`.
POST/PATCH/DELETE on every Phase 6S endpoint return 405.
Admin/director/superuser auth required for every endpoint.

## Phase 6R — Payment → WhatsApp / Courier Dispatch Readiness (audit-only readiness contract, CLI-only review state changes)

Read-only HTTP layer over the Phase 6R dispatch readiness review
records. **There is no POST endpoint that prepares, approves, rejects,
or archives a readiness gate** — review state changes are exclusively
dispatched via CLI. **Phase 6R never sends a WhatsApp message, never
calls Meta Cloud, never calls Delhivery, never creates a shipment /
AWB, never mutates real ``Order`` / ``Payment`` / ``Shipment`` /
``DiscountOfferLog`` / ``Customer`` / ``Lead`` / ``WhatsAppMessage`` /
``WhatsAppConversation`` rows, never calls Razorpay, never flips an
env flag.**

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/payment-dispatch-readiness/` | admin/staff | Phase 6R readiness composition: locked-False safety invariants, env flag state, readiness counters (`pendingManualReview` / `approvedForFuturePhase6S` / `rejected` / `archived` / `blocked` / `whatsAppMessageCreated` / `whatsAppMessageQueued` / `metaCloudCallAttempted` / `delhiveryCallAttempted` / `shipmentCreated` / etc), Phase 6Q approved-gate count, 9-row dispatch readiness contract, three readiness checklists (WhatsApp / courier / dispatch), rollback plan, forbidden-action list, blockers, warnings, `safeToStartPhase6S`, `nextAction`. |
| GET | `/api/v1/saas/razorpay/payment-dispatch-readiness-gates/?limit=N` | admin/staff | List recent `RazorpayPaymentDispatchReadinessGate` rows (sanitized — no raw payload, no PII) + counts + locked safety booleans. Response carries `frontendCanExecute=false`, `apiEndpointCanExecute=false`, `apiEndpointCanApprove=false`, plus every Phase 6R safety boolean (`realOrderMutationWasMade=false`, `whatsAppMessageCreated=false`, `whatsAppMessageQueued=false`, `metaCloudCallAttempted=false`, `delhiveryCallAttempted=false`, `shipmentCreated=false`, `customerNotificationSent=false`, `providerCallAttempted=false`). |
| GET | `/api/v1/saas/razorpay/payment-dispatch-readiness-gates/<id>/` | admin/staff | Detail (sanitized). |
| GET | `/api/v1/saas/razorpay/payment-dispatch-readiness-preview/?gate_id=<PHASE6Q_GATE_ID>` | admin/staff | Read-only preview of how a Phase 6R readiness gate would map from an approved Phase 6Q workflow gate. Never creates rows. Returns `proposedContract` (whatsappSendAllowedInPhase6R / courierBookingAllowedInPhase6R / providerCallAllowedInPhase6R all `false`). |

Every response preserves the 12 locked-False safety booleans:
`realOrderMutationWasMade=false`, `realPaymentMutationWasMade=false`,
`shipmentMutationWasMade=false`, `shipmentCreated=false`,
`whatsAppMessageCreated=false`, `whatsAppMessageQueued=false`,
`customerNotificationSent=false`, `metaCloudCallAttempted=false`,
`delhiveryCallAttempted=false`, `providerCallAttempted=false`,
`dispatchReadinessAllowedInPhase6R=false`. POST/PATCH/DELETE on every
Phase 6R endpoint return 405. Admin/director/superuser auth required
for every endpoint.

## Phase 6Q — Payment → Order Workflow Safety Gate (audit-gate-only, CLI-only review state changes)

Read-only HTTP layer over the Phase 6Q workflow gate review records.
**There is no POST endpoint that prepares, approves, rejects, or
archives a gate** — gate state changes are exclusively dispatched
via CLI. **Phase 6Q never mutates real ``Order`` / ``Payment`` /
``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead`` /
``WhatsAppMessage`` / ``WhatsAppConversation`` rows.** It never calls
Razorpay, never sends a customer notification, never flips an env
flag.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/payment-order-workflow-gate-readiness/` | admin/staff | Phase 6Q readiness composition: locked-False safety state, env flag state, gate counters (`pendingManualReview` / `approvedForFuturePhase6R` / `rejected` / `archived` / `blocked`), Phase 6P proof counters (`phase6PExecutedCount` / `phase6PRolledBackCount`), 9-row Payment → Order workflow contract, manual review checklist, rollback plan, forbidden-action list, blockers, warnings, `safeToStartPhase6R`, `nextAction`. |
| GET | `/api/v1/saas/razorpay/payment-order-workflow-gates/?limit=N` | admin/staff | List recent `RazorpayPaymentOrderWorkflowGate` rows (sanitized — no raw payload, no PII) + counts + locked safety booleans. Response carries `frontendCanExecute=false`, `apiEndpointCanExecute=false`, `apiEndpointCanApprove=false` so the frontend can render a clear CLI-only banner. |
| GET | `/api/v1/saas/razorpay/payment-order-workflow-gates/<id>/` | admin/staff | Detail (sanitized). |
| GET | `/api/v1/saas/razorpay/payment-order-workflow-gate-preview/?attempt_id=<ID>` | admin/staff | Read-only preview of how a Phase 6Q gate would map. Never creates rows. |

Every response preserves `realOrderMutationWasMade=false`,
`realPaymentMutationWasMade=false`, `shipmentMutationWasMade=false`,
`discountMutationWasMade=false`, `customerNotificationSent=false`,
`providerCallAttempted=false`, `workflowMutationAllowedInPhase6Q=false`.
POST/PATCH/DELETE on every Phase 6Q endpoint return 405.
Admin/director/superuser auth required for every endpoint.

## Phase 6P — Controlled Internal Paid-Status Mutation Test (sandbox-ledger-only, CLI-only execution)

Read-only / preview-only HTTP layer over the Phase 6P sandbox ledger
+ attempt rows. **There is no POST execute / rollback / prepare
endpoint** — Phase 6P mutation is exclusively dispatched via the CLI.
**Phase 6P never mutates real ``Order`` / ``Payment`` / ``Shipment``
/ ``DiscountOfferLog`` / ``Customer`` / ``Lead`` / ``WhatsAppMessage``
/ ``WhatsAppConversation`` rows.** It never calls Razorpay, never
sends a customer notification, never flips an env flag.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/sandbox-paid-status-mutation-readiness/` | admin/staff | Phase 6P readiness composition: locked-False safety state, env flag state, attempt counters (`prepared` / `executed` / `rolledBack` / `archived` / `everExecuted` / `everRolledBack`), ledger counters, 9-event mapping plan, forbidden-action list, blockers, warnings, `safeToStartPhase6Q`, `nextAction`. |
| GET | `/api/v1/saas/razorpay/sandbox-paid-status-mutation-attempts/?limit=N` | admin/staff | List recent `RazorpaySandboxPaidStatusMutationAttempt` rows + `RazorpaySandboxPaidStatusLedger` rows (sanitized — no raw payload, no PII) + counts + locked safety booleans. Response carries `frontendCanExecute=false` and `apiEndpointCanExecute=false` so the frontend can render a clear CLI-only banner. |
| GET | `/api/v1/saas/razorpay/sandbox-paid-status-mutation-attempts/<id>/` | admin/staff | Detail (sanitized). |
| GET | `/api/v1/saas/razorpay/sandbox-paid-status-mutation-preview/?review_id=<ID>` | admin/staff | Read-only preview of how a Phase 6P attempt would map. Never creates rows. |

Every response preserves `realOrderMutationWasMade=false`,
`realPaymentMutationWasMade=false`, `businessMutationWasMade=false`,
`customerNotificationSent=false`, `providerCallAttempted=false`.
POST/PATCH/DELETE on every Phase 6P endpoint return 405.
Admin/director/superuser auth required for every endpoint.

## Phase 6O — Razorpay Sandbox Status Mapping + Manual Review (sandbox-review-only)

Read-only / review-only layer for converting verified Phase 6M
`RazorpayWebhookEvent` rows into proposed sandbox status mapping
review records. **Phase 6O never mutates `Order` / `Payment` /
`Shipment` / `DiscountOfferLog` / `Customer`, never sends a customer
notification, never calls Razorpay, never flips an env flag.**
Approving a review only marks it `approved_for_future_phase6p` —
permission to consider the mapping in Phase 6P, not application.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/sandbox-status-mapping-readiness/` | admin/staff | Phase 6O readiness composition: locked-False safety state, the 9-event mapping plan, review counters, blockers, warnings, `safeToStartPhase6P`, `nextAction`. |
| GET | `/api/v1/saas/razorpay/sandbox-status-reviews/?limit=N` | admin/staff | List recent `RazorpaySandboxStatusReview` rows (sanitized — no raw payload, no PII) + counts + locked safety booleans. |
| GET | `/api/v1/saas/razorpay/sandbox-status-reviews/<id>/` | admin/staff | Detail (sanitized). |
| POST | `/api/v1/saas/razorpay/sandbox-status-reviews/prepare/` | admin/staff | Create / re-fetch a review row from a Phase 6M-verified event. Refuses unless `RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=true` AND the source event is synthetic-eligible (signature_valid / replay_window_valid / first_seen / no business mutation / no customer notification / no PII / amount ≤ 100 paise / event allowlisted). 201 on create, 200 on reuse. |
| POST | `/api/v1/saas/razorpay/sandbox-status-reviews/<id>/approve/` | admin/staff | Mark the review **approved for future Phase 6P only**. NEVER mutates business tables. NEVER calls Razorpay. NEVER sends a customer notification. |
| POST | `/api/v1/saas/razorpay/sandbox-status-reviews/<id>/reject/` | admin/staff | Mark the review rejected. Audit-only. |
| POST | `/api/v1/saas/razorpay/sandbox-status-reviews/<id>/archive/` | admin/staff | Archive the review. Audit-only. |

Every response preserves `mutationAllowedInPhase6O=false`,
`businessMutationWasMade=false`, `customerNotificationSent=false`,
`providerCallAttempted=false`, `shipmentEffectAllowed=false`,
`discountEffectAllowed=false`. POST/PATCH/DELETE on read endpoints
return 405. Admin/director/superuser auth required for every endpoint.

## Phase 6N — Razorpay Webhook Business-Mutation Sandbox Plan (planning-only / readiness-only)

Read-only planning + readiness layer. **Phase 6N never calls Razorpay,
never creates a payment link, never captures a payment, never refunds,
never sends a customer notification, never mutates any business
record, and never flips an env flag.**

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/business-mutation-sandbox-plan/` | admin/staff | Returns the canonical Phase 6N planning JSON: 9-event mapping, synthetic-order eligibility policy, manual-review checklist, rollback plan, safety invariants, forbidden actions, required env defaults, audit plan. |
| GET | `/api/v1/saas/razorpay/business-mutation-sandbox-readiness/` | admin/staff | Returns the Phase 6N readiness composition: `safeToStartPhase6O`, blockers, warnings, `nextAction`, Phase 6M safety-counter snapshot. |

Every Phase 6N endpoint preserves `businessMutationEnabled=false`,
`customerNotificationEnabled=false`, `rawPayloadStorageEnabled=false`,
and every event-mapping row preserves `mutationAllowedInPhase6N=false`,
`customerNotificationAllowed=false`, `shipmentEffectAllowed=false`,
`discountEffectAllowed=false`, `idempotencyRequired=true`,
`rollbackRequired=true`. POST/PATCH/DELETE return 405.

## Analytics

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/analytics/` | `{funnel, revenueTrend, stateRto, productPerformance, discountImpact}` |
| GET | `/api/analytics/funnel/` | `KPITrend[]` |
| GET | `/api/analytics/revenue-trend/` | `KPITrend[]` |
| GET | `/api/analytics/state-rto/` | `KPITrend[]` |
| GET | `/api/analytics/product-performance/` | `KPITrend[]` |

## Field naming

DRF serializers expose camelCase (e.g. `qualityScore`, `paymentLinkSent`,
`rtoRisk`) so the JSON matches the TS interfaces 1-to-1. DB columns stay
snake_case Python-side. The mapping lives in each app's `serializers.py`.

## Master Event Ledger

The `audit.AuditEvent` table is the source of truth for `/api/dashboard/activity/`.
Receivers in `apps/audit/signals.py` write rows on:

- `lead.created` — Lead row created (post-save signal)
- `lead.updated` — explicit, fired by service layer on PATCH
- `lead.assigned` — explicit, fired by service layer on POST `/leads/{id}/assign/`
- `customer.upserted` — explicit, on POST/PATCH customers
- `order.created` / `order.status_changed` — Order row created or stage changed (post-save signal)
- `confirmation.outcome` — explicit, on POST `/orders/{id}/confirm/`
- `payment.link_created` — explicit, on POST `/payments/links/`
- `payment.received` — Payment row saved with status=Paid (post-save signal)
- `shipment.created` — explicit, on POST `/shipments/`
- `shipment.status_changed` — Shipment row saved (post-save signal)
- `shipment.delivered` — explicit, on Delhivery webhook `delivered`
- `shipment.ndr` — explicit, on Delhivery webhook `ndr`
- `shipment.rto_initiated` / `shipment.rto_delivered` — explicit, on Delhivery webhook RTO events
- `rescue.attempted` / `rescue.updated` — explicit, on POST/PATCH `/rto/rescue/`
- `call.triggered` — explicit, on POST `/api/calls/trigger/`
- `call.started` / `call.completed` / `call.failed` — explicit, on Vapi webhook
- `call.transcript` — explicit, on Vapi `transcript.updated` / `transcript.final`
- `call.analysis` / `call.handoff_flagged` — explicit, on Vapi `analysis.completed` (handoff_flagged fires only when one of the 6 safety triggers is present)
- `lead.meta_ingested` — explicit, on Meta Lead Ads webhook delivery (created or refreshed)
- `ai.agent_run.created` / `ai.agent_run.completed` / `ai.agent_run.failed` — explicit, on POST `/api/ai/agent-runs/` (Phase 3A)
- `ai.ceo_brief.generated` — explicit, on CEO daily briefing run when the LLM returns usable content (Phase 3B)
- `ai.caio_sweep.completed` — explicit, on CAIO audit-sweep success (Phase 3B)
- `ai.agent_runtime.completed` / `ai.agent_runtime.failed` — explicit, on every per-agent runtime endpoint (Phase 3B)
- `ai.scheduler.daily_briefing.started` / `.completed` / `.failed` — explicit, on the Celery beat task wrapping CEO + CAIO sweeps (Phase 3C)
- `ai.provider.fallback_used` — explicit, when the dispatcher answered with a fallback provider after the primary failed (Phase 3C)
- `ai.cost_tracked` — explicit, on every successful AgentRun whose adapter reported token usage (Phase 3C)
- `ai.prompt_version.created` / `.activated` / `.rolled_back` — explicit, on PromptVersion CRUD + activate + rollback (Phase 3D)
- `ai.sandbox.enabled` / `.disabled` — explicit, on PATCH `/api/ai/sandbox/status/` (Phase 3D)
- `ai.budget.warning` / `.blocked` — explicit, when an agent's spend crosses the alert threshold or exceeds the configured cap (Phase 3D)
- `runtime.live_gate.previewed` / `.request_created` / `.request_blocked` / `.request_approved` / `.request_rejected` / `.ready_but_not_executed` — explicit, on Phase 6H live-gate preview/request/approval decisions. Payloads contain only sanitized summaries and hashes.
- `runtime.kill_switch.enabled` / `.disabled` — explicit, on Phase 6H runtime kill-switch changes. Enabled means live external side effects are blocked.
- `runtime.live_gate.simulation_prepared` / `.simulation_approval_requested` / `.simulation_approved` / `.simulation_rejected` / `.simulation_blocked` / `.simulation_ran` / `.simulation_rolled_back` — explicit, on Phase 6I simulation lifecycle events. Payloads contain only sanitized summaries, hashes, gate decisions, and safety booleans.

Phase 4+ will add: reward/penalty assigned, CAIO audit completed,
CEO approval recorded.

---

## Writes (Phase 2A)

All write endpoints require `Authorization: Bearer <jwt>` and a user role of
`operations`, `admin`, or `director`. Anonymous → 401, viewer/compliance → 403.

### CRM

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/leads/` | Create a lead |
| PATCH | `/api/leads/{id}/` | Update lead fields |
| POST | `/api/leads/{id}/assign/` | Assign a lead (`{ assignee }`) |
| POST | `/api/customers/` | Create a customer (upsert) |
| PATCH | `/api/customers/{id}/` | Update a customer |

### Orders & confirmation

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/orders/` | Punch a new order |
| POST | `/api/orders/{id}/transition/` | Move order to a new stage (validated by state machine) |
| POST | `/api/orders/{id}/move-to-confirmation/` | Convenience for `Order Punched → Confirmation Pending` |
| POST | `/api/orders/{id}/confirm/` | Record confirmation outcome (`confirmed` / `rescue_needed` / `cancelled`) |

#### State machine

```
New Lead              → Interested, Cancelled
Interested            → Payment Link Sent, Order Punched, Cancelled
Payment Link Sent     → Order Punched, Cancelled
Order Punched         → Confirmation Pending, Cancelled
Confirmation Pending  → Confirmed, Cancelled  (rescue_needed stays here)
Confirmed             → Dispatched, Cancelled
Dispatched            → Out for Delivery, RTO
Out for Delivery      → Delivered, RTO
Delivered             → terminal (reorder cycle in Phase 6)
RTO                   → terminal (reward/penalty in Phase 5)
Cancelled             → terminal
```

Invalid transitions return HTTP 400 with a `detail` message.

### Payments

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/payments/links/` | Mock payment link generator. Body: `{ orderId, amount, gateway, type }`. Returns `{ payment, paymentUrl }`. The Payment row starts in `Pending` status. |

### Shipments & RTO rescue

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/shipments/` | Create a Delhivery shipment. Body: `{ orderId }`. Routes through the three-mode adapter (`DELHIVERY_MODE=mock\|test\|live`). Mock mode generates `DLH<8 digits>` deterministically; test/live mode hits the real Delhivery API. Returns the `Shipment` row with `trackingUrl` populated. |
| POST | `/api/rto/rescue/` | Create a rescue attempt. Body: `{ orderId, channel, notes? }`. |
| PATCH | `/api/rto/rescue/{id}/` | Update outcome. Body: `{ outcome, notes? }`. Bubbles up to parent order's `rescue_status`. |

### Voice (Phase 2D)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/calls/trigger/` | Trigger an outbound Vapi voice call. Body: `{ leadId, purpose? }`. Routes through the three-mode adapter (`VAPI_MODE=mock\|test\|live`). Returns `{ callId, provider, status, leadId, providerCallId }`. |

### AI agent runs (Phase 3A — read-only / dry-run)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/ai/agent-runs/` | Trigger a dry-run agent analysis. Body: `{ agent: "ceo"\|"caio"\|"ads"\|"rto"\|"sales_growth"\|"marketing"\|"cfo"\|"compliance", input: {...}, dryRun?: true }`. Admin/director only. Phase 3A coerces `dryRun` to `true` server-side; the field is on the wire for forward-compat with Phase 5 approval-matrix execution. Routes through `apps/integrations/ai/<provider>.py` based on `AI_PROVIDER` (`disabled`/`openai`/`anthropic`/`grok`). When the provider is disabled or no key is configured the run is persisted with `status: "skipped"` — no LLM call. Every call is grounded in `apps.compliance.Claim` via the prompt builder; medical/product prompts with no approved-claim entries return `failed` rather than dispatching. CAIO can never execute business actions: payloads with intents like `execute`, `apply`, `create_order`, `transition`, etc. are rejected before any LLM dispatch. |
| GET | `/api/ai/agent-runs/` | List recent agent runs (admin/director only). |
| GET | `/api/ai/agent-runs/{id}/` | Single run detail (admin/director only). |

### AI agent runtime (Phase 3B — per-agent dispatch with pre-built DB slices)

Every endpoint is admin/director only and dry-run by construction. Each call dispatches the agent's read-only DB slice through `run_readonly_agent_analysis`; the underlying LLM never runs when `AI_PROVIDER=disabled` (every run is persisted as `skipped`). Each endpoint returns the persisted `AgentRun`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/agent-runtime/status/` | Snapshot — phase + dry-run flag + the last `AgentRun` per agent. |
| POST | `/api/ai/agent-runtime/ceo/daily-brief/` | Generate the daily CEO briefing. On `success` with usable output, refreshes the `CeoBriefing` row + writes `ai.ceo_brief.generated`. Skipped/failed runs leave the existing briefing untouched. |
| POST | `/api/ai/agent-runtime/caio/audit-sweep/` | CAIO audit/monitor sweep. Reads recent `AgentRun` rows + handoff flags + Claim Vault status. Never writes to business state — `services.CAIO_FORBIDDEN_INTENTS` blocks any execute/apply/create_* payload before the LLM is called. |
| POST | `/api/ai/agent-runtime/ads/analyze/` | Meta attribution + ad recommendations. Reads `Lead.meta_*` fields grouped by campaign / ad / form. |
| POST | `/api/ai/agent-runtime/rto/analyze/` | High-risk orders, NDR/RTO shipments, and rescue-attempt outcomes. Suggestions only. |
| POST | `/api/ai/agent-runtime/sales-growth/analyze/` | Call outcomes + order conversion + advance/discount ratios. |
| POST | `/api/ai/agent-runtime/cfo/analyze/` | Revenue + delivered/RTO + payment status. Reporting only. |
| POST | `/api/ai/agent-runtime/compliance/analyze/` | Claim Vault coverage + handoff flags + critical CAIO audits. Fails closed when the vault is empty (`ClaimVaultMissing` → `failed` AgentRun). |

Cron / Windows Task Scheduler can also call `python manage.py run_daily_ai_briefing` to fire the CEO + CAIO sweeps in one shot (`--skip-ceo` / `--skip-caio` to run just one).

### AI scheduler + cost tracking (Phase 3C)

Celery beat schedules the daily CEO briefing + CAIO sweep at **09:00 IST** (morning) and **18:00 IST** (evening). The dispatcher walks the provider chain in `AI_PROVIDER_FALLBACKS` (default: `openai → anthropic`); the first provider whose adapter returns `success` wins. Every AgentRun row stores `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`, `provider_attempts` (full attempt log), `fallback_used`, and `pricing_snapshot` (model-wise rates from `apps/integrations/ai/pricing.py` frozen at run time).

Local dev never needs Redis: `CELERY_TASK_ALWAYS_EAGER=true` (the default) makes `.delay()` run synchronously. To run the beat schedule for real:

```bash
docker compose -f docker-compose.dev.yml up -d redis
celery -A config worker -B --loglevel=info
```

Pricing fallback for `ClaimVaultMissing`: never. The prompt builder fails closed before any adapter is invoked, so a compliance refusal does not trigger a fallback to a different provider.

### AI governance — sandbox / prompt rollback / budget guards (Phase 3D)

All endpoints are admin/director only.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/sandbox/status/` | Read the global sandbox toggle. Phase 14E enriches the response additively with `sandboxEnabled`, `statusLabel: "enabled" \| "disabled"`, `reason`, `updatedAt`, and `confirmationPhrases.{enableSandboxMode, disableSandboxMode}`. Legacy `isEnabled` / `updatedBy` / `note` fields preserved for Phase 3D / 4D consumers. |
| PATCH | `/api/ai/sandbox/status/` | Body: `{ isEnabled, note? }`. Flips the singleton; writes `ai.sandbox.{enabled,disabled}`. While ON, successful AgentRuns NEVER refresh `CeoBriefing` or any other business-state row. |
| POST | `/api/ai/sandbox/status/` | **Phase 14E** — UI-driven sandbox toggle. Body: `{action: "enable_sandbox_mode" \| "disable_sandbox_mode", reason: string (>= 10 chars), confirmationPhrase: string}`. The `confirmationPhrase` must equal `"ENABLE SANDBOX MODE"` (for enable) or `"DISABLE SANDBOX MODE"` (for disable); mismatch → HTTP 400. Disable still routes through the Phase 4C approval matrix as `ai.sandbox.disable` (`director_override`) — a non-director admin gets refused by the matrix even though `_AdminAndUpAlways` lets them in. Writes a `sandbox.mode.ui_changed` audit row with `phase="14E"` + actor + previous/new state + reason, alongside the legacy `ai.sandbox.{enabled,disabled}` rows. NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi / WhatsApp / OpenAI / NVIDIA; NEVER mutates any business row; NEVER touches `RuntimeKillSwitch` state. |
| POST | `/api/ai/prompt-versions/` | Body: `{ agent, version, title?, systemPolicy?, rolePrompt?, instructionPayload?, metadata? }`. Creates a `draft` PromptVersion. The Approved Claim Vault block is always appended to every dispatched prompt — a PromptVersion CANNOT skip it. |
| POST | `/api/ai/prompt-versions/{id}/activate/` | Make this version the active one for its agent. The previous active version is auto-archived. |
| POST | `/api/ai/prompt-versions/{id}/rollback/` | Body: `{ reason }`. Re-activate this version and mark the prior active as `rolled_back` with the reason recorded. (Phase 3D legacy — preserved for the Governance page.) |
| POST | `/api/ai/prompt-versions/rollback-from-ui/` | **Phase 14F** — UI-driven typed-phrase + reason-gated wrapper around the Phase 3D rollback service. Admin/director only. Body: `{agent, targetVersionId, reason: string (>= 10 chars), confirmationPhrase: string}`. `confirmationPhrase` must equal `"ROLLBACK PROMPT VERSION"` exactly; mismatch → HTTP 400. Cross-checks: target version must exist (404 if not), target's agent must match submitted `agent` (400 mismatch), target must not be the currently active row (400 no-op refusal). Records Phase 4C `mark_auto_approved(action="ai.prompt_version.activate")` for the matrix audit trail. Writes a `prompt_version.rollback.ui_changed` audit row with `phase="14F"` + actor + previous/target version ids + reason, alongside the legacy `ai.prompt_version.rolled_back` row that the service writes. NEVER calls any provider; NEVER mutates any business row; NEVER touches `RuntimeKillSwitch` / `SandboxState` state. Response: `{ok, status: "rolled_back", agent, previousActiveVersionId, targetVersionId, auditKind, promptVersion, message}`. |
| GET | `/api/ai/prompt-versions/rollback-history/` | **Phase 15A** — read-only rollback history surface. Admin/director only. Returns sanitised metadata for the two allow-listed audit kinds (`prompt_version.rollback.ui_changed` from Phase 14F + `ai.prompt_version.rolled_back` from Phase 3D service); all other audit kinds excluded. Query params: `?agent=<agent_label>` (filter), `?kind=<allow-listed kind>` (filter; non-allow-listed kinds → HTTP 400), `?limit=` (default 50, hard-capped at 200), `?offset=` (pagination). Response: `{items: [{id, createdAt, kind, tone, actor, agent, previousVersionId, previousVersionLabel, targetVersionId, targetVersionLabel, reason, matrixAction, matrixStatus, status, source, summary}], count, limit, offset, kindsIncluded}`. **NEVER** returns `systemPolicy`, `rolePrompt`, `instructionPayload`, raw audit payload, tokens, phones, addresses, customer data, or any field outside the allow-list — defended by an explicit `_safe_payload_slice` allow-list helper. POST/PUT/PATCH/DELETE return 405. NEVER mutates state; NEVER calls `rollback_prompt_version`; NEVER calls any provider. |
| POST | `/api/ai/budgets/` | Upsert by `agent`. Body: `{ agent, dailyBudgetUsd, monthlyBudgetUsd, isEnforced?, alertThresholdPct? }`. |
| PATCH | `/api/ai/budgets/{id}/` | Update an existing budget row. |

Behavior of the budget guard inside `run_readonly_agent_analysis`:

1. Compute the agent's daily + monthly spend from successful `AgentRun.cost_usd`.
2. If `is_enforced=True` AND spend exceeds the daily or monthly cap → write `ai.budget.blocked`, persist a `failed` AgentRun, and **never** call any adapter (no fallback either).
3. Else if spend ≥ `alert_threshold_pct`% of either cap → write `ai.budget.warning` and continue.
4. Snapshot of the budget check is stamped onto every `AgentRun.budget_snapshot`.

### Approval Matrix Middleware (Phase 4C)

The Phase 3E approval matrix is now actively **enforced**. Risky write paths call `apps.ai_governance.approval_engine.enforce_or_queue()` before performing the write; when the matrix mode is `approval_required`, `director_override`, `auto_with_consent` (no consent), or `human_escalation`, the engine creates an `ApprovalRequest` row and the caller stops. Every status transition writes an `ApprovalDecisionLog` + a Master Event Ledger audit row.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/approvals/` | List approval requests. **Admin/director only.** Query params: `status` (`pending`/`approved`/`rejected`/`auto_approved`/`blocked`/`escalated`/`expired`), `action` (matrix key exact match), `limit` (default 200, max 1000). Each row carries `latestExecutionStatus`, `latestExecutionAt`, `latestExecutionResult`, `latestExecutionError`, `executionLogs[]` (Phase 4D). |
| GET | `/api/ai/approvals/{id}/` | Single request with `decisionLogs[]` + `executionLogs[]`. Admin/director only. |
| POST | `/api/ai/approvals/{id}/approve/` | Body `{ note? }`. Admin/director. **Director-only when `policy.mode == director_override`** — admin → 403. Status flips to `approved`; the underlying business write still flows through its own service path. |
| POST | `/api/ai/approvals/{id}/reject/` | Body `{ note? }`. Admin/director only. Status flips to `rejected`. |
| POST | `/api/ai/approvals/{id}/execute/` | **Phase 4D.** Body `{ payloadOverride?, note? }`. Admin/director only. **Director-only when `policy.mode == director_override`**. CAIO refused at engine + bridge + execute layer. Pre-checks: idempotency (returns prior result if already executed) → CAIO refusal → role gate → status gate (must be `approved` or `auto_approved`; else 409). Routes through the **allow-listed Phase 4D registry** (`payment.link.advance_499`, `payment.link.custom_amount`, `ai.prompt_version.activate`); every other action returns HTTP 400 + `ai.approval.execution_skipped` audit. Response: `{ approvalRequestId, action, executionStatus, executedAt, executedBy, result, errorMessage, message, alreadyExecuted }`. |
| POST | `/api/ai/approvals/evaluate/` | Body `{ action, actorRole?, actorAgent?, payload?, target?, persist?, reason? }`. Admin/director only. With `persist=false` (default) returns the pure evaluation; with `persist=true`, runs `enforce_or_queue` and returns the persisted `approvalRequestId`. Response: `{ action, mode, approver, status, allowed, requiresHuman, reason, policy, approvalRequestId, notes }`. |
| POST | `/api/ai/agent-runs/{id}/request-approval/` | Body `{ reason? }`. Admin/director only. Promotes a successful, non-CAIO AgentRun whose `output_payload` contains `action` (matrix key) and `proposedPayload` into a pending ApprovalRequest. CAIO → 403; failed / skipped / unknown-action runs → 400. |

**Locked rules** (Master Blueprint §12 / §26 + Apr 2026):
- The approval matrix is the single source of truth — views / services call `enforce_or_queue`, not duplicate policy.
- `approve_request` flips status to `approved` and writes audits. It does **not** silently execute the underlying business write; that still flows through its existing tested service path. Phase 4D will add explicit safe execution paths action-by-action.
- **CAIO can never** request an executable approval (refused at the AgentRun bridge AND at the matrix evaluator).
- Unknown action / unknown mode → fail closed.

Audit kinds (Phase 4C):
- `ai.approval.requested`, `ai.approval.auto_approved`, `ai.approval.approved`, `ai.approval.rejected`, `ai.approval.blocked`, `ai.approval.escalated`, `ai.approval.expired`, `ai.agent_run.approval_requested`.

Audit kinds (Phase 4D):
- `ai.approval.executed`, `ai.approval.execution_failed`, `ai.approval.execution_skipped`. Every execute attempt — success, failure, or skipped (unmapped action / pre-check refused) — writes both an `ApprovalExecutionLog` row and a Master Event Ledger audit row.

**Execution registry (Phase 4D + 4E — 6 actions total):**
1. `payment.link.advance_499` → `apps.payments.services.create_payment_link` (amount **always** resolved to `FIXED_ADVANCE_AMOUNT_INR`; tampered payload amounts are ignored).
2. `payment.link.custom_amount` → same service path; requires `amount > 0`.
3. `ai.prompt_version.activate` → `apps.ai_governance.prompt_versions.activate_prompt_version`. Idempotent on already-active.
4. **Phase 4E** `discount.up_to_10` → `apps.orders.services.apply_order_discount`. Accepts ApprovalRequest status `approved` OR `auto_approved` (the matrix lets this band auto-approve). Band-edge guard: rejects `discount_pct > 10`, negative, or missing. Mutates ONLY `Order.discount_pct`; writes `discount.applied` audit.
5. **Phase 4E** `discount.11_to_20` → same service; `discount_pct` must be `> 10` and `<= 20`. Auto_approved is enough only because the backend approval_engine put it there — frontend / AI cannot fake the status.
6. **Phase 4E** `ai.sandbox.disable` → `apps.ai_governance.sandbox.set_sandbox_enabled(enabled=False, …)`. **Director-only** via matrix `director_override` (admin → 403). Requires `note` or `overrideReason` in `proposed_payload`. Idempotent: returns `{ alreadyDisabled: true, isEnabled: false }` when sandbox is already off.

Everything else (`discount.above_20`, `ad.budget_change`, `payment.refund`, `whatsapp.*`, `complaint.*`, `ai.production.live_mode_switch`, etc.) is intentionally unmapped and returns HTTP 400 + `ai.approval.execution_skipped` audit. The registry is an explicit allow-list — expansion needs Prarit sign-off + matching tests.

Live enforcement is wired into 3 high-value paths today:
- `POST /api/payments/links/` — `payment.link.advance_499` (auto, type=Advance + amount in {0, 499}) vs `payment.link.custom_amount` (admin approval).
- `POST /api/ai/prompt-versions/{id}/activate/` — logs `ai.prompt_version.activate` as auto-approved (admin/director already cleared the role gate).
- `PATCH /api/ai/sandbox/status/` with `isEnabled=false` — `ai.sandbox.disable` (`director_override`); admin → 403, director with `director_override=true` + `note` → allowed.

Other normal workflows (lead create / call trigger / ₹499 advance / Delhivery dispatch / RTO rescue / 0–10% discount) stay auto per matrix.

**Phase 4D + 4E shipped:** the Approved Action Execution Layer at `POST /api/ai/approvals/{id}/execute/` now serves a 6-action allow-listed registry. Phase 4E added discount.up_to_10 + discount.11_to_20 (via `apps.orders.services.apply_order_discount`) and ai.sandbox.disable (Director-only via matrix `director_override`). Future expansion (ad-budget execution, refunds, production live-mode switch, discount.above_20) requires explicit Prarit sign-off + matching tests. CAIO + Claim Vault + idempotency hard stops remain in place.

### Realtime AuditEvent WebSockets (Phase 4A)

Django Channels powers a single live AuditEvent stream alongside the
existing polling endpoints. The frame carries the **full stored**
`AuditEvent.payload` verbatim — never trimmed.

| Method | Path | Purpose |
| --- | --- | --- |
| WS | `ws://<host>/ws/audit/events/[?token=<jwt>]` | Live AuditEvent stream. On connect: `{ "type": "audit.snapshot", "events": [<latest 25>] }`. On every new AuditEvent: `{ "type": "audit.event", "event": { id, kind, text, tone, icon, payload, createdAt, time } }`. Optional `?token=<jwt>` validates a simplejwt access token (best-effort attach for telemetry; connection still accepts on validation failure to keep the dev dashboard working). Client may send `{ "type": "ping" }` and receive `{ "type": "pong" }`. |

Settings:

- `CHANNEL_LAYER_BACKEND` — `memory` (default for tests / dev) or `redis` (production target).
- `CHANNEL_REDIS_URL` — `redis://localhost:6379/2` (Channels uses Redis index 2 so it does not collide with Celery's 0/1).
- `ASGI_APPLICATION = "config.asgi.application"` — `ProtocolTypeRouter` over `config/routing.py`.

Frontend `services/realtime.ts`:

- `buildWebSocketUrl(path?, options?)` — derives `ws://` / `wss://` from `VITE_WS_BASE_URL` if set, otherwise from `VITE_API_BASE_URL` (`http`→`ws`, `https`→`wss`, `/api` suffix stripped). Optional `?token=…` append.
- `connectAuditEvents({ onSnapshot, onEvent, onStatusChange, onError, token?, path? })` — opens the socket, dedupes events by `id`, exponential reconnect, never throws to the caller.

Existing HTTP polling endpoints (`GET /api/dashboard/activity/`, `GET /api/ai/approvals/`) **remain as fallback** when the WebSocket is unavailable.

Locked Phase 4A rules: full payload streamed (existing rule still applies — secrets must never be put in audit payloads); CAIO never executes (consumer is read-and-fanout only); publish failures are swallowed inside `apps.audit.realtime.publish_audit_event` and never break a service-layer write.

### Reward / Penalty Engine (Phase 4B)

The legacy `GET /api/rewards/` list endpoint stays public and now returns the agent-level rollup with Phase 4B fields (`agentId`, `agentType`, `rewardedOrders`, `penalizedOrders`, `lastCalculatedAt`) appended in camelCase. Three new endpoints power the per-order scoring view:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/rewards/` | Agent-level leaderboard (camelCase). Public read; backwards-compatible. |
| GET | `/api/rewards/events/` | Per-order, per-AI-agent scoring events. **Admin/director only.** Query params: `agent` (substring match on agent name), `orderId` (exact), `eventType` (`reward`/`penalty`/`mixed`), `limit` (default 200, max 1000). |
| GET | `/api/rewards/summary/` | Top-line totals + last sweep snapshot + agent leaderboard + missing-data warnings. **Admin/director only.** |
| POST | `/api/rewards/sweep/` | Trigger a sweep. **Admin/director only.** Body `{ startDate?, endDate?, orderId?, dryRun? }`. Returns `{ evaluatedOrders, createdEvents, updatedEvents, skippedOrders, totalReward, totalPenalty, netScore, dryRun, leaderboardUpdated, missingDataWarnings }`. |

**Locked rules** (Master Blueprint §10.2 + §26 + Prarit Apr 2026):
- AI-agents only — no human staff scoring.
- Eligible stages: `Delivered` (rewards), `RTO` + `Cancelled` (penalties); other stages skipped.
- **CEO AI net accountability** — every delivered order generates a CEO AI reward event mirroring the order's reward total; every RTO / cancelled order generates a CEO AI penalty event mirroring the order's penalty total. Always present, every sweep.
- **CAIO excluded** from business reward / penalty (audit-only).
- **Idempotent** — re-running a sweep updates rows in place via `unique_key = phase4b_engine:{order_id}:{agent_id}:{event_type}`.
- **Missing data is recorded, never invented** — `missing_data` JSON on every event; `missingDataWarnings` aggregated in the summary endpoint.

Cron / one-off:
- `python manage.py calculate_reward_penalties [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--order-id NRG-...] [--dry-run] [--rebuild-leaderboard]` — no Redis required.
- Celery task `apps.rewards.tasks.run_reward_penalty_sweep_task` runs the all-eligible sweep + leaderboard rebuild. Eager mode for dev / tests; production picks it up via the existing worker.

Audit kinds (Phase 4B):
- `ai.reward.calculated`, `ai.penalty.applied`, `ai.reward_penalty.sweep_started`, `ai.reward_penalty.sweep_completed`, `ai.reward_penalty.sweep_failed`, `ai.reward_penalty.leaderboard_updated`.

### Catalog (Phase 3E)

Reads stay public; writes are admin/director-only via `RoleBasedPermission` (anonymous → 401, viewer/operations → 403).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/catalog/categories/` | List all `ProductCategory` rows (camelCase: `id`, `name`, `slug`, `description`, `isActive`, `sortOrder`, `createdAt`, `updatedAt`). |
| POST/PUT/PATCH/DELETE | `/api/catalog/categories/[{id}/]` | Admin/director only. Each successful write fires `catalog.category.{created,updated}`. |
| GET | `/api/catalog/products/` | List products with nested `skus`. Camel: `id`, `categoryId`, `name`, `slug`, `description`, `defaultPriceInr`, `defaultQuantityLabel`, `productCostInr`, `defaultUsageInstructions`, `activeClaimProducts`, `isActive`, `metadata`, `createdAt`, `updatedAt`, `skus[]`. |
| GET | `/api/catalog/products/{id}/` | Single product detail. |
| POST/PUT/PATCH/DELETE | `/api/catalog/products/[{id}/]` | Admin/director only. Fires `catalog.product.{created,updated}`. |
| GET | `/api/catalog/skus/?productId={id}` | List SKUs (optionally filtered by `productId`). Camel: `id`, `productId`, `skuCode`, `title`, `quantityLabel`, `mrpInr`, `sellingPriceInr`, `productCostInr`, `stockQuantity`, `isActive`, `metadata`, `createdAt`, `updatedAt`. |
| POST/PUT/PATCH/DELETE | `/api/catalog/skus/[{id}/]` | Admin/director only. Fires `catalog.sku.{created,updated}`. |

### Approval matrix (Phase 3E — public read)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/ai/approval-matrix/` | Returns the policy table from `apps.ai_governance.approval_matrix.APPROVAL_MATRIX`: `{ version, actions: [{ action, approver, mode, description }] }`. **Public read** — the data is policy, not secret. Phase 4C middleware enforces it. |

### Phase 3E — Business policy modules (no endpoints; service-layer policies)

These shape behaviour but expose no new HTTP endpoints. They are imported by services and (in Phase 4) the approval-matrix middleware:

- **Discount policy** (`apps/orders/discounts.py`): `validate_discount(discount_pct, actor_role, approval_context=None) → DiscountValidationResult`. Bands: 0–10% auto, 11–20% approval (CEO AI / admin / director), > 20% blocked unless `actor_role='director'` AND `approval_context['director_override']=True`. Director ceiling: 50%.
- **Advance payment policy** (`apps/payments/policies.py`): `FIXED_ADVANCE_AMOUNT_INR = 499`. `POST /api/payments/links/` with `type="Advance"` and no `amount` (or `amount=0`) defaults to ₹499. Other types still require an explicit positive amount.
- **Reward / penalty scoring** (`apps/rewards/scoring.py`): `calculate_order_reward_penalty(order, context=None) → OrderRewardPenaltyResult`. 7 reward components (max +100), 10 penalty components (max -100). Missing data is recorded explicitly — never invented. Phase 4B wires this into the engine.
- **WhatsApp design scaffold** (`apps/crm/whatsapp_design.py`): 9 supported message types, consent + admin-approval flags. NO live sender yet — Phase 4+ ships the actual integration.

### Webhooks (gateway → backend, public)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/webhooks/razorpay/` | Razorpay payment events (Phase 2B production). HMAC-verified via `RAZORPAY_WEBHOOK_SECRET`; idempotent on `event.id`. |
| POST | `/api/webhooks/razorpay/test/` | Razorpay test-mode webhook (Phase 6M, dormant by default). Refuses every inbound when `RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false`. When enabled, verifies HMAC-SHA256 over the raw body in constant time using a separate `RAZORPAY_WEBHOOK_TEST_SECRET` (production webhook secret is **never** consumed here), validates a 300-second replay window (`x_razorpay_signature_age`), dedupes on `X-Razorpay-Event-Id`, masks payloads against a 13-key scrub list, classifies via 9-event allowlist + 9-event denylist, and persists only a safe summary on `RazorpayWebhookEvent`. **Never** mutates Order / Payment / Shipment / DiscountOfferLog / Customer (`assert_no_business_mutation` invariant). **Never** sends a customer notification. |
| POST | `/api/webhooks/delhivery/` | Delhivery tracking events (Phase 2C). HMAC-verified via `DELHIVERY_WEBHOOK_SECRET` (`X-Delhivery-Signature`); idempotent on `event.id`. Status mapping: `pickup_scheduled` / `picked_up` / `in_transit` / `out_for_delivery` / `delivered` / `ndr` / `rto_initiated` / `rto_delivered`. NDR + RTO events bump parent order's `rto_risk` and write danger-tone `AuditEvent` rows. |
| POST | `/api/webhooks/vapi/` | Vapi voice events (Phase 2D). HMAC-verified via `VAPI_WEBHOOK_SECRET` (`X-Vapi-Signature`) when configured; signature is skipped when the secret is empty so dev/test fixtures stay simple. Idempotent on `event.id` via `calls.WebhookEvent`. Event types handled: `call.started` / `call.ended` / `transcript.updated` / `transcript.final` / `analysis.completed` / `call.failed`. `analysis.completed` records `handoff_flags` (medical_emergency, side_effect_complaint, very_angry_customer, human_requested, low_confidence, legal_or_refund_threat); the service falls back to keyword matching on the transcript when Vapi omits the explicit flags. |
| GET | `/api/webhooks/meta/leads/` | Meta Lead Ads subscription handshake (Phase 2E). Echoes `hub.challenge` only when `hub.mode == "subscribe"` and `hub.verify_token == META_VERIFY_TOKEN`; otherwise 403. |
| POST | `/api/webhooks/meta/leads/` | Meta Lead Ads delivery (Phase 2E). HMAC-verified via `META_WEBHOOK_SECRET` (or `META_APP_SECRET` as fallback) on `X-Hub-Signature-256` when configured. Idempotent on `leadgen_id` via `crm.MetaLeadEvent`. `META_MODE=mock` (default) parses the inbound body directly; `test`/`live` expand each `leadgen_id` via the Graph API (`v20.0` by default). Each accepted leadgen creates or refreshes a `Lead` and writes a `lead.meta_ingested` AuditEvent. |
| GET | `/api/webhooks/whatsapp/meta/` | Meta WhatsApp Cloud subscription handshake (Phase 5A). Echoes `hub.challenge` only when `hub.mode == "subscribe"` and `hub.verify_token == META_WA_VERIFY_TOKEN`; otherwise 403. |
| POST | `/api/webhooks/whatsapp/meta/` | Meta WhatsApp Cloud delivery (Phase 5A). HMAC-verified via `META_WA_APP_SECRET` (or `WHATSAPP_WEBHOOK_SECRET` override) on `X-Hub-Signature-256`. Optional replay-window check via `X-Hub-Timestamp` (default 300 s). Idempotent on a SHA1-of-body / `entry[].id` composite via `whatsapp.WhatsAppWebhookEvent.provider_event_id`. Inbound message events create / update `WhatsAppConversation` + `WhatsAppMessage`, run opt-out detection (`STOP / UNSUBSCRIBE / BAND KARO / BAND / CANCEL`), and write `whatsapp.inbound.received`. Status events update the matching outbound message and write `whatsapp.message.delivered/read/failed`. |

### WhatsApp (Phase 5A)

`apps.whatsapp` adds a single-tenant WhatsApp Cloud (Meta) sender / inbox foundation. Every send must be **consent + approved-template + Claim-Vault gated** server-side; failed sends never mutate `Order` / `Payment` / `Shipment`. CAIO can never originate a customer-facing send (refused at engine + service entry). The provider is selected via `WHATSAPP_PROVIDER` (`mock` / `meta_cloud` / `baileys_dev`). Templates are mirrored from Meta — only `status=APPROVED && is_active=True` rows can be used for live sends.

| Method | Path | Auth / role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/whatsapp/provider/status/` | admin / director only | Redacted status of the configured provider (`provider`, `healthy`, `connection`, `accessTokenSet`, `verifyTokenSet`, `appSecretSet`, `apiVersion`). Tokens are **never** exposed; ids are masked. |
| GET | `/api/whatsapp/connections/` | authenticated | List configured `WhatsAppConnection` rows. |
| GET | `/api/whatsapp/templates/` | authenticated | List Meta-approved templates. Filters: `actionKey`, `category`, `status`. |
| POST | `/api/whatsapp/templates/sync/` | admin / director only | Refresh the local mirror from a Meta WABA payload (`{"data": [...]}`). With no payload the command falls back to seeding the canonical lifecycle templates so dev / CI always has working rows. Writes a `whatsapp.template.synced` audit per row. |
| GET | `/api/whatsapp/conversations/` | authenticated | List threads. Filters: `customerId`, `status`. |
| GET | `/api/whatsapp/conversations/{id}/` | authenticated | Conversation detail. |
| GET | `/api/whatsapp/conversations/{id}/messages/` | authenticated | Last 200 messages on a conversation. |
| GET | `/api/whatsapp/messages/` | authenticated | Cross-conversation message search. Filters: `conversationId`, `customerId`, `status`, `limit`. |
| POST | `/api/whatsapp/send-template/` | operations+ | Body `{customerId, actionKey, templateId?, variables?, triggeredBy?, idempotencyKey?}`. Runs consent → template → Claim Vault → matrix gates, then enqueues. Returns `{message, conversationId, approvalRequestId, autoApproved}`. |
| POST | `/api/whatsapp/messages/{id}/retry/` | operations+ | Re-queue a failed outbound message. 409 if the message is already in a non-retryable state. |
| GET | `/api/whatsapp/consent/{customer_id}/` | authenticated | Live `Customer.consent_whatsapp` boolean + the lifecycle history row. |
| PATCH | `/api/whatsapp/consent/{customer_id}/` | operations+ | Body `{consentState, source?, note?}`. Only `granted / revoked / opted_out` are settable; flips both the live gate and the history. |

#### Phase 5B — Inbox + Customer 360 timeline endpoints

Phase 5B adds the operator inbox surface. Inbox is **manual-only**: AI auto-reply / chat-to-call handoff / rescue discount / order-booking-from-chat all stay deferred to Phase 5C–5F. The aggregate inbox response carries an explicit `aiSuggestions` block with `enabled: false, status: "disabled"` so the frontend never invents AI behavior.

| Method | Path | Auth / role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/whatsapp/inbox/` | authenticated | Inbox snapshot. Returns `{ conversations[], counts: { all, unread, open, pending, resolved, escalatedToHuman }, aiSuggestions: { enabled, status, message } }`. Optional `?limit=` (default 50, max 200). |
| PATCH | `/api/whatsapp/conversations/{id}/` | operations+ | Safe-field update only — body accepts `status` (open/pending/resolved/escalated_to_human), `assignedToId` (User PK), `tags` (list[str]), `subject`. Anything else is silently ignored by the serializer; an empty payload returns 400. Status flip to `resolved` stamps `resolved_at + resolved_by`. Assignment changes write `whatsapp.conversation.assigned`; every PATCH writes `whatsapp.conversation.updated`. |
| POST | `/api/whatsapp/conversations/{id}/mark-read/` | operations+ | Resets `unread_count=0`. Idempotent when already 0. Writes `whatsapp.conversation.read`. |
| GET | `/api/whatsapp/conversations/{id}/notes/` | authenticated | List internal notes (newest first). |
| POST | `/api/whatsapp/conversations/{id}/notes/` | operations+ | Create an internal note. Body `{ body, metadata? }`. **Notes are NEVER sent to the customer.** Writes `whatsapp.internal_note.created`. |
| POST | `/api/whatsapp/conversations/{id}/send-template/` | operations+ | Manual operator-triggered template send for the conversation. Body `{ actionKey, templateId?, variables?, triggeredBy?, idempotencyKey? }`. The customer is resolved from the conversation; the call routes through `services.queue_template_message` so consent + approved-template + Claim Vault + approval matrix + CAIO + idempotency gates all stay in force. Writes `whatsapp.template.manual_send_requested` audit before queuing. |
| GET | `/api/whatsapp/customers/{customer_id}/timeline/` | authenticated | WhatsApp-only timeline. Returns `{ customerId, consentWhatsapp, conversations[], items[], aiSuggestions }` where `items[].kind ∈ {message, internal_note, status_event}` and `items` is sorted by `occurredAt` desc. **Phase 5B intentionally does NOT merge calls / payments / orders.** |

Conversation list filters now accept `?unread=true`, `?assignedTo=<user_pk>`, `?q=<search>` (icontains over customer name / phone / last_message_text / subject). The conversation serializer exposes `customerName / customerPhone / assignedToUsername`, and the message serializer exposes `templateName`. New audit kinds: `whatsapp.conversation.opened/updated/assigned/read`, `whatsapp.internal_note.created`, `whatsapp.template.manual_send_requested`.

#### Phase 5C — WhatsApp AI Chat Sales Agent endpoints

Phase 5C wires the OpenAI-backed Chat Sales Agent on top of Phase 5A's send pipeline + Phase 5B's inbox. Auto-reply defaults to OFF (`WHATSAPP_AI_AUTO_REPLY_ENABLED=false`). Backend gates remain final on every send: consent + approved-template (greeting) / Claim Vault (freeform) + blocked-phrase filter + discount discipline + 50% total cap + matrix + CAIO refusal + idempotency + per-conversation/per-customer rate limits.

| Method | Path | Auth / role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/whatsapp/ai/status/` | authenticated | Returns the global AI runtime state. `{ enabled, status: "auto" / "auto_reply_off" / "provider_disabled", message, provider, autoReplyEnabled, confidenceThreshold, rateLimits: { maxTurnsPerConversationPerHour, maxMessagesPerCustomerPerDay } }`. |
| PATCH | `/api/whatsapp/conversations/{id}/ai-mode/` | operations+ | Body `{ aiEnabled?, aiMode? }` where `aiMode ∈ {auto, suggest, disabled}`. Persists into `WhatsAppConversation.metadata.ai`. Writes `whatsapp.conversation.updated`. |
| POST | `/api/whatsapp/conversations/{id}/run-ai/` | operations+ | Manual one-shot trigger of the AI orchestrator on the latest inbound. Honours all gates; returns the orchestrator outcome (`action, sent, sentMessageId, handoffRequired, blockedReason, stage, confidence, language, category, orderId, paymentId`). |
| GET | `/api/whatsapp/conversations/{id}/ai-runs/` | authenticated | Returns `{ ai: <state>, events: [<latest 50 whatsapp.ai.* audit rows>] }`. Frontend polls this for the AI Agent panel. |
| POST | `/api/whatsapp/conversations/{id}/handoff/` | operations+ | Operator forces handoff. Sets `metadata.ai.handoffRequired=true / aiEnabled=false` and flips conversation to `escalated_to_human`. Body `{ reason? }`. Writes `whatsapp.ai.handoff_required`. |
| POST | `/api/whatsapp/conversations/{id}/resume-ai/` | operations+ | Re-enables AI on a previously handed-off conversation. Sets `metadata.ai.aiEnabled=true / handoffRequired=false`. Flips `escalated_to_human → open`. |

Inbound webhook flow: `services.handle_inbound_message_event` now enqueues `tasks.run_whatsapp_ai_agent_for_conversation` after persisting the inbound row (eager mode dispatches synchronously; production uses `transaction.on_commit` + Redis-backed Celery). The orchestrator is idempotent on `inbound_message_id` — duplicate webhooks never produce duplicate AI runs.

New audit kinds (18): `whatsapp.ai.run_started`, `whatsapp.ai.run_completed`, `whatsapp.ai.run_failed`, `whatsapp.ai.reply_auto_sent`, `whatsapp.ai.reply_blocked`, `whatsapp.ai.suggestion_stored`, `whatsapp.ai.greeting_sent`, `whatsapp.ai.greeting_blocked`, `whatsapp.ai.language_detected`, `whatsapp.ai.category_detected`, `whatsapp.ai.address_updated`, `whatsapp.ai.order_draft_created`, `whatsapp.ai.order_booked`, `whatsapp.ai.payment_link_created`, `whatsapp.ai.handoff_required`, `whatsapp.ai.discount_objection_handled`, `whatsapp.ai.discount_offered`, `whatsapp.ai.discount_blocked`.

#### Phase 5D — Chat-to-Call Handoff + Lifecycle Automation

Phase 5D ships the direct WhatsApp → Vapi handoff bridge, the lifecycle automation service that fires approved-template sends on Order/Payment/Shipment events, and the Claim Vault coverage audit. Handoff and lifecycle automation both default OFF (`WHATSAPP_CALL_HANDOFF_ENABLED=false`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false`); the limited live-Meta test gate (`WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`) is the bridge between mock+OpenAI verification and a full production rollout. AI-booked orders move directly into the confirmation queue from the chat (Phase 5C `book_order_from_decision` calls `apps.orders.services.move_to_confirmation`).

| Method | Path | Auth / role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/compliance/claim-coverage/` | admin / director | Returns the Claim Vault coverage report. `{ totalProducts, okCount, weakCount, missingCount, items[] }` where each item carries `product, category, approvedClaimCount, hasApprovedClaims, missingRequiredUsageClaims, lastApprovedAt, risk: "ok"|"weak"|"missing", notes[]`. Writes a single `compliance.claim_coverage.checked` audit. |
| POST | `/api/whatsapp/conversations/{id}/handoff-to-call/` | operations+ | Operator manual trigger. Body `{ reason?, note? }` (default reason `customer_requested_call`). Routes through `apps.whatsapp.call_handoff.trigger_vapi_call_from_whatsapp` → existing `apps.calls.services.trigger_call_for_lead`. Idempotent on `(conversation, inbound_message, reason)`. Returns `{ handoffId, status, callId, providerCallId, reason, skipped, errorMessage, message }`. Safety reasons (`medical_emergency`, `side_effect_complaint`, `legal_threat`) are recorded as `skipped` for human/doctor pickup — never auto-dialed. |
| GET | `/api/whatsapp/conversations/{id}/handoffs/` | authenticated | Lists the most recent 50 `WhatsAppHandoffToCall` rows for the conversation. |
| GET | `/api/whatsapp/lifecycle-events/` | authenticated | Lists the most recent 100 `WhatsAppLifecycleEvent` rows. Optional filters `?objectType=order|payment|shipment`, `?objectId=...`, `?status=queued|sent|blocked|skipped|failed`, `?limit=N` (max 500). |

Lifecycle service (`apps.whatsapp.lifecycle.queue_lifecycle_message`) is the single dispatch path; signals in `apps.whatsapp.signals` listen on `orders.Order` / `payments.Payment` / `shipments.Shipment` `post_save` and queue the matching template via Celery (`send_whatsapp_lifecycle_message_task`) on commit. The send pipeline still flows through Phase 5A's `queue_template_message`, so consent + approved-template + Claim Vault + matrix + CAIO + idempotency gates are all in force on every lifecycle send. Idempotency key shape: `lifecycle:{action_key}:{object_type}:{object_id}:{event_kind}`. Template `whatsapp.usage_explanation` fails closed when `apps.compliance.coverage.coverage_for_product` reports `missing` / `weak` for the customer's product interest.

New audit kinds (11): `whatsapp.handoff.call_requested`, `whatsapp.handoff.call_triggered`, `whatsapp.handoff.call_failed`, `whatsapp.handoff.call_skipped`, `whatsapp.handoff.call_skipped_duplicate`, `whatsapp.lifecycle.queued`, `whatsapp.lifecycle.sent`, `whatsapp.lifecycle.blocked`, `whatsapp.lifecycle.skipped_duplicate`, `whatsapp.lifecycle.failed`, `whatsapp.ai.order_moved_to_confirmation`, plus `compliance.claim_coverage.checked` for the coverage endpoint.

#### Phase 5E — Rescue Discount Flow + Day-20 Reorder + Default Claim Vault Seeds

Phase 5E adds the cross-channel rescue discount engine, lifecycle templates for confirmation / delivery / RTO refusal-based rescue + Day-20 reorder reminder, and a default Claim Vault seed for the eight current product categories. All rescue + Day-20 flags default OFF (`WHATSAPP_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_REORDER_DAY20_ENABLED=false`). Cumulative 50% cap is absolute and enforced both at the calculator (`apps.orders.rescue_discount.validate_total_discount_cap`) and at the accept time (re-checks the cap before mutating `Order.discount_pct` via `apply_order_discount`).

| Method | Path | Auth / role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/orders/{id}/discount-offers/` | authenticated | Returns `{ orderId, currentDiscountPct, cap: { currentTotalPct, capRemainingPct, finalTotalIfAppliedPct, capPassed, totalCapPct }, offers[] }`. ``offers[]`` is the latest 200 `DiscountOfferLog` rows for the order. |
| POST | `/api/orders/{id}/discount-offers/rescue/` | operations+ | Body `{ sourceChannel, stage, triggerReason, refusalCount?, riskLevel?, requestedPct?, conversationId?, metadata? }`. Calculates the next rescue offer, persists a `DiscountOfferLog`, and (when over band / cap) auto-creates a CEO / admin `ApprovalRequest`. Returns the new offer row. CAIO refused at the service entry. |
| POST | `/api/orders/{id}/discount-offers/{offer_id}/accept/` | operations+ | Customer accepted → applies the discount via `apps.orders.services.apply_order_discount`, sets log status to `accepted`. Cap is re-validated; over-cap at accept time flips status to `needs_ceo_review`. |
| POST | `/api/orders/{id}/discount-offers/{offer_id}/reject/` | operations+ | Body `{ note? }`. Records rejection. Never mutates `Order`. |
| GET | `/api/whatsapp/reorder/day20/status/` | admin / director | Returns `{ enabled, lifecycleEnabled, lowerBoundDays, upperBoundDays, events[] }` — last 50 Day-20 lifecycle rows. |
| POST | `/api/whatsapp/reorder/day20/run/` | admin / director | Body `{ dryRun? }`. Runs the Day-20 sweep on demand. Returns `{ eligible, queued, skipped, blocked, failed, dryRun }`. |

Lifecycle automation table grows by four (`whatsapp.confirmation_rescue_discount`, `whatsapp.delivery_rescue_discount`, `whatsapp.rto_rescue_discount`, `whatsapp.reorder_day20_reminder`) — all `auto_with_consent` in the matrix. Idempotency keys:

- `lifecycle:whatsapp.confirmation_rescue_discount:order:{id}:confirmation_refusal`
- `lifecycle:whatsapp.delivery_rescue_discount:shipment:{id}:delivery_refusal`
- `lifecycle:whatsapp.rto_rescue_discount:shipment:{id}:rto_risk`
- `lifecycle:whatsapp.reorder_day20_reminder:order:{id}:day20`

The Phase 5C orchestrator now also writes a `DiscountOfferLog` row whenever the WhatsApp AI proposes a discount, regardless of channel — so the orders / analytics surfaces have a single canonical history.

New audit kinds (12): `discount.offer.created`, `discount.offer.sent`, `discount.offer.accepted`, `discount.offer.rejected`, `discount.offer.blocked`, `discount.offer.needs_ceo_review`, `whatsapp.lifecycle.rescue_discount_queued`, `whatsapp.lifecycle.rescue_discount_sent`, `whatsapp.lifecycle.reorder_day20_queued`, `whatsapp.lifecycle.reorder_day20_sent`, `compliance.default_claims.seeded`.

#### Phase 5F-Gate - Approved Customer Pilot Readiness

This gate prepares a tiny approved customer pilot only. Auto-reply
remains OFF, limited Meta test mode remains ON, campaigns/broadcast stay
locked, and call handoff / lifecycle / rescue / RTO / reorder stay OFF.
The earlier 4-hour soak was accelerated, not full-duration. Pilot
tooling is read-only/prep and never sends WhatsApp messages or mutates
Order / Payment / Shipment / Discount data.

| Method | Endpoint | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/whatsapp/monitoring/pilot/?hours=2` | admin / director / superuser monitoring permission | Read-only pilot readiness summary. Returns counts, blockers, `nextAction`, safety flags, SaaS guardrail gaps, and masked pilot members only. |
| GET | `/api/v1/whatsapp/monitoring/overview/?hours=2` | admin / director / superuser monitoring permission | Existing WhatsApp monitoring overview plus `pilot` summary. |

Pilot command surfaces:

| Command | Purpose |
| --- | --- |
| `python manage.py inspect_whatsapp_customer_pilot --json` | Read-only summary; no DB writes, no audit writes, masked phones only. |
| `python manage.py prepare_whatsapp_customer_pilot_member --phone +91XXXXXXXXXX --name "Customer Name" --source approved_customer_pilot --json` | Creates/reuses `crm.Customer` and `WhatsAppPilotCohortMember` only. Missing consent keeps the member `pending`; consented customers can become `approved`. Writes `whatsapp.pilot.member_prepared`. |
| `python manage.py pause_whatsapp_customer_pilot_member --phone +91XXXXXXXXXX --reason "..." --json` | Pauses the member and writes `whatsapp.pilot.member_paused`. |

`WhatsAppPilotCohortMember` stores masked phone/suffix only and
references `Customer` for the existing full phone field. Readiness
requires explicit WhatsApp consent, approved member status, limited-mode
allow-list membership, a daily cap, and no recent safety issue.

New management commands:

```
python manage.py seed_default_claims              # idempotent, demo-only seeds
python manage.py seed_default_claims --reset-demo # refresh demo rows (real claims protected)
python manage.py seed_default_claims --json       # machine-readable summary
python manage.py run_reorder_day20_sweep          # Day-20 reorder sweep
python manage.py run_reorder_day20_sweep --dry-run
```

## SaaS Admin + Integration Settings (Phase 6E)

Phase 6D org-aware write assignment is complete and remains nullable /
single-tenant-safe. Phase 6E adds a future SaaS control surface without
switching runtime provider routing away from env/config.

| Method | Endpoint | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/admin/overview/` | staff / superuser / global admin / director | Read-only SaaS admin overview: active default org, org-scope readiness, write-path readiness, integration readiness, safety locks, and SaaS audit timeline. |
| GET | `/api/v1/saas/admin/organizations/` | same | Organization list with membership summary, feature flags, and integration-setting counts. |
| GET | `/api/v1/saas/admin/organizations/{id}/` | same | Single organization detail plus integration readiness. |
| GET / POST | `/api/v1/saas/admin/integration-settings/` | same | List or create per-org integration setting rows. Create accepts non-sensitive `config` and `secretRefs` only. |
| PATCH | `/api/v1/saas/admin/integration-settings/{id}/` | same | Update admin-safe integration setting metadata/config/secret refs; does not call or activate any provider. |
| GET | `/api/v1/saas/admin/integration-readiness/` | same | Provider readiness for WhatsApp Meta, Razorpay, PayU, Delhivery, Vapi, and OpenAI. |
| GET | `/api/v1/saas/write-path-readiness/` | authenticated | Phase 6E-hardened write-path report with `enforcementMode`, covered/deferred paths, recent unscoped writes, system/global exceptions, and `safeToStartPhase6F`. |
| GET | `/api/v1/saas/org-scope-readiness/` | authenticated | Existing Phase 6C org-scope readiness. |

`OrganizationIntegrationSetting` stores only non-sensitive config and secret
references such as `ENV:META_WA_ACCESS_TOKEN` or `VAULT:path/to/secret`.
APIs return masked references/booleans only, never raw values. Runtime
providers still read the existing env/config settings in Phase 6E;
per-org runtime routing is deferred to Phase 6F. WhatsApp flags remain
untouched and global tenant filtering is still not blanket-enabled.

Diagnostic commands:

```bash
python manage.py inspect_saas_admin_readiness --json
python manage.py inspect_org_integration_settings --json
python manage.py inspect_org_write_path_readiness --json
```

### Permissions

`apps/accounts/permissions.py` exposes:

- `OPERATIONS_AND_UP` = `{director, admin, operations}`
- `COMPLIANCE_AND_UP` = `{director, admin, compliance}`
- `ADMIN_AND_UP` = `{director, admin}`
- `DIRECTOR_ONLY` = `{director}`

ViewSets opt in by setting `permission_classes = [RoleBasedPermission]` and
`allowed_write_roles = OPERATIONS_AND_UP`. Reads stay open via the global
default `IsAuthenticatedOrReadOnly`.

CAIO is intentionally absent from every role-set: it is an AI-agent identity,
not a user role, and per blueprint §6.3 must never execute business actions.

## Phase 7D - Razorpay Controlled Pilot Execution (CLI-only review; one-shot TEST execute path)

Read-only HTTP layer. Phase 7D was executed once on 2026-05-07
(`order_SmThqpK6sc6Dhs`, attempt id 1, rolled back, no business
mutation). The execute path is CLI-only via
`manage.py execute_razorpay_controlled_pilot_test_order` and refuses
unless every safety gate is green. Phase 7D-Hotfix-1 will add a
structured UTC window guard before any future re-run.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/controlled-pilot-execution-readiness/` | admin/staff | Phase 7D readiness, env flag state, attempt counters, kill-switch state, source-chain eligibility, blockers/warnings, `nextAction`. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-execution-attempts/?limit=N` | admin/staff | Phase 7D attempt list with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-execution-attempts/<int:pk>/` | admin/staff | Read-only attempt detail (whitelist serializer; never returns raw signoff text or raw provider response). |
| GET | `/api/v1/saas/razorpay/controlled-pilot-execution-preview/?gate_id=<ID>` | admin/staff | Read-only preview from a Phase 7B-approved gate. Never creates rows. |
| GET | `/api/v1/saas/razorpay/controlled-pilot-execution-rollbacks/<int:attempt_id>/` | admin/staff | List of rollback records for a Phase 7D attempt. |

POST/PATCH/DELETE on every endpoint return 405. **No POST execute /
approve / reject / archive endpoint exists.**

## Phase 7E - WhatsApp Internal Notification Readiness Gate (CLI-only review)

Read-only HTTP layer over the Phase 7E gate. Approval flips status
to `approved_for_future_phase7f_or_7e_send_review` only — it does
NOT enable any send path. Phase 7E never sends WhatsApp, never
queues, never calls Meta Cloud / Delhivery / Vapi, never creates a
shipment / AWB / payment link, never captures, never refunds, never
sends a customer notification, never mutates real business rows,
never edits any `.env*` file.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-readiness/` | admin/staff | Phase 7E readiness, `PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED` flag, gate counters, Phase 7D rolled-back-eligible counter, kill-switch state, blockers/warnings, `nextAction`, forbidden-actions list. |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-gates/?limit=N` | admin/staff | Phase 7E gate list. Locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; never returns full director sign-off text or any PII). |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-preview/?attempt_id=<ID>` | admin/staff | Read-only preview from a rolled-back Phase 7D attempt. Never creates rows. |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-dry-runs/<int:gate_id>/` | admin/staff | List of dry-run / rollback-dry-run records for a Phase 7E gate. |

POST/PATCH/DELETE on every endpoint return 405. **No POST endpoint
dispatches state changes** — every gate transition is CLI-only via
the 8 management commands documented in CLAUDE.md "Where things
live".

## Phase 7F - Delhivery / Courier Controlled Readiness Gate (CLI-only review)

Read-only HTTP layer over the Phase 7F gate. Approval flips status
to `approved_for_future_phase7g_or_courier_execution_review` only —
it does NOT enable any provider call. Phase 7F never calls
Delhivery, never creates a `Shipment` / `WorkflowStep` /
`RescueAttempt` row, never creates an AWB, never books a pickup,
never generates a courier label, never sends or queues WhatsApp,
never calls Meta Cloud / Razorpay / Vapi, never sends a customer
notification, never mutates real business rows, never edits any
`.env*` file.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/delhivery/courier-readiness/` | admin/staff | Phase 7F readiness, `PHASE7F_COURIER_READINESS_GATE_ENABLED` flag, gate counters, Phase 7E approved-gate counter, kill-switch state, Delhivery mode + env presence (token / base URL / pickup loc / return addr — booleans only, never values), Phase 7D-Hotfix-1 importable flag, blockers/warnings, `nextAction`, 31 forbidden-actions list. |
| GET | `/api/v1/saas/delhivery/courier-readiness-gates/?limit=N` | admin/staff | Phase 7F gate list. Locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/delhivery/courier-readiness-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; never returns raw Delhivery env values or customer PII). |
| GET | `/api/v1/saas/delhivery/courier-readiness-preview/?phase7e_gate_id=<ID>` | admin/staff | Read-only preview from a Phase 7E approved gate. Never creates rows. |
| GET | `/api/v1/saas/delhivery/courier-readiness-dry-runs/<int:gate_id>/` | admin/staff | List of dry-run / rollback-dry-run records for a Phase 7F gate. |

POST/PATCH/DELETE on every endpoint return 405. **No POST endpoint
dispatches state changes** — every gate transition is CLI-only via
the 8 management commands documented in CLAUDE.md "Where things
live". **Archive command intentionally deferred** (mirrors Phase 7E
pattern); reachable via reject + later one-shot operator workflow.

### Phase 7H — Courier Execution Evidence Lock (lock-only)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/delhivery/courier-execution-evidence-lock-readiness/` | admin/staff | Read-only readiness composition. |
| GET | `/api/v1/saas/delhivery/courier-execution-evidence-locks/?limit=N` | admin/staff | Phase 7H lock listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/delhivery/courier-execution-evidence-locks/<int:pk>/` | admin/staff | Read-only lock detail (whitelist serializer; never returns raw provider response / Director sign-off text / customer PII). |
| GET | `/api/v1/saas/delhivery/courier-execution-evidence-lock-preview/?attempt_id=<ID>` | admin/staff | Read-only preview from a completed Phase 7G attempt. Never creates rows. |

POST/PATCH/DELETE on every Phase 7H endpoint return 405. **No POST
endpoint dispatches lock state changes** — every transition is
CLI-only via the 6 management commands
(`inspect_phase7h_courier_execution_evidence_lock`, `preview_…`,
`prepare_…`, `approve_…_lock --reason`, `reject_…_lock --reason`,
`archive_…_lock --reason`). Phase 7H never calls Delhivery, never
creates a `Shipment` / AWB row, never mutates business rows.

### Phase 7E-Live-A — Internal Allowed-list WhatsApp One-shot Send

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/whatsapp/internal-send-readiness/` | admin/staff | Read-only readiness composition. |
| GET | `/api/v1/saas/whatsapp/internal-send-attempts/?limit=N` | admin/staff | Phase 7E-Live-A attempt listing with `recipientScope=internal_staff_allow_list` + safety locks. |
| GET | `/api/v1/saas/whatsapp/internal-send-attempts/<int:pk>/` | admin/staff | Read-only attempt detail (whitelist serializer; never returns raw Meta token / full phone / raw provider response / Director sign-off text). |
| GET | `/api/v1/saas/whatsapp/internal-send-preview/?gate_id=<ID>` | admin/staff | Read-only preview from an approved Phase 7E gate. Never creates rows. |

POST/PATCH/DELETE on every Phase 7E-Live-A endpoint return 405.
**No POST endpoint dispatches state changes** — every transition
is CLI-only via the 8 management commands. Phase 7E-Live-A never
sends to a real customer phone; never queues broad automation;
never calls Delhivery / Razorpay / Vapi; never sends a customer
notification; never mutates real business rows; never edits any
`.env*` file. **Phase 7E-Live-B (real customer WhatsApp send)
remains NOT approved.**

### Phase 7I — Final Phase 7 Payment + WhatsApp + Courier Audit Lock (lock-only)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase7/final-audit-lock-readiness/` | admin/staff | Read-only readiness composition (eligibility counters + locked-False safety contract). |
| GET | `/api/v1/saas/phase7/final-audit-locks/?limit=N` | admin/staff | Phase 7I lock listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase7/final-audit-locks/<int:pk>/` | admin/staff | Read-only lock detail (whitelist serializer; never returns raw token / full phone / raw provider response / Director sign-off text). |
| GET | `/api/v1/saas/phase7/final-audit-lock-preview/?phase7g_attempt_id=N&phase7h_evidence_lock_id=N[&phase7e_live_attempt_id=N][&phase7d_attempt_id=N]` | admin/staff | Read-only preview composed from the four source records. Never creates rows. |

POST/PATCH/DELETE on every Phase 7I endpoint return 405. **No POST
endpoint dispatches lock state changes** — every transition is
CLI-only via the 6 management commands
(`inspect_phase7i_final_audit_lock`, `preview_…`, `prepare_…`,
`approve_…_lock --reason`, `reject_…_lock --reason`,
`archive_…_lock --reason`). Phase 7I never calls Razorpay / Meta
Cloud / Delhivery / Vapi, never sends or queues WhatsApp, never
creates a `Shipment` / AWB / payment link, never captures /
refunds, never sends a customer notification, never mutates real
business rows. **Phase 7G-Live (real customer courier execution)
and Phase 7E-Live-B (real customer WhatsApp send) remain NOT
approved.**

### Phase 8A — Payment → Order Mutation Sandbox Gate (sandbox-only)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/payment-order-mutation-sandbox-readiness/` | admin/staff | Read-only readiness composition (eligibility counters + sandbox-only safety contract). |
| GET | `/api/v1/saas/phase8/payment-order-mutation-sandbox-gates/?limit=N` | admin/staff | Phase 8A gate listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase8/payment-order-mutation-sandbox-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; never returns raw token / full phone / raw provider response). |
| GET | `/api/v1/saas/phase8/payment-order-mutation-sandbox-preview/?phase7i_lock_id=N` | admin/staff | Read-only preview from a locked Phase 7I final audit lock. Never creates rows. |
| GET | `/api/v1/saas/phase8/payment-order-mutation-sandbox-dry-runs/<int:gate_id>/` | admin/staff | Read-only list of dry-run records for one Phase 8A gate. |

POST/PATCH/DELETE on every Phase 8A endpoint return 405. **No POST
endpoint dispatches state changes** — every transition is CLI-only
via the 8 management commands. Phase 8A approval flips status to
`approved_for_future_phase8b_review` only — it does NOT authorize
any real mutation. Phase 8A never calls Razorpay / Meta Cloud /
Delhivery / Vapi, never sends or queues WhatsApp, never creates a
`Shipment` / AWB / payment link, never captures / refunds, never
sends a customer notification, never mutates real business rows.
**Phase 8B (real payment-order mutation) is review-only; Phase 8C
(controlled real mutation) remains NOT approved.**

### Phase 8B — Payment → Order Mutation Review Gate (review-only)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/payment-order-mutation-review-readiness/` | admin/staff | Read-only readiness composition (eligibility counters + review-only safety contract). |
| GET | `/api/v1/saas/phase8/payment-order-mutation-review-gates/?limit=N` | admin/staff | Phase 8B gate listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase8/payment-order-mutation-review-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; never returns raw token / full phone / raw provider response). |
| GET | `/api/v1/saas/phase8/payment-order-mutation-review-preview/?phase8a_gate_id=N` | admin/staff | Read-only preview from an approved Phase 8A sandbox gate. Never creates rows. |
| GET | `/api/v1/saas/phase8/payment-order-mutation-review-dry-runs/<int:gate_id>/` | admin/staff | Read-only list of dry-run records for one Phase 8B gate. |

POST/PATCH/DELETE on every Phase 8B endpoint return 405. **No POST
endpoint dispatches state changes** — every transition is CLI-only
via the 8 management commands
(`inspect_phase8b_payment_order_mutation_review_gate`, `preview_…`,
`prepare_…`, `dry_run_…`, `rollback_dry_run_… --reason`,
`approve_…_gate --reason`, `reject_…_gate --reason`,
`archive_…_gate --reason`). Phase 8B approval flips status to
`approved_for_future_phase8c_controlled_mutation_review` only — it
does NOT authorize any real mutation. Phase 8B never calls Razorpay
/ Meta Cloud / Delhivery / Vapi, never sends or queues WhatsApp,
never creates a `Shipment` / AWB / payment link, never captures /
refunds, never sends a customer notification, never mutates real
`Order` / `Payment` / `Shipment` / `DiscountOfferLog` / `Customer` /
`Lead` / `WhatsAppMessage` / `WhatsAppLifecycleEvent` /
`WhatsAppHandoffToCall` rows. **Phase 8C (controlled real
mutation), Phase 7E-Live-B (real customer WhatsApp send) and Phase
7G-Live (real customer courier execution) remain NOT approved.**

### Phase 8C — Controlled Real Payment → Order Mutation (CLI-only one-shot)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/payment-order-controlled-mutation-readiness/` | admin/staff | Read-only readiness composition (3 env flag states + eligibility counters + locked-False safety contract). |
| GET | `/api/v1/saas/phase8/payment-order-controlled-mutation-gates/?limit=N` | admin/staff | Phase 8C gate listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase8/payment-order-controlled-mutation-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; never returns raw token / full phone / raw Director sign-off — only a SHA-256 hash hint). |
| GET | `/api/v1/saas/phase8/payment-order-controlled-mutation-preview/?phase8b_gate_id=N` | admin/staff | Read-only preview from an approved Phase 8B review gate. Never creates rows. |
| GET | `/api/v1/saas/phase8/payment-order-controlled-mutation-attempts/<int:gate_id>/` | admin/staff | Read-only list of attempt rows for one Phase 8C gate. |
| GET | `/api/v1/saas/phase8/payment-order-controlled-mutation-rollbacks/<int:attempt_id>/` | admin/staff | Read-only list of rollback rows for one Phase 8C attempt. |

POST/PATCH/DELETE on every Phase 8C endpoint return 405. **No POST
endpoint dispatches state changes or execute** — both review state
transitions AND the one-shot execute are CLI-only via the 9
management commands
(`inspect_phase8c_payment_order_controlled_mutation`, `preview_…`,
`prepare_…`, `dry_run_…` with target ids + references,
`approve_…_gate --reason`, `execute_… --confirm-one-shot-mutation
--director-signoff … --operator-name …`, `rollback_… --reason`,
`reject_…_gate --reason`, `archive_…_gate --reason`). Phase 8C
approval flips status to `approved_for_one_shot_controlled_mutation`
only — it does NOT execute the mutation. Phase 8C execute is
strictly CLI-only, refuses unless three env flags are true + kill
switch enabled + structured 15-min Director UTC window + target
safety proof intact + no prior execution; the only mutation
performed is writing `Order.payment_status` and `Payment.status` to
`"Paid"`. Phase 8C never calls Razorpay / Meta Cloud / Delhivery /
Vapi, never sends or queues WhatsApp, never creates a `Shipment` /
AWB / payment link, never captures / refunds, never sends a
customer notification, never mutates real `Customer` / `Lead` /
`Shipment` / `DiscountOfferLog` / `WhatsAppMessage` /
`WhatsAppLifecycleEvent` / `WhatsAppHandoffToCall` rows. **Phase
7E-Live-B (real customer WhatsApp send), Phase 7G-Live (real
customer courier execution), and broad customer automation all
remain NOT approved.**

### Phase 8D — Controlled Mutation Evidence Lock (lock-only meta-audit)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/controlled-mutation-evidence-lock-readiness/` | admin/staff | Read-only readiness composition (eligibility counters + locked-False safety contract). |
| GET | `/api/v1/saas/phase8/controlled-mutation-evidence-locks/?limit=N` | admin/staff | Phase 8D lock listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase8/controlled-mutation-evidence-locks/<int:pk>/` | admin/staff | Read-only lock detail (whitelist serializer; never returns raw token / full phone / raw provider response / Director sign-off text). |
| GET | `/api/v1/saas/phase8/controlled-mutation-evidence-lock-preview/?phase8c_gate_id=N` | admin/staff | Read-only preview from a Phase 8C rolled_back gate. Never creates rows. |

POST/PATCH/DELETE on every Phase 8D endpoint return 405. **No POST
endpoint dispatches lock state changes** — every transition is
CLI-only via the 6 management commands
(`inspect_phase8d_controlled_mutation_evidence_lock`, `preview_…`,
`prepare_…`, `lock_…_lock --reason`, `reject_…_lock --reason`,
`archive_…_lock --reason`). Phase 8D approval flips status to
`locked` only — it does NOT execute Phase 8C again and does NOT
authorise any provider call. Phase 8D never executes Phase 8C
again, never rolls back Phase 8C again, never calls Razorpay /
Meta Cloud / Delhivery / Vapi, never sends or queues WhatsApp,
never creates a `Shipment` / AWB / payment link, never captures /
refunds, never sends a customer notification, never mutates real
`Order` / `Payment` / `Customer` / `Lead` / `Shipment` /
`DiscountOfferLog` / `WhatsAppMessage` rows. **Phase 7E-Live-B
(real customer WhatsApp send), Phase 7G-Live (real customer
courier execution), and broad customer automation all remain NOT
approved.**

### Phase 8E — Real Customer Payment → Order Pilot (review-only)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-readiness/` | admin/staff | Read-only readiness composition (eligibility counters + locked-False safety contract + masked candidate counts). |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-gates/?limit=N` | admin/staff | Phase 8E gate listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; phones masked to last-4 only; customer names masked to first-letter-of-each-word + asterisks; raw provider payloads / `gateway_reference_id` / full payment URLs / Director sign-off text NEVER returned). |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-preview/?phase8d_lock_id=N` | admin/staff | Read-only preview from a locked Phase 8D evidence lock. Never creates rows. |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-candidates/<int:gate_id>/` | admin/staff | Read-only candidate listing for a Phase 8E gate (phones masked, payment references truncated to first 8 chars as `paymentReferencePrefix`). |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-dry-runs/<int:gate_id>/` | admin/staff | Read-only dry-run record listing for a Phase 8E gate (would_* locked-False booleans surfaced; before/after Order + Payment status snapshots equal — the gate did NOT flip them). |

POST/PATCH/DELETE on every Phase 8E endpoint return 405. **No POST
endpoint dispatches gate state changes** — every transition is
CLI-only via the 8 management commands
(`inspect_phase8e_real_customer_payment_order_pilot`, `preview_…`,
`prepare_…`, `select_phase8e_real_customer_candidate`, `dry_run_…`,
`approve_…_pilot --reason`, `reject_…_pilot --reason`,
`archive_…_pilot --reason`). Phase 8E approval flips status to
`approved_for_future_phase8f_real_customer_controlled_mutation`
only — it does NOT execute any mutation and does NOT authorise any
provider call. Phase 8E never calls Razorpay / Meta Cloud /
Delhivery / Vapi, never sends or queues WhatsApp, never creates a
`Shipment` / AWB / payment link, never captures / refunds, never
sends a customer notification, never mutates real `Order` /
`Payment` / `Customer` / `Lead` / `Shipment` / `DiscountOfferLog` /
`WhatsAppMessage` rows. Candidate selection refuses Phase 8C
sandbox rows (real-customer-only). **Phase 7E-Live-B (real
customer WhatsApp send), Phase 7G-Live (real customer courier
execution), Phase 8F (real customer controlled mutation), and
broad customer automation all remain NOT approved.**

### Phase 8E-Hotfix-1 — Candidate Pool Inspector (read-only)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/real-customer-payment-order-pilot-candidate-pool/?limit=N&include_blocked=true\|false` | admin/staff | Read-only candidate pool classification. Returns `totalLinkedPairs`, `eligibleStrictPendingPendingCount`, `eligiblePartialPendingReviewOnlyCount`, `blockedCountsByReason`, and `recommendedCandidates[]` (each row is masked: phone last-4 only, customer name first-letter-of-each-word + asterisks, `paymentReferencePrefix` truncated to first 8 chars). Raw `Payment.raw_response` / full `gateway_reference_id` / full payment URLs NEVER appear. |

POST/PATCH/DELETE on the candidate-pool endpoint return 405. This
endpoint is the read-only sibling of the new
`python manage.py inspect_phase8e_real_customer_candidate_pool`
CLI command; both delegate to the same selector. **Phase 8E-Hotfix-1
also widens the candidate validator** to accept
`Order.payment_status ∈ {"Pending", "Partial"}` (was `"Pending"`
only) when `Payment.status="Pending"` AND the Order stage is
non-terminal AND no Phase 8C sandbox marker is present. When
`Order.payment_status="Partial"` the candidate carries an explicit
`phase8e_candidate_partial_order_pending_payment_review_only`
warning — this is **review-only**; approval still only flips the
gate status to
`approved_for_future_phase8f_real_customer_controlled_mutation`
and does NOT execute any mutation. Phase 8E-Hotfix-1 never calls
Razorpay / Meta Cloud / Delhivery / Vapi, never sends or queues
WhatsApp, never creates a `Shipment` / AWB / payment link, never
captures / refunds, never sends a customer notification, never
mutates real `Order.payment_status` / `Order.state` /
`Payment.status` / `Customer` / `Lead` / `Shipment` /
`DiscountOfferLog` / `WhatsAppMessage` rows. 1 new audit kind
(`phase8e.pilot.pool_inspected`, 28 chars).

### Phase 8F — Controlled Real Customer Payment → Order Mutation (CLI-only one-shot)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/saas/phase8/real-customer-controlled-mutation-readiness/` | admin/staff | Read-only readiness composition (Phase 8F env flag map, eligible Phase 8E gate count, gate status counts, locked-False safety contract). |
| GET | `/api/v1/saas/phase8/real-customer-controlled-mutation-gates/?limit=N` | admin/staff | Phase 8F gate listing with locked-False safety booleans on the response shell. |
| GET | `/api/v1/saas/phase8/real-customer-controlled-mutation-gates/<int:pk>/` | admin/staff | Read-only gate detail (whitelist serializer; raw provider payloads / customer names / addresses / Director sign-off text NEVER returned). |
| GET | `/api/v1/saas/phase8/real-customer-controlled-mutation-preview/?phase8e_gate_id=N` | admin/staff | Read-only preview from an approved Phase 8E pilot gate. Never creates rows. |
| GET | `/api/v1/saas/phase8/real-customer-controlled-mutation-attempts/<int:gate_id>/` | admin/staff | Read-only list of attempt rows for one Phase 8F gate. |
| GET | `/api/v1/saas/phase8/real-customer-controlled-mutation-rollbacks/<int:attempt_id>/` | admin/staff | Read-only list of rollback rows for one Phase 8F attempt. |

POST/PATCH/DELETE on every Phase 8F endpoint return 405. **No POST
endpoint dispatches state changes or executes the mutation** —
every transition is CLI-only via the 8 management commands
(`inspect_phase8f_real_customer_controlled_mutation`,
`preview_phase8f_real_customer_controlled_mutation --phase8e-gate-id`,
`prepare_phase8f_real_customer_controlled_mutation --phase8e-gate-id`,
`approve_phase8f_real_customer_controlled_mutation --gate-id --reason`,
`execute_phase8f_real_customer_controlled_mutation --attempt-id --director-signoff --operator-name --confirm-one-shot-real-mutation`,
`rollback_phase8f_real_customer_controlled_mutation --attempt-id --reason`,
`reject_phase8f_real_customer_controlled_mutation --gate-id --reason`,
`archive_phase8f_real_customer_controlled_mutation --gate-id --reason`).
Phase 8F approval flips status to
`approved_for_one_shot_real_customer_mutation` only — it does NOT
execute the mutation. Phase 8F execute is exclusively CLI-driven
and requires three Phase 8F env flags ALL true, a structured 15-min
Director sign-off UTC window (via
`apps.saas.utc_window.validate_within_director_window`), the kill
switch enabled, `--confirm-one-shot-real-mutation`, non-empty
`--operator-name`, and a Director sign-off body that literally
references `phase8f_attempt_id_<ID>`, `phase8f_gate_id_<ID>`,
`phase8e_gate_id_<ID>`, `target_order_<ORDER_ID>`,
`target_payment_<PAYMENT_ID>`. Execute mutates ONLY
`Order.payment_status` and `Payment.status` to `"Paid"` on the
named target rows. `Order.state` is NEVER mutated. Phase 8F never
calls Razorpay / Meta Cloud / Delhivery / Vapi, never sends or
queues WhatsApp, never creates a `Shipment` / AWB / payment link,
never captures / refunds, never sends a customer notification,
never mutates real `Customer` / `Lead` / `Shipment` /
`DiscountOfferLog` / `WhatsAppMessage` rows. 10 new audit kinds
(`phase8f.real_mutation.{readiness_inspected,previewed,prepared,
approved,executed,rollback_recorded,rejected,archived,blocked,
failed}`, each ≤ 64 chars). **Phase 7E-Live-B (real customer
WhatsApp send) and Phase 7G-Live (real customer courier execution)
remain NOT approved.**

---

## Phase 9 AI Agent APIs (Tier-2 deterministic agents — recommendations-only)

All Phase 9 endpoints are **read-only** (GET / HEAD / OPTIONS only;
POST / PATCH / PUT / DELETE return 405). Auth: admin / director /
superuser only — same permission class as the Phase 6E SaaS admin
endpoints. None of these endpoints trigger calls, WhatsApp,
payments, or shipments — they surface the snapshot rows the Celery
beat schedule (08:00 → 13:00 IST) writes.

### Phase 9A — Customer Success / Reorder Agent

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/customer-success/snapshots/` | Paginated list of `CustomerSuccessSnapshot` rows. |
| GET | `/api/v1/customer-success/snapshots/latest/` | Latest single snapshot row. |
| GET | `/api/v1/customer-success/snapshots/<int:pk>/` | Single snapshot detail. |
| GET | `/api/v1/customer-success/cohorts/` | Aggregate counts: `fresh_delivery`, `early_usage`, `mid_usage`, `reorder_window`, `late_reorder`, `lapsed`, `at_risk_count`, `reorder_candidate_count`. |

### Phase 9B — RTO Prevention Agent

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/rto-prevention/snapshots/` | Paginated `RtoRiskSnapshot` rows for in-flight orders. |
| GET | `/api/v1/rto-prevention/snapshots/<int:pk>/` | Single risk snapshot detail. |
| GET | `/api/v1/rto-prevention/cohorts/` | Aggregate counts: `low`, `medium`, `high`, `critical` tier breakdown. |

### Phase 9C — CFO Agent

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/cfo/snapshots/` | Paginated `CfoFinancialSnapshot` rows. |
| GET | `/api/v1/cfo/snapshots/latest/` | Latest daily financial snapshot. |
| GET | `/api/v1/cfo/snapshots/<int:pk>/` | Single snapshot detail. |

### Phase 9D — Data Analyst Agent

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/data-analyst/snapshots/` | Paginated `DataAnalystSnapshot` rows. |
| GET | `/api/v1/data-analyst/snapshots/latest/` | Latest daily funnel snapshot. |
| GET | `/api/v1/data-analyst/snapshots/<int:pk>/` | Single snapshot detail. |

### Phase 9E — Calling Team Leader Agent

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/calling-team-leader/snapshots/` | Paginated `CallingTeamLeaderSnapshot` rows. |
| GET | `/api/v1/calling-team-leader/snapshots/latest/` | Latest daily call-performance snapshot. |
| GET | `/api/v1/calling-team-leader/snapshots/<int:pk>/` | Single snapshot detail. |

### Phase 9F — CEO AI Orchestration (synthesis over 9A-9E)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/ceo-orchestration/snapshots/` | Paginated `CeoOrchestrationSnapshot` rows. |
| GET | `/api/v1/ceo-orchestration/snapshots/latest/` | Latest composite snapshot — business health score, tier, top-3 priorities, cross-cutting alerts, agent status summary, deterministic briefing text. |
| GET | `/api/v1/ceo-orchestration/snapshots/sidebar-status/` | **Phase 15B** — slim allow-list response for the Sidebar Director Briefing badge. Admin/director/owner/superuser only. Response: `{status: "ready" \| "stale" \| "critical" \| "missing", label, latestSnapshotId, latestSnapshotAt (ISO), ageMinutes, healthScore (0-100), tier (HealthTier choice), targetRoute: "/ceo-ai"}`. NEVER returns `briefingText`, `crossCuttingAlerts`, `top3Priorities`, `agentStatusSummary`, `alerts`, or any other field outside the 8-key allow-list. POST/PUT/PATCH/DELETE return 405. NEVER triggers a new orchestration run, NEVER enqueues a Celery task, NEVER mutates any row, NEVER writes an AuditEvent. Status precedence: `tier == "critical"` → critical (regardless of age); else `age >= 36h` → stale; else → ready. No snapshot → missing. |
| GET | `/api/v1/ceo-orchestration/snapshots/<int:pk>/` | Single composite snapshot detail. |

Phase 9F does NOT touch the legacy `ai_governance.CeoBriefing`
model or its `ai-daily-briefing-morning` / `ai-daily-briefing-evening`
beat entries; it ships alongside as a new synthesis layer.

---

## Phase 10 Diagnostics APIs (read-only Director review)

Phase 10 is the first **diagnostics** module under `apps/diagnostics/`
(service-only Django app — no models, no migrations).

### Phase 10A — Pending Payments Drilldown

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/diagnostics/pending-payments/?include_partial=true|false&limit=N&state=Delhi` | Read-only list of `Payment` rows with status `Pending` (and `Partial` when `include_partial=true`), joined with `Order` + `crm.Customer` + last outbound `WhatsAppMessage` + last `Call`. |

Auth: admin / director / superuser only. `http_method_names = ["get",
"head", "options"]` — POST / PATCH / PUT / DELETE return 405.

Query params:

| Param | Type | Default | Notes |
| --- | --- | --- | --- |
| `include_partial` | bool | `true` | Include `Payment.status = Partial` rows. |
| `limit` | int | `100` (max `500`) | Cap on result rows. |
| `state` | str | none | Case-insensitive `Order.state` filter. |

Response shape `{count, filters, results}`. Each row carries:
`payment_id`, `payment_status`, `amount` (integer rupees),
`payment_link_url`, `gateway_reference_id`, `created_at`,
`days_since_creation`, `order_id`, `order_state`, `order_status`,
`customer_name`, `customer_phone`, `phone_source`,
`last_whatsapp_at`, `last_call_at`, `last_call_outcome`. Sorted
oldest-first.

Phase 10A NEVER mutates state, NEVER calls Razorpay / Meta Cloud /
Delhivery / Vapi, NEVER sends or queues WhatsApp. Action on the
returned rows still requires the existing Phase 7E-Live-B Director
directive.

### Phase 10B — Payment Reminder Preparer (CLI-only)

Phase 10B is a stage-aware CLI wrapper around Phase 7E-Live-B; **no
API endpoint is exposed**. The only entrypoint is:

```bash
python manage.py prepare_payment_reminder_send <payment_id> [--template-id NAME] [--force] [--operator-note TEXT] [--operator-name NAME] [--json]
```

The output is a Phase 7E-Live-B gate row in `draft` status; Director
still has to run the existing `inspect_/approve_/execute_phase7e_live_b_real_customer_gate`
commands.

### Phase 10C — Razorpay Payment Link Refresh Gate (CLI-only)

Phase 10C is a CLI-only heavyweight gate; **no API endpoint is
exposed for `Phase10CPaymentLinkRefreshGate`**. The 6 entrypoints
are `prepare_/approve_/execute_/rollback_/cancel_/inspect_phase10c_payment_link_refresh_gate`.

Phase 10C never sends WhatsApp / makes a call / dispatches a
shipment — it only mutates `Payment.payment_url` and writes a
`Phase10CPaymentLinkRefreshGate` row for evidence. The refreshed
link is delivered to the customer only via the separate Phase
7E-Live-B `payment_reminder` template send.

---

## Phase 11 Calls Observability APIs (Tier-3 — read-only)

All Phase 11 endpoints are **read-only** (GET / HEAD / OPTIONS only;
POST / PATCH / PUT / DELETE return 405). Auth: admin / director /
superuser only. Phone numbers and Vapi call ids are masked to
last-4 in every response.

### Phase 11A — Transcript Ingestion Pipeline V1

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/calls/transcript-backlog/?window_days=N` | Backlog summary: total Calls in window, ingested count, missing-transcript count, ingest ratio, oldest + newest backlog rows, top-10 backlog call ids masked with `provider_call_id_last4`. |
| GET | `/api/v1/calls/transcripts/<str:call_id>/` | Per-utterance transcript list for one Call (Phase 2D `CallTranscriptLine` shape: `order` / `who` / `text`). |

Phase 11A NEVER triggers WhatsApp / makes a call / dispatches a
shipment / mutates `Customer` / `Order` / `Payment` / `Lead` /
`Shipment` / `DiscountOfferLog`. The daily ingest sweep
(`apps.calls.tasks.ingest_transcript_backlog_daily` at 23:00 IST)
refuses with `transcript.daily_ingest.blocked` audit when the
runtime kill switch is off, sandbox mode is active, or
`VAPI_API_KEY` is missing.

### Phase 11B — Call Quality Scorer V1 (deterministic, no LLM)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/calls/quality-scores/?limit=N` | Paginated list of `CallQualityScore` rows (cap 200). |
| GET | `/api/v1/calls/quality-scores/<str:call_id>/` | Single score detail with full `raw_signals` JSON. |
| GET | `/api/v1/calls/quality-scores/summary/?window_days=N` | Aggregate: `totalScored`, `avgComposite`, `lowComplianceCount`, `topFlags[]`, `avgByAgent[]` (per agent label: `callCount`, `avgComposite`, `avgCompliance`). Ready for the Phase 11C CAIO Audit Agent to consume. |

Each `CallQualityScore` carries 5 deterministic dimension scores
(`connection_score`, `product_knowledge_score`, `compliance_score`,
`objection_handling_score`, `tonality_score`) + a weighted
`composite_score` + a `flags` JSON list (`compliance_violation`,
`no_greeting`, `weak_product_knowledge`, `no_objection_response`,
`short_call`, `zero_agent_utterances`, `no_transcript`). The daily
scoring sweep (`apps.calls.tasks.score_call_transcripts_daily` at
23:30 IST) runs 30 minutes after Phase 11A so freshly-ingested
transcripts get scored the same evening.

### Phase 11C — CAIO Audit Agent V1 (governance, recommendations-only)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/caio/snapshots/` | Paginated list of `CaioAuditSnapshot` rows (cap 200). |
| GET | `/api/v1/caio/snapshots/latest/` | Most recent CAIO snapshot. 404 when none. |
| GET | `/api/v1/caio/snapshots/<int:pk>/` | Single snapshot detail with full `recommendation_text` + `raw` JSON. |

CAIO is a **pure governance layer** — Master Blueprint §26 #2
("CAIO Agent never executes business actions. Monitor / audit /
suggest only."). The agent reads compliance risk from Phase 11B
flagged calls, transcript backlog from Phase 11A, call quality
trend (7d vs prior 7d), and the latest Phase 9A-9F agent
snapshots. Each daily run (`apps.caio.tasks.run_caio_audit_agent_daily`
at 14:00 IST) writes one `CaioAuditSnapshot` + one `AgentRun` +
2 audit rows.

### Phase 11D — Learning Loop Gate V1 (Director-approved)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/learning/proposals/?status=&type=&limit=N` | Paginated `LearningProposal` rows (cap 200). |
| GET | `/api/v1/learning/proposals/pending/` | Shortcut for `status=pending`. |
| GET | `/api/v1/learning/proposals/<int:pk>/` | Single proposal detail with full `evidence`, `proposed_change_text`, `implementation_note`. |
| GET | `/api/v1/learning/proposals/summary/` | Camel-cased aggregate counts: `pending`, `approved`, `rejected`, `implemented`, `cancelled`, `highImpactPending`, `total`. |

Phase 11D is a **paper-trail system** — no auto-execution of any
kind. `implement_proposal` only records what the Director did
manually outside the platform. Phase 11D never mutates
`PromptVersion`, never touches Vapi prompt config, never triggers
WhatsApp / makes a call / dispatches a shipment. Proposals are
created on demand by the existing `caio-audit-daily` task; no
new beat task added (beat count stays at 11 entries through
Phase 11D).

---

## Phase 12 AI Calling APIs (Tier-4 — read-only)

All Phase 12 endpoints are **read-only** (GET / HEAD / OPTIONS only;
POST / PATCH / PUT / DELETE return 405). Auth: admin / director /
superuser only. Phone numbers, Vapi assistant ids, and Vapi call
ids are masked to last-4 in every response.

### Phase 12A — AI Calling Campaign Gate V1 (Director-approved)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/calls/campaigns/?limit=N` | Paginated `AiCallCampaignGate` rows (cap 200). |
| GET | `/api/v1/calls/campaigns/latest/` | Most recent campaign gate. 404 when none. |
| GET | `/api/v1/calls/campaigns/<int:pk>/` | Single campaign detail with camelCased fields including `aiAssistantIdLast4` (never the full Vapi assistant id). |

Phase 12A is the **only** path that may dispatch real Vapi calls,
and only when ALL guards pass: gate status `approved`,
`--confirm-ai-calling-campaign` CLI flag, `AI_CALLING_ENABLED=true`
runtime env (defaults locked off — `.env.production` is NEVER
edited), Postgres-safe runtime kill switch enabled, now ∈
[recorded UTC window start, end], `VAPI_MODE=live`. There is no
rollback path — cannot un-make a Vapi call.

### Phase 12B — Call Outcome Classifier V1 (deterministic, suggestions-only)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/calls/outcomes/?review_status=&outcome=&campaign_gate_id=&limit=N` | Paginated `CallOutcomeRecord` rows (cap 200). |
| GET | `/api/v1/calls/outcomes/<int:pk>/` | Single outcome detail with full `evidence` JSON. |
| GET | `/api/v1/calls/outcomes/summary/` | Camel-cased aggregate: `total`, `pendingCount`, `approvedCount`, `appliedCount`, `skippedCount`, `byOutcome` map. |

Phase 12B is **suggestions-only** — V1 has NO auto-apply path.
`Lead.status` is mutated ONLY by `apply_outcome_updates` when
called with `--operator-name`, `--confirm-outcome-apply` flag,
and for records already in `review_status="approved"` with a
non-blank `suggested_lead_status`. Sandbox mode skips the
mutation but records the intent. The deterministic classifier
(no LLM) cascades rejection → conversion → callback → unclear,
with Hinglish-aware signal lists.

### Phase 12C — Post-Call WhatsApp Follow-up Queue V1 (Director-triggered)

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/api/v1/calls/followups/?status=&type=&limit=N` | Paginated `PostCallFollowUpQueue` rows (cap 200). |
| GET | `/api/v1/calls/followups/<int:pk>/` | Single follow-up detail. |
| GET | `/api/v1/calls/followups/summary/` | Camel-cased aggregate: `total`, `byStatus` map, `byFollowUpType` map. |

Phase 12C **never sends WhatsApp automatically** — it only
queues a draft-status `Phase7ELiveBRealCustomerSendGate` row;
the Director still owns the approve + execute via the existing
Phase 7E-Live-B CLI commands. Phone numbers are masked to last-4
everywhere; full E.164 NEVER appears in API responses or audit
payloads.

### Phase 12D — Tier-4 AI Calling Performance Dashboard (frontend-only)

Phase 12D is **frontend-only** — it reads the existing Phase 12A-C
endpoints (`/api/v1/calls/{campaigns,outcomes,outcomes/summary,
followups,followups/summary}/`) and renders the
`/operations/calling-dashboard` Director review surface (Campaign
History table, Call Outcomes summary tiles + tabs, WhatsApp
Follow-up Queue summary + masked-phone table, CLI Reference card).
**No "Run Campaign" / "Send WhatsApp" / "Approve" / "Apply" /
"Trigger Call" / "Reassign Agent" / "Auto-dial" buttons anywhere.**
State changes still happen exclusively via Phase 12A/B/C CLI.

---

## Phase 13 Director Auth APIs

### Phase 13A — Director Login Flow (JWT-backed)

| Method | Path | Auth | Behaviour |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login/` | public | SimpleJWT `TokenObtainPairView` alias. Frontend `api.login(email, password)` targets this path. On success returns `{access, refresh}`; access token saved to `localStorage["nirogidhara.jwt"]`. |
| POST | `/api/v1/auth/refresh/` | public | SimpleJWT `TokenRefreshView`. Exchanges a refresh token for a fresh access token. |
| POST | `/api/auth/token/` | public | **Legacy alias** — preserved for backward compatibility with the original `apps.accounts.urls` registration. New code must target `/api/v1/auth/login/`. |

The Director user (`1995praritsidana@gmail.com`,
`is_superuser=True`) was created manually on the VPS Postgres via
`python manage.py shell` + `getpass()` — the password is NEVER
stored in code, env, or git. `RequireAuth`
(`frontend/src/components/RequireAuth.tsx`) wraps every
`AppLayout`-rendered route; unauthenticated users redirect to
`/login` with the attempted path captured in `location.state.from`.
`safeFetch` gains a 401 interceptor that clears the JWT and
dispatches a `nirogidhara:auth-cleared` window event.

**`safeFetch` production fix (Phase 13A):** the mock-data fallback
now only runs when `import.meta.env.DEV === true`; production
builds throw real backend errors instead of silently masking them.

Phase 13B added a SaaS Admin defensive optional-chaining pass on
Phase 7 readiness card array accesses + a WebSocket scheme fix
(`audit.events` connection now matches the page protocol). Phase
13C wrapped the SaaS Admin route in an `ErrorBoundary` component
and ran a broad defensive pass over 148 array-like accesses. No
new endpoints in 13B / 13C — code-quality hardening only.

### Phase 13D-1 — Integration Readiness DB Cleanup (DB-ops only)

DB-operations only — no new API endpoints, no new models, no
new migrations. Cleared orphaned readiness rows on the VPS via a
one-time `python manage.py shell` block.

---

## Phase 14A Founder Operating Model (docs-only)

Phase 14A is the **solo-operator design constraint** lock — a
docs-only commit that adds a new "Founder Operating Model" section
to `nd.md` (§1.5) anchoring every future automation decision to
the ₹10,000 cr solo-operator North Star. No code, no migration,
no endpoint, no env var — pure vision lock.
