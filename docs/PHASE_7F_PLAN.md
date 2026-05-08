# Phase 7F — Delhivery / Courier Controlled Readiness Gate

> Persisted plan. Source of truth for Phase 7F implementation. If
> this doc and `nd.md` disagree, `nd.md` wins; this doc must be
> updated to match.

---

## 0. Summary

Phase 7F adds a **gate-only, CLI-only, read-only-API courier
readiness layer** that turns an approved Phase 7E WhatsApp internal
notification gate into an audit-only "is the Delhivery surface
conceptually ready for a future Phase 7G courier execution?" record.

Phase 7F **never** calls the Delhivery API, **never** creates a
``Shipment`` / ``WorkflowStep`` / ``RescueAttempt`` row, **never**
creates an AWB, **never** books a pickup, **never** generates a
courier label, **never** mutates real ``Order`` / ``Payment`` /
``Customer`` / ``Lead`` / ``DiscountOfferLog`` rows, **never** sends
a customer notification, **never** sends or queues WhatsApp,
**never** calls Meta Cloud / Razorpay / Vapi, **never** edits any
``.env*`` file.

Approval flips status to
``approved_for_future_phase7g_or_courier_execution_review`` only —
it does **NOT** enable any provider call. Live courier dispatch
stays an explicit Phase 7G decision that requires a fresh, dated
Director directive AND a future "execute-window guard for
Delhivery" extension reusing
``apps.saas.utc_window.validate_within_director_window``.

---

## 1. Status lifecycle

```text
draft  ─────────►  pending_manual_review  ─────────►  approved_for_future_phase7g_or_courier_execution_review
  │                       │                                        │
  │                       ├─────────► rejected                     │
  │                       │                                        │
  │                       └─────────► archived ◄───────────────────┘
  │                                       ▲
  ▼                                       │
blocked ◄────── invariant violation / kill switch off / source-chain bad / Hotfix-1 missing / DELHIVERY_MODE=live
```

---

## 2. Source-chain requirements

1. ``RazorpayWhatsAppInternalNotificationGate(pk=phase7e_gate_id)``
   exists.
2. Phase 7E gate ``status ==
   APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW``.
3. Phase 7E gate ``dry_run_passed=True`` AND
   ``rollback_dry_run_passed=True`` AND ``claim_vault_grounded=True``.
4. Phase 7E gate
   ``phase7e_future_review_signoff_window_valid=True``.
5. Source Phase 7D attempt: ``status in {EXECUTED, ROLLED_BACK}``,
   ``rollback_status == COMPLETED``, ``provider_call_attempted ==
   True``, all 12 mutation/send/courier/notification booleans False.
6. Phase 7B gate ``APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW``.
7. Phase 6T audit lock
   ``LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW``.
8. ``RuntimeKillSwitch(scope=GLOBAL).enabled == True``.
9. ``DELHIVERY_MODE in {"mock", "test"}`` — refuses if ``live``.
10. ``WHATSAPP_PROVIDER == "mock"`` OR
    ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE == True``.
11. WhatsApp automation flags **all False** (six flags).
12. Phase 6K / 7D execute env flags **all False** (four flags).
13. ``apps.saas.utc_window.validate_within_director_window`` is
    importable (Phase 7D-Hotfix-1 must be shipped). If the import
    fails, prepare blocks with
    ``phase7d_hotfix_1_must_be_shipped_before_phase7f_review``.
14. Phase 7F service module **NEVER** imports the Delhivery client
    or shipments service (asserted by static-file scan).
15. **No prior ``Shipment`` row** referencing the source Phase 7D
    attempt exists (defence-in-depth — Phase 7D never created one).

---

## 3. Locked-False booleans (25, asserted by guard + tests)

```text
delhiveryCallAllowedInPhase7F                      = False
courierBookingAllowedInPhase7F                     = False
shipmentCreationAllowedInPhase7F                   = False
awbCreationAllowedInPhase7F                        = False
pickupBookingAllowedInPhase7F                      = False
labelGenerationAllowedInPhase7F                    = False
customerNotificationAllowedInPhase7F               = False
whatsappSendAllowedInPhase7F                       = False
whatsappQueueAllowedInPhase7F                      = False
metaCloudCallAllowedInPhase7F                      = False
razorpayCallAllowedInPhase7F                       = False
businessMutationAllowedInPhase7F                   = False
realCustomerAllowedInPhase7F                       = False
providerCallAttempted                              = False
delhiveryCallAttempted                             = False
shipmentCreated                                    = False
awbCreated                                         = False
pickupBooked                                       = False
labelGenerated                                     = False
customerNotificationSent                           = False
realOrderMutationWasMade                           = False
realPaymentMutationWasMade                         = False
realShipmentMutationWasMade                        = False
phase7FApprovalImpliesLiveCourier                  = False
phase7FRequiresFutureExecuteWindowGuardForCourier  = True
```

---

## 4. Models (one migration: `payments.0015_phase7f_courier_readiness_gate`)

### `payments.RazorpayCourierReadinessGate` (chain naming)

Fields:

- `source_phase7e_gate FK PROTECT` (required)
- `source_phase7d_attempt FK PROTECT` (required, denormalised)
- `source_phase7b_gate FK PROTECT` (required, denormalised)
- `source_phase6t_lock FK PROTECT, null=True, blank=True`
- `status CharField(max_length=64)` — 6 states
- `delhivery_mode_at_prepare CharField(max_length=16, default="mock")`
- `delhivery_env_token_present BooleanField(default=False)`
- `delhivery_env_base_url_present BooleanField(default=False)`
- `delhivery_env_pickup_location_present BooleanField(default=False)`
- `delhivery_env_return_address_present BooleanField(default=False)`
- `kill_switch_snapshot_at_each_step JSONField`
- `env_flag_snapshot_at_each_step JSONField`
- `dry_run_passed BooleanField(default=False)`
- `dry_run_failed_reasons JSONField(default=list)`
- `rollback_dry_run_passed BooleanField(default=False)`
- `rollback_dry_run_failed_reasons JSONField(default=list)`
- `source_phase7d_signoff_window_validation_status CharField`
  (`valid_structured_window` / `failed_or_legacy_free_text` /
  `not_applicable`)
- `phase7d_hotfix_1_present BooleanField(default=False)`
- `safety_invariants_snapshot JSONField`
- `before_counts JSONField`, `after_counts JSONField`
- `idempotency_key CharField unique` =
  `phase7f::courier_readiness::phase7e_gate::<phase7e_gate_pk>`
- `blockers JSONField(default=list)`, `warnings JSONField(default=list)`
- `next_action CharField`
- `reject_reason TextField`, `archive_reason TextField`
- `requested_by` / `reviewed_by` / `rejected_by` / `archived_by` FKs
- `created_at` / `updated_at` / `approved_at` / `rejected_at` /
  `archived_at`
- `organization` / `branch` FKs (Phase 6B convention)

**Notably absent:** `director_signoff_text`, phone, address,
pincode. Phase 7F holds zero customer PII and no signoff window
fields.

### `payments.RazorpayCourierReadinessDryRunRecord`

Mirrors Phase 7E's dry-run record (gate FK CASCADE, kind, status,
idempotency_key, snapshots, before/after counts, blockers/warnings,
reason, created_at).

Migration is a pure `CreateModel` × 2. No `RunPython`. No edits to
existing tables.

---

## 5. Management commands (8 — archive deferred)

1. `inspect_delhivery_courier_readiness [--no-audit] [--json]`
2. `preview_delhivery_courier_readiness_gate --phase7e-gate-id <ID>
   [--json]`
3. `prepare_delhivery_courier_readiness_gate --phase7e-gate-id <ID>
   [--json]`
4. `dry_run_delhivery_courier_readiness_gate --gate-id <ID> [--json]`
5. `rollback_dry_run_delhivery_courier_readiness_gate --gate-id <ID>
   --reason "…" [--json]` (require_reason=True)
6. `approve_delhivery_courier_readiness_gate --gate-id <ID>
   --reason "…" [--json]` (require_reason=True; **no
   `--director-signoff` argument**; refuses unless
   `dry_run_passed=True` AND `rollback_dry_run_passed=True` AND
   `phase7d_hotfix_1_present=True`)
7. `reject_delhivery_courier_readiness_gate --gate-id <ID> --reason
   "…" [--json]` (require_reason=True; refuses unless gate is
   `draft` / `pending_manual_review`)
8. `inspect_delhivery_courier_readiness_gates [--limit N] [--json]`

**Forbidden imports** (asserted by static-file scan):

- `apps.shipments.integrations.delhivery_client.create_awb`
- `apps.shipments.integrations.delhivery_client._create_via_sdk`
- `apps.shipments.services.create_shipment`
- `apps.shipments.services.create_rescue_attempt`
- `apps.shipments.services.update_rescue_outcome`
- `apps.whatsapp.services.send_freeform_text_message`
- `apps.whatsapp.services.send_queued_message`
- `apps.whatsapp.services.queue_template_message`
- `apps.whatsapp.integrations.whatsapp.meta_cloud_client`
- `apps.payments.integrations.razorpay_client`
- `dotenv` (any form)

Read-only count diagnostics on
`apps.shipments.models.{Shipment,WorkflowStep,RescueAttempt}` and
`apps.whatsapp.models.{WhatsAppMessage,WhatsAppLifecycleEvent,
WhatsAppHandoffToCall}` are allowed — **never** `.create()` /
`.update()` / `.save()`.

---

## 6. Audit kinds (13, all ≤ 64 chars)

```text
razorpay.courier_readiness.readiness_inspected
razorpay.courier_readiness.previewed
razorpay.courier_readiness.prepared
razorpay.courier_readiness.dry_run_passed
razorpay.courier_readiness.dry_run_failed
razorpay.courier_readiness.rb_dry_run_passed
razorpay.courier_readiness.rb_dry_run_failed
razorpay.courier_readiness.approved_future_courier
razorpay.courier_readiness.rejected
razorpay.courier_readiness.archived
razorpay.courier_readiness.blocked
razorpay.courier_readiness.kill_switch_blocked
razorpay.courier_readiness.invariant_violation
```

Audit payloads NEVER carry: `token`, `phone`, `email`, `address`,
`pincode`, `pin_code`, `card`, `vpa`, `upi`, `bank_account`,
`wallet`, `verify_token`, `app_secret`, `META_WA_TOKEN`,
`META_WA_APP_SECRET`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`, `DELHIVERY_API_TOKEN`, `raw_payload`,
`raw_signature`, `raw_secret`. Director-supplied `--reason` is
recorded as `reason_excerpt` (first 120 chars).

---

## 7. Read-only DRF endpoints (5)

Mounted under `/api/v1/saas/delhivery/`. Auth + admin only.
POST/PATCH/DELETE return 405 on every endpoint. **No POST endpoint
dispatches state changes.**

| Method | Path |
|---|---|
| GET | `/api/v1/saas/delhivery/courier-readiness/` |
| GET | `/api/v1/saas/delhivery/courier-readiness-gates/?limit=N` |
| GET | `/api/v1/saas/delhivery/courier-readiness-gates/<int:pk>/` |
| GET | `/api/v1/saas/delhivery/courier-readiness-preview/?phase7e_gate_id=<ID>` |
| GET | `/api/v1/saas/delhivery/courier-readiness-dry-runs/<int:gate_id>/` |

---

## 8. Frontend `/saas-admin` section

`data-testid="delhivery-courier-readiness-section"`.

Read-only:

- Phase badge (Phase 7B + 7D rolled-back + 7E approved + 7F
  readiness).
- Kill-switch status pill.
- Delhivery mode pill.
- Phase 7E approved gate count + Phase 7F gate counts per status.
- 25 locked-False rows (every row a green "No" pill).
- "CLI-only Review" banner + forbidden-actions chip cloud (31
  entries).

**No buttons.** Forbidden-button regex assertion in vitest.

---

## 9. Forbidden actions list (31 entries — count corrected)

```text
call_delhivery_api
call_delhivery_create_awb
call_delhivery_book_pickup
call_delhivery_generate_label
call_delhivery_track_awb
call_delhivery_cancel_awb
create_shipment_row
create_workflow_step_row
create_rescue_attempt_row
create_awb
book_courier_pickup
generate_courier_label
print_courier_label
send_customer_notification
send_whatsapp_template
send_whatsapp_freeform
queue_whatsapp_outbound
call_meta_cloud_api
call_razorpay_api
create_payment_link
capture_razorpay_payment
refund_razorpay_payment
mutate_real_order_status
mutate_real_payment_status
mutate_real_shipment_status
mutate_real_customer
mutate_real_lead
execute_via_frontend
execute_via_api_endpoint
approve_via_api_endpoint
edit_dotenv_any
```

---

## 10. Tests (~55)

Backend `tests/test_phase7f_courier_readiness.py`:

- Contract returns Phase 7F shape with all 23+ locked-False
  booleans False (parametrized).
- Audit-kind length (each ≤ 64 chars, parametrized × 13).
- Forbidden-actions list contains 31 entries.
- Forbidden payload-keys list contains 21 entries.
- Readiness command + endpoint shape; admin auth.
- POST/PATCH/PUT/DELETE → 405 on every GET endpoint
  (parametrized × 5).
- Detail endpoint 404; dry-runs endpoint 404.
- Preview never creates rows; preview endpoint requires
  `phase7e_gate_id`.
- Prepare blocked when env flag false / source Phase 7E gate not
  approved / source Phase 7D attempt status invalid / kill switch
  off / DELHIVERY_MODE=live / WhatsApp automation flag True / Phase
  6K-7D execute env flag True / Hotfix-1 absent / mutation booleans
  flipped on source attempt.
- Prepare creates gate row with all 25 locked-False booleans False;
  populates Delhivery env presence (booleans only).
- Prepare idempotent on same Phase 7E gate.
- Dry-run never creates Shipment / WorkflowStep / RescueAttempt /
  WhatsAppMessage / WhatsAppLifecycleEvent rows.
- Dry-run blocks if a `Shipment` row exists for the source attempt
  (defence-in-depth).
- Rollback-dry-run requires reason; sets flag only on full pass.
- Approve refuses without reason / without dry-run pass / without
  rollback-dry-run pass / without Hotfix-1.
- Approve flips status to
  `approved_for_future_phase7g_or_courier_execution_review` only.
- Second approve refused.
- Reject requires reason; refuses unless gate is draft /
  pending_manual_review.
- Defensive guard parametrized × 25.
- Static-file scans for forbidden imports (× 8).
- No raw secret / phone / address / pincode in any output.
- Provider mock spies (`create_awb`, `create_shipment`)
  `assert_not_called` across full lifecycle.
- Full-lifecycle smoke (prepare → dry-run → rollback-dry-run →
  approve): no business-row mutation across 11 tables.

Frontend `frontend/src/test/saas-admin.test.tsx` adds 2 cases:

- Renders the "Delhivery / Courier Readiness" section with all 25
  locked-False columns.
- Section never exposes a Create Shipment / Create AWB / Book
  Pickup / Generate Label / Call Delhivery / Send WhatsApp /
  Approve / Reject / Execute / Edit .env button.

Test-baseline target: 1705 → ~1760 backend, 68 → 70 frontend.

---

## 11. Verification commands

```bash
cd backend
python manage.py makemigrations --check --dry-run    # expect: No changes detected
python manage.py check                               # expect: 0 issues
python -m pytest -q                                  # target: ~1760 passed
python manage.py inspect_delhivery_courier_readiness --json --no-audit
# expect: phase=7F, status=courier_readiness_only,
#         all 23+ locked-False booleans False,
#         delhiveryEnvPresence keys present (booleans only),
#         nextAction=enable_phase7f_courier_readiness_gate_flag_for_review_only

cd ../frontend
npm run lint                                         # expect: 0 errors
npm test                                             # target: 70 passed
npm run build                                        # expect: OK

cd ..
git diff --cached --name-only | grep -E "(\.env$|\.env\.|db\.sqlite3)" || echo "clean"
```

Commit message: `feat: add phase 7f delhivery courier readiness gate`.
Push to `origin/main`.

---

## 12. Decisions locked for this implementation

- Archive command: **deferred**. No `archive_*` CLI in this phase.
- Model name: **`RazorpayCourierReadinessGate`** (chain naming).
- Phase 7F approve: **no `--director-signoff` argument**. Live
  courier dispatch requires Phase 7G + future execute-window guard.
- Forbidden actions count: **31** (corrected from earlier "29").

---

## 13. Phase 7G (live courier) prerequisites

Before any future Phase 7G live courier execution can proceed:

1. Phase 7F gate must be in
   `approved_for_future_phase7g_or_courier_execution_review`.
2. A new "execute-window guard for Delhivery" extension on
   `apps.saas.utc_window` (mirrors Phase 7D-Hotfix-1; structured
   `BEGIN_UTC=...` / `END_UTC=...` markers, 15-minute cap, freshness
   check, current-time-in-window check).
3. Director directive that names the exact Phase 7F gate id AND
   includes the structured UTC window markers.
4. A new env flag (e.g. `PHASE7G_DELHIVERY_COURIER_EXECUTION_ENABLED`)
   default `false`.
5. A separate dedicated CLI command
   (`execute_phase7g_delhivery_test_shipment_*`) with explicit
   `--confirm-one-shot-courier-execution` flag (mirrors Phase 7D
   one-shot pattern).

Phase 7G is **not approved** as of this commit and is **not
designed** in this turn.
