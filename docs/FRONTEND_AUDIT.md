# Frontend Audit

Frontend was generated using Lovable, then refined for the AI command-center
direction.

## Status (current)

Item | Status
--- | ---
All 20 pages exist | done — Phase 3C added Scheduler page; Phase 3D added Governance page (no new pages added in 3E — backend-only phase). Phase 4B enhanced the existing Rewards page with agent-wise leaderboard + order-wise scoring events + sweep summary cards + Run Sweep button. **Phase 4C** appended an Approval queue table on the Governance page (Action / Mode / Approver / Target / Status / Proposed payload / Approve + Reject controls + decision-note input). **Phase 4D** added an Execution column + Execute button on approved rows. **Phase 4A** added a `services/realtime.ts` WebSocket client wired into the Dashboard "Live Activity" feed and the Governance "Approval queue" (snapshot + per-event push, dedupe by id, capped at 25 rows). **Phase 4E** is backend-only. **Phase 5A** adds a read-only `/whatsapp-templates` page (Meta-mirrored templates, claim-vault flag, sync button — admin/director only on the API), a Settings → WABA section showing provider / health / phone-number-id (masked) / app-secret + verify-token + access-token configured flags / API version / dev-provider toggle warning, and a sidebar entry under a new "Messaging" group.
Pages go through `src/services/api.ts` only | done — no page imports `mockData.ts` directly
TypeScript shared types in `src/types/domain.ts` | done
Sidebar collapse layout | done — shared collapsed state
Mobile responsiveness | baseline done — KPI stack, sidebar drawer, tables horizontal-scroll on small screens; per-page tuning continues
Dashboard polish | baseline done — premium spacing, hierarchy, executive feel; iterate as needed
Workflow visuals | UI-component diagrams in `WorkflowMap`
Vitest tests | 13 tests passing (5 page/sidebar + 3 API fallback + 5 realtime)
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
| `/whatsapp-templates` | `WhatsAppTemplates.tsx` | 5A | Meta-mirrored WhatsApp templates (read-only) + Sync from Meta button |
| `/settings` | `Settings.tsx` | 1 / 5A | Settings & Control + WABA section |

20 pages total. Sidebar groups: Overview · Sales · Operations · AI Layer (5 entries: Agents Center, CEO AI Briefing, CAIO Audit Center, AI Scheduler & Cost, AI Governance) · Governance · Insights · Messaging (Phase 5A) · System.
