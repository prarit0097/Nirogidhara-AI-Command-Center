# Deploying Nirogidhara AI Command Center to Hostinger VPS

> Target domain: **`ai.nirogidhara.com`**
> App folder on VPS: **`/opt/nirogidhara-command`**
> Stack: isolated Postgres + Redis + Daphne backend + Celery worker + Celery beat + Nginx (Vite SPA)
> Compose project name: **`nirogidhara-command`**

This runbook is the authoritative production deploy path. Every command
below runs on the VPS unless explicitly marked _(local)_. Local dev keeps
using `python manage.py runserver` + `npm run dev` — Docker is **production
only**.

> **Phase 16N — Director AI Daily Briefing Real Data Wiring + Safe Recommendation Pack is implemented and pushed to origin/main; VPS production verification pending.** Read-only / internal-only decision layer over the existing Phase 16I–16M workboard data — extends `apps.ai_copilot` with **NO new model and NO migration**: a new `apps.ai_copilot.briefing` module + 3 read-only endpoints `GET /api/v1/ai-copilot/director-briefing/` + `.../summary/` + `.../recommendations/` (`AuthenticatedReadAdminWrite`, GET-only; POST/PATCH/DELETE → 405). Composes the Phase 16M analytics + Phase 16K director-attention queue + pending suggestion/action counts into a deterministic AI briefing (executive summary, attention items, department/member focus, safe internal-only recommendations with `permittedAction` ∈ {internal_review, assign_internal, create_internal_action, review_blocker, no_external_action}, blocked-live-actions, safety snapshot). New **Director AI Briefing** section on `/operations/ai-copilot` (read-only, no live-action button). Never calls a provider, mutates a business/workboard row, enqueues a Celery job, or touches `RuntimeKillSwitch` / `SandboxState`. Verification: backend 17 Phase 16N + 97 regression = 114 passed targeted, frontend 423/423, lint 0, build green; `makemigrations --check` → "No changes detected" (NO migration) + `manage.py check` clean. **Phase 16N is implemented and pushed, VPS production verification pending — do NOT mark production verified until a VPS deploy + Director browser validation pass. Phase 16O is NOT started.** Phase 16M (`a992207`) is the previous verified baseline.
>
> **Previous verified baseline: Phase 16M — Workboard Analytics + SLA Throughput Dashboard, PRODUCTION VERIFIED on the VPS and CLOSED at commit `a992207`.** Route: `/operations/ai-copilot` (Workboard Analytics + SLA Throughput section). Read-only / internal-only analytics over the existing Phase 16J/16K/16L workboard — it extends `apps.ai_copilot` with **NO new model and NO migration**: 1 read-only service `get_workboard_analytics(window_days=14)` + 1 read-only endpoint `GET /api/v1/ai-copilot/workboard/analytics/` (`AuthenticatedReadAdminWrite`, GET-only; POST/PATCH/DELETE → 405). Derives summary / per-department / per-member / SLA / blocker / daily-throughput-trend analytics purely from existing fields; never calls a provider, mutates a business row, enqueues a business Celery job, or touches `RuntimeKillSwitch` / `SandboxState`. Verification: backend 15 Phase 16M + 82 regression = 97 passed targeted, frontend 410/410, lint 0, build green; `makemigrations --check` → "No changes detected" (**NO migration — a fresh deploy needs no `migrate` for Phase 16M**) + `manage.py check` clean. **Phase 16M is PRODUCTION VERIFIED on the VPS and CLOSED at commit `a992207` (deployed with the standard `docker compose -f docker-compose.prod.yml up -d --build`; no DB migration for Phase 16M). Phase 16N is implemented and pushed to origin/main (VPS verification pending); Phase 16O is NOT started.** Rollback for Phase 16M is a plain `git revert` + rebuild (no migration to reverse). Phase 16L (`9d144f5`) is the previous verified baseline.
>
> **Phase 16L — Scoped Team Member Work Permissions + My Work Queue, PRODUCTION VERIFIED on the VPS and CLOSED at commit `9d144f5`.** Route: `/operations/ai-copilot` (My work queue section). Phase 16L extends the existing `apps.ai_copilot` app with 1 additive model `AiWorkboardDepartmentMember` (`user` / `department` [the 9 Phase 16K teams] / `is_active` / `can_claim` / `can_work` / `can_complete` / `created_by` / timestamps); migration `ai_copilot.0004_phase16l_workboard_department_member` (pure `CreateModel`; no existing table altered) + 7 endpoints under `/api/v1/ai-copilot/` (`workboard/my/`, `workboard/my/summary/`, `workboard/my-permissions/`, `workboard/department-members/` GET+POST, `.../<id>/activate/` + `.../deactivate/`). Lets internal team members safely work their own assigned internal actions (+ claim eligible department work) without broad Director/Admin power; the 6 Phase 16K scoped transitions now run `IsAuthenticated` + service scoped checks (assign/reassign + membership-management stay Director/Admin-only); every transition is DB-only and never calls a provider, never broadens operations users to admin (locked `provider_action_*` / `external_action_*` = false). Verification: backend 24 Phase 16L + 58 regression = 82 passed targeted, frontend 398/398, lint 0, build green; `makemigrations --check` + `manage.py check` clean. **VPS production verification PASSED (2026-06-05):** HEAD `9d144f5`; pre-deploy backup `phase16l_pre_deploy_2026-06-05_072806.sql`; `docker compose ... up -d --build` healthy (backend / nginx / db / redis + worker / beat); entrypoint applied `ai_copilot.0004_phase16l_workboard_department_member ... OK` (manual `migrate` → "No migrations to apply"); `makemigrations --check --dry-run` → "No changes detected"; `manage.py check` → "0 issues"; `pytest tests/test_phase16l_workboard_permissions.py` + 16K/16J/16I regression → `[100%]`; nginx restarted; `http://127.0.0.1:18020/api/healthz/` → 200 and `https://ai.nirogidhara.com/api/healthz/` → 200 `{"status": "ok", "service": "nirogidhara-backend"}` (a transient 502 during the Docker nginx restart cleared on the next check — non-blocking timing; host `nginx -t` passed, host nginx active); Director browser validation of `/operations/ai-copilot` (My work queue + workboard) + `/operations/pilot-workbench` passed with the safety shell unchanged and provider/external flags false. **Reference fresh-deploy commands (already applied on the VPS — the migration is in place):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/phase16l_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 25
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate --noinput          # → applies ai_copilot.0004_phase16l_workboard_department_member
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16l_workboard_permissions.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of the My Work queue + scoped permissions on `/operations/ai-copilot` **PASSED** (2026-06-05): the AI Copilot Center + Approved action queue + Department action workboard + My work queue all rendered; Director/Admin controls (Start / Block / Complete internal / Reassign / Add note / Claim) rendered; rows showed `provider_action_taken=false` / `external_action_taken=false`; the safety shell was unchanged (AI Paused · Sandbox OFF · Briefing STALE · Sync Live); `/operations/pilot-workbench` stayed internal-control-only with the blocked-live-actions panel; no live side effect. Scoped-member / viewer login was not visually exercised in the browser, but the Phase 16L backend tests cover the scoped-member / non-member / viewer permission matrix. **Phase 16L is PRODUCTION VERIFIED + CLOSED at `9d144f5`. Next planned work is Phase 16O (NOT started; separate Director directive required); Phase 16N is implemented and pushed to origin/main (VPS verification pending).**
>
> **Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer, PRODUCTION VERIFIED on the VPS and CLOSED at commit `efea751`.** Route: `/operations/ai-copilot` (Department action workboard section). Phase 16K extends the existing `apps.ai_copilot` app — `AiApprovedAction` gains 8 additive workboard fields (`department` / `assignee_user` / `work_status` / `due_at` / `blocker_reason` / `completed_by` / `completed_at` / `last_activity_at`) + a new model `AiActionWorkEvent`; migration `ai_copilot.0003_phase16k_action_workboard` (pure `CreateModel` + `AddField` + `AddIndex`; no existing table altered) + 12 endpoints under `/api/v1/ai-copilot/` (`workboard/`, `workboard/summary/`, `workboard/director-attention/`, `actions/<id>/{assign,claim,start,block,unblock,complete-internal,reassign,notes}/`). Makes the Phase 16J AI-approved internal actions operational for real internal departments (ownership / SLA / blocked / Director attention); every transition is DB-only and never calls a provider (locked `provider_action_*` / `external_action_*` = false). All workboard mutations require director/admin/superuser; reads = auth. Verification: backend 23 Phase 16K + 102 regression = 125 passed targeted, frontend 385/385, lint 0, build green; `makemigrations --check` + `manage.py check` clean. **VPS production verification PASSED:** browser validation of the Department action workboard on `/operations/ai-copilot` — Assign / Claim / Block (Director attention updated) / Unblock / Complete internal / Add note all PASSED; external action taken=false / provider action taken=false; safety shell unchanged; no live provider / customer-facing action. **Phase 16K ADDS migration `ai_copilot.0003_phase16k_action_workboard`, so a fresh VPS deploy REQUIRES `migrate` after a pre-deploy backup (already applied + verified on the VPS):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/phase16k_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 25
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate --noinput          # → applies ai_copilot.0003_phase16k_action_workboard
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16k_action_workboard.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of the Department action workboard on `/operations/ai-copilot` **PASSED** (assigned an internal action to a department; started it; blocked with a reason [Director attention updated]; unblocked; completed internal; added a note; summary cards updated; `provider_action_taken` / `external_action_taken` stayed false; safety shell unchanged; no live side effect). **Phase 16K is PRODUCTION VERIFIED + CLOSED at `efea751` (Phase 16L has since shipped on top — PRODUCTION VERIFIED + CLOSED at `9d144f5`; the current next-planned work is Phase 16N).**
>
> **Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge, PRODUCTION VERIFIED on the VPS and CLOSED at commit `aa8cf13`.** Route: `/operations/ai-copilot` (Approved action queue section). Phase 16J extends the existing `apps.ai_copilot` app with 2 new models (`AiApprovedAction` / `AiApprovedActionEvent`) + migration `ai_copilot.0002_phase16j_ai_action_queue` (pure CreateModel; no existing table altered) + 7 endpoints under `/api/v1/ai-copilot/actions...` — converts an **approved** Phase 16I suggestion into an internal-only work item a human applies; applying is DB-only (may create an internal `PilotTask` via the Phase 16H safe service, else records a `result_payload`) and never calls a provider (locked `provider_action_attempted` / `provider_action_taken` / `external_action_allowed` / `external_action_taken` = false). Verification: backend 16 new + regression 102 passed targeted, frontend 374/374, lint 0, build green; `makemigrations --check` + `manage.py check` clean. **VPS production verification PASSED:** browser validation of the Approved action queue on `/operations/ai-copilot` — an approved suggestion created an internal action (PENDING INTERNAL ACTION → Apply → APPLIED INTERNAL; Reject → REJECTED); safety flags stayed false; safety shell unchanged; no live provider / customer-facing action. **Phase 16J ADDS migration `ai_copilot.0002_phase16j_ai_action_queue`, so a fresh VPS deploy REQUIRES `migrate` after a pre-deploy backup (already applied + verified on the VPS):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/phase16j_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 20
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate                            # → applies ai_copilot.0002_phase16j_ai_action_queue
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16j_ai_action_queue.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director-led browser validation of the Approved action queue on `/operations/ai-copilot` **PASSED** (approved a suggestion; created an action from it; it landed in the **PENDING INTERNAL ACTION** state with external-action flags false; **Apply** → `applied_internal`; **Reject** → `rejected`; no live side effect; safety shell unchanged). **Phase 16J is PRODUCTION VERIFIED + CLOSED at `aa8cf13` (Phase 16K has since shipped on top — PRODUCTION VERIFIED + CLOSED at `efea751`; the current next-planned work is Phase 16N).**
>
> **Phase 16I — AI Copilot Enablement + Human Approval Workflow, PRODUCTION VERIFIED on the VPS and CLOSED at commit `0f91f6b`.** Route: `/operations/ai-copilot`. Phase 16I adds the additive `apps.ai_copilot` app with 2 new models (`AiCopilotSuggestion` / `AiCopilotReviewEvent`) + migration `ai_copilot.0001_phase16i_ai_copilot` (pure CreateModel; no existing table altered) + a deterministic, human-approved AI copilot layer (no live AI/LLM call; locked `provider_call_made` / `external_action_allowed` / `external_action_taken` = false). **VPS proof:** browser validation of `/operations/ai-copilot` (AI Copilot Center; sidebar AI Copilot; safety shell AI Paused / Sandbox OFF / Sync Live; AI Mode mock / Live Autonomous Locked / Live Provider unavailable / Provider disabled / Human Approval Required / Provider Call None; suggestion generated → pending review → approved + rejected internally; external action allowed/taken + provider call false; no live side effect); `pytest tests/test_phase16i_ai_copilot.py` → 19 passed `[100%]`; regression (16H/16G/16F/16E) → 67 passed `[100%]`; `makemigrations --check` + `manage.py check` clean; `GET https://ai.nirogidhara.com/api/healthz/` → `{"status":"ok","service":"nirogidhara-backend"}`. **Phase 16I ADDS migration `ai_copilot.0001_phase16i_ai_copilot`, so a fresh VPS deploy REQUIRES `migrate` after a pre-deploy backup (the current VPS already has it applied):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/phase16i_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 20
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate                            # → applies ai_copilot.0001_phase16i_ai_copilot
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16i_ai_copilot.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of `/operations/ai-copilot` **PASSED** (AI Copilot Center opened; AI mode banner + live autonomous Locked confirmed; a safe suggestion generated with `provider call: None` + no external action; one approved, one rejected; no live side effect). **Phase 16I is PRODUCTION VERIFIED + CLOSED at `0f91f6b`.** (Phases 16J / 16K / 16L have since shipped on top and are all PRODUCTION VERIFIED + CLOSED — see the current-baseline note at the top of this file; the current next-planned work is Phase 16O.)
>
> **Phase 16H — Internal Pilot Execution Workbench + Role-Based Task Queues, PRODUCTION VERIFIED on the VPS and CLOSED at commit `d733cf0`.** Route: `/operations/pilot-workbench`. Phase 16H extends the additive `apps.pilot` app with 2 new models (`PilotTask` / `PilotTaskEvent`) + migration `pilot.0003_phase16h_pilot_execution` (pure CreateModel; no existing table altered) + a DB-only role-based task-queue execution layer (`provider_actions_allowed` locked false at every task status including `in_progress`/`done`). **VPS proof:** browser validation of `/operations/pilot-workbench` passed (title Internal Pilot Execution Workbench; sidebar Pilot Workbench; safety shell AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked; pilot plan created + approved; 14 internal tasks generated; task lifecycle Start→IN PROGRESS / Complete→DONE / Block→BLOCKED / Unblock→IN PROGRESS / Skip→SKIPPED; no live side effect); `makemigrations --check` → "No changes detected"; `manage.py check` → "0 issues"; `pytest tests/test_phase16h_pilot_execution.py --tb=no -q` → 19 passed `[100%]`; `GET https://ai.nirogidhara.com/api/healthz/` → `{"status":"ok","service":"nirogidhara-backend"}`. **Phase 16H ADDS migration `pilot.0003_phase16h_pilot_execution`, so a fresh VPS deploy REQUIRES `migrate` after a pre-deploy backup (the current VPS already has it applied):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/phase16h_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 20
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate                            # → applies pilot.0003_phase16h_pilot_execution
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16h_pilot_execution.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of `/operations/pilot-workbench` **PASSED** (an approved plan selected; role-based task queues generated; a task driven start → block[reason] → unblock → complete; per-team progress updated; no live side effect + safety shell unchanged). **Phase 16H is PRODUCTION VERIFIED + CLOSED at `d733cf0`.** (Phases 16I / 16J / 16K / 16L have since shipped on top and are all PRODUCTION VERIFIED + CLOSED — see the current-baseline note at the top of this file; the current next-planned work is Phase 16O.)
>
> **Phase 16G — Internal Pilot Control Center / Pilot Execution Dashboard, PRODUCTION VERIFIED on the VPS and CLOSED at commit `38e8dc8`.** Route: `/operations/pilot-control`. Phase 16G extends the additive `apps.pilot` app with 3 new models (`PilotPlan` / `PilotPlanEvent` / `PilotPlanReview`) + migration `pilot.0002_phase16g_pilot_control` (pure CreateModel; no existing table altered) + a DB-only pilot-management layer. **VPS proof:** browser validation of `/operations/pilot-control` passed (title Internal Pilot Control Center; sidebar Pilot Control; safety shell AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked; status counters + Create pilot plan form + Pilot plans panel rendered; safety copy confirms internal control only / no live provider automation; no live side effect); `git log` HEAD `38e8dc8`; `git status` clean except untracked `backups/`; `makemigrations --check` → "No changes detected"; `manage.py check` → "0 issues"; `pytest tests/test_phase16g_pilot_control.py --tb=no -q` → 19 passed `[100%]`; `GET https://ai.nirogidhara.com/api/healthz/` → `{"status":"ok","service":"nirogidhara-backend"}`. **Phase 16G ADDS migration `pilot.0002_phase16g_pilot_control`, so a fresh VPS deploy REQUIRES `migrate` after a pre-deploy backup (the current VPS already has it applied):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/phase16g_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 20
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate                            # → applies pilot.0002_phase16g_pilot_control
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16g_pilot_control.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of `/operations/pilot-control` **PASSED** (a pilot plan created; mark_ready → approve → start → pause → resume → complete run; a Director note added; events updated; no live side effect + safety shell unchanged). **Phase 16G is PRODUCTION VERIFIED + CLOSED at `38e8dc8`.** (Phases 16H / 16I / 16J / 16K / 16L have since shipped on top and are all PRODUCTION VERIFIED + CLOSED — see the current-baseline note at the top of this file; the current next-planned work is Phase 16O.)
>
> **Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run, PRODUCTION VERIFIED on the VPS and CLOSED at commit `967ed3d`.** Route: `/operations/pilot-readiness`. **VPS proof:** browser validation passed (Controlled Internal Pilot Readiness title; safety shell AI Paused / Sandbox OFF / Sync Live / Live Provider Actions Locked; gate matrix payment/shipment/Vapi-AI BLOCKED + data/calling/order/confirmation/safety PASS; internal dry-run recorded with status BLOCKED [correct — live actions locked]; no live side effect); `migrate --noinput` → "No migrations to apply." (migration `pilot.0001_initial` already applied on the VPS); regression suite + targeted `tests/test_phase16f_pilot_readiness.py` → `[100%]`; `curl -sS https://ai.nirogidhara.com/api/healthz/` → `{"status": "ok", "service": "nirogidhara-backend"}`. An observed gate-matrix warning ("WhatsApp live automation blocked — WARNING" / "WhatsApp automation appears enabled — review before pilot.") is a risk to review before any future pilot, NOT a blocker. Phase 16F added the additive `apps.pilot` app — **2 models (`PilotDryRun` / `PilotDecision`), migration `pilot.0001_initial`** (pure CreateModel; no existing table altered) — plus a DB-only dry-run engine reusing the Phase 16E readiness services. **Phase 16F ADDS a migration, so a fresh VPS deploy REQUIRES `migrate` after a pre-deploy backup (the current VPS already has it applied):**
>
> ```bash
> cd /opt/nirogidhara-command
> docker compose -f docker-compose.prod.yml exec -T db pg_dump -U nirogidhara nirogidhara > backups/phase16f_pre_deploy_$(date +%F_%H%M%S).sql
> git pull origin main && docker compose -f docker-compose.prod.yml up -d --build && sleep 20
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py migrate                            # → applies pilot.0001_initial
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16f_pilot_readiness.py --tb=no -q   # → [100%]
> docker compose -f docker-compose.prod.yml restart nginx
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of `/operations/pilot-readiness` **PASSED** (the page loaded with the no-side-effect banner + 12-gate matrix [provider gates blocked]; an internal dry-run recorded a verdict + `provider_actions_blocked=True`; no live action button; safety shell unchanged). **Phase 16F is PRODUCTION VERIFIED + CLOSED at `967ed3d`.** (Phases 16G / 16H / 16I / 16J / 16K / 16L have since shipped on top and are all PRODUCTION VERIFIED + CLOSED — see the current-baseline note at the top of this file; the current next-planned work is Phase 16O.)
>
> **Phase 16E — Payment / Logistics Integration Hardening, PRODUCTION VERIFIED on the VPS + CLOSED (commit `36395f6`).** Phase 16E added the additive `apps.integration_hardening` app — **NO models, NO migration** (read-only readiness services) — plus a surgical hardening of `ShipmentViewSet.create()`. Deploy was a code rebuild + restart (no migrate needed; `makemigrations --check` reports no changes). **VPS validation proof:**
>
> ```bash
> docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run   # → No changes detected
> docker compose -f docker-compose.prod.yml exec backend python manage.py check                              # → 0 issues
> docker compose -f docker-compose.prod.yml exec backend python -m pytest tests/test_phase16e_payment_logistics.py --tb=no -q   # → [100%]
> curl -sS https://ai.nirogidhara.com/api/healthz/                                                            # → {"status":"ok","service":"nirogidhara-backend"}
> ```
>
> Director browser validation of `/operations/payment-logistics` passed (hardening mode; Razorpay blocked / PayU unavailable / Delhivery ready/mock; payment + shipment gates live-blocked; recent events visible; no live provider action triggered). Phase 16D (Uploaded Data Campaigns, `c0be74a`), Phase 16C (Director Daily Briefing + Team Roles, `687ef41`), and Phase 16B (Customer Lifecycle UI Backbone, `00c3295`) are earlier verified baselines. This file remains the valid VPS deployment runbook; [`../nd.md`](../nd.md) head-of-file wins for current project truth. The Phase 15 safety shell remains FROZEN at code commit `eefd8b3`. **Next planned work is Phase 16O (NOT started; requires a separate written Director directive); Phase 16N is implemented and pushed to origin/main (VPS verification pending).** No live WhatsApp / payment / courier / Vapi / AI-provider automation is approved.

---

## 0. Why this stack

| Need | Choice | Why |
| --- | --- | --- |
| HTTP + WebSockets in one process | Daphne ASGI | Phase 4A `/ws/audit/events/` requires Channels. Gunicorn alone would not work. |
| Background tasks + cron | Celery worker + beat | Phase 3C scheduler + Phase 5A retry/backoff/jitter on WhatsApp sends. |
| Database | Postgres 16 (container) | SQLite is dev only. Postgres handles concurrent webhooks (Razorpay / Delhivery / Vapi / Meta / WhatsApp). |
| Cache + broker + Channels layer | Redis 7 (container) | Three indices (0/1/2) used by Celery broker / Celery results / Channels group fan-out. |
| Static assets + reverse proxy | Nginx (container) with built Vite SPA | Single host port (18020) serves the SPA + proxies API/WS/admin to the backend container. |
| Host-port isolation | **18020 → 80** | Existing Postzyo / OpenClaw containers already use other host ports. 18020 is free. The host Nginx / Hostinger Traefik then proxies `ai.nirogidhara.com → 127.0.0.1:18020`. |

---

## 1. Prerequisites on the VPS

```bash
# Already present from Postzyo / OpenClaw — just verify.
docker --version          # >= 24
docker compose version    # v2 plugin
git --version             # any
```

If Docker is missing, install via Docker's official `get.docker.com`
script. **Do not** add this user to the `docker` group on a shared VPS
without confirming with the team — the existing setup may already use
`sudo docker`.

---

## 2. Initial setup (one-time)

```bash
# Clone into the production folder.
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/prarit0097/Nirogidhara-AI-Command-Center.git nirogidhara-command
cd /opt/nirogidhara-command

# Stamp the production env file from the example.
sudo cp .env.production.example .env.production
sudo chmod 600 .env.production
sudo nano .env.production
```

Inside `.env.production`, fill in at minimum:

- `DJANGO_SECRET_KEY` — `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `JWT_SIGNING_KEY` — different long random string
- `POSTGRES_PASSWORD` — strong; reflect the same string into `DATABASE_URL`
- `DJANGO_ALLOWED_HOSTS` — `ai.nirogidhara.com,localhost,127.0.0.1`
- `CORS_ALLOWED_ORIGINS` — `https://ai.nirogidhara.com`
- `CSRF_TRUSTED_ORIGINS` — `https://ai.nirogidhara.com`

Leave `WHATSAPP_PROVIDER=mock`, `RAZORPAY_MODE=mock`, `DELHIVERY_MODE=mock`,
`VAPI_MODE=mock`, `META_MODE=mock`, `AI_PROVIDER=disabled` until the
production credentials for each are confirmed by Prarit. Switching them
to live before keys are valid will fail closed (the adapters refuse to
load), but configuring them prematurely with the wrong values risks
sending a customer message during a smoke test — keep them mocked.

Phase 6I runtime live-gate note: Phase 6H Controlled Runtime Live Audit
Gate is **FULL PASS**, and Phase 6I adds simulation-only rehearsal rows
and APIs. Do not move live Meta/Razorpay/PayU/Delhivery/Vapi/OpenAI
secrets from `.env.production` into the database. Only `ENV:` / `VAULT:`
secret references are allowed, and runtime providers still read
env/config. The default global runtime kill switch must stay enabled. An
approved Phase 6I simulation is audit/readiness-only and does not send
WhatsApp, create Razorpay/PayU payments, create Delhivery shipments, place
Vapi calls, or call AI/provider side-effect endpoints.

> **Never commit `.env.production`.** It is gitignored at the repo root.

---

## 3. First boot

```bash
cd /opt/nirogidhara-command
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Compose builds two images (`nirogidhara/backend`, `nirogidhara/nginx`)
and starts six containers:

```
nirogidhara-db          postgres:16-alpine        internal-only
nirogidhara-redis       redis:7-alpine            internal-only
nirogidhara-backend     custom (Daphne :8000)     internal-only
nirogidhara-worker      custom (celery worker)    internal-only
nirogidhara-beat        custom (celery beat)      internal-only
nirogidhara-nginx       custom (vite + nginx)     127.0.0.1:18020 → 80
```

Wait ~60 seconds for the healthchecks, then verify:

```bash
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

Expected output: `db reachable at postgres:5432 → redis reachable at redis:6379 → migrate → collectstatic → daphne listening on 0.0.0.0:8000`.

---

## 4. Migrate + create superuser

The backend entrypoint already runs `migrate` on every restart, but the
first boot may not have a Django admin user. Create one:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py createsuperuser
```

After **every** `git pull` on the VPS, run the migration drift gate so
schema drift is caught at deploy time, not at the next dev session:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py makemigrations --check --dry-run

# Phase 6E — SaaS admin + integration settings foundation.
# Phase 6D org-aware write assignment is FULL PASS. These checks are
# read-only except ensure_default_organization, which is idempotent and
# keeps the single-tenant default org/branch present.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py ensure_default_organization --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_default_organization_coverage --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_scoped_api_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_write_path_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_saas_admin_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_org_integration_settings --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_controlled_runtime_routing_dry_run \
        --operation all --include-ai --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_runtime_live_audit_gate --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py preview_live_gate_decision \
        --operation whatsapp.send_text --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py preview_live_gate_decision \
        --operation razorpay.create_order --live-requested --json

# Phase 5E-Hotfix-2 — refresh demo Claim Vault rows to demo-v2 once.
# Real admin / doctor-approved claims are NEVER overwritten.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_default_claims --reset-demo

# Confirm no demo row is reported as weak.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py check_claim_vault_coverage

# Phase 5E-Smoke — controlled smoke harness. Defaults are SAFE
# (dry-run + mock-WhatsApp + mock-Vapi + OpenAI off). Run before
# flipping any automation flag. Refuses real Meta provider outright.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario all --json

# Phase 5E-Smoke-Fix-2 — adapter code change. Modern OpenAI Chat
# models (gpt-4o, gpt-5, o1, o3, …) reject 'max_tokens' and require
# 'max_completion_tokens'. The adapter now always uses the modern
# parameter. After this commit, rebuild + restart so the new adapter
# code lands in the backend image, then re-run the OpenAI smoke.

# Phase 5E-Smoke-Fix — when the requirements.txt changes (e.g. the
# openai SDK was added), rebuild the backend image so pip install
# picks up the new dep, then re-run the OpenAI provider smoke. The
# expected outcome is openaiSucceeded=true + providerPassed=true.
# A safeFailure=true result means the SDK / API key / AI_PROVIDER
# is wrong — fix it before flipping any automation flag.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production build backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d backend worker beat
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python -c "from openai import OpenAI; print('openai SDK OK')"
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test \
        --scenario ai-reply --language hinglish --use-openai --mock-whatsapp --dry-run --json

# Single-scenario examples (use these to debug a specific surface).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario claim-vault --json

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hinglish --mock-whatsapp --dry-run

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario rescue-discount --dry-run --json

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario vapi-handoff --mock-vapi --dry-run

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario reorder-day20 --dry-run
```

Expected output: `No changes detected`. If the `--check` reports
pending migrations, **stop the deploy** — a hand-rolled migration
drifted from the model definition. Generate the missing migration
locally with `python manage.py makemigrations`, push the new
`apps/<app>/migrations/0XXX_*.py` file, then re-pull on the VPS.

Phase 5E-Hotfix is the canonical example of this drift: Phase 5D / 5E
shipped with hand-rolled short index names (`whatsapp_wh_convers_h0_idx`,
`orders_disc_order_i_dol_idx`, …) that did not match Django's auto-suffix
form, and the VPS first-deploy after commit `8374863` reported pending
migrations until two `RenameIndex` migrations (`0004_rename_*`) were
generated locally and re-pulled.

Optional demo seed (do **not** run on a live customer DB):

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_demo_data --reset
```

Sync the canonical lifecycle WhatsApp templates so the `/whatsapp-templates`
page has working rows:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py sync_whatsapp_templates
```

---

## 5. Smoke tests

```bash
# Backend health (DRF)
curl -fsS http://127.0.0.1:18020/api/healthz/
# {"status":"ok","service":"nirogidhara-backend"}

# Frontend SPA root
curl -fsSI http://127.0.0.1:18020/

# WebSocket route exists (will 426 / 400 without a proper Upgrade header)
curl -fsSI http://127.0.0.1:18020/ws/audit/events/ | head -1
```

Browser tour (after the host Nginx / Traefik step in §6):

- `https://ai.nirogidhara.com/` — Command Center dashboard
- `https://ai.nirogidhara.com/whatsapp-inbox` — Phase 5B inbox (manual-only)
- `https://ai.nirogidhara.com/admin/` — Django admin (login with the superuser above)

### 5.1 Phase 5F-Gate — Limited Live Meta WhatsApp One-Number Test

Required gate before flipping any of the six automation flags. Run on
the VPS, against the production-target backend container:

```bash
# 1. Print the expected Meta webhook callback URL + verify-token presence.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_meta_one_number_test \
    --check-webhook-config --json

# 2. Add ONE approved test MSISDN to .env.production:
#    WHATSAPP_PROVIDER=meta_cloud
#    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
#    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS=+91XXXXXXXXXX
#    META_WA_ACCESS_TOKEN=<approved Meta WA Cloud token>
#    META_WA_PHONE_NUMBER_ID=<from WABA>
#    META_WA_BUSINESS_ACCOUNT_ID=<from WABA>
#    META_WA_VERIFY_TOKEN=<random secret you choose, paste same in Meta console>
#    META_WA_APP_SECRET=<from Meta App settings>
#    Restart the backend + worker containers after editing.

# 3. Verify-only — runs the precondition stack and exits without sending.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_meta_one_number_test \
    --to +91XXXXXXXXXX --template nrg_greeting_intro --verify-only --json

# 4. Real send (only after verify-only reports passed=true).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_meta_one_number_test \
    --to +91XXXXXXXXXX --template nrg_greeting_intro --send --json
```

Required outputs:

- `passed=true` for both `--verify-only` and `--send` runs.
- `auditEvents` for the `--send` run includes
  `whatsapp.meta_test.sent` and `nextAction=verify_inbound_webhook_callback`.
- The destination phone receives the locked greeting on WhatsApp.
- The Meta webhook posts a status (`sent`/`delivered`) back to
  `https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/`; check the
  audit ledger for `whatsapp.message.delivered`.

If anything is amber, the JSON output's `nextAction` field tells you
exactly what to fix (see RUNBOOK §"Phase 5F-Gate"). The harness refuses
outright if any of the six automation flags is on.

### 5.2 Phase 5F-Gate Hardening Hotfix — post-live-pass diagnostics

Once the one-number test has passed at least once, run the
**read-only inspector** after every deploy to confirm the limited
live state stays healthy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_live_test \
    --phone +918949879990 --json
```

Required output for a clean state:

- `nextAction == "gate_hardened_ready_for_limited_ai_auto_reply_plan"`
  (or `observe_status_events_optional` if Meta has not yet posted any
  status webhooks — soft signal only).
- `customer.found == true` and `whatsappConsent.consent_state == "granted"`.
- `messages.latestOutbound[0].status == "sent"` (or `delivered` / `read`).
- `messages.latestInbound[0]` present.
- `wabaSubscription.wabaSubscriptionActive == true`.
- `errors == []`.

Inspector is **strictly read-only** — never sends, never mutates the
DB, never prints `META_WA_ACCESS_TOKEN` / `META_WA_VERIFY_TOKEN` /
`META_WA_APP_SECRET`. Safe to re-run any time. If `nextAction ==
"subscribe_waba_to_app_webhooks"`, the WABA's webhook subscription has
fallen out — re-run the curl `POST /{WABA_ID}/subscribed_apps` +
override-callback fix from §5.1.

Re-run the harness's `--check-webhook-config --json` whenever the
inspector flags `subscribe_waba_to_app_webhooks` — the new diagnostics
block surfaces `wabaSubscriptionActive` + `wabaSubscribedAppCount`
without printing tokens.

### 5.3 Phase 5F-Gate Controlled AI Auto-Reply Test

After the inspector reports a clean state, run the controlled AI
auto-reply test against the **single allowed test number** without
flipping the global `WHATSAPP_AI_AUTO_REPLY_ENABLED` env. The flag
must stay `false` for this test to run — the harness is the only
sanctioned path that may produce a real AI reply during the gate
phase.

```bash
# 1. Dry-run — every precondition, no LLM call, no DB inbound row.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste mujhe weight loss product ke baare me bataye" \
    --dry-run --json

# 2. Live `--send` — drives the orchestrator with force_auto_reply=True
# for ONE call only. Refused on any amber gate.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste mujhe weight loss product ke baare me bataye" \
    --send --json
```

Required outputs for a clean live `--send` run:

- `passed == true`
- `replySent == true`
- `outboundMessageId` and `providerMessageId` populated
- `auditEvents` includes `whatsapp.ai.controlled_test.sent` and
  `whatsapp.ai.controlled_test.completed`
- `nextAction == "live_ai_reply_sent_verify_phone"`
- The test phone receives the AI reply on WhatsApp

**Rollback / safety check.** If anything looks wrong, immediately
verify automation flags stay off:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend printenv | grep -E \
    "WHATSAPP_AI_AUTO_REPLY_ENABLED|WHATSAPP_CALL_HANDOFF_ENABLED|\
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED|WHATSAPP_RESCUE_DISCOUNT_ENABLED|\
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED|WHATSAPP_REORDER_DAY20_ENABLED|\
WHATSAPP_LIVE_META_LIMITED_TEST_MODE|WHATSAPP_PROVIDER"
```

Expected safe state:

```
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
WHATSAPP_PROVIDER=meta_cloud
WHATSAPP_AI_AUTO_REPLY_ENABLED=false
WHATSAPP_CALL_HANDOFF_ENABLED=false
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false
WHATSAPP_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_REORDER_DAY20_ENABLED=false
```

If `WHATSAPP_AI_AUTO_REPLY_ENABLED` is `true`, **stop and revert it**.
Phase 5F (broadcast campaigns) remains LOCKED until a 24-hour soak
under the controlled harness has been observed cleanly.

### 5.4 Phase 5F-Gate Claim Vault Grounding Fix — re-run after deploy

After the Claim Vault Grounding Fix lands on the VPS, re-run the
dry-run + live-send with an explicit weight-management prompt and
require the **new grounding diagnostics** to come back clean before
proceeding:

```bash
# Confirm the Claim Vault still has the Weight Management row.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py check_claim_vault_coverage --json

# Inspector check (read-only).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_live_test \
    --phone +918949879990 --json

# Dry-run with the explicit weight-management prompt.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --dry-run --json
```

Required JSON fields on the dry-run:

- `passed == true`
- `nextAction == "dry_run_passed_ready_for_send"`
- `groundingStatus.claimProductFound == true`
- `groundingStatus.approvedClaimCount >= 1`
- `groundingStatus.promptGroundingInjected == true`

```bash
# Live --send (only after dry-run passes).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Post-live audit tail to confirm the grounding context is in the
# audit ledger (no tokens, last-4 phone only).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.ai').order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

If the live `--send` returns `nextAction=blocked_for_unapproved_claim`
again with `groundingStatus.approvedClaimCount=0`, the Claim Vault
seed has not been re-applied — re-run `seed_default_claims --reset-demo`
or restore the doctor-approved row before retrying.

### 5.5 Phase 5F-Gate Controlled Reply Confidence Fix — re-run

After the Confidence Fix lands on the VPS, re-run the live `--send`
and verify the LLM now chooses `action=send_reply` with
`confidence ≥ confidenceThreshold` and the reply literally carries
both an approved Claim Vault phrase AND the ₹3000/30-capsules/₹499
business facts.

```bash
# Same dry-run from §5.4 — must still pass.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --dry-run --json

# Live --send. Required JSON:
#   passed=true
#   replySent=true
#   action="send_reply"
#   claimVaultUsed=true
#   confidence>=confidenceThreshold (0.75 default)
#   replyPreview literally contains at least one approved phrase
#     (e.g. "Supports healthy metabolism") AND ₹3000 / 30 capsules
#     when the customer asked about price/quantity
#   nextAction="live_ai_reply_sent_verify_phone"
#   sendEligibilitySummary="Live AI reply sent ..."
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Audit tail — verify the new split counts (claim_row_count vs
# approved_claim_count vs disallowed_phrase_count) appear cleanly.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.ai').order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

If the LLM still returns `action=handoff` on a grounded inquiry,
inspect the audit row's `confidence`, `approved_claim_count`, and
`category` fields and confirm the prompt rebuild reached the
backend container (`docker compose ... build --no-cache backend`).
The fix is in the prompt — not in lowering the threshold. Do **not**
edit `WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD` to compensate.

### 5.6 Phase 5F-Gate Deterministic Grounded Reply Builder — re-run

After the Deterministic Grounded Reply Builder lands on the VPS,
the controlled-test command's `--send` no longer depends on the
LLM choosing `action=send_reply`. If the LLM blocks with a soft
non-safety reason (`claim_vault_not_used` / `low_confidence` /
`ai_handoff_requested` / `auto_reply_disabled`) AND the backend has
valid grounding AND the inbound is a normal product-info inquiry,
the command **falls back** to a deterministic Hinglish reply built
from `Claim.approved` + locked business facts and dispatches it
through the same `services.send_freeform_text_message` path.

```bash
# Inspector first.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_live_test \
    --phone +918949879990 --json

# Dry-run.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --dry-run --json

# Live --send. Two outcomes count as success:
#   (a) LLM honoured the prompt → finalReplySource="llm",
#       deterministicFallbackUsed=false.
#   (b) LLM still blocked but backend fallback dispatched →
#       finalReplySource="deterministic_grounded_builder",
#       deterministicFallbackUsed=true,
#       fallbackReason ∈ {"claim_vault_not_used", "low_confidence",
#                         "ai_handoff_requested",
#                         "auto_reply_disabled"}.
# Either way: passed=true, replySent=true, claimVaultUsed=true,
# finalReplyValidation.passed=true,
# finalReplyValidation.containsApprovedClaim=true.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "Namaste. Mujhe Nirogidhara ke weight management product ke baare me approved safe jaankari chahiye. Price, capsule quantity aur use guidance bata dijiye." \
    --send --json

# Audit tail — confirm whatsapp.ai.deterministic_grounded_reply_used
# fires (path b) or whatsapp.ai.controlled_test.sent fires alone
# (path a). No tokens / secrets in payloads.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__startswith='whatsapp.ai').order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

If `deterministicFallbackUsed=true` and the test phone receives the
deterministic reply, the gate is **passing safely** — the LLM's
inability to self-report `claimVaultUsed=true` no longer blocks the
controlled live test. Webhook-driven production runs still flow
through the orchestrator's strict path; this fallback is
controlled-test-only.

### 5.7 Phase 5F-Gate Objection & Handoff Reason Refinement — re-run

After this phase lands on the VPS, re-run the **scenario matrix
subset** to confirm the typed reasons now appear correctly:

```bash
# Scenario A — discount objection.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "weight management product accha hai lekin thoda mehenga lag raha hai. Kuch kam ho sakta hai?" \
    --send --json
# Expected:
#   passed=true, replySent=true,
#   detectedIntent="discount_objection",
#   objectionDetected=true, objectionType ∈ {discount, price},
#   finalReplySource="deterministic_objection_reply",
#   replyPolicy.upfrontDiscountOffered=false,
#   replyPolicy.discountMutationCreated=false,
#   replyPolicy.businessMutationCreated=false,
#   replyPreview embeds an approved Claim Vault phrase + ₹3000 / 30 capsules.

# Scenario B — human call request.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "AI se baat nahi karni, mujhe call karwa do" \
    --send --json
# Expected:
#   passed=false, replySent=false, replyBlocked=true,
#   detectedIntent="human_request", humanRequestDetected=true,
#   blockedReason="human_advisor_requested",
#   handoffReason="human_advisor_requested",
#   nextAction="human_handoff_requested",
#   finalReplySource="blocked_handoff", safetyBlocked=false.
#   The whatsapp.ai.handoff_required audit row payload reason MUST
#   be "human_advisor_requested" — NOT "claim_vault_not_used".

# Scenario C — side-effect complaint.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "medicine khane ke baad ulta asar ho gaya, vomiting bhi hui" \
    --send --json
# Expected: passed=false, safetyBlocked=true,
#   nextAction="blocked_for_medical_safety",
#   detectedIntent="unsafe".

# Scenario D — legal/refund threat.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_auto_reply_test \
    --phone +918949879990 \
    --message "consumer forum me complaint karunga, refund chahiye" \
    --send --json
# Expected: passed=false, replyBlocked=true, no sales reply,
#   detectedIntent="unsafe" (legal vocabulary disqualifies).

# Scenario E — mutation safety check (read-only Python shell).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
print('DiscountOfferLog:', DiscountOfferLog.objects.count())
print('Order:', Order.objects.count())
print('Payment:', Payment.objects.count())
print('Shipment:', Shipment.objects.count())
"
# Expected: counts unchanged from pre-test snapshot — the controlled
# objection / human-request paths NEVER mutate business state.
```

Then tail the audit ledger and confirm the new typed reasons + the
four new audit kinds appear cleanly:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
for e in AuditEvent.objects.filter(kind__in=[
    'whatsapp.ai.objection_detected',
    'whatsapp.ai.objection_reply_used',
    'whatsapp.ai.objection_reply_blocked',
    'whatsapp.ai.human_request_detected',
    'whatsapp.ai.handoff_required',
]).order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.tone)
    print(e.text)
    print(e.payload)
    print('-' * 100)
"
```

Confirm the `whatsapp.ai.handoff_required` row from Scenario B
carries `payload['reason'] == 'human_advisor_requested'`. **Do not
proceed to flag flips if any row carries `reason=claim_vault_not_used`
on a human-request inbound.**

### 5.8 Phase 5F-Gate Internal Allowed-Number Cohort Tooling — expand to 2–3 staff numbers

After the one-number scenario matrix passes cleanly, expand the
controlled live test to a tiny internal cohort of 2–3 staff numbers
without unlocking any broad automation.

```bash
# 1. Edit .env.production to ADD staff numbers (start with 2–3 only).
#    KEEP every automation flag default OFF.
#    DO NOT paste real phone numbers in public docs / Slack / GitHub.

# 2. Recreate backend/worker/beat/nginx so the new env is read.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never backend worker beat nginx

# 3. Inspect cohort readiness (phones masked to last-4 by default).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_internal_cohort --json

# 4. Prepare each new number (refuses non-allow-list phones).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py prepare_whatsapp_internal_test_number \
    --phone +91XXXXXXXXXX \
    --name "Internal Staff Name" \
    --source internal_cohort_test \
    --json

# 5. (Optional) Cohort dry-run readiness across all five scenarios.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_whatsapp_internal_cohort_dry_run --json

# 6. Run the 7-scenario matrix per number (use the messages from
#    §5.7 and §5.4–5.6). Do this one number at a time and confirm
#    the WhatsApp phone receives the correct reply / no reply per
#    scenario before moving to the next number.

# 7. Audit + mutation safety check.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py shell -c "
from apps.audit.models import AuditEvent
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
print('DiscountOfferLog:', DiscountOfferLog.objects.count())
print('Order:', Order.objects.count())
print('Payment:', Payment.objects.count())
print('Shipment:', Shipment.objects.count())
print('---')
for e in AuditEvent.objects.filter(kind__in=[
    'whatsapp.internal_cohort.number_prepared',
    'whatsapp.ai.controlled_test.sent',
    'whatsapp.ai.controlled_test.blocked',
    'whatsapp.ai.handoff_required',
]).order_by('-occurred_at')[:30]:
    print(e.occurred_at, '|', e.kind, '|', e.payload)
"
```

**Hard constraints during cohort expansion:**

- `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` stays.
- `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` stays.
- `WHATSAPP_CALL_HANDOFF_ENABLED=false` stays.
- `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false` stays.
- `WHATSAPP_RESCUE_DISCOUNT_ENABLED=false` stays.
- `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false` stays.
- `WHATSAPP_REORDER_DAY20_ENABLED=false` stays.
- Cohort starts with 2–3 numbers only. Do NOT add customer
  numbers; this is for internal staff testing only.
- Full phone numbers NEVER committed to docs / git / audit
  payloads. The audit row carries `phone_suffix` only.

---

## 6. DNS + TLS for `ai.nirogidhara.com`

### 6.1 DNS

Add an A record at the registrar:

```
Type:  A
Host:  ai
Value: <Hostinger VPS public IP>     # e.g. 187.127.132.106
TTL:   300
```

Wait for propagation (`dig +short ai.nirogidhara.com`) before requesting
a TLS cert.

### 6.2 Option A — Host-level Nginx + Certbot (recommended)

This is the cleanest path on a Hostinger VPS that already runs other
Docker projects. Each project keeps its own internal Nginx and exposes
one host port; the host Nginx terminates TLS and routes by domain.

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

sudo tee /etc/nginx/sites-available/ai.nirogidhara.com >/dev/null <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name ai.nirogidhara.com;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:18020;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/ai.nirogidhara.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Auto-issues + auto-renews. Pick redirect-to-HTTPS when prompted.
sudo certbot --nginx -d ai.nirogidhara.com
```

After certbot completes, browse to `https://ai.nirogidhara.com/`.

### 6.3 Option B — Hostinger Traefik / Docker Manager

If the VPS is managed entirely through Hostinger's Docker UI, point the
`ai.nirogidhara.com` route at this project's container port `80` (the
inner Nginx). Hostinger's Traefik handles TLS via Let's Encrypt
automatically. The container's host port (`18020`) is unchanged so it
stays compatible with the host-Nginx fallback above.

> Pick **one** of A or B — running both at the same time leaks the same
> upstream behind two domains and confuses CSRF / consent telemetry.

---

## 7. Daily operations

### 7.1 Logs

```bash
cd /opt/nirogidhara-command
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f beat
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f nginx
```

### 7.2 Restart / stop

```bash
# Restart everything (keeps volumes + data).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production restart

# Stop the stack (keeps volumes + data).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production down

# Stop + delete volumes (DANGER — wipes DB + Redis state).
# Only on explicit user confirmation.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production down -v
```

### 7.3 Update deployment

```bash
cd /opt/nirogidhara-command
sudo git pull origin main

# Rebuild + restart. `--pull never` keeps the local image cache in
# place; without it Compose tries to pull `nirogidhara/backend:latest`
# from a registry that does not exist and the deploy stalls.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never

# Run migrations explicitly (the entrypoint also does this, but an
# explicit run is easier to scan for warnings).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    run --rm --entrypoint sh backend -lc "python manage.py migrate --no-input"
```

### 7.4 Backups (recommended before going live)

```bash
# Postgres dump → host filesystem.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec -T postgres pg_dump -U nirogidhara nirogidhara | gzip > \
    /opt/nirogidhara-command/backups/db-$(date +%F).sql.gz

# Static + media (rarely needed but cheap to copy).
sudo docker run --rm \
    -v nirogidhara_static_volume:/from \
    -v /opt/nirogidhara-command/backups:/to alpine \
    sh -c 'cd /from && tar czf /to/static-$(date +%F).tgz .'
```

Schedule via cron once the customer DB is live.

---

## 8. Resource safety on a shared VPS

Postzyo + OpenClaw already run on this host. Do **not** prune Docker
state globally without checking with the user.

```bash
# Safe — read-only.
docker stats
sudo docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker system df
docker network ls
docker volume ls | grep nirogidhara

# DANGER — deletes images, networks, volumes for ALL stacks.
# docker system prune -a --volumes      ← only on explicit user approval.
```

Tuning knobs that are safe to dial up after watching `docker stats` for
a day:

- `worker.command` → bump `--concurrency=1` to 2 once memory is stable.
- `nirogidhara-redis` → keep `--appendonly yes`; rotate `appendonly.aof`
  via Redis if it grows past a few hundred MB.
- Postgres → 16-alpine ships sensible defaults; only tune
  `max_connections` if observed contention happens.

---

## 8.5 Troubleshooting — duplicate Postgres index on first migrate

> **Status (2026-05-04):** the underlying drift is now fixed in-tree by
> a hotfix to `apps/calls/migrations/0002_phase2d_vapi_fields.py`. The
> manual recovery procedure below is preserved for older deploys that
> applied 0002 before the hotfix landed and still carry the legacy
> index name.

### 8.5.1 Root cause

`apps/calls/migrations/0001_initial.py` creates `CallTranscriptLine`
with FK `call → ActiveCall` and Django auto-names its FK index
`calls_calltranscriptline_call_id_5bc33dc3` (the hash is derived from
`(table, column="call_id")`). `0002_phase2d_vapi_fields.py` then runs
`RenameField call → active_call`. Depending on Django version + Postgres
backend behaviour, the **column** is renamed but the auto-named
**index** is left in place attached to the new `active_call_id` column.
The very next `AddField call → Call` then asks Django to create the FK
index for the new `call_id` column — same column name, same hash, same
auto-name — and Postgres rejects with:

```
django.db.utils.ProgrammingError:
    relation "calls_calltranscriptline_call_id_5bc33dc3" already exists
django.db.utils.ProgrammingError:
    relation "calls_calltranscriptline_call_id_5bc33dc3_like" already exists
```

### 8.5.2 In-tree fix (current)

`0002_phase2d_vapi_fields.py` now contains an idempotent Postgres-only
`RunPython` step inserted between `RenameField call → active_call`
(plus the matching `AlterField active_call`) and `AddField call → Call`.
The step issues:

```sql
DROP INDEX IF EXISTS "calls_calltranscriptline_call_id_5bc33dc3";
DROP INDEX IF EXISTS "calls_calltranscriptline_call_id_5bc33dc3_like";
```

Properties of this fix:

- **Postgres-only** — `vendor != "postgresql"` short-circuits the step,
  so SQLite-based local tests stay green.
- **Idempotent on a fresh Postgres DB** — `IF EXISTS` makes the drop a
  no-op when the legacy index has already been removed by an earlier
  rename. After the drop, `AddField call → Call` is free to create its
  own `calls_calltranscriptline_call_id_5bc33dc3` index without
  collision.
- **No-op on production where 0002 has already been applied** — Django
  never re-runs an applied migration. The patch only changes how the
  migration behaves on first apply; existing deploys are not touched.
- **Reverse intentionally noop** — the surrounding `AddField` /
  `RenameField` reverse paths already restore the original index, so
  re-creating it inside the hotfix step would conflict.

> Verification: `python manage.py makemigrations --check --dry-run`
> reports `No changes detected`, and `python manage.py showmigrations
> calls` keeps the existing applied state on already-deployed
> production DBs.

### 8.5.3 Manual recovery — only for older deploys still hitting the duplicate-index error

This block is the **legacy** workaround for VPS instances that applied
0002 before the in-tree hotfix and now have a half-applied schema
(e.g. on a fresh test DB, after a partial migration retry). After
pulling the hotfix, a fresh Postgres should not need this block — but
keep it for emergency recovery.

```bash
cd /opt/nirogidhara-command

# 1) Stop everything that talks to the schema. Keep only Postgres + Redis up.
docker compose -f docker-compose.prod.yml --env-file .env.production stop \
    backend worker beat nginx
docker compose -f docker-compose.prod.yml --env-file .env.production up -d \
    postgres redis

# 2) Drop the two clashing indexes (idempotent — safe to re-run).
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c \
    'DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3; DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3_like;'

# 3) Re-run migrate via a one-shot backend container (entrypoint runs
#    migrate automatically, so we override it to a plain shell here to
#    avoid double-collectstatic in the recovery path).
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
    --entrypoint sh backend -lc "python manage.py migrate --no-input"

# 4) Bring the rest of the stack back up. `--pull never` keeps the local
#    image in place (the recovery already proved it works).
docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never
```

If multiple FK index variants exist (e.g. after several failed retries),
sweep all of them in one shot:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c "DO \$\$ DECLARE r RECORD; BEGIN FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'calls_calltranscriptline_call_id_%' LOOP EXECUTE format('DROP INDEX IF EXISTS %I', r.indexname); END LOOP; END \$\$;"
```

After the sweep:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
curl -fsS http://127.0.0.1:18020/api/healthz/
```

The backend should boot cleanly and `migrate` should be a no-op.

## 8.1 Phase 5F-Gate customer pilot readiness post-deploy

This phase prepares a tiny approved customer pilot only. It does not
enable broad rollout, does not send WhatsApp messages, and does not
mutate Order / Payment / Shipment / Discount rows. Keep:

```bash
WHATSAPP_AI_AUTO_REPLY_ENABLED=false
WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true
WHATSAPP_CALL_HANDOFF_ENABLED=false
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false
WHATSAPP_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false
WHATSAPP_REORDER_DAY20_ENABLED=false
```

After deploy:

```bash
cd /opt/nirogidhara-command

docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate --no-input

docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py makemigrations --check --dry-run

docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_whatsapp_customer_pilot --json

curl -fsS -H "Authorization: Bearer <admin-jwt>" \
    "https://ai.nirogidhara.com/api/v1/whatsapp/monitoring/pilot/?hours=2" | jq
```

Use `prepare_whatsapp_customer_pilot_member --phone +91XXXXXXXXXX
--name "Customer Name" --source approved_customer_pilot --json` only
after explicit customer consent is documented. Missing consent leaves the
pilot member pending. The dashboard section at `/whatsapp-monitoring`
must show masked phones only and no send/enable controls. The prior
4-hour soak was accelerated, not full-duration, so this customer pilot
still needs conservative monitoring before any flag flip.

## 8.6 Phase 6K-B verification — Razorpay test-mode execution artefact

Phase 6K-B is the only real Razorpay write the platform has ever made:
`execution_id=pex_8f309650e9644cfaae4418f9` →
`provider_object_id=order_Sks3KPf0vntKhf`, `amount=100 paise INR`, no
payment link, no capture, no notification, no business mutation,
`rollback_status=completed`. After every deploy, re-verify the artefact
without touching Razorpay:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_test_execution_audit \
    --execution-id pex_8f309650e9644cfaae4418f9 --json
```

Expected: `passed=true`, every Phase 6K invariant green,
`business_mutation_was_made=false`, `rollback_status=completed`, no leaked
secret in any linked AuditEvent. **`PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED`
must remain `false` on the VPS.** Do not re-run a Phase 6K execution
without explicit Director sign-off + a fresh approved Phase 6J plan.

## 8.7 Phase 6M production posture — Razorpay webhook handler dormant

Phase 6M ships `POST /api/webhooks/razorpay/test/` but keeps it
**dormant by default** in production. The production webhook secret
(`RAZORPAY_WEBHOOK_SECRET`) is consumed only by the Phase 2B
`/api/webhooks/razorpay/` endpoint. The Phase 6M test-mode handler uses
a SEPARATE `RAZORPAY_WEBHOOK_TEST_SECRET` env value that is itself
empty / undefined in `.env.production`.

Required posture in `.env.production`:

```dotenv
# Phase 6M Razorpay webhook handler — keep all four FALSE on production
RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false
RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED=false
RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED=false
RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_webhook_handler_readiness --json
```

Expected: `razorpay_webhook_handler_dormant=true`,
`business_mutation_was_made=false`, `customer_notification_sent=false`,
`raw_secret_exposed=false`, `full_pii_exposed=false`. Do not flip any
of the four `RAZORPAY_WEBHOOK_*` env flags without a written Phase 6N
sandbox plan signed off by the Director.

## 8.8 Phase 6M-0 production posture — MCP Gateway dormant

Phase 6M-0 ships the dormant MCP Gateway scaffolding. Required posture in
`.env.production`:

```dotenv
# Phase 6M-0 MCP Gateway — keep all four FALSE on production
MCP_ENABLED=false
MCP_READ_ONLY_MODE=true
MCP_WRITE_TOOLS_ENABLED=false
MCP_PROVIDER_TOOLS_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_mcp_gateway_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_mcp_tool_invocations --hours 24 --json
```

Expected: `mcp_enabled=false`, `mcp_read_only_mode=true`,
`forbidden_tool_count=13`, **zero** invocations in the last 24 hours.
Re-run after every Docker recreate so the env is read fresh from
`.env.production`.

## 8.87 Phase 7B production posture - Razorpay Controlled Pilot Execution Gate (gate-only, CLI-only review state changes)

Phase 7B is **gate-only** and does not approve live execution.
The service writes to `RazorpayControlledPilotExecutionGate` +
`RazorpayControlledPilotGateDryRunRecord` +
`RazorpayControlledPilotGateRollbackDryRunRecord` only - it NEVER
calls Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends or queues
a WhatsApp message, NEVER creates a shipment / AWB, NEVER mutates real
`Order` / `Payment` / `Customer` / `Lead`. Phase 7B does **not**
validate the live `RAZORPAY_KEY_ID`; provider-execution key validation
is deferred to Phase 7C+. **There is no API endpoint or frontend
button that dispatches Phase 7B review state changes, and there is no
`execute_*` command anywhere in the Phase 7B surface.**

Required posture in `.env.production`:

```dotenv
# Phase 7B Controlled Pilot Execution Gate - keep false on production.
PHASE7_CONTROLLED_PILOT_GATE_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_controlled_pilot_gate_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_controlled_pilot_gates --limit 25 --json
```

Expected: `phase=7B`, `status=controlled_pilot_gate_only`,
`phase7ControlledPilotGateEnabled=false`,
`phase7BMakesProviderCall=false`,
`phase7BSendsOrQueuesWhatsApp=false`,
`phase7BCreatesShipmentOrAwb=false`,
`phase7BMutatesBusinessRow=false`, `phase7BCallsRazorpay=false`,
`phase7BValidatesLiveRazorpayKey=false`,
`frontendCanExecute=false`, `apiEndpointCanExecute=false`,
`apiEndpointCanApprove=false`, `executionPath="cli_only_review"`,
`maxPilotOrders=1`, `maxSafeAmountPaise=100`. Counters
(`controlledPilotExecutionAllowedInPhase7B`, `providerCallAttempted`,
`realOrderMutationWasMade`, `realPaymentMutationWasMade`,
`shipmentCreated`, `awbCreated`, `whatsAppMessageCreated`,
`whatsAppMessageQueued`, `customerNotificationSent`,
`metaCloudCallAttempted`, `delhiveryCallAttempted`,
`razorpayCallAttempted`) all zero. **Phase 7C / live execution is
not approved.**

## 8.85 Phase 6T production posture - Razorpay final Phase 6 audit lock (audit-lock-only, CLI-only review state changes)

Phase 6T is **audit-lock-only** and does not approve live execution.
Keep the safe default off unless Prarit explicitly authorizes a CLI
review window:

```bash
RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=false
```

Production-safe verification:

```bash
cd /opt/nirogidhara-command
docker compose -f docker-compose.prod.yml exec backend python manage.py inspect_razorpay_phase6_final_audit_lock_readiness --json
docker compose -f docker-compose.prod.yml exec backend python manage.py inspect_razorpay_phase6_final_audit_locks --json
docker compose -f docker-compose.prod.yml exec backend python manage.py check
```

Expected: `phase=6T`, `status=final_audit_lock_only`,
`futureControlledPilotAllowedByPhase6T=false`,
`controlledPilotExecutionAllowedInPhase6T=false`,
`safeToStartPhase7A=false`, no provider call counters, no WhatsApp
send/queue counters, no shipment/AWB counters, no real business
mutation counters. Phase 6T never calls Meta Cloud / Delhivery /
Razorpay and never creates live pilot execution controls.

## 8.84 Phase 6S production posture — Razorpay limited internal dispatch pilot plan (planning-only, CLI-only review state changes)

Phase 6S is **planning-only** with CLI-only review state changes.
The service writes to `RazorpayPaymentDispatchPilotPlan` only — it
NEVER executes a pilot, NEVER sends a WhatsApp message, NEVER calls
Meta Cloud / Delhivery / Razorpay, NEVER creates a shipment / AWB,
NEVER mutates real `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer` / `Lead` / `WhatsAppMessage` rows.
**There is no API endpoint or frontend button that dispatches Phase
6S review state changes.**

Required posture in `.env.production`:

```dotenv
# Phase 6S Razorpay Limited Internal Dispatch Pilot Plan — keep false on production.
RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_payment_dispatch_pilot_plan_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_payment_dispatch_pilot_plans --json
```

Expected: `phase=6S`, `status=pilot_planning_only`,
`razorpayPaymentDispatchPilotPlanEnabled=false`,
`pilotExecutionEnabled=false`, `businessMutationEnabled=false`,
`customerNotificationEnabled=false`,
`providerCallAttempted=false`, `frontendCanExecute=false`,
`apiEndpointCanExecute=false`, `apiEndpointCanApprove=false`,
`executionPath="cli_only"`, `maxPilotOrders=1`,
`maxSafeAmountPaise=100`. Counters
(`pilotExecutionAllowedInPhase6S`, `realOrderMutationWasMade`,
`realPaymentMutationWasMade`, `shipmentMutationWasMade`,
`shipmentCreated`, `awbCreated`, `whatsAppMessageCreated`,
`whatsAppMessageQueued`, `customerNotificationSent`,
`metaCloudCallAttempted`, `delhiveryCallAttempted`,
`providerCallAttempted`) all zero on plan summaries. Do **not** flip
`RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED` to `true` on production
without a written Director sign-off — and even then, review state
changes remain CLI-only and only write to the Phase 6S pilot plan
review table.

## 8.83 Phase 6R production posture — Razorpay payment → WhatsApp / courier dispatch readiness (audit-only readiness contract, CLI-only review state changes)

Phase 6R is **audit-only readiness contract** with CLI-only review
state changes. The service writes to
`RazorpayPaymentDispatchReadinessGate` only — it NEVER sends a
WhatsApp message, NEVER calls Meta Cloud / Delhivery, NEVER creates a
shipment / AWB, NEVER mutates real `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer` / `Lead` / `WhatsAppMessage` rows,
NEVER calls Razorpay. **There is no API endpoint or frontend button
that dispatches Phase 6R review state changes.**

Required posture in `.env.production`:

```dotenv
# Phase 6R Razorpay Payment → WhatsApp / Courier Dispatch Readiness — keep false on production.
RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_payment_dispatch_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_payment_dispatch_readiness_gates --json
```

Expected: `phase=6R`, `status=dispatch_readiness_only`,
`razorpayPaymentDispatchReadinessEnabled=false`,
`businessMutationEnabled=false`,
`customerNotificationEnabled=false`,
`providerCallAttempted=false`, `frontendCanExecute=false`,
`apiEndpointCanExecute=false`, `apiEndpointCanApprove=false`,
`executionPath="cli_only"`. Counters
(`realOrderMutationWasMade`, `realPaymentMutationWasMade`,
`shipmentMutationWasMade`, `shipmentCreated`,
`whatsAppMessageCreated`, `whatsAppMessageQueued`,
`customerNotificationSent`, `metaCloudCallAttempted`,
`delhiveryCallAttempted`, `providerCallAttempted`) all zero on gate
summaries. Do **not** flip
`RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED` to `true` on production
without a written Director sign-off — and even then, review state
changes remain CLI-only and only write to the Phase 6R readiness
review table.

## 8.82 Phase 6Q production posture — Razorpay payment → order workflow safety gate (audit-gate-only, CLI-only review state changes)

Phase 6Q is **audit-gate-only** with CLI-only review state changes.
The service writes to `RazorpayPaymentOrderWorkflowGate` only — it
NEVER mutates real `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer` / `Lead` / `WhatsAppMessage` rows.
**There is no API endpoint or frontend button that dispatches Phase
6Q gate state changes.**

Required posture in `.env.production`:

```dotenv
# Phase 6Q Razorpay Payment → Order Workflow Safety Gate — keep false on production.
RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_payment_order_workflow_gate_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_payment_order_workflow_gates --json
```

Expected: `phase=6Q`, `status=audit_gate_only`,
`razorpayPaymentOrderWorkflowGateEnabled=false`,
`businessMutationEnabled=false`,
`customerNotificationEnabled=false`,
`providerCallAttempted=false`, `frontendCanExecute=false`,
`apiEndpointCanExecute=false`, `apiEndpointCanApprove=false`,
`executionPath="cli_only"`. Counters
(`realOrderMutationWasMade`, `realPaymentMutationWasMade`,
`shipmentMutationWasMade`, `discountMutationWasMade`,
`customerNotificationSent`, `providerCallAttempted`) all zero on
gate summaries. Do **not** flip
`RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED` to `true` on
production without a written Director sign-off — and even then,
gate state changes remain CLI-only and only mutate the Phase 6Q
gate review table.

## 8.83 Phase 6P production posture — Razorpay sandbox paid-status mutation test (sandbox-ledger-only, CLI-only)

Phase 6P is **sandbox-ledger-only and CLI-only**. There is no API
endpoint or frontend button that dispatches Phase 6P mutation. The
service writes to `RazorpaySandboxPaidStatusLedger` +
`RazorpaySandboxPaidStatusMutationAttempt` only — it NEVER mutates
real `Order` / `Payment` / `Shipment` / `DiscountOfferLog` /
`Customer` / `Lead` / `WhatsAppMessage` rows.

Required posture in `.env.production`:

```dotenv
# Phase 6P Razorpay Sandbox Paid-Status Mutation Test — keep false on production.
RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_sandbox_paid_status_mutation_readiness --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_sandbox_paid_status_mutation_attempts --json
```

Expected: `phase=6P`, `status=sandbox_ledger_only`,
`razorpaySandboxPaidStatusMutationEnabled=false`,
`businessMutationEnabled=false`,
`customerNotificationEnabled=false`,
`providerCallAttempted=false`, `frontendCanExecute=false`,
`apiEndpointCanExecute=false`, `executionPath="cli_only"`. Counters
(`businessMutationWasMade`, `realOrderMutationWasMade`,
`realPaymentMutationWasMade`, `customerNotificationSent`,
`providerCallAttempted`) all zero on both attempts and ledger
summaries. Do **not** flip
`RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED` to `true` on
production without a written Director sign-off — and even then,
execute additionally requires `--confirm-sandbox-paid-status-mutation`
+ non-empty `--director-signoff`, and only mutates the Phase 6P
ledger.

## 8.84 Phase 6O production posture — Razorpay sandbox status mapping + manual review (sandbox-review-only)

Phase 6O is **sandbox-review-only**. It maps verified Phase 6M
`RazorpayWebhookEvent` rows into proposed sandbox status reviews.
**It never mutates `Order` / `Payment` / `Shipment` /
`DiscountOfferLog` / `Customer`, never sends a customer notification,
never calls Razorpay, never flips an env flag.** Approving a review
flips its `status` to `approved_for_future_phase6p` only.

Required posture in `.env.production`:

```dotenv
# Phase 6O Razorpay Sandbox Status Mapping + Manual Review — keep false on production
RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=false
```

Verify dormant state after every deploy:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_sandbox_status_mapping_readiness --json
```

Expected: `phase=6O`, `status=sandbox_review_only`,
`razorpaySandboxStatusMappingEnabled=false`,
`businessMutationEnabled=false`,
`customerNotificationEnabled=false`,
`providerCallAttempted=false`,
`reviewCounts.businessMutationWasMade=0`,
`reviewCounts.customerNotificationSent=0`,
`reviewCounts.providerCallAttempted=0`. Do **not** flip
`RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED` to `true` on production
without a written Director sign-off — and even then, the flag only
unlocks review preparation; mutation paths stay closed (Phase 6P
implementation will own those behind a SEPARATE env flag).

## 8.85 Phase 6N production posture — Razorpay business-mutation sandbox plan (planning-only)

Phase 6N is **planning + readiness only**. Verify the read-only
inspectors after every deploy; they never call Razorpay, never mutate
business records, never send a customer notification, and never flip
an env flag.

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_business_mutation_sandbox_plan --json
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py inspect_razorpay_business_mutation_sandbox_readiness --json
```

Expected: `phase=6N`, `status=planning_only`,
`businessMutationEnabled=false`, `customerNotificationEnabled=false`,
`rawPayloadStorageEnabled=false`. The readiness command additionally
reports `safeToStartPhase6O=true` only when the Phase 6M handler flags
stay locked off and every safety counter on `RazorpayWebhookEvent` is
zero. **No Phase 6N env flag changes are required on the VPS** — Phase 6N
shares the Phase 6M env defaults; Phase 6O will introduce its own NEW
env flag.

## 8.86 Running the backend pytest suite safely on the VPS

`.env.production` is tuned for live operation, not for tests. Several
test fixtures assert on values that drift when production env wins
(model name, webhook secret, eager Celery, broad-automation flags).
Run the suite inside the backend container with the env overrides
below — this matches what the in-tree fixes (conftest eager-mode pin,
`AI_MODEL` precedence, `override_settings` of `WHATSAPP_WEBHOOK_SECRET`,
etc.) expect:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend \
    env \
    AI_PROVIDER=disabled \
    AI_MODEL=gpt-4o-mini \
    OPENAI_API_KEY= \
    ANTHROPIC_API_KEY= \
    GROK_API_KEY= \
    WHATSAPP_PROVIDER=mock \
    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=false \
    WHATSAPP_AI_AUTO_REPLY_ENABLED=false \
    WHATSAPP_CALL_HANDOFF_ENABLED=false \
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false \
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=false \
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false \
    WHATSAPP_REORDER_DAY20_ENABLED=false \
    META_WA_APP_SECRET= \
    META_WA_ACCESS_TOKEN= \
    META_WA_PHONE_NUMBER_ID= \
    RAZORPAY_MODE=mock \
    RAZORPAY_KEY_ID= \
    RAZORPAY_KEY_SECRET= \
    RAZORPAY_WEBHOOK_TEST_MODE_ENABLED=false \
    RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED=false \
    RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED=false \
    RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD=false \
    RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=false \
    RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=false \
    RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=false \
    python -m pytest -q
```

Notes:

- The conftest already pins `CELERY_TASK_ALWAYS_EAGER=True` for the
  test session, so `.delay()` is synchronous regardless of the
  production env value. The override above is therefore not required
  for that flag — but the rest **are** required to keep tests
  deterministic on a real VPS.
- The override does **not** touch the running stack — `docker compose
  exec backend` runs the command in a one-shot subprocess inside the
  already-running container. No env file is rewritten.
- After the run completes, the existing backend / worker / beat
  containers continue running with the unmodified `.env.production`
  values.

## 8.9 Reminder — recreate containers after env changes

Whenever you edit `.env.production` (e.g., adding a real Vapi
`phone_number_id` + `webhook_secret`, or rotating a key), **recreate**
the backend / worker / beat containers; a `restart` alone will not pick
up new env values:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --force-recreate backend worker beat
```

After recreate, immediately re-run the Phase 6M / 6M-0 / 6K-B
verification commands above to confirm posture stayed locked.

## 9. Security checklist before customers go live

- [ ] `DJANGO_SECRET_KEY` and `JWT_SIGNING_KEY` are unique, long, and never committed.
- [ ] `DEBUG=false` everywhere in `.env.production`.
- [ ] `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` all include `ai.nirogidhara.com` and nothing wildcarded.
- [ ] Postgres password is strong and matches the value embedded in `DATABASE_URL`.
- [ ] `WHATSAPP_PROVIDER`, `RAZORPAY_MODE`, `DELHIVERY_MODE`, `VAPI_MODE`, `META_MODE` all stay `mock` until Prarit confirms each integration's live credentials.
- [ ] `AI_PROVIDER` stays `disabled` until OpenAI / Anthropic keys are in place.
- [ ] `WHATSAPP_DEV_PROVIDER_ENABLED=false` (the Baileys stub refuses to load anyway when DEBUG=false, but this is belt + braces).
- [ ] Postgres `pg_dump` backup taken before the first real customer payment / order.
- [ ] Host Nginx (or Traefik) terminates TLS; HTTP 80 either redirects to HTTPS or is closed at the firewall.
- [ ] `docker stats` confirms the new stack is leaving headroom for Postzyo + OpenClaw.
- [ ] **Phase 5C — WhatsApp AI Chat Sales Agent.** `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` until: (a) `AI_PROVIDER=openai` + `OPENAI_API_KEY` set, (b) the locked greeting template (`whatsapp.greeting`) is synced and approved, (c) `Claim` rows exist for every product the agent must explain, (d) a controlled run on test numbers passes. Flip the env to `true` and recreate the backend / worker / beat containers (see §8.9) to enable auto-mode.
- [ ] **Phase 6K — Razorpay test-mode execution gate.** `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=false` is the steady-state value. The Phase 6K-B artefact (`pex_8f309650e9644cfaae4418f9` → `order_Sks3KPf0vntKhf`) must keep `business_mutation_was_made=false` + `rollback_status=completed` on every audit replay (§8.6).
- [ ] **Phase 6M — Razorpay webhook handler.** All four `RAZORPAY_WEBHOOK_*` env flags stay `false`; production webhook secret (`RAZORPAY_WEBHOOK_SECRET`) is consumed only by the Phase 2B `/api/webhooks/razorpay/` endpoint, never by the Phase 6M test-mode handler (§8.7).
- [ ] **Phase 6M-0 — MCP Gateway.** All four `MCP_*` env flags stay locked (`MCP_ENABLED=false`, `MCP_READ_ONLY_MODE=true`, `MCP_WRITE_TOOLS_ENABLED=false`, `MCP_PROVIDER_TOOLS_ENABLED=false`). Tool invocation count in the last 24 h must be zero (§8.8).
- [ ] **Runtime kill switch.** The global `RuntimeKillSwitch` row must be `enabled=true`. `/api/v1/saas/runtime-live-gate/kill-switch/` must report `enabled=true` after every deploy.

---

## 11. Production Posture (historical — Phase 12D snapshot as of 2026-05-16)

> **Historical note (superseded).** At Phase 15M the operational baseline was the **Foundation Release Freeze + Director Sign-off Pack** (docs-only; safety shell frozen at commit `eefd8b3`, docs/sign-off at `8fc77d6`). **That baseline has since advanced to Phase 16C — Director Daily Briefing + Team Roles UI, PRODUCTION VERIFIED + CLOSED at commit `687ef41`** (Phase 16B — Customer Lifecycle UI Backbone is the previous verified baseline at `00c3295`). The Phase 15 safety shell remains frozen at `eefd8b3`. **Phase 16E — Payment / Logistics Integration Hardening is next planned only and requires a separate written Director directive.** For current production posture see [`../nd.md`](../nd.md) head-of-file + [`PHASE_15M_DIRECTOR_SIGNOFF_PACK.md`](PHASE_15M_DIRECTOR_SIGNOFF_PACK.md). The numbers in this section are the **historical Phase 12D snapshot**; do not treat them as current.

**Historical test baseline (Phase 12D):** 2730 backend tests + 82 frontend tests. All green
at that snapshot. Current verification baseline lives in `nd.md`.

**VPS path / compose / env:** `/opt/nirogidhara-command`,
`docker-compose.prod.yml`, `.env.production` (never committed, never
edited by automation). Host port `18020 → 80`.

### Beat schedule (8 daily entries as of Phase 9F)

The Celery beat container runs the legacy CEO Briefing twin plus six
new Tier-2 deterministic snapshots, staggered hourly so the CEO
orchestrator sees fresh upstream data at 13:00 IST.

| Beat task name | Cron (IST) | Source |
| --- | --- | --- |
| `ai-daily-briefing-morning` | morning | legacy `ai_governance.CeoBriefing` |
| `ai-daily-briefing-evening` | evening | legacy `ai_governance.CeoBriefing` |
| `customer-success-daily` | 08:00 | `apps.agents.customer_success.tasks` |
| `rto-prevention-daily` | 09:00 | `apps.agents.rto_prevention.tasks` |
| `cfo-daily` | 10:00 | `apps.agents.cfo.tasks` |
| `data-analyst-daily` | 11:00 | `apps.agents.data_analyst.tasks` |
| `calling-team-leader-daily` | 12:00 | `apps.agents.calling_team_leader.tasks` |
| `ceo-orchestration-daily` | 13:00 | `apps.agents.ceo_orchestration.tasks` (synthesis over 9A-9E) |

Every task is **recommendations-only**. None send WhatsApp, place
calls, mutate payments, or dispatch shipments. Each refuses to run
when the Postgres-safe kill switch is off (Phase 7E-Live-B Hotfix-1
pattern — `RuntimeKillSwitch.enabled=False` row ordered by `-pk`
wins). Sandbox mode propagates to both `Snapshot.sandbox=True` AND
`AgentRun.sandbox_mode=True`.

### Migration chains (latest per app, as of 2026-05-20)

```text
apps/agents/migrations/
  0001_initial.py
  0002_customer_success_snapshot.py
  0003_rto_risk_snapshot.py
  0004_cfo_financial_snapshot.py
  0005_data_analyst_snapshot.py
  0006_calling_team_leader_snapshot.py
  0007_ceo_orchestration_snapshot.py

apps/calls/migrations/
  0001_initial.py
  0002_phase2d_vapi_fields.py
  0003_call_branch_call_organization.py
  0004_phase11a_transcript_fields.py            # Phase 11A
  0005_phase11b_call_quality_score.py           # Phase 11B
  0006_phase12a_ai_call_campaign_gate.py        # Phase 12A
  0007_phase12b_call_outcome_record.py          # Phase 12B
  0008_phase12c_post_call_follow_up_queue.py    # Phase 12C

apps/caio/migrations/                            # Phase 11C
  0001_initial.py

apps/learning/migrations/                        # Phase 11D
  0001_initial.py

apps/payments/migrations/
  ...
  0024_phase8f_real_customer_controlled_mutation.py   # Phase 8F
  0025_phase8f_hotfix_rename_indexes.py               # Phase 8F-Hotfix
  0026_phase10c_payment_link_refresh_gate.py          # Phase 10C

apps/whatsapp/migrations/
  ...
  0006_whatsappconsent_organization_and_more.py
  0007_phase7e_live_b_real_customer_send_gate.py      # Phase 7E-Live-B

apps/shipments/migrations/
  ...
  0005_phase7g_live_real_customer_dispatch_gate.py    # Phase 7G-Live

apps/ai_governance/migrations/
  ...
  0010_phase9e_add_calling_team_leader_agent.py       # Phase 9E

apps/diagnostics/                                     # Phase 10A — service-only app, no models
  (no migrations)
```

`python manage.py makemigrations --check --dry-run` must report
`No changes detected` at every commit. If migrations drift after a
`git pull`, run `docker compose exec backend python manage.py migrate`
inside the running stack — never edit `.env.production` to bypass.

**Phase 13A note** — Phase 13A added the SimpleJWT login endpoint
alias `/api/v1/auth/login/` + `/api/v1/auth/refresh/` directly in
`config/urls.py` (no migration). The Director user was created
manually via `docker compose exec backend python manage.py shell`
+ `getpass()` — the password is NEVER stored in code, env, or
git. To rotate the Director password on the VPS, see
[`docs/RUNBOOK.md`](RUNBOOK.md#director-login-phase-13a) §"Rotate
the password".

### Director payment-recovery workflow (Phase 10 family CLI commands)

The Phase 10 chain is `10A diagnose → 10C refresh link → 10B prepare
reminder → 7E-Live-B Director approve+execute`. None of the Phase 10
commands send WhatsApp; only the final 7E-Live-B execute does (inside
the same 15-min UTC window the Director signed).

```bash
# 10A — read-only drilldown
python manage.py inspect_pending_payments [--limit N] [--include-partial] [--json]

# 10C — refresh stale Razorpay payment link (test default, live gated)
python manage.py prepare_phase10c_payment_link_refresh_gate <payment_id> --mode test --operator-name "Prarit Sidana"
python manage.py prepare_phase10c_payment_link_refresh_gate <payment_id> --mode live --operator-name "Prarit Sidana"   # LIVE
python manage.py approve_phase10c_payment_link_refresh_gate --gate-id N --operator-name "Prarit Sidana" --intent "..." --director-signoff "BEGIN_UTC=...Z END_UTC=...Z"
python manage.py execute_phase10c_payment_link_refresh_gate --gate-id N --operator-name "Prarit Sidana" [--confirm-phase10c-payment-link-refresh-live]
python manage.py rollback_phase10c_payment_link_refresh_gate --gate-id N --operator-name "Prarit Sidana"
python manage.py cancel_phase10c_payment_link_refresh_gate --gate-id N --operator-name "Prarit Sidana" --reason "..."
python manage.py inspect_phase10c_payment_link_refresh_gate <gate_id> [--json]

# 10B — prepare Phase 7E-Live-B reminder gate (stage-aware)
python manage.py prepare_payment_reminder_send <payment_id> [--operator-name "Prarit Sidana"] [--force] [--json]

# 7E-Live-B — Director approve + execute (LIVE WhatsApp send)
python manage.py inspect_phase7e_live_b_real_customer_gate
python manage.py approve_phase7e_live_b_real_customer_gate --gate-id N --director-signoff "...BEGIN_UTC=...Z END_UTC=...Z..." --operator-name "..." --confirm-phase7e-live-b-real-customer-send
python manage.py execute_phase7e_live_b_real_customer_send --gate-id N --director-signoff "<same>" --operator-name "..." --confirm-phase7e-live-b-real-customer-send
```

### Live-mode env baseline (current `.env.production` posture)

| Setting | Value | Notes |
| --- | --- | --- |
| `RAZORPAY_MODE` | `live` | Live keys (`rzp_live_*`); test/live mismatch-safety enforced at Phase 10C execute |
| `WHATSAPP_PROVIDER` | `meta_cloud` | Live Meta Cloud API |
| `WHATSAPP_LIVE_META_LIMITED_TEST_MODE` | `true` | Limited allow-list still gates every send |
| `WHATSAPP_AI_AUTO_REPLY_ENABLED` | `false` | Auto-reply OFF post-soak |
| `DELHIVERY_MODE` | mock or test | Phase 7G-Live not approved |
| `VAPI_MODE` | mock | Phase 5D call-handoff stays gated |
| `PHASE10C_PAYMENT_LINK_REFRESH_ENABLED` | `false` | Runtime env prefix only when running a live refresh |
| `PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED` | `false` | Runtime env prefix only when executing a live send |
| `RuntimeKillSwitch` (global) | `enabled=True` | `enabled=False` row ordered by `-pk` always wins |

`.env.production` is NEVER edited by a Phase 10 workflow — live-mode
flips happen only by prefixing the relevant CLI command with the
runtime env var (e.g. `PHASE10C_PAYMENT_LINK_REFRESH_ENABLED=true
RAZORPAY_MODE=live python manage.py execute_phase10c_...`).

### Verification after deploy (Phase 9-10 specific)

```bash
# Confirm migrations clean
docker compose exec backend python manage.py makemigrations --check --dry-run

# Confirm beat schedule sees all 8 entries
docker compose exec beat python manage.py shell -c "from django_celery_beat.models import PeriodicTask; print(PeriodicTask.objects.values_list('name', flat=True))"

# Confirm CEO Orchestration latest snapshot reachable (admin-only)
curl -sS https://ai.nirogidhara.com/api/v1/ceo-orchestration/snapshots/latest/ -H "Authorization: Bearer <admin token>" | jq

# Read-only diagnostics surface
curl -sS "https://ai.nirogidhara.com/api/v1/diagnostics/pending-payments/?limit=10" -H "Authorization: Bearer <admin token>" | jq

# Phase 10C / Phase 7E-Live-B are CLI-only (no API endpoints) — verify
# their CLI registration:
docker compose exec backend python manage.py help | grep -E "phase10c|payment_reminder|phase7e_live_b"
```

---

## 10. What's intentionally NOT here

This deployment scaffold ships through Phase 6N (planning-only). The
following stay locked out at the application layer regardless of how
the container is configured:

- WhatsApp inbound auto-reply (Phase 5C — gated by `WHATSAPP_AI_AUTO_REPLY_ENABLED=false`)
- Chat-to-call handoff (Phase 5D — gated by `WHATSAPP_CALL_HANDOFF_ENABLED=false`)
- Order booking from WhatsApp chat (Phase 5C — guarded by limited test mode)
- Discount automation / rescue-discount flow (Phase 5E — gated by `WHATSAPP_RESCUE_DISCOUNT_ENABLED=false` and `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false`)
- Day-20 reorder cadence (Phase 5E — gated by `WHATSAPP_REORDER_DAY20_ENABLED=false`)
- Campaign / broadcast WhatsApp sends (Phase 5F — LOCKED)
- Freeform outbound WhatsApp text (LOCKED — only approved templates allowed)
- CAIO-originated customer messages (LOCKED — CAIO is monitor / audit only)
- Phase 6K-style real Razorpay test execution (gated by `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=false`; one-shot only)
- Phase 6M Razorpay webhook handler (dormant by default — all four `RAZORPAY_WEBHOOK_*` env flags stay false)
- Phase 6N Razorpay webhook business-mutation sandbox path (planning-only — Phase 6N has no execution path)
- Phase 6O Razorpay sandbox status mapping (review-only — `RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=false` default; even when `true`, only review preparation is unlocked, never any Order/Payment/Shipment/DiscountOfferLog mutation)
- Phase 6P Razorpay sandbox paid-status mutation test (sandbox-ledger-only, CLI-only — `RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=false` default; even when `true`, execute requires `--confirm-sandbox-paid-status-mutation` + non-empty `--director-signoff` and mutates only the Phase 6P ledger; no API endpoint or frontend button dispatches mutation)
- Phase 6Q Razorpay payment → order workflow safety gate (audit-gate-only, CLI-only review state changes — `RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=false` default; even when `true`, prepare/approve/reject/archive are CLI-only and write only to the Phase 6Q gate review table; no API endpoint or frontend button dispatches gate state changes)
- Phase 6R Razorpay payment → WhatsApp / courier dispatch readiness (audit-only readiness contract, CLI-only review state changes — `RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=false` default; even when `true`, prepare/approve/reject/archive are CLI-only and write only to the Phase 6R readiness review table; no API endpoint or frontend button dispatches review state changes; never sends WhatsApp, never calls Meta Cloud / Delhivery, never creates a shipment / AWB, never calls Razorpay)
- Phase 6S Razorpay limited internal dispatch pilot plan (planning-only, CLI-only review state changes — `RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=false` default; even when `true`, prepare/approve/reject/archive are CLI-only and write only to the Phase 6S pilot plan review table; no API endpoint or frontend button dispatches review state changes; never executes a pilot, never sends WhatsApp, never calls Meta Cloud / Delhivery / Razorpay, never creates a shipment / AWB; internal cohort only with `max_pilot_orders=1` and `max_amount_paise=100`; Phase 6T will own the final Phase 6 audit + lock / controlled pilot execution decision gate behind a SEPARATE env flag)
- MCP Gateway tools / provider tools (gated by `MCP_ENABLED=false` and `MCP_*` flag siblings)
- Per-org runtime provider routing (Phase 6F preview only — `runtimeSource=env_config`, `perOrgRuntimeEnabled=false`)
- Live execution through the Runtime Live Audit Gate (Phase 6H — `RuntimeKillSwitch.enabled=true`, every operation `allowedInPhase6H=false`)

If the deploy somehow turns any of those on, **stop the rollout** and
re-read `docs/WHATSAPP_INTEGRATION_PLAN.md`, `nd.md` §2 hard stops, and
the Current Working Memory block at the top of `nd.md`.
