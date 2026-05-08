# Phase 7E — Controlled Internal WhatsApp Notification Readiness Gate

> Persisted plan. Source of truth for Phase 7E implementation. If this
> doc and `nd.md` disagree, `nd.md` wins; this doc must be updated to
> match.

---

## 0. Summary

Phase 7E adds a **gate-only, CLI-only readiness layer** that turns a
successful, rolled-back Phase 7D Razorpay TEST execution into an
audit-only readiness contract for a future Phase 7F (Delhivery /
WhatsApp send) sub-phase or a future Phase 7E-Live decision.

Phase 7E **never** sends a WhatsApp message, **never** queues an
outbound, **never** calls Meta Cloud, **never** calls Delhivery,
**never** creates a shipment / AWB, **never** creates a payment link,
**never** captures, **never** refunds, **never** mutates real `Order`
/ `Payment` / `Shipment` / `DiscountOfferLog` / `Customer` / `Lead`
rows, **never** sends a customer notification, and **never** edits
any `.env*` file.

---

## 1. Phase 7D actual final state (used by Phase 7E source-chain check)

| Field | Value |
|---|---|
| Phase 7D execute path status | executed once on 2026-05-07 |
| Provider order id | `order_SmThqpK6sc6Dhs` |
| Phase 7D attempt id | `1` |
| Source Phase 7B gate id | `1` |
| `attempt.status` | `rolled_back` |
| `attempt.rollback_status` | `completed` |
| `attempt.provider_call_attempted` | `True` (count = 1) |
| `attempt.business_mutation_was_made` | `False` |
| `attempt.payment_link_created` / `_captured` / `_refunded` | `False` |
| `attempt.shipment_created` / `awb_created` | `False` |
| `attempt.whatsapp_message_created` / `_queued` | `False` |
| `attempt.whatsapp_lifecycle_event_created` | `False` |
| `attempt.meta_cloud_call_attempted` | `False` |
| `attempt.delhivery_call_attempted` | `False` |
| `attempt.customer_notification_sent` | `False` |
| `attempt.real_order_mutation_was_made` / `real_payment_mutation_was_made` | `False` |
| `attempt.executed_at` | `2026-05-07T12:42:46Z` |
| Director-approved UTC window | `2026-05-07T12:45:00Z → 2026-05-07T13:00:00Z` |
| **UTC-window adherence** | **VIOLATED** — execution was ~134s before window start. **No business or customer impact** (all mutation booleans stayed False, attempt was rolled back). |
| `safeToRunPhase7DExecution` | `false` |
| `nextPhase` | `7E_not_approved` |

The Phase 7D model does NOT yet carry structured window fields
(`recorded_signoff_window_valid` / `_start_utc` / `_end_utc`); these
are added in Phase 7D-Hotfix-1 (separate later turn — see
`docs/PHASE_7D_HOTFIX_1_PLAN.md`). Until Hotfix-1 ships, every
existing Phase 7D attempt is treated as **legacy free-text sign-off**
by Phase 7E (`source_phase7d_signoff_window_validation_status =
failed_or_legacy_free_text`).

---

## 2. Status lifecycle

```text
draft  ─────────►  pending_manual_review  ─────────►  approved_for_future_phase7f_or_7e_send_review
  │                       │                                        │
  │                       ├─────────► rejected                     │
  │                       │                                        │
  │                       └─────────► archived ◄───────────────────┘
  │                                       ▲
  ▼                                       │
blocked ◄────── invariant violation / kill switch off / source-chain bad
```

| State | Set by | Allowed transitions out |
|---|---|---|
| `draft` | initial row create (rare; `prepare_*` usually goes straight to `pending_manual_review`) | `pending_manual_review`, `blocked`, `archived` |
| `pending_manual_review` | `prepare_*` on success | `approved_for_future_phase7f_or_7e_send_review`, `rejected`, `archived`, `blocked` |
| `approved_for_future_phase7f_or_7e_send_review` | `approve_*` on success | `archived` |
| `rejected` | `reject_*` on success | `archived` |
| `archived` | terminal | — |
| `blocked` | invariant violation / source not eligible | `archived` |

Approval is a **status transition only**. It does NOT enable any
send path. Live customer notification still requires Phase 7F or a
future Phase 7E-Live with a fresh Director directive AND
Phase 7D-Hotfix-1 must already have shipped.

---

## 3. Required safety booleans (locked-False)

```text
whatsappSendAllowedInPhase7E                         = False
whatsappQueueAllowedInPhase7E                        = False
metaCloudCallAllowedInPhase7E                        = False
businessMutationAllowedInPhase7E                     = False
customerNotificationAllowedInPhase7E                 = False
realCustomerAllowedInPhase7E                         = False
providerCallAttempted                                = False
whatsAppMessageCreated                               = False
whatsAppMessageQueued                                = False
whatsAppLifecycleEventCreated                        = False
metaCloudCallAttempted                               = False
customerNotificationSent                             = False
realOrderMutationWasMade                             = False
realPaymentMutationWasMade                           = False
phase7EApprovalImpliesLiveSend                       = False
phase7DSourceSignoffMayBeLegacyFreeTextWithAck       = True
phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand = True
```

---

## 4. Source-chain requirements

1. `RazorpayControlledPilotExecutionAttempt(pk=attempt_id)` exists.
2. `attempt.status == EXECUTED`.
3. `attempt.rollback_status == COMPLETED`.
4. `attempt.provider_call_attempted == True`.
5. All 11 mutation/send/courier/notification booleans on the attempt
   are False.
6. Source Phase 7B gate is approved
   (`APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW`).
7. Phase 7B gate `dry_run_passed=True` AND
   `rollback_dry_run_passed=True`.
8. Phase 6T audit lock is `LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW`
   (walked via `attempt.source_phase7b_gate.source_final_audit_lock`).
9. `RuntimeKillSwitch(scope=GLOBAL).enabled == True`.
10. WhatsApp automation flags **all False**:
    `WHATSAPP_AI_AUTO_REPLY_ENABLED`,
    `WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED`,
    `WHATSAPP_CALL_HANDOFF_ENABLED`,
    `WHATSAPP_RESCUE_DISCOUNT_ENABLED`,
    `WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED`,
    `WHATSAPP_REORDER_DAY20_ENABLED`.
11. `WHATSAPP_PROVIDER == "mock"` OR
    `WHATSAPP_LIVE_META_LIMITED_TEST_MODE == True`.
12. `DELHIVERY_MODE in {"mock", "test"}`.
13. Phase 7D / 6K env flags **all False**:
    `PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED`,
    `PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED`,
    `PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION`,
    `PHASE7D_ALLOW_RAZORPAY_TEST_ORDER`.

`recorded_signoff_window_valid` on the source attempt is **stored
but not blocking**. If the field does not exist (pre-Hotfix-1) OR
is False, the gate row carries
`source_phase7d_signoff_window_validation_status =
failed_or_legacy_free_text` and approval requires the explicit
acknowledgement flag (§6).

---

## 5. Models (one migration, two new tables)

### `payments.RazorpayWhatsAppInternalNotificationGate`

Non-exhaustive field list (see `PHASE_7E_PLAN.md` §3 for the full
spec; the actual implementation is the source of truth):

- `source_phase7d_attempt FK PROTECT`
- `source_phase7b_gate FK PROTECT`
- `source_phase6t_lock FK PROTECT`
- `status CharField` (6 choices — see §2)
- `target_internal_cohort_phone_suffix_last4 CharField(4)` (last-4
  only; never full E.164)
- `target_internal_cohort_member FK SET_NULL`
- `proposed_template_action_keys JSONField` (subset of
  `whatsapp.payment_reminder` /
  `whatsapp.confirmation_reminder` /
  `whatsapp.delivery_reminder`)
- `proposed_template_names_resolved JSONField`
- `proposed_variable_keys JSONField` (variable **keys** only — never
  values, never PII)
- `claim_vault_grounded BooleanField`
- `dry_run_passed BooleanField`
- `rollback_dry_run_passed BooleanField`
- `source_phase7d_signoff_window_validation_status CharField` (one
  of `valid_structured_window`, `failed_or_legacy_free_text`,
  `not_applicable`)
- `source_phase7d_window_violation_acknowledged BooleanField`
- `phase7e_future_review_signoff_window_start_utc DateTimeField`
- `phase7e_future_review_signoff_window_end_utc DateTimeField`
- `phase7e_future_review_signoff_window_valid BooleanField`
- `director_signoff_text TextField` (stored; serializer NEVER
  returns)
- `kill_switch_snapshot_at_each_step JSONField`
- `env_flag_snapshot_at_each_step JSONField`
- `safety_invariants_snapshot JSONField`
- `before_counts JSONField` / `after_counts JSONField`
- `idempotency_key CharField unique` =
  `phase7e::wa_notify::attempt::<phase7d_attempt_pk>`
- `blockers JSONField` / `warnings JSONField`
- `next_action CharField`
- `requested_by` / `reviewed_by` / `archived_by` FKs
- `created_at` / `updated_at` / `approved_at` / `rejected_at` /
  `archived_at`
- `organization` / `branch` FKs (Phase 6B convention)

### `payments.RazorpayWhatsAppInternalNotificationDryRunRecord`

- `gate FK CASCADE`
- `kind CharField` (`dry_run` | `rollback_dry_run`)
- `status CharField` (`passed` | `failed` | `blocked`)
- `idempotency_key CharField unique`
- `safety_invariants_snapshot JSONField`
- `before_counts` / `after_counts` JSONField
- `claim_vault_grounded BooleanField`
- `blockers` / `warnings` JSONField
- `reason TextField`
- `created_at`

Migration `payments.0013_phase7e_whatsapp_internal_notification_gate`
is a pure `CreateModel` for these two tables. No `RunPython`. No
field changes on existing tables.

---

## 6. Management commands (8)

| # | Command | Purpose |
|---|---|---|
| 1 | `inspect_razorpay_whatsapp_internal_notification_readiness` | Read-only readiness composition. |
| 2 | `preview_razorpay_whatsapp_internal_notification_gate --attempt-id <ID>` | Read-only preview from a Phase 7D attempt. Never creates rows. |
| 3 | `prepare_razorpay_whatsapp_internal_notification_gate --attempt-id <ID>` | Atomic, idempotent. Creates / re-fetches gate row. |
| 4 | `dry_run_razorpay_whatsapp_internal_notification_gate --gate-id <ID>` | Walks Claim-Vault grounding + invariants; writes a `RazorpayWhatsAppInternalNotificationDryRunRecord(kind=dry_run)`. **Never opens the Meta Cloud client; never queues a `WhatsAppMessage` row.** |
| 5 | `rollback_dry_run_razorpay_whatsapp_internal_notification_gate --gate-id <ID> --reason "…"` | Re-validates invariants; writes `kind=rollback_dry_run`. Reason required. |
| 6 | `approve_razorpay_whatsapp_internal_notification_gate --gate-id <ID> --reason "…" --director-signoff "…" [--acknowledge-source-phase7d-window-violation]` | Refuses unless `dry_run_passed=True` AND `rollback_dry_run_passed=True` AND `claim_vault_grounded=True` AND `--reason` non-empty AND `--director-signoff` parses a structured Phase 7E review window via `apps.saas.utc_window.parse_director_signoff_window` (window length ≤ 24h, references source Phase 7D attempt id literally). If `source_phase7d_signoff_window_validation_status != valid_structured_window`, requires `--acknowledge-source-phase7d-window-violation` AND `--reason` body must literally contain `acknowledged_phase7d_window_violation_ref_attempt_<ATTEMPT_ID>`. **Never sends. Never queues.** |
| 7 | `reject_razorpay_whatsapp_internal_notification_gate --gate-id <ID> --reason "…"` | Sets status to `rejected`. Reason required. Refuses if status not in `{draft, pending_manual_review}`. |
| 8 | `inspect_razorpay_whatsapp_internal_notification_gates [--limit N]` | Read-only list. Counts per status. |

---

## 7. Audit kinds (14, all ≤ 64 chars)

```text
razorpay.whatsapp_internal_notification.readiness_inspected
razorpay.whatsapp_internal_notification.previewed
razorpay.whatsapp_internal_notification.prepared
razorpay.whatsapp_internal_notification.dry_run_passed
razorpay.whatsapp_internal_notification.dry_run_failed
razorpay.whatsapp_internal_notification.rb_dry_run_passed
razorpay.whatsapp_internal_notification.rb_dry_run_failed
razorpay.whatsapp_internal_notification.approved_future_send
razorpay.whatsapp_internal_notification.rejected
razorpay.whatsapp_internal_notification.archived
razorpay.whatsapp_internal_notification.blocked
razorpay.whatsapp_internal_notification.kill_switch_blocked
razorpay.whatsapp_internal_notification.invariant_violation
razorpay.whatsapp_internal_notification.acked_legacy_signoff
```

Audit payloads NEVER carry: `token`, `phone`, `email`, `address`,
`card`, `vpa`, `upi`, `bank_account`, `wallet`, `verify_token`,
`app_secret`, `META_WA_TOKEN`, `META_WA_APP_SECRET`,
`RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `raw_payload`,
`raw_signature`, `raw_secret`, `director_signoff_text`. Only
`{window_start_utc, window_end_utc, gate_id_referenced}` from the
sign-off is recorded.

---

## 8. Read-only DRF endpoints (5)

Mounted under `/api/v1/saas/razorpay/whatsapp-internal-notification-*`.
Auth + admin only. POST/PATCH/DELETE return 405 on every endpoint.
**No POST endpoint dispatches state changes.**

| Method | Path |
|---|---|
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-readiness/` |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-gates/?limit=N` |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-gates/<pk>/` |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-preview/?attempt_id=<ID>` |
| GET | `/api/v1/saas/razorpay/whatsapp-internal-notification-dry-runs/<gate_id>/` |

---

## 9. Frontend `/saas-admin` section

`data-testid="razorpay-whatsapp-internal-notification-section"`.

Read-only:
- Phase badge (kill-switch enabled/disabled, current source attempt id).
- 14 locked-False columns (every row a green "No" pill).
- Recent gate counters per status.
- Recent gates table (id / status / attempt id / claim_vault_grounded
  / dry_run_passed / rollback_dry_run_passed / phase7e review window
  valid / created_at).
- Allowed actions panel: "Inspect, preview, dry-run, rollback-dry-run,
  approve, reject, list via CLI only — no Send / Queue / Approve /
  Reject buttons exist on this page."

**No buttons.** Forbidden-button regex assertion in vitest.

---

## 10. `apps/saas/utc_window.py` (NEW shared utility)

Phase 7E creates this module as a **pure shared utility for
review-window parsing only**. Phase 7E uses it only for review-only
approval validation. Phase 7D-Hotfix-1 (separate later turn) reuses
and extends the same module to enforce structured execution windows
on `execute_razorpay_controlled_pilot_test_order` and
`execute_single_razorpay_test_order`.

### Public API (Phase 7E scope)

```python
@dataclass(frozen=True)
class ParsedWindow:
    window_start_utc: datetime
    window_end_utc: datetime
    raw_signoff_text_truncated: str  # first 80 chars only, no PII guarantee — caller decides whether to persist


@dataclass(frozen=True)
class WindowValidationResult:
    valid: bool
    blockers: tuple[str, ...]
    window_start_utc: datetime | None
    window_end_utc: datetime | None
    window_length_seconds: int


def parse_director_signoff_window(signoff_text: str) -> ParsedWindow | None:
    """
    Parse `BEGIN_UTC=<iso8601Z>` and `END_UTC=<iso8601Z>` markers from
    a free-text Director sign-off. Returns None if either marker is
    missing or malformed. Never raises.

    Marker format: literal substrings
        BEGIN_UTC=YYYY-MM-DDTHH:MM:SSZ
        END_UTC=YYYY-MM-DDTHH:MM:SSZ
    Whitespace tolerant; case-insensitive on the marker name; the
    timestamp must be strict ISO-8601 UTC ending in 'Z'.
    """


def validate_review_window(
    parsed: ParsedWindow | None,
    *,
    now: datetime | None = None,
    max_window_seconds: int = 86_400,  # 24h for Phase 7E review windows
    stale_window_max_age_seconds: int = 86_400,
) -> WindowValidationResult:
    """
    Validate a parsed review window for Phase 7E approve. Phase 7E
    review windows may be up to 24h. Phase 7D-Hotfix-1 will add a
    second validator (`validate_execution_window`) with
    max_window_seconds=900 for execute commands.
    """
```

Phase 7E **does not call** any execute helper here; the execute-side
validator lands in Hotfix-1. Phase 7E simply parses + validates a
review window for `approve_razorpay_whatsapp_internal_notification_gate`.

### Tests for `apps/saas/utc_window.py`

`backend/tests/test_saas_utc_window.py` — ~12 cases covering:
- Returns None on missing `BEGIN_UTC=` marker.
- Returns None on missing `END_UTC=` marker.
- Returns None on malformed timestamp (non-ISO, no 'Z' suffix, etc).
- Parses a clean window correctly.
- Parses ignoring surrounding free text.
- `raw_signoff_text_truncated` is ≤ 80 chars.
- Validate refuses on `parsed is None`.
- Validate refuses when `end - start > max_window_seconds`.
- Validate refuses when `end ≤ start`.
- Validate refuses on stale window (`start < now - stale_window_max_age_seconds`).
- Validate accepts a clean review window.
- Validate is pure (no DB read, no env read).

---

## 11. Tests (~50 service + ~12 utility = ~62 new backend tests)

`backend/tests/test_phase7e_whatsapp_internal_notification.py` covers
contract, audit-kind length, forbidden actions, readiness command +
endpoint shape, GET-only enforcement, preview no-row-creation,
prepare gating (env flag, source-chain checks parametrized),
prepare idempotency, dry-run pass / fail, dry-run never creates a
WhatsApp row, rollback-dry-run, approve refusals (missing window
markers, window too long, no source attempt id reference,
acknowledgement flag missing for legacy free-text source,
acknowledgement flag present but reason token missing), approve
success, reject refusals (no reason / wrong status), reject success,
defensive guard (parametrized over 14 booleans), provider mocks
`assert_not_called`, no business-row mutation across full lifecycle,
service-module static-file scans (no `dotenv` import; no
`apps.whatsapp.services.send_*` import; no `meta_cloud_client`
import), no raw secret / phone / signoff text in any output, audit
payloads forbidden-keys absent.

`frontend/src/test/saas-admin.test.tsx` adds 2 cases (read-only
render + no live execute / send / queue / notify / approve / reject
button).

Test-baseline target after Phase 7E ships:
- Backend: 1581 → ~1643.
- Frontend: 66 → 68.

---

## 12. Verification commands

```bash
cd backend
python manage.py makemigrations --check --dry-run    # expect: No changes detected
python manage.py check                               # expect: 0 issues
python -m pytest -q                                  # target: ~1643 passed
python manage.py inspect_razorpay_whatsapp_internal_notification_readiness --json --no-audit
# expect: phase=7E, status=whatsapp_internal_notification_readiness_only,
#         all 14 locked-False booleans False,
#         nextAction=enable_phase7e_gate_flag_for_review_only

cd ../frontend
npm run lint                                         # expect: 0 errors
npm test                                             # target: 68 passed
npm run build                                        # expect: OK

cd ..
git diff --cached --name-only | grep -E "(\.env$|\.env\.|db\.sqlite3)" || echo "clean"
```

Commit message: `feat: add phase 7e whatsapp internal notification readiness gate`. Push to `origin/main`.
