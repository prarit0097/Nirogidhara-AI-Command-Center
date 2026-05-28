# Phase 15M — Foundation Release Freeze + Director Sign-off Pack

> **Supersession note (current truth):** This is a point-in-time Phase 15M sign-off artifact. The Phase 15 **safety shell** remains frozen at `eefd8b3` and this pack is still the authority on that freeze. But the **current overall operational baseline has advanced to Phase 16B — Customer Lifecycle UI Backbone (PRODUCTION VERIFIED + CLOSED at `00c3295`)**, and the next planned work is **Phase 16C — Director Daily Briefing + Team Roles UI** (NOT Phase 16A, which has already shipped). For current truth read [`../nd.md`](../nd.md) head-of-file. References to "Phase 16A next" below are historical to this pack's authoring date.
>
> **Status:** SHIPPED — docs-only release-freeze attestation.
> **Phase 15 safety shell is FROZEN as of this commit.** No further small Safety / UX polish phases unless a production P0/P1 blocker, security defect, or compliance defect is observed, or the Director explicitly authorises a critical follow-on phase.

---

## 1. Title

**Phase 15M — Foundation Release Freeze + Director Sign-off Pack**

Read-only attestation that the Phase 15 safety/UI foundation is feature-complete and frozen. *(As authored at Phase 15M sign-off, the next planned work was Phase 16A — Business MVP Gap Audit. That has since shipped, along with Phase 16B; the current next planned work is **Phase 16C — Director Daily Briefing + Team Roles UI**, separate Director directive required. See the supersession note at the top of this file and `nd.md` head-of-file for current truth.)*

---

## 2. Purpose

Phase 15 shipped a 16-piece read-only safety chrome on top of the production app (kill switch UI, sandbox UI, rollback system + history, sidebar briefing badge, audit timeline, topbar safety pill with responsive overflow polish, shared `SafetyStateProvider` with WebSocket auto-refresh + sync indicator, settings diagnostics panel + detail drawer, session-expiry UX, manual refresh button). Each sub-phase added one tightly-scoped surface; cumulatively they form a complete read-only Director safety command center.

Phase 15M closes the foundation chapter by:

- **Recording the verified baseline** (commit hash, test counts, production posture, accepted warnings) at a single point in time so future Director reviews can compare against a frozen reference.
- **Codifying the freeze rule** so coding agents do not accidentally extend the safety shell on momentum. The Director must explicitly authorise any further safety-shell change.
- **Providing a route-wise smoke checklist** the Director can run when signing off the release.
- **Naming the next planned work** (Phase 16A Business MVP Gap Audit) and pointing the reader at it instead of inventing Phase 15N / 15O / 15P incrementally.
- **Documenting the rollback plan** so any unforeseen issue with Phase 15 chrome can be undone surgically without dragging the production VPS.

Phase 15M ships **zero backend code, zero frontend code, zero migrations, zero env changes, zero provider calls, zero business mutation, zero AuditEvent writes, zero Celery enqueues**. It is a docs-only release-freeze pack.

---

## 3. Current verified baseline

| Field | Value |
| --- | --- |
| Commit (HEAD = origin/main) | `eefd8b3fb8cb6bfd5f4fbb7ea7c5e9149b4a5eef` (`eefd8b3 feat: phase 15l add safety diagnostics manual refresh`) |
| Production URL | <https://ai.nirogidhara.com> |
| Production server | Hostinger VPS, `/opt/nirogidhara-command`, Docker Compose 6-container stack (Postgres 16, Redis 7, Daphne backend, Celery worker, Celery beat, Nginx → SPA) |
| Backend health | `GET /api/healthz/` → `{"status":"ok","service":"nirogidhara-backend"}` |
| AI state | **AI Paused** (`RuntimeKillSwitch.enabled=True` — kill switch active; AI execution blocked) |
| Sandbox state | **OFF** (`SandboxState.is_enabled=False`) |
| CEO Director Briefing | **STALE** in current production state (Phase 9F daily sweep not running on the production VPS by default) |
| Phase 7E-Live-B real customer WhatsApp send | **NOT approved** |
| Phase 7G-Live real customer Delhivery dispatch | **NOT approved** |
| Phase 8F real customer payment → order mutation | **Not staged**. Reading 1 ran 2026-05-14 and rolled back the same hour. |
| Backend test suite | 2200+ tests, passing on local SQLite. Full VPS Postgres parity per Test Hygiene Hotfix-1 (`backend/tests/conftest.py` pins integration modes to mock for tests). |
| Frontend test suite | **275 / 275 passed** (Phase 15K baseline 265 + 10 new Phase 15L tests). |
| Frontend build | clean (`npm run build` produces a green production bundle). |
| Lint | 0 errors (`npm run lint`). |
| Migrations | clean — `python manage.py makemigrations --check --dry-run` reports `No changes detected`. |
| `manage.py check` | clean. |
| Safety Sync indicator | **Live** when the `/ws/audit/events/` WebSocket is connected. |
| Frozen production env defaults (locked OFF) | `WHATSAPP_AI_AUTO_REPLY_ENABLED=false`, `WHATSAPP_CALL_HANDOFF_ENABLED=false`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=false`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=false`, `WHATSAPP_REORDER_DAY20_ENABLED=false`, `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=false`, `PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED=false`, `PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED=false`, `PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=false`, `PHASE7G_COURIER_EXECUTION_ENABLED=false`, `PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=false`, `PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=false`, `AI_CALLING_ENABLED=false`, `MCP_ENABLED=false`. |

> **`nd.md` head-of-file remains the canonical source of truth.** If anything in this pack ever drifts from `nd.md`, `nd.md` wins.

---

## 4. Frozen safety shell scope (16 sub-phases)

Phase 15M freezes the following 16 already-shipped sub-phases as the v1.0 safety / chrome foundation. Each sub-phase delivers one tightly-scoped read-only surface; together they form the Director's complete safety command center.

| # | Sub-phase | Commit | Summary |
| --- | --- | --- | --- |
| 1 | **Phase 14D — AI Kill Switch UI wiring** | `fd99119` | Topbar + Settings AI Kill Switch surface. Hits `GET/POST /api/v1/saas/runtime-live-gate/kill-switch/`. |
| 2 | **Phase 14E — Sandbox Mode UI wiring** | `869fa42` | Settings Sandbox Mode card. Hits `GET/POST /api/ai/sandbox/{status,enable,disable}/`. |
| 3 | **Phase 14E-Hotfix-1 — Safety Status UI Polish** | `b725f0f` | Sidebar bottom safety indicator + polish. |
| 4 | **Phase 14F — Rollback System UI wiring** | `abc334c` | Settings Rollback System card. Hits the rollback endpoints. |
| 5 | **Phase 15A — Rollback History View** | `74a132d` | Read-only rollback history modal (paginated, sanitised). |
| 6 | **Phase 15B — Sidebar Director Daily Briefing Badge** | `c6a2960` | Sidebar status badge on the "CEO AI Briefing" nav. New `GET /api/v1/ceo-orchestration/snapshots/sidebar-status/` (slim allow-list of 8 keys; never returns briefing body / priorities / alerts). |
| 7 | **Phase 15C — Audit Timeline Page** | `6f41554` | `/operations/audit-timeline` read-only paginated audit feed (sanitised; allow-list slice; truncation). |
| 8 | **Phase 15D — Topbar Safety Compact Pill** | `fae1257` | Topbar compact pill summarising kill switch + sandbox + briefing in one chip. |
| 9 | **Phase 15E — Topbar Responsive Overflow Polish** | `c0e1bed` | Fixes horizontal overflow at narrow widths; AppLayout `overflow-x-clip` + `min-w-0`. |
| 10 | **Phase 15F — Shared Safety State Hook** | `f1fec7d` | `SafetyStateProvider` + `useSafetyState()` consolidates the three safety GETs; inert hook-outside-provider fallback for test ergonomics. |
| 11 | **Phase 15G — Safety State Auto-Refresh on Audit Events** | `d1ebbc2` | Provider auto-refreshes via Phase 4A `/ws/audit/events/` for allow-listed kinds (`runtime.kill_switch.*` / `ai.sandbox.*` / `ceo_orchestration.snapshot.*`), debounced 750 ms. |
| 12 | **Phase 15H — Safety WebSocket Health Indicator** | `74ea16e` | Topbar Safety Sync indicator (`connecting` / `live` / `reconnecting` / `offline` / `unavailable`). |
| 13 | **Phase 15I — Safety Diagnostics Mini Panel** | `822ee56` | Settings page mini panel (6 rows: sync / last refresh / last event / per-endpoint health pills). |
| 14 | **Phase 15J — Safety Diagnostics Detail Drawer** | `285525b` | "View details" button opens a shadcn Dialog with three sections + read-only guarantee paragraph. |
| 15 | **Phase 15K — Session Expiry UX Polish** | `9e33f82` | Replaces per-widget HTTP 401 toast spam with one deduped global "Session expired" toast + passive `SessionExpiredBanner` on `/login`. New `AuthExpiredError` + `isAuthError` + `notifySessionExpiredOnce`. |
| 16 | **Phase 15L — Safety Diagnostics Manual Refresh Button** | `eefd8b3` | Small "Refresh status" button on panel + drawer that re-fires the three safety GETs on demand. Concurrent clicks coalesce to one wave. |

> All 16 sub-phases are strictly **read-only** chrome on the Director side. Together they invoke at most these three safe GET endpoints during normal operation:
>
> - `GET /api/v1/saas/runtime-live-gate/kill-switch/` (Phase 14D)
> - `GET /api/ai/sandbox/status/` (Phase 14E)
> - `GET /api/v1/ceo-orchestration/snapshots/sidebar-status/` (Phase 15B)
>
> Plus one read-only WebSocket subscription: `/ws/audit/events/` (Phase 4A, reused by Phase 15G).
> Plus the Phase 15A rollback history modal's read-only GET (`/api/v1/ai/prompt-versions/rollback-history/`).
> Plus the Phase 15C audit timeline page's read-only GET (`/api/v1/audit/timeline/`).
> Nothing else is fetched, mutated, queued, sent, or executed by the Phase 15 chrome.

---

## 5. Freeze rule

**The Phase 15 safety shell is frozen at commit `eefd8b3`.**

Coding agents and the Director must follow this rule until the freeze is explicitly lifted:

1. **No new "Phase 15X" sub-phases** unless the change is one of:
   - A production **P0** blocker (chrome crashes the SPA, infinite reload loop, blank page).
   - A production **P1** security defect (the chrome leaks a token / phone / payload / prompt body / hidden reasoning / Director note in any rendered surface).
   - A production **P1** compliance defect (the chrome surfaces a medical claim not in the Claim Vault, or surfaces blocked-claim vocabulary).
   - A Director-approved critical change with a written directive that names "Phase 15M freeze override" explicitly.

2. **No additional Safety UI polish** unless the above gate is met. Examples of polish that are **frozen out**: new diagnostics rows, new sync states, new badge tones, new toast variants, new tooltip helpers, new keyboard shortcuts, new dark-mode tweaks, new responsive breakpoints, new icon swaps, new copy edits to existing rows.

3. **No new safety endpoints** (no GET, no POST, no WebSocket channel) unless the above gate is met. The current three GETs + one WebSocket are the complete read-only contract.

4. **No expansion of existing safety endpoints** to return new keys, new fields, raw payloads, raw secrets, full phones, customer PII, prompt bodies, hidden reasoning, or provider payloads. The Phase 15B slim allow-list (8 keys) and Phase 15C allow-list slice (70 keys + 200-char truncation) are frozen.

5. **No code change** to `frontend/src/context/SafetyStateContext.tsx`, `frontend/src/components/layout/Topbar.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/settings/SafetyDiagnosticsPanel.tsx`, `frontend/src/components/settings/SafetyDiagnosticsDetailModal.tsx`, `frontend/src/components/auth/SessionExpiredBanner.tsx`, `frontend/src/services/realtime.ts`, `frontend/src/pages/AuditTimeline.tsx`, `frontend/src/pages/Login.tsx` (auth-banner block only) unless the above gate is met.

6. **No code change** to `backend/apps/audit/views.py` (AuditTimelineView), `backend/apps/agents/ceo_orchestration/views.py` (sidebar-status endpoint) unless the above gate is met.

7. **Routine maintenance is allowed** if it does not change behaviour: dependency bumps, lint auto-fixes, prettier reformatting, type-only tightening, test-only edits, comment/JSDoc fixes — provided the rendered output and tested behaviour are unchanged. Document any such change in a `chore:` commit, not a new Phase 15X label.

8. **The freeze does NOT cover Phase 16A onwards.** Phase 16A — Business MVP Gap Audit — is the explicitly named next planned work and is **outside** the Phase 15 freeze. Phase 16A may add new features as long as it does not modify the frozen Phase 15 safety chrome surfaces above.

If in doubt about whether a proposed change is inside or outside the freeze, **ask the Director before touching the file** rather than after. Coding agents must not interpret silence as authorisation.

---

## 6. Route-wise smoke checklist

Director runs this after a deploy or before a sign-off to verify the safety chrome still works end-to-end. All steps are read-only.

### 6.1 Login + session

- [ ] Open <https://ai.nirogidhara.com/login> in an incognito window. No `SessionExpiredBanner` visible (direct-first-visit case).
- [ ] Sign in as the Director (`1995praritsidana@gmail.com`). Lands on `/saas-admin` (or `/`) without a redirect loop.
- [ ] Open DevTools → Network → confirm `POST /api/v1/auth/login/` returns 200; `localStorage.getItem("nirogidhara.jwt")` is a non-empty string.
- [ ] Browser tab title shows the app name; no console error spam.

### 6.2 Topbar safety chrome (Phase 15D / 15E / 15F / 15G / 15H)

- [ ] Topbar Safety Pill renders. Expected text in current production: `Safety: AI Paused · Sandbox OFF · Briefing STALE` (amber tone) — production AI is paused and the daily CEO sweep is not running.
- [ ] Hover the pill → tooltip shows long-form breakdown (`Kill Switch: Paused. Sandbox: OFF. Briefing: STALE. Read-only summary.`).
- [ ] Topbar Safety Sync indicator renders. Expected initial state `Connecting`, settles to `Live` within ~2s on a healthy WebSocket connection.
- [ ] Narrow the browser window to ~640px wide. No horizontal scrollbar on the Topbar. The pill compactly truncates instead of overflowing.

### 6.3 Sidebar safety chrome (Phase 14E-Hotfix-1 / 15B)

- [ ] Sidebar bottom safety indicator renders. Expected text: `AI Paused — Sandbox OFF` (amber tone).
- [ ] Sidebar "CEO AI Briefing" nav item shows a small badge. Expected current production state: `stale` (amber) — never `ready` when the daily sweep has not produced a recent snapshot.
- [ ] Collapse the sidebar. Both the bottom safety indicator and the briefing badge hide gracefully.

### 6.4 Audit Timeline page (Phase 15C)

- [ ] Navigate to `/operations/audit-timeline`. Page loads. No console errors.
- [ ] Verify the page shows recent audit rows. Each row's payload column shows only the allow-listed truncated keys — **never** raw `token`, `verify_token`, `app_secret`, full phones (`+91XXXXXXXXXX`), full customer emails, raw `Authorization` headers, raw provider payloads, or prompt bodies.
- [ ] Filter by category (`safety`, `rollback`, `whatsapp`, `payment`, `delivery`). The filter narrows the list. No POST/PATCH/DELETE controls visible.

### 6.5 Settings & Control page (Phase 14D / 14E / 14F / 15A / 15I / 15J / 15K / 15L)

Navigate to `/settings`.

- [ ] **AI Kill Switch card** — renders `Paused` (red). Refresh button works (GET-only).
- [ ] **Sandbox Mode card** — renders `OFF` (neutral). Refresh button works.
- [ ] **Rollback System card** — renders. "View rollback history" opens the Phase 15A modal; modal is paginated; no raw prompt body, no Director note leakage; modal closes cleanly.
- [ ] **AI Action Approval Matrix** — renders read-only.
- [ ] **Safety Diagnostics panel (Phase 15I)** — six rows render: Safety sync (`Live`), Last safety refresh (timestamp), Last audit event (timestamp or `No event seen yet`), Kill switch endpoint (`OK`), Sandbox endpoint (`OK`), Briefing status endpoint (`OK`). No buttons except `View details` and `Refresh status`.
- [ ] **`Refresh status` button (Phase 15L)** — click once. Button flips to `Refreshing…` and disables for ~200ms; "Last safety refresh" timestamp updates; all three endpoint pills stay `OK` afterwards.
- [ ] **Concurrent click test (Phase 15L)** — rapid-click the button 5 times. Only one network wave fires; subsequent clicks coalesce.
- [ ] **`View details` button (Phase 15J)** — click. Modal `Safety Diagnostics Details` opens. Three sections render (Safety sync / Endpoint health / Safe error summary). Read-only guarantee paragraph renders verbatim. `Refresh source` row shows `Initial load` after first mount, `Manual refresh` after a manual refresh, `Audit event` after a WebSocket-triggered refresh. Close button works.

### 6.6 Session expiry UX (Phase 15K)

- [ ] In DevTools → Application → Local Storage, delete `nirogidhara.jwt`.
- [ ] Click any nav item that requires auth (e.g. `/saas-admin`).
- [ ] One global toast `Session expired` fires (NOT three per-widget toasts).
- [ ] Redirected to `/login` with the passive `SessionExpiredBanner` rendered above the form. Banner text: `Session expired — Please sign in again to continue. Safety data may be stale until you sign in.`
- [ ] Sign back in. Banner does not re-render on the next direct visit to `/login`.

### 6.7 WebSocket live-refresh sanity (Phase 15G — optional smoke step)

This step exists for completeness; on a production VPS where the Director cannot run a Django shell, skip it.

- [ ] SSH to the VPS; `docker compose -f docker-compose.prod.yml exec backend python manage.py shell`.
- [ ] In a separate browser tab, keep `/settings` open with the Safety Diagnostics panel visible.
- [ ] In the shell: `from apps.audit.signals import write_event; write_event(kind="runtime.kill_switch.smoke_test", payload={"note": "phase15m smoke"}, actor=None)`.
- [ ] In the browser tab, observe the Safety Diagnostics panel's "Last audit event" timestamp update within ~1 second.

### 6.8 Backend health smoke

- [ ] `curl -sf https://ai.nirogidhara.com/api/healthz/` returns `{"status":"ok","service":"nirogidhara-backend"}`.
- [ ] `docker compose -f docker-compose.prod.yml ps` shows all six containers `Up`.
- [ ] `docker compose -f docker-compose.prod.yml logs --since 60s backend` shows no `Traceback` lines.

---

## 7. Director sign-off checklist

The Director signs off Phase 15M by initialling each item below. Sign-off does NOT authorise any new live execution; it only attests that the safety chrome v1.0 foundation is feature-complete and frozen.

- [ ] I have read **`nd.md` §0 TL;DR** + the Phase 15M entry in **`nd.md` §8 (current state)**.
- [ ] I have read this `docs/PHASE_15M_DIRECTOR_SIGNOFF_PACK.md` end-to-end.
- [ ] I have read the **Freeze rule** in §5 above and understand that coding agents will refuse new Phase 15X sub-phases without an explicit Director directive that names "Phase 15M freeze override".
- [ ] I have run the **Route-wise smoke checklist** (§6) in production and every required item passes.
- [ ] I confirm the **production safety posture** in §3 matches what I see in the UI: `AI Paused`, `Sandbox OFF`, Briefing `STALE`, Safety Sync `Live`.
- [ ] I confirm **Phase 7E-Live-B (real customer WhatsApp send) remains NOT approved**.
- [ ] I confirm **Phase 7G-Live (real customer Delhivery dispatch) remains NOT approved**.
- [ ] I confirm **Phase 8F (real customer payment → order mutation) remains not staged for next run** (Reading 1 already rolled back 2026-05-14; any future Reading requires a fresh Director directive).
- [ ] I confirm **broad WhatsApp automation flags** (`WHATSAPP_AI_AUTO_REPLY_ENABLED`, `WHATSAPP_CALL_HANDOFF_ENABLED`, `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`, `WHATSAPP_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`, `WHATSAPP_REORDER_DAY20_ENABLED`) remain `false` on the VPS `.env.production`.
- [ ] I confirm **`AI_CALLING_ENABLED=false`** on the VPS `.env.production` (Phase 12A campaign gate is shipped but never auto-triggers).
- [ ] I confirm **`MCP_ENABLED=false`** on the VPS `.env.production` (Phase 6M-0 gateway is read-only and disabled by default).
- [ ] I authorise the project to begin **Phase 16A — Business MVP Gap Audit** as the next planned work, with the understanding that Phase 16A operates outside the Phase 15 chrome freeze but does not modify the frozen Phase 15 surfaces.

Director signature (Prarit Sidana): ____________________________   Date: ____________

---

## 8. Known warnings / accepted risks

The following items are **known and accepted** as of the freeze. They are not blockers; they are documented so future operators do not waste time investigating them.

1. **Phase 4A pytest test-DB teardown warning** — During a full backend pytest run, the `WebSocketCommunicator` connection holding pattern can produce a non-blocking teardown warning ("database test_nirogidhara is being accessed by one other session"). Test outcomes are unaffected; the warning is the test DB layer noticing the Daphne consumer still has its WebSocket loop open during fixture teardown. **Accepted.** Do not retry-loop or sleep around it.
2. **Phase 4A WebSocket reconnect cadence** — `realtime.connectAuditEvents` uses internal backoff. Phase 15H exposes `connecting` / `live` / `reconnecting` / `offline` / `unavailable` states but does not expose an attempt counter; the Safety Diagnostics detail drawer labels reconnect attempts as `Not tracked`. **Accepted.** Adding an attempt counter is explicitly out of scope for the freeze.
3. **CEO Director Briefing typically `STALE`** — The Phase 9F daily CEO orchestration sweep is not running on the production VPS by default; the Sidebar briefing badge consequently shows `stale`. **Accepted as current production posture.** The Director may enable the daily sweep at any time; the chrome is already wired to flip to `ready` when a recent snapshot exists.
4. **VPS `.env.production` deviation flagged for Director reconciliation** — `nd.md §17` notes that the VPS `.env.production` carries `RAZORPAY_MODE=test`, `WHATSAPP_PROVIDER=meta_cloud`, `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`. The WhatsApp pair is intentional for the limited live test cohort. `RAZORPAY_MODE=test` must be flipped to `live` separately before any real customer payment collection goes live. **Accepted for the freeze;** flipping to live is a future Director-approved phase, not a Phase 15 chrome change.
5. **Phase 8F-Hotfix-1 / Hotfix-2 / Hotfix-3 recovery paths are CLI-only** — The recovery commands are governance/admin only and never re-execute Phase 8F. Documented in `nd.md` and `CLAUDE.md`. **Accepted.**
6. **No frontend POST endpoint dispatches state changes for Phase 6Q–6T / 7B / 7E / 7F / 7G / 8A–8F review** — All review state transitions live in CLI commands by design. **Accepted.** The Safety chrome is intentionally read-only.
7. **Mock-mode pinning in pytest** — `backend/tests/conftest.py` pins Razorpay / WhatsApp / Delhivery / Vapi / Meta / AI provider modes to mock for test isolation. Production code, models, migrations, services, views, env flags, `.env*` files, and frontend remain untouched by this pinning. **Accepted.**

If any of the above items changes meaningfully — for example, the daily CEO sweep starts running, or the WhatsApp limited test cohort expands, or `RAZORPAY_MODE` is flipped to `live` — `nd.md` head-of-file must be updated and `nd.md` wins.

---

## 9. Production safety posture (as of Phase 15M freeze)

| Surface | State | Notes |
| --- | --- | --- |
| `RuntimeKillSwitch` | **Paused** (`enabled=True` — kill switch active; AI execution blocked) | AI execution blocked. Topbar / Sidebar / Settings all surface this consistently. |
| `SandboxState` | **OFF** (`is_enabled=False`) | AI is not running in shadow / dry-run mode. |
| CEO Director Briefing | **STALE** | Daily sweep not running on the VPS by default. |
| Safety Sync (WebSocket) | **Live** when the VPS is healthy | `/ws/audit/events/` reachable from the SPA; falls back to `reconnecting` on transient disconnect, `unavailable` when the browser cannot reach the server at all. |
| Phase 7E-Live-B real customer WhatsApp | **NOT approved** | No live customer send has been performed by Phase 7E-Live-B. |
| Phase 7G-Live real customer Delhivery dispatch | **NOT approved** | No live customer courier dispatch has been performed by Phase 7G-Live. |
| Phase 8F real customer payment → order mutation | **Not staged for next run** | Reading 1 ran 2026-05-14, rolled back same hour. No business or customer impact. Future Readings require fresh Director directive. |
| Phase 12A AI calling campaign | **Director-triggered, never auto-triggered** | `AI_CALLING_ENABLED=false`. Beat schedule unchanged at 11 daily entries; campaign execution requires Director sign-off + explicit confirmation flag. |
| MCP Gateway | **Disabled (`MCP_ENABLED=false`)** | Read-only by default. No tool execution surface live. |
| Master Event Ledger (`AuditEvent`) | **Active** | Every important state change continues to write an audit row. Phase 15C surfaces the ledger read-only with allow-list sanitisation. |
| Master Blueprint §26 hard stops | **In force** | Free-style medical claims forbidden. CAIO never executes business actions. CEO AI is the execution approval layer. 50% total discount cap. All blocked-claim phrases forbidden. |

Everything in this table is **frozen at the Phase 15M commit**. Any deviation in production from this table must be reflected in `nd.md` head-of-file (which wins).

---

## 10. Phase 16A — Next planned work

After Phase 15M, the next planned phase is **Phase 16A — Business MVP Gap Audit**.

**Scope (planning-only — no code in Phase 15M):**

Phase 16A is a **gap-audit** phase that catalogues which Master Blueprint §26 + nd.md §3 business workflows are already implemented end-to-end on the VPS vs. which are partially implemented vs. which are stubbed vs. which are completely missing. It is **read-only** at the source-code level: discovery, classification, gap matrix, recommended next sub-phases, and risk ranking. Phase 16A produces a single new document (`docs/PHASE_16A_BUSINESS_MVP_GAP_AUDIT.md`) and may also update `nd.md` §8 / §11 to reflect the audit. **No backend code, no frontend code, no migration, no env edit** until the gap audit is signed off by the Director and a subsequent Phase 16B (implementation) is explicitly authorised.

**Phase 16A explicit non-goals (locked from the freeze):**

- **No modification to the frozen Phase 15 safety chrome surfaces.**
- **No new safety endpoints.**
- **No new safety toasts / badges / pills / drawers.**
- **No expansion of `SafetyStateProvider` or `useSafetyState`.**
- **No re-implementation of Phase 4A WebSocket layer.**
- **No business mutation (Order / Payment / Shipment / Customer / Lead / DiscountOfferLog).**
- **No provider call (Razorpay / Meta Cloud / Delhivery / Vapi / OpenAI / Anthropic / NVIDIA / NIM / OpenRouter).**
- **No env flag flip on `.env.production`.**

**Director directive required to start Phase 16A.** Do not begin Phase 16A on momentum. The Director must explicitly authorise the start with a written directive that names "Phase 16A — Business MVP Gap Audit kick-off".

---

## 11. Rollback plan

The Phase 15 chrome is purely additive read-only UI on top of pre-Phase-14 endpoints + three new safety GET endpoints + one Phase 4A WebSocket (which itself predates Phase 15). Rolling back any single Phase 15X sub-phase, or all of them at once, never touches business data.

### 11.1 Per-sub-phase rollback

For each of the 16 sub-phases listed in §4, the rollback is a `git revert` of the corresponding commit. The commits are independent — reverting Phase 15L does not require reverting Phase 15K, etc. — because each sub-phase only added passive read-only chrome and (where applicable) one read-only backend endpoint or one shared provider field.

To revert a specific sub-phase:

```bash
# Example: revert Phase 15L only
git revert eefd8b3 --no-edit
cd backend && python -m pytest -q                    # confirm green
cd ../frontend && npm run lint && npm test && npm run build
git push origin main
# Then on the VPS: git pull && docker compose -f docker-compose.prod.yml build && \
#                  docker compose -f docker-compose.prod.yml up -d
```

### 11.2 Full Phase 15 chrome rollback (worst case)

To roll back the entire Phase 15 chrome at once, revert from the most recent Phase 15X commit (Phase 15L = `eefd8b3`) back to the last pre-Phase-15 commit (Phase 14F = `abc334c`).

```bash
# Worst-case full Phase 15 chrome revert
git revert --no-commit eefd8b3 9e33f82 285525b 822ee56 74ea16e \
           d1ebbc2 f1fec7d c0e1bed fae1257 6f41554 c6a2960 74a132d
git commit -m "revert: roll back full phase 15 safety chrome to pre-15A baseline"
```

After the revert the SPA loses the Phase 15 chrome (no Safety Pill, no Sync indicator, no diagnostics panel, no detail drawer, no manual refresh button, no audit timeline page, no rollback history modal, no Director Briefing badge), but: **the production database is untouched**, the **AI Kill Switch + Sandbox Mode + Rollback System (Phase 14D/14E/14F) remain functional from the Settings page**, the **kill switch stays Paused**, sandbox stays **OFF**, and no business state changes.

### 11.3 What the rollback does NOT do

- Does **not** flip `RuntimeKillSwitch` from `Paused` to `Running`.
- Does **not** enable any automation flag.
- Does **not** call any provider.
- Does **not** mutate any business row.
- Does **not** edit `.env.production`.
- Does **not** restart Celery beat or worker; existing beat schedule (11 / 12 / 13 daily entries depending on what's currently shipped) continues to run.

### 11.4 Post-rollback verification

After any rollback, run the §6 smoke checklist again — items that depended on the reverted chrome will be absent, but the underlying Phase 14D/14E/14F safety state must remain consistent: AI Paused, Sandbox OFF, no business mutation. If the Director observes any business-state drift after a rollback, that is a P0 bug — investigate immediately and notify the Director.

---

> **End of Phase 15M Director Sign-off Pack.** Safety foundation v1.0 is frozen. *(As authored at Phase 15M sign-off, the next planned work was Phase 16A — Business MVP Gap Audit. Phase 16A and Phase 16B have since shipped; Phase 16B is PRODUCTION VERIFIED + CLOSED at `00c3295`, and the current next planned work is **Phase 16C — Director Daily Briefing + Team Roles UI**, separate Director directive required. See the supersession note at the top of this file and `nd.md` head-of-file for current truth.)*
