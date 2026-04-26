# Frontend Audit

Frontend was generated using Lovable, then refined for the AI command-center
direction.

## Status (current)

Item | Status
--- | ---
All 17 pages exist | done
Pages go through `src/services/api.ts` only | done — no page imports `mockData.ts` directly
TypeScript shared types in `src/types/domain.ts` | done
Sidebar collapse layout | done — shared collapsed state
Mobile responsiveness | baseline done — KPI stack, sidebar drawer, tables horizontal-scroll on small screens; per-page tuning continues
Dashboard polish | baseline done — premium spacing, hierarchy, executive feel; iterate as needed
Workflow visuals | UI-component diagrams in `WorkflowMap`
Vitest tests | 8 tests passing (5 page/sidebar + 3 API fallback)
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
