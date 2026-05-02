# Frontend Audit

Frontend was generated using Lovable, then refined for the AI command-center
direction.

## Status (current)

Phase 6H SaaS admin update: Phase 6G Controlled Runtime Routing Dry Run is
**FULL PASS**. `/saas-admin` now includes a read-only/admin-safe
"Controlled Runtime Live Audit Gate" section backed by backend-computed
Phase 6H APIs. It shows global live safety state, default-enabled kill
switch, operation gate table, approval queue, recent gate audit events, and
warnings. Runtime providers still use env/config, default dry-run remains
true, live execution remains blocked, and approving in Phase 6H does not
execute external calls. No raw secrets, raw payloads, or full phone numbers
are rendered.

Phase 5F-Gate pilot readiness update: `/whatsapp-monitoring` now includes
a read-only "Approved Customer Pilot Readiness" section backed by
`/api/v1/whatsapp/monitoring/pilot/`. Phones are masked, blockers and
daily caps render from the backend, and there are no send / enable /
approve / pause buttons. Auto-reply remains OFF, campaigns/broadcast stay
locked, and the customer pilot requires explicit consent + approval. The
earlier 4-hour soak was accelerated, not full-duration.

Item | Status
--- | ---
Phase 6H `/saas-admin` | done - SaaS admin panel now includes Controlled Runtime Live Audit Gate with global kill-switch state, operation policies, approval queue, and recent audit events; no provider execution, WhatsApp send/enable, payment/shipment/call, campaign, or org-switch mutation controls.
All 21 pages exist | done — Phase 3C added Scheduler page; Phase 3D added Governance page; Phase 4B enhanced the Rewards page; Phase 4C added an Approval queue table on Governance; Phase 4D added an Execute button on approved rows; Phase 4A added a `services/realtime.ts` WebSocket client wired into the Dashboard "Live Activity" feed and the Governance "Approval queue"; Phase 4E is backend-only; Phase 5A added a read-only `/whatsapp-templates` page + Settings → WABA section + new "Messaging" sidebar group; Phase 5B added a three-pane `/whatsapp-inbox` page + Customer 360 WhatsApp tab; Phase 5C replaces the Phase 5B "AI suggestions disabled" placeholder with a live `AiAgentPanel`; Phase 5D adds a "Call customer" button on the `AiAgentPanel` + handoff and lifecycle event endpoints; **Phase 5E** adds a Rescue Discount cap card to the `AiAgentPanel` (current cumulative %, cap remaining out of 50%, customer ask count) plus six new TS types (`DiscountOffer`, `DiscountOfferListResponse`, `CreateRescueOfferPayload`, `DiscountOfferCap`, `ReorderDay20StatusResponse`, `ReorderDay20RunResponse`) and six new `api` methods (`getOrderDiscountOffers`, `createRescueDiscountOffer`, `acceptRescueDiscountOffer`, `rejectRescueDiscountOffer`, `getReorderDay20Status`, `runReorderDay20Sweep`). All cap math and CEO escalation logic lives in the backend (`apps.orders.rescue_discount`); the frontend renders cap state and dispatches API calls only.
Pages go through `src/services/api.ts` only | done — no page imports `mockData.ts` directly
TypeScript shared types in `src/types/domain.ts` | done
Sidebar collapse layout | done — shared collapsed state
Mobile responsiveness | baseline done — KPI stack, sidebar drawer, tables horizontal-scroll on small screens; per-page tuning continues
Dashboard polish | baseline done — premium spacing, hierarchy, executive feel; iterate as needed
Workflow visuals | UI-component diagrams in `WorkflowMap`
Vitest tests | Phase 6H SaaS admin tests cover live gate render, kill switch, operation table, approval queue, warning text, no raw secrets/full phones, and no provider execution buttons.
ESLint warnings | 8 pre-existing shadcn warnings (`react-refresh/only-export-components`); 0 errors
Mock fallback in `api.ts` | done — pages never break when backend is offline

## Backend wiring

`src/services/api.ts` calls `${VITE_API_BASE_URL}/...` (default
`http://localhost:8000/api`). On any network or HTTP failure, the request
falls back to the deterministic fixtures in `mockData.ts`.

To talk to the real backend in dev:

```bash
copy .env.example .env       # cp on macOS/Linux
# Backend running at :8000:
cd ../backend && python manage.py runserver 0.0.0.0:8000
# Frontend:
cd ../frontend && npm run dev
```

## Open improvements

- Iterate per-page mobile tuning where data tables remain dense.
- Replace placeholder login flow when JWT auth is wired (Phase 2).
- Bundle is ~900 KB gzipped to ~257 KB — code-split heavy charts (recharts is
  the dominant chunk) when bundle size matters.

## Page inventory (Phase 3D)

| Route | Page | Phase | Notes |
| --- | --- | --- | --- |
| `/` | `Index.tsx` | 1 | Command Center dashboard |
| `/leads` | `Leads.tsx` | 1 / 2A | Leads CRM |
| `/customers` | `Customers.tsx` | 1 / 2A | Customer 360 |
| `/calling` | `Calling.tsx` | 1 / 2D | AI Calling Console |
| `/orders` | `Orders.tsx` | 1 / 2A | Orders Pipeline |
| `/confirmation` | `Confirmation.tsx` | 1 / 2A | Confirmation Queue |
| `/payments` | `Payments.tsx` | 1 / 2B | Payments — Razorpay link generation |
| `/delivery` | `Delivery.tsx` | 1 / 2C | Delhivery + Tracking |
| `/rto` | `Rto.tsx` | 1 / 2A | RTO Rescue Board |
| `/agents` | `Agents.tsx` | 1 | AI Agents Center |
| `/ceo-ai` | `CeoAi.tsx` | 1 / 3B | CEO AI Briefing |
| `/caio` | `Caio.tsx` | 1 / 3B | CAIO Audit Center |
| `/ai-scheduler` | `Scheduler.tsx` | 3C | Celery beat + cost / fallback snapshot (admin/director only on the API) |
| `/ai-governance` | `Governance.tsx` | 3D | Sandbox toggle + prompt version rollback + per-agent USD budgets |
| `/rewards` | `Rewards.tsx` | 1 | Reward & Penalty leaderboard |
| `/learning` | `Learning.tsx` | 1 | Call Learning Studio |
| `/claims` | `Claims.tsx` | 1 | Claim Vault |
| `/analytics` | `Analytics.tsx` | 1 | Analytics |
| `/whatsapp-inbox` | `WhatsAppInbox.tsx` | 5B | Three-pane manual-only WhatsApp inbox + internal notes + manual template send + AI-suggestions-disabled placeholder |
| `/whatsapp-templates` | `WhatsAppTemplates.tsx` | 5A | Meta-mirrored WhatsApp templates (read-only) + Sync from Meta button |
| `/whatsapp-monitoring` | `WhatsAppMonitoring.tsx` | 5F-Gate | Read-only auto-reply safety dashboard + Approved Customer Pilot Readiness; masked phones only; no send/enable controls |
| `/saas-admin` | `SaasAdmin.tsx` | 6E-6H | SaaS admin panel: organization overview, org/write readiness, integration readiness, safety locks, runtime routing preview, AI provider routing preview, Controlled Runtime Live Audit Gate; no activation/send/provider-execution controls |
| `/settings` | `Settings.tsx` | 1 / 5A | Settings & Control + WABA section |

Phase 6H note: `/saas-admin` now includes live-gate visibility only. Approval buttons, when used, call backend audit endpoints that still do not execute providers.
Current total: 23 pages. Sidebar groups include Overview, Sales, Operations, AI Layer, Governance, Insights, Messaging, and System.
