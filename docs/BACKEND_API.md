# Backend API Reference

Django REST Framework endpoints exposed by `backend/`. Every entry is consumed
by `frontend/src/services/api.ts`. Response shapes match the TypeScript
interfaces in `frontend/src/types/domain.ts`.

All paths are prefixed by `/api/`. JSON in, JSON out. CORS allows
`http://localhost:8080` by default.

## Health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/healthz/` | Liveness probe |

## Auth

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/auth/token/` | none | JWT login (`{username, password}`) |
| POST | `/api/auth/refresh/` | refresh token | Rotate access token |
| GET | `/api/auth/me/` | bearer access | Current user + role |
| GET | `/api/settings/` | none | Approval matrix + integration flags + kill-switch state |

## Dashboard

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/dashboard/metrics/` | `Record<string, DashboardMetric>` |
| GET | `/api/dashboard/activity/` | `ActivityEvent[]` (last 25 audit-ledger rows) |

## CRM

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/leads/` | `Lead[]` |
| GET | `/api/leads/{id}/` | `Lead` |
| GET | `/api/customers/` | `Customer[]` |
| GET | `/api/customers/{id}/` | `Customer` |

## Orders

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/orders/` | `Order[]` |
| GET | `/api/orders/pipeline/` | `Order[]` (sorted by stage) |
| GET | `/api/confirmation/queue/` | `(Order & {hoursWaiting, addressConfidence, checklist})[]` |

## Calls

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/calls/` | `Call[]` |
| GET | `/api/calls/active/` | `ActiveCall` (latest) |
| GET | `/api/calls/active/transcript/` | `CallTranscriptLine[]` |

## Payments / Shipments / RTO

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/payments/` | `Payment[]` |
| GET | `/api/shipments/` | `Shipment[]` (with `timeline`) |
| GET | `/api/rto/risk/` | `(Order & {riskReasons, rescueStatus})[]` |

## Agents & AI Governance

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/agents/` | `Agent[]` |
| GET | `/api/agents/hierarchy/` | `{root, ceo, caio, departments}` |
| GET | `/api/ai/ceo-briefing/` | `CeoBriefing` (latest) |
| GET | `/api/ai/caio-audits/` | `CaioAudit[]` |

## Compliance / Rewards / Learning

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/compliance/claims/` | `Claim[]` (Approved Claim Vault) |
| GET | `/api/rewards/` | `RewardPenalty[]` |
| GET | `/api/learning/recordings/` | `LearningRecording[]` |

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
Signals in `apps/audit/signals.py` write rows on:

- Lead created
- Order created / order status changed
- Payment received (status = Paid only)
- Shipment status changed

Phase 2 will add: reward/penalty assigned, prompt updated, rollback performed,
CAIO audit completed, CEO approval recorded.
