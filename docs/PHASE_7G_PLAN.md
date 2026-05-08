# Phase 7G — One-shot Delhivery TEST/MOCK Courier Execution Gate

> Persisted plan. Source of truth for Phase 7G implementation. If
> this doc and `nd.md` disagree, `nd.md` wins; this doc must be
> updated to match.
>
> **Phase 7G-Hotfix-1 — Structured UTC Window Guard for Delhivery
> execute command — SHIPPED.** `execute_phase7g_courier_one_shot`
> (and the `execute_delhivery_courier_one_shot` CLI) now refuse to
> dispatch unless `--director-signoff` contains literal
> `BEGIN_UTC=<ISO-Z>` / `END_UTC=<ISO-Z>` markers, parsed window
> length ≤ 15 minutes (reuses `apps.saas.utc_window.validate_within_director_window`
> with `max_window_seconds=900`), window not stale > 24h,
> `END_UTC > BEGIN_UTC`, and `now ∈ [window_start, window_end]`.
> Refusal happens **before** the lazy `_create_awb_via_dedicated_wrapper`
> import + Delhivery client touch (asserted in every refusal test
> with `mock.MagicMock.assert_not_called`). On success the parsed
> window is persisted via `recorded_signoff_window_valid=True` +
> `recorded_signoff_window_start_utc` + `recorded_signoff_window_end_utc`
> (nullable fields already on `RazorpayCourierExecutionAttempt`
> from Phase 7G migration `payments.0016` — no new migration). New
> blockers: `phase7g_director_signoff_missing_structured_utc_window`,
> `phase7g_director_signoff_malformed_structured_utc_window`,
> `phase7g_director_signoff_window_too_long_max_15_min`,
> `phase7g_director_signoff_window_stale_more_than_24h_old`,
> `phase7g_now_before_director_signoff_utc_window_start`,
> `phase7g_now_after_director_signoff_utc_window_end`.
>
> **Phase 7G-Live (real customer courier execution) remains NOT
> approved as of this commit.** Phase 7G is the only currently
> approved design path in this controlled Phase 7 chain that may
> later issue one Delhivery TEST/MOCK API request after fresh
> Director approval.

---

## 0. Summary

Phase 7G converts an **approved Phase 7F courier readiness gate**
into a one-shot Delhivery **TEST/MOCK** courier execution attempt.
Even after implementation, the actual `execute_*` CLI requires a
fresh, dated, written Director directive AND a structured UTC
window AND every safety gate green at runtime to issue exactly one
`delhivery_client.create_awb` request against a synthetic
internal-only payload.

**Critical scope decision (per Shipment model compatibility
inspection):** Phase 7G **does NOT create a `Shipment` row** at
execute time. The existing `apps.shipments.Shipment` model has a
`customer` `CharField(max_length=120)` that stores plain customer
names and would surface a synthetic Phase 7G row in operator
dashboards / RTO boards / shipment listings. Forcing a synthetic
`customer="Phase 7G TEST"` string into that field violates the
"do not force fake real Order/Customer references" guardrail.
Provider / AWB summary is recorded on
`RazorpayCourierExecutionAttempt` only. `shipment_created` stays
`False` permanently. `business_mutation_was_made` stays `False`
permanently.

Phase 7G **never** sends WhatsApp, **never** queues an outbound,
**never** calls Meta Cloud, **never** calls Razorpay, **never**
calls Vapi, **never** sends a customer notification, **never**
books a courier pickup, **never** generates a courier label,
**never** creates a `Shipment` / `WorkflowStep` / `RescueAttempt`
row, **never** mutates real `Order` / `Payment` / `Customer` /
`Lead` / `DiscountOfferLog` rows, **never** edits any `.env*`
file.

---

## 1. Locked decisions for this implementation

- **Archive command:** **DEFERRED.** No `archive_*` CLI in
  Phase 7G.
- **Recover command:** **DEFERRED.** No `recover_*` CLI in
  Phase 7G. (Future Phase 7G-Hotfix may add it if an orphan-AWB
  scenario is observed in practice.)
- **Model name:** **`RazorpayCourierExecutionAttempt`** (chain
  naming).
- **Execute-window cap:** **`max_window_seconds=900`** (15
  minutes; same as Phase 7D-Hotfix-1 default).
- **Phase 7G scope:** **TEST/MOCK only.** Phase 7G-Live (real
  customer courier flow) remains NOT approved.
- **Shipment row write:** **DISABLED.** Phase 7G does not write a
  `Shipment` row — see Summary above.

---

## 2. Source-chain requirements

1. `RazorpayCourierReadinessGate(pk=phase7f_gate_id)` exists.
2. Phase 7F gate `status ==
   APPROVED_FOR_FUTURE_PHASE7G_OR_COURIER_EXECUTION_REVIEW`.
3. Phase 7F gate `dry_run_passed=True` AND
   `rollback_dry_run_passed=True` AND
   `phase7d_hotfix_1_present=True`.
4. Source Phase 7E gate is `APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW`.
5. Source Phase 7D attempt: `status in {EXECUTED, ROLLED_BACK}`,
   `rollback_status == COMPLETED`, `provider_call_attempted ==
   True`, all 12 mutation/send/courier/notification booleans
   `False`.
6. Source Phase 7B gate: `APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW`.
7. Source Phase 6T audit lock:
   `LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW`.
8. `RuntimeKillSwitch(scope=GLOBAL).enabled == True`.
9. `DELHIVERY_MODE in {"mock", "test"}` for prepare/approve/execute.
   `live` is refused at every step. Live customer courier execution
   is a separate Phase 7G-Live decision and remains **not approved**.
10. WhatsApp automation flags **all `False`** (six flags).
11. Phase 6K / 7D execute-related env flags **all `False`** (four
    flags).
12. `apps.saas.utc_window.parse_director_signoff_window` AND
    `apps.saas.utc_window.validate_within_director_window` are
    importable (Phase 7D-Hotfix-1 must be shipped). Re-checked at
    execute time.
13. **No prior** `RazorpayCourierExecutionAttempt` exists for this
    Phase 7F gate with `status in
    {APPROVED_FOR_ONE_SHOT_RUN, EXECUTED, FAILED}`.

---

## 3. Status lifecycle (9 states)

```text
draft → pending_director_signoff → approved_for_one_shot_courier_test_or_live_review
                                       │
                                       ├→ rejected → archived
                                       │
                                       ▼
                                    executed → rolled_back_recorded → archived
                                       │                  ▲
                                       └→ failed ─────────┘
                                       
blocked ←─ invariant violation / kill switch off / source-chain bad /
            Hotfix-1 missing / DELHIVERY_MODE=live
```

Approval is a status transition only. It does NOT call Delhivery.
Only the dedicated `execute_delhivery_courier_one_shot` CLI may, at
runtime, issue exactly one `delhivery_client.create_awb` request
after re-validating every gate.

---

## 4. Locked-False booleans (asserted by guard + tests)

```text
delhiveryCallAllowedOnlyAtExecute              = True   # scoped
shipmentCreationAllowed                        = False  # never (model compat)
shipmentCreated                                = False  # never (model compat)
awbCreationAllowedOnlyAtExecute                = True   # scoped
pickupBookingAllowed                           = False
labelGenerationAllowed                         = False
whatsappSendAllowed                            = False
whatsappQueueAllowed                           = False
metaCloudCallAllowed                           = False
razorpayCallAllowed                            = False
customerNotificationAllowed                    = False
businessMutationAllowed                        = False  # always False (no Shipment row write)
realCustomerAllowed                            = False
providerCallAttempted                          = False  # before execute
delhiveryCallAttempted                         = False  # before execute
awbCreated                                     = False  # before execute
customerNotificationSent                       = False  # always
realOrderMutationWasMade                       = False
realPaymentMutationWasMade                     = False
realShipmentMutationWasMade                    = False  # always (no Shipment row)
phase7GApprovalImpliesLiveCourier              = False
phase7GExecutePathIsSingleShot                 = True
phase7GRollbackIsRecordOnlyUnlessSeparatelyApproved = True
phase7GRequiresStructuredUtcWindowGuard        = True
phase7GIsTestOrMockModeOnly                    = True
phase7GLiveCustomerCourierFlowApproved         = False
```

---

## 5. Models (one migration: `payments.0016_phase7g_courier_execution_attempt`)

### `payments.RazorpayCourierExecutionAttempt`

Key fields:

- `source_phase7f_gate FK PROTECT` (required)
- `source_phase7e_gate FK PROTECT` (denormalised)
- `source_phase7d_attempt FK PROTECT` (denormalised)
- `source_phase7b_gate FK PROTECT` (denormalised)
- `source_phase6t_lock FK PROTECT, null=True, blank=True`
- `status CharField(max_length=64)` — 9 states
- `delhivery_mode_at_each_step JSONField`
- `delhivery_env_token_present BooleanField` (presence-only)
- `delhivery_env_base_url_present BooleanField`
- `delhivery_env_pickup_location_present BooleanField`
- `delhivery_env_return_address_present BooleanField`
- `kill_switch_snapshot_at_each_step JSONField`
- `env_flag_snapshot_at_each_step JSONField`
- `safety_invariants_snapshot JSONField`
- `before_counts JSONField`, `after_counts JSONField`
- `synthetic_order_id CharField(max_length=64)` —
  `phase7g::ctrl_courier::gate::<G>::attempt::<A>` (NOT a real
  `Order.id`)
- `synthetic_payload_summary JSONField` — locked template:
  ```
  {
    "customer_name_redacted": "Phase 7G TEST",
    "customer_phone_last4": "<last-4 from Phase 7F gate>",
    "address_line_redacted": "[redacted Phase 7G internal test address]",
    "pin_code_prefix": "11",
    "weight_grams": 100,
    "mode": "Prepaid",
    "payment_amount_inr": 0
  }
  ```
- `idempotency_key CharField unique` =
  `phase7g::courier_execution::phase7f_gate::<phase7f_gate_pk>`
- `provider_object_id CharField(max_length=64)` (the AWB returned)
- `provider_status CharField(max_length=64)`
- `safe_request_summary JSONField` (whitelist:
  `{order_id, weight_grams, mode, payment_amount_inr,
  customer_phone_last4, pin_code_prefix}`)
- `safe_response_summary JSONField` (whitelist:
  `{awb, status, used_mock, raw_keys}`)
- `provider_call_attempted BooleanField`
- `delhivery_call_attempted BooleanField`
- `awb_created BooleanField`
- `shipment_created BooleanField` (always False; recorded for
  contract clarity)
- `business_mutation_was_made BooleanField` (always False; no
  Shipment row write)
- `real_order_mutation_was_made BooleanField` (always False)
- `real_payment_mutation_was_made BooleanField` (always False)
- `real_shipment_mutation_was_made BooleanField` (always False)
- `customer_notification_sent BooleanField` (always False)
- `idempotency_lock_acquired BooleanField`
- `recorded_signoff_window_valid BooleanField(null=True)`
- `recorded_signoff_window_start_utc DateTimeField(null=True)`
- `recorded_signoff_window_end_utc DateTimeField(null=True)`
- `director_signoff_text TextField` (stored; serializer NEVER returns)
- `director_signoff_present BooleanField`
- `operator_name CharField`
- `confirm_one_shot_courier_execution BooleanField`
- `mode_acknowledgement CharField(max_length=16)` (`"mock"` /
  `"test"`)
- `rollback_record_only_acknowledged BooleanField`
- `rollback_status CharField(max_length=40, choices)`:
  `not_required` / `pending` /
  `recorded_only_no_provider_cancel` /
  `cancellation_attempted_separately`
- `rolled_back_at`, `rollback_reason`, `archive_reason`,
  `reject_reason`
- `executed_at` / `failed_at` / `archived_at` / `rejected_at` /
  `approved_at` timestamps
- `requested_by` / `reviewed_by` / `executed_by` / `rolled_back_by`
  / `archived_by` / `rejected_by` FKs (`accounts.User SET_NULL`)
- `created_at` / `updated_at`
- `organization` / `branch` FKs
- `audit_event_id BigIntegerField(null=True)`

### `payments.RazorpayCourierExecutionRollback`

Mirrors Phase 7D rollback record. **Record-only** semantics:

- `attempt FK CASCADE`
- `verified_at DateTimeField`
- `rollback_status CharField` — `pending` /
  `recorded_only_no_provider_cancel` /
  `cancellation_attempted_separately`. **Never `completed`.**
- `rollback_reason TextField`
- `cancellation_attempted BooleanField(default=False)`
- `cancellation_attempted_by_command CharField(blank, default="")`
- `provider_object_id_recorded CharField(max_length=64)`
- `env_flag_presence_at_rollback JSONField`
- `evaluated_safety_invariants JSONField`
- `recovery_notes TextField`
- `idempotency_key CharField unique`
- `created_at`

Migration is a pure `CreateModel × 2`. No `RunPython`. No edits to
existing tables.

---

## 6. Three new env flags (mirrors Phase 7D pattern; defaults False)

```python
PHASE7G_COURIER_EXECUTION_ENABLED                  = False
PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION = False
PHASE7G_ALLOW_DELHIVERY_TEST_AWB                   = False
```

`execute_delhivery_courier_one_shot` refuses unless **all three**
are `True` at runtime AND `DELHIVERY_MODE in {"mock", "test"}` AND
the kill switch is enabled AND the structured Director sign-off
window is currently open.

---

## 7. Execute-window guard (reuses Hotfix-1)

`execute_delhivery_courier_one_shot` calls
`apps.saas.utc_window.parse_director_signoff_window` +
`apps.saas.utc_window.validate_within_director_window`
(default `max_window_seconds=900` — kept at 15 minutes).

Translated blockers:

```
phase7g_director_signoff_missing_structured_utc_window
phase7g_now_outside_director_signoff_utc_window
phase7g_director_signoff_window_too_long_max_15_min
phase7g_director_signoff_window_stale_more_than_24h_old
phase7g_director_signoff_malformed_structured_utc_window
phase7g_director_signoff_must_reference_source_phase7f_gate_id
phase7d_hotfix_1_must_be_shipped_before_phase7g_execute
```

The execute command refuses if the sign-off body does not literally
contain `phase7f_gate_id_<ID>` (mirrors Phase 7E's
`phase7d_attempt_id_<ID>` pattern).

Persists `recorded_signoff_window_valid=True` +
`recorded_signoff_window_start_utc` +
`recorded_signoff_window_end_utc` on the attempt row before any
SDK call.

---

## 8. CLI arguments for `execute_delhivery_courier_one_shot`

```text
--attempt-id <ID>                                # int; positive
--confirm-one-shot-courier-execution             # required boolean flag
--director-signoff "..."                         # must contain BEGIN_UTC=, END_UTC=, phase7f_gate_id_<ID>
--operator-name "..."                            # non-empty string
--mode-acknowledgement <mock|test>               # must equal current DELHIVERY_MODE; "live" refused
--acknowledge-rollback-record-only               # required boolean flag
--json                                           # optional output mode
```

---

## 9. Management commands (8; archive + recover deferred)

| # | Command | Purpose |
|---|---|---|
| 1 | `inspect_delhivery_courier_execution_readiness [--no-audit] [--json]` | Read-only readiness. |
| 2 | `preview_delhivery_courier_execution_attempt --phase7f-gate-id <ID> [--json]` | Read-only preview. Never creates rows. |
| 3 | `prepare_delhivery_courier_execution_attempt --phase7f-gate-id <ID> [--json]` | Atomic, idempotent. Status `pending_director_signoff`. |
| 4 | `approve_delhivery_courier_execution_attempt --attempt-id <ID> --reason "…" [--json]` | `require_reason=True`. **No `--director-signoff`** at approve. Sets status `approved_for_one_shot_courier_test_or_live_review`. |
| 5 | `reject_delhivery_courier_execution_attempt --attempt-id <ID> --reason "…" [--json]` | `require_reason=True`. Refuses unless attempt is `draft` / `pending_director_signoff`. |
| 6 | `inspect_delhivery_courier_execution_attempts [--limit N] [--json]` | Read-only summary. |
| 7 | `execute_delhivery_courier_one_shot --attempt-id <ID> --confirm-one-shot-courier-execution --director-signoff "…" --operator-name "…" --mode-acknowledgement <mock\|test> --acknowledge-rollback-record-only [--json]` | The **only** Phase 7G command that may issue a Delhivery API request. Single-shot. |
| 8 | `rollback_delhivery_courier_execution_attempt --attempt-id <ID> --reason "…" [--json]` | `require_reason=True`. **Record-only.** Never calls Delhivery cancel. |

**Forbidden imports** (asserted by static-file scan):

- `apps.shipments.services.create_shipment`
- `apps.shipments.services.create_rescue_attempt`
- `apps.shipments.services.update_rescue_outcome`
- `apps.whatsapp.services.send_freeform_text_message`
- `apps.whatsapp.services.send_queued_message`
- `apps.whatsapp.services.queue_template_message`
- `apps.whatsapp.integrations.whatsapp.meta_cloud_client`
- `apps.payments.integrations.razorpay_client`
- `dotenv` (any form)

`apps.shipments.integrations.delhivery_client.create_awb` IS
allowed but ONLY via lazy local-scope import inside the
`_create_awb_via_dedicated_wrapper` helper called by
`execute_phase7g_courier_one_shot`. Static-file scan asserts no
top-level `from apps.shipments.integrations.delhivery_client
import create_awb` line.

---

## 10. Audit kinds (13, all ≤ 64 chars)

```text
razorpay.courier_execution.readiness_inspected
razorpay.courier_execution.previewed
razorpay.courier_execution.attempt_prepared
razorpay.courier_execution.approved_for_one_shot
razorpay.courier_execution.executed
razorpay.courier_execution.failed
razorpay.courier_execution.rolled_back_recorded
razorpay.courier_execution.archived
razorpay.courier_execution.blocked
razorpay.courier_execution.kill_switch_blocked
razorpay.courier_execution.invariant_violation
razorpay.courier_execution.window_guard_blocked
razorpay.courier_execution.rejected
```

Audit payloads NEVER carry: `token`, `phone`, `email`, `address`,
`pincode`, `pin_code`, `name`, `card`, `vpa`, `upi`, `bank_account`,
`wallet`, `verify_token`, `app_secret`, `META_WA_TOKEN`,
`META_WA_APP_SECRET`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`, `DELHIVERY_API_TOKEN`, `raw_payload`,
`raw_signature`, `raw_secret`. Director-supplied `--reason` is
recorded as `reason_excerpt[:120]`. `--director-signoff` is
recorded as `signoff_window_only={start, end,
attempt_id_referenced}` only.

---

## 11. Read-only DRF endpoints (5)

Mounted under `/api/v1/saas/delhivery/`. Auth + admin only.
POST/PATCH/DELETE return 405 on every endpoint.

| Method | Path |
|---|---|
| GET | `/api/v1/saas/delhivery/courier-execution-readiness/` |
| GET | `/api/v1/saas/delhivery/courier-execution-attempts/?limit=N` |
| GET | `/api/v1/saas/delhivery/courier-execution-attempts/<int:pk>/` |
| GET | `/api/v1/saas/delhivery/courier-execution-preview/?phase7f_gate_id=<ID>` |
| GET | `/api/v1/saas/delhivery/courier-execution-rollbacks/<int:attempt_id>/` |

---

## 12. Frontend `/saas-admin` section

`data-testid="delhivery-courier-execution-section"`.

Read-only. No buttons. Phase 7G section shows kill switch, Delhivery
mode, three Phase 7G env flags (all green when `false`), Phase 7F
approved-gate count, Phase 7G attempt counts per status,
locked-False rows, "CLI-only Execution Path" banner, 33 forbidden
actions.

---

## 13. Verification commands

```bash
cd backend
python manage.py makemigrations --check --dry-run    # expect: No changes detected
python manage.py check                               # expect: 0 issues
python -m pytest -q                                  # target: ~1860 passed
python manage.py inspect_delhivery_courier_execution_readiness --json --no-audit
# expect: phase=7G, status=courier_one_shot_test_mock_execution,
#         3 PHASE7G_* env flags all False, all locked-False booleans False,
#         nextAction=enable_phase7g_courier_execution_flag_for_review_only

cd ../frontend
npm run lint                                         # expect: 0 errors
npm test                                             # target: 72 passed
npm run build                                        # expect: OK

cd ..
git diff --cached --name-only | grep -E "(\.env$|\.env\.|db\.sqlite3)" || echo "clean"
```

Commit message: `feat: add phase 7g delhivery courier one-shot execution gate`. Push to `origin/main`.

**Operator MUST NOT run `execute_delhivery_courier_one_shot` during the implementation turn.** The command lands in the codebase but is never invoked. The three Phase 7G env flags remain `false` in every environment.

---

## 14. Phase 7G-Live (real customer courier flow) prerequisites

Before any future Phase 7G-Live can proceed:

1. Phase 7G TEST/MOCK gate must have been executed once and
   reviewed end-to-end without business or customer impact.
2. A separate Phase 7G-Live plan must be drafted and approved.
3. A new env flag (e.g. `PHASE7G_LIVE_CUSTOMER_COURIER_ENABLED`)
   must be added with default `false`.
4. A new audit-trail layer for real Order / Customer linkage must
   be designed (since Phase 7G default scope intentionally avoids
   this).
5. Director directive that names the exact Phase 7G TEST attempt
   id AND the Phase 7G-Live use case AND the structured UTC
   window markers.

Phase 7G-Live is **not approved** as of this commit and is **not
designed** in this turn.
