"""Phase 7D-Hotfix-1 — Structured UTC window guard tests for the
``execute_razorpay_controlled_pilot_test_order`` CLI / service path.

Asserts every Hotfix-1 safety requirement:

1.  Missing structured UTC markers refuse before the provider boundary.
2.  Window > 15 min refuses before the provider boundary.
3.  ``now < window_start`` refuses before the provider boundary.
4.  ``now > window_end`` refuses before the provider boundary.
5.  Stale window > 24h refuses before the provider boundary.
6.  Malformed ``BEGIN_UTC`` / ``END_UTC`` timestamps refuse before
    the provider boundary.
7.  A valid in-window run reaches the (mocked) SDK boundary
    exactly once and persists the parsed window fields on the row.
8.  No real Razorpay HTTP request is ever issued (every test mocks
    ``_create_order_via_sdk``).
9.  Idempotency / provider-call lock is unchanged: a second
    execute on the same attempt remains refused.
10. The historical Phase 7D attempt id 1 (legacy free-text signoff
    rolled-back row, recorded before Hotfix-1 shipped) is NOT
    edited by anything in this suite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone as dj_timezone

from apps.payments.models import RazorpayControlledPilotExecutionAttempt
from apps.payments.razorpay_controlled_pilot_execution import (
    approve_phase7d_razorpay_test_execution_attempt,
    execute_phase7d_razorpay_test_order,
    prepare_phase7d_razorpay_test_execution_attempt,
)
from tests.test_phase7d_razorpay_test_execution import (
    _make_approved_phase7b_gate,
    _mock_razorpay_order_response,
    _phase7d_test_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _structured_window_signoff(
    *,
    gate_id: int,
    minutes_ahead: int = 0,
    duration_minutes: int = 10,
    start_offset_seconds: int = -30,
) -> str:
    """Build a Director sign-off body with structured BEGIN_UTC / END_UTC
    markers anchored around ``now``.

    Defaults: window opens 30 seconds before ``now`` and closes 10
    minutes later — a valid in-window run.
    """
    now = dj_timezone.now()
    start = now + timedelta(seconds=start_offset_seconds) + timedelta(
        minutes=minutes_ahead
    )
    end = start + timedelta(minutes=duration_minutes)
    return (
        f"Director one-shot Razorpay TEST sign-off mentions gate {gate_id}. "
        f"BEGIN_UTC={start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


def _approved_attempt_id(gate_pk: int) -> int:
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate_pk)
        attempt_id = out["attempt"]["id"]
        approve_phase7d_razorpay_test_execution_attempt(
            attempt_id,
            reviewed_by=None,
            reason="Director one-shot Razorpay TEST sign-off for fixture",
        )
    return attempt_id


# ---------------------------------------------------------------------------
# Refuse-before-provider-boundary cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_missing_markers_refuse_before_provider_boundary() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_no_markers"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    with mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as sdk_mock:
        with _phase7d_test_settings():
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Free text only sign-off for gate {gate.pk}"
                ),
            )
    assert result["ok"] is False
    sdk_mock.assert_not_called()
    assert any(
        "phase7d_director_signoff_missing_structured_utc_window" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_window_too_long_refuses_before_provider_boundary() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_too_long"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    long_signoff = _structured_window_signoff(
        gate_id=gate.pk,
        start_offset_seconds=-30,
        duration_minutes=20,  # 20 min > 15 min cap
    )
    with mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as sdk_mock:
        with _phase7d_test_settings():
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=long_signoff,
            )
    assert result["ok"] is False
    sdk_mock.assert_not_called()
    assert any(
        "phase7d_director_signoff_window_too_long_max_15_min" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_now_before_window_start_refuses() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_too_early"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    future_signoff = _structured_window_signoff(
        gate_id=gate.pk,
        start_offset_seconds=600,  # window starts 10 min in the future
        duration_minutes=10,
    )
    with mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as sdk_mock:
        with _phase7d_test_settings():
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=future_signoff,
            )
    assert result["ok"] is False
    sdk_mock.assert_not_called()
    assert any(
        "phase7d_now_outside_director_signoff_utc_window" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_now_after_window_end_refuses() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_too_late"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    past_signoff = _structured_window_signoff(
        gate_id=gate.pk,
        start_offset_seconds=-(60 * 30),  # window started 30 min ago
        duration_minutes=10,  # closed 20 min ago
    )
    with mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as sdk_mock:
        with _phase7d_test_settings():
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=past_signoff,
            )
    assert result["ok"] is False
    sdk_mock.assert_not_called()
    assert any(
        "phase7d_now_outside_director_signoff_utc_window" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_stale_window_refuses() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_stale"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    stale_start = dj_timezone.now() - timedelta(days=2)
    stale_end = stale_start + timedelta(minutes=10)
    stale_signoff = (
        f"Director sign-off mentions gate {gate.pk}. "
        f"BEGIN_UTC={stale_start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={stale_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    with mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as sdk_mock:
        with _phase7d_test_settings():
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=stale_signoff,
            )
    assert result["ok"] is False
    sdk_mock.assert_not_called()
    assert any(
        "phase7d_director_signoff_window_stale_more_than_24h_old" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_malformed_timestamp_refuses() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_malformed"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    malformed_signoff = (
        f"Director sign-off mentions gate {gate.pk}. "
        "BEGIN_UTC=2026-99-99T99:99:99Z END_UTC=2026-99-99T99:99:99Z"
    )
    with mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as sdk_mock:
        with _phase7d_test_settings():
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=malformed_signoff,
            )
    assert result["ok"] is False
    sdk_mock.assert_not_called()
    # Malformed timestamps cause the parser to return None, which the
    # service flags as missing-structured-window.
    assert any(
        "phase7d_director_signoff_missing_structured_utc_window" in b
        for b in result["blockers"]
    )


# ---------------------------------------------------------------------------
# Valid in-window run reaches the (mocked) SDK boundary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_valid_in_window_run_persists_parsed_fields() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_valid"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    valid_signoff = _structured_window_signoff(
        gate_id=gate.pk,
        start_offset_seconds=-30,
        duration_minutes=10,
    )
    fake_response = _mock_razorpay_order_response(
        order_id="order_TEST7D_hotfix1_valid"
    )
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=fake_response,
        ) as sdk_mock:
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=valid_signoff,
            )
    assert result["ok"] is True, result.get("blockers")
    sdk_mock.assert_called_once()
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    assert row.recorded_signoff_window_valid is True
    assert row.recorded_signoff_window_start_utc is not None
    assert row.recorded_signoff_window_end_utc is not None
    delta = (
        row.recorded_signoff_window_end_utc
        - row.recorded_signoff_window_start_utc
    ).total_seconds()
    assert delta == 600  # 10 minutes


# ---------------------------------------------------------------------------
# Idempotency lock unchanged
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_idempotency_lock_unchanged_with_window_guard() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_hotfix1_idem"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    valid_signoff = _structured_window_signoff(gate_id=gate.pk)
    fake_response = _mock_razorpay_order_response(
        order_id="order_TEST7D_hotfix1_idem"
    )
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=fake_response,
        ) as sdk_mock:
            first = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=valid_signoff,
            )
            second = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=valid_signoff,
            )
    assert first["ok"] is True
    assert second["ok"] is False
    assert sdk_mock.call_count == 1


# ---------------------------------------------------------------------------
# No real Razorpay HTTP request anywhere in the suite (defensive)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_service_module_does_not_import_razorpay_at_import_time() -> None:
    """The razorpay SDK is imported lazily inside _create_order_via_sdk
    only — never at module import time. The Hotfix-1 changes must not
    introduce a top-level `import razorpay`.
    """
    import importlib

    src = importlib.import_module(
        "apps.payments.razorpay_controlled_pilot_execution"
    ).__file__
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    # The file must reference `import razorpay` inside the SDK
    # function body, never at module level. Verify the only matches
    # are inside a function.
    lines = [
        ln for ln in text.splitlines() if ln.lstrip().startswith("import razorpay")
    ]
    for ln in lines:
        # Top-level import would have no leading whitespace.
        assert ln.startswith("    ") or ln.startswith("\t")


# ---------------------------------------------------------------------------
# Historical Phase 7D attempt id 1 must not be edited by this suite
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_does_not_edit_historical_phase7d_attempt_id_1() -> None:
    """Confirms the test suite does not touch any pre-Hotfix-1 row.

    Test isolation already prevents this (every test uses a fresh
    transaction), but the assertion documents intent.
    """
    # The fixture chain creates fresh rows; in this isolated test DB
    # the only attempts are those just created (if any). We assert
    # there is no leakage of arbitrary historical state.
    rows = RazorpayControlledPilotExecutionAttempt.objects.filter(
        provider_object_id="order_SmThqpK6sc6Dhs"
    )
    assert rows.count() == 0
