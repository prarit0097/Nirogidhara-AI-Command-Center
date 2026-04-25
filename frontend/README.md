# Nirogidhara AI Command Center Frontend

Premium React/Vite prototype for Nirogidhara Private Limited's Ayurveda + AI operating system. The app models the full lead-to-delivery workflow with mock data only and is structured for a future Django REST Framework backend.

## Tech Stack

- React 18 + Vite
- TypeScript
- Tailwind CSS + shadcn-style UI components
- React Router
- Recharts
- Vitest + Testing Library

## Setup

```bash
npm install
npm run dev
npm run build
npm run lint
npm test
```

## Pages

- Command Center Dashboard
- Leads CRM
- Customer 360
- AI Calling Console
- Orders Pipeline
- Confirmation Queue
- Payments
- Delhivery & Delivery Tracking
- RTO Rescue Board
- AI Agents Center
- CEO AI Briefing
- CAIO Audit Center
- Reward & Penalty Engine
- Human Call Learning Studio
- Claim Vault & Compliance
- Analytics
- Settings & Control Center

## Mock API Layer

All page data must go through `src/services/api.ts`. `src/services/mockData.ts` is an internal data source for the mock API layer and should not be imported by pages or UI components.

Future endpoint placeholders are documented in `api.ts`, including `/api/dashboard/metrics`, `/api/leads`, `/api/customers`, `/api/orders`, `/api/calls`, `/api/payments`, `/api/shipments`, `/api/agents`, `/api/ai/ceo-briefing`, `/api/ai/caio-audits`, `/api/rewards`, `/api/compliance/claims`, and `/api/learning/recordings`.

## Future Django Integration

Keep the frontend API-first:

- Replace `api.ts` mock returns with authenticated `fetch`/client calls.
- Preserve the exported function names where practical to avoid page churn.
- Keep business execution in the backend. The frontend should visualize workflows, approvals, audit states, and mock actions.
- Do not add Supabase or real payment, courier, voice, or ad platform integrations in this prototype.

## Theme Guidelines

Preserve the premium Ayurveda + modern AI SaaS direction: deep green, emerald, teal, saffron/gold, ivory, charcoal, rounded premium cards, soft shadows, clean typography, and enterprise command-center density.
