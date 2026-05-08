# Phase 7D-Hotfix-1 — Structured UTC Window Guard for Provider Execute Commands

> **STATUS: SHIPPED.** Implemented in the Hotfix-1 commit on
> `origin/main`. Migration:
> `payments.0014_phase7d_hotfix_director_signoff_window` +
> `saas.0007_phase7d_hotfix_director_signoff_window`. New shared
> validator: `apps.saas.utc_window.validate_within_director_window`
> (alias `validate_execution_window`). Both execute commands
> (`execute_razorpay_controlled_pilot_test_order` and
> `execute_single_razorpay_test_order`) now refuse to dispatch unless
> the Director sign-off contains structured `BEGIN_UTC=...` /
> `END_UTC=...` markers, the window length is ≤ 15 minutes, the
> window is fresh (≤ 24h old), and the current UTC time is inside the
> window. **Hotfix-1 did NOT re-run any execute command.**

> Historical Phase 7D attempt id 1 (`order_SmThqpK6sc6Dhs`, executed
> 2026-05-07T12:42:46Z, rolled back) is the canonical legacy
> free-text row. Its `recorded_signoff_window_*` fields stayed `NULL`
> (no backfill) — Phase 7E continues to handle this row via the
> legacy-acknowledgement path.

---

## Problem

The Phase 7D execute path was run on 2026-05-07 with a free-text
Director sign-off and **no structured UTC window check**. The actual
`executed_at` of `2026-05-07T12:42:46Z` fell ~134 seconds **before**
the Director-approved window of `2026-05-07T12:45:00Z →
2026-05-07T13:00:00Z`. There was no business or customer impact (all
mutation booleans stayed False, the attempt was rolled back), but
the time invariant was violated.

The same gap exists in Phase 6K's `execute_single_razorpay_test_order`.

## Scope

1. **Reuse and extend** the shared `apps/saas/utc_window.py` module
   that Phase 7E creates (review-window scope only). Hotfix-1 adds:
   ```python
   def validate_execution_window(
       parsed: ParsedWindow | None,
       *,
       now: datetime | None = None,
       max_window_seconds: int = 900,            # 15 min for execute
       stale_window_max_age_seconds: int = 86_400,
   ) -> WindowValidationResult: ...
   ```

2. Modify `apps/payments/management/commands/execute_razorpay_controlled_pilot_test_order.py`:
   - Replace existing free-text `--director-signoff` check with a
     call to `parse_director_signoff_window` +
     `validate_execution_window`.
   - Reject if parser returns `None` (no structured markers).
   - Reject if window length > 15 min.
   - Reject if `now < window_start` or `now > window_end`.
   - Reject if window is stale (`window_start < now - 24h`).
   - Keep the existing "must contain source Phase 7B gate id"
     substring check.
   - New blocker strings:
     `phase7d_director_signoff_missing_structured_utc_window`,
     `phase7d_now_outside_director_signoff_utc_window`,
     `phase7d_director_signoff_window_too_long_max_15_min`,
     `phase7d_director_signoff_window_stale_more_than_24h_old`.

3. Modify `apps/saas/management/commands/execute_single_razorpay_test_order.py`
   (Phase 6K) **identically**.

4. Add 3 nullable fields to `RazorpayControlledPilotExecutionAttempt`:
   - `recorded_signoff_window_start_utc DateTimeField(null=True, blank=True)`
   - `recorded_signoff_window_end_utc DateTimeField(null=True, blank=True)`
   - `recorded_signoff_window_valid BooleanField(default=False)`

5. Add the same 3 nullable fields to
   `RuntimeProviderExecutionAttempt` (Phase 6K model).

6. **Do NOT backfill historical rows.** Past rows keep `NULL` /
   `False`. Phase 7E reads this state via
   `source_phase7d_signoff_window_validation_status =
   failed_or_legacy_free_text` for any pre-Hotfix-1 attempt, and
   approval requires explicit acknowledgement.

7. Migration: `payments.0014_phase7d_hotfix_director_signoff_window`.
   Pure `AddField`s. No data migration.

8. Tests:
   - `backend/tests/test_phase7d_hotfix_director_signoff_window.py`
   - `backend/tests/test_phase6k_hotfix_director_signoff_window.py`
   - Both parametrized over: missing markers, malformed timestamp,
     window > 15 min, `now < start`, `now > end`, stale window,
     valid in-window run accepted, idempotency unchanged, mock SDK
     never invoked.

## Order of operations

```
Phase 7E plan (this turn)
  → Phase 7E implementation (THIS commit)
    → Phase 7D-Hotfix-1 (separate later turn)
      → any future provider-touching command (re-running execute_*,
        Phase 7E-Live, Phase 7F)
```

Phase 7E implementation **may land before** Hotfix-1 because Phase 7E
makes no provider call. Hotfix-1 **must land before** any future
execute command runs.

## Hotfix-1 commit message

`fix: phase 7d hotfix 1 enforce structured utc window on razorpay test execute commands`
