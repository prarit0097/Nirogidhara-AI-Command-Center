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
- `rescue.attempted` / `rescue.updated` — explicit, on POST/PATCH `/rto/rescue/`

Phase 2B+ will add: reward/penalty assigned, prompt updated, rollback performed,
CAIO audit completed, CEO approval recorded.

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
| POST | `/api/shipments/` | Mock Delhivery dispatch. Body: `{ orderId }`. Generates `DLH<8 digits>` AWB and a 5-step timeline. |
| POST | `/api/rto/rescue/` | Create a rescue attempt. Body: `{ orderId, channel, notes? }`. |
| PATCH | `/api/rto/rescue/{id}/` | Update outcome. Body: `{ outcome, notes? }`. Bubbles up to parent order's `rescue_status`. |

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
