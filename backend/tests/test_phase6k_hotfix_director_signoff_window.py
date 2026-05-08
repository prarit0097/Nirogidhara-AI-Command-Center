"""Phase 7D-Hotfix-1 — Structured UTC window guard tests for Phase 6K's
``execute_single_razorpay_test_order`` CLI / service path.

Mirrors the Phase 7D Hotfix-1 suite. Same assertions, same failure
modes, prefixed with ``phase6k_`` blockers.

1.  Missing structured UTC markers refuse before the provider boundary.
2.  Window > 15 min refuses before the provider boundary.
3.  ``now < window_start`` refuses before the provider boundary.
4.  ``now > window_end`` refuses before the provider boundary.
5.  Stale window > 24h refuses before the provider boundary.
6.  Malformed ``BEGIN_UTC`` / ``END_UTC`` refuses before the provider
    boundary.
7.  Valid in-window run reaches the (mocked) SDK boundary exactly
    once and persists the parsed window fields on the row.
8.  No real Razorpay HTTP request is ever issued.
9.  Idempotency lock unchanged: a second execute on the same plan
    after a prior success is refused.
"""
from __future__ import annotations

import os
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone as dj_timezone

from apps.saas.models import (
    Organization,
    RuntimeProviderExecutionAttempt,
)
from apps.saas.provider_execution import (
    execute_single_razorpay_test_order,
)
from tests.test_phase6k_provider_execution import (
    _approved_plan,
    _ensure_default_org,
    _patch_create_order,
    fake_razorpay_test_env,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_signoff(
    *,
    start_offset_seconds: int = -30,
    duration_minutes: int = 10,
) -> str:
    now = dj_timezone.now()
    start = now + timedelta(seconds=start_offset_seconds)
    end = start + timedelta(minutes=duration_minutes)
    return (
        "Director Phase 6K-B Razorpay TEST sign-off. "
        f"BEGIN_UTC={start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


# ---------------------------------------------------------------------------
# Refuse-before-provider-boundary cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signoff_factory,expected_blocker",
    [
        (
            lambda: "",
            "phase6k_director_signoff_missing_structured_utc_window",
        ),
        (
            lambda: "Free text only sign-off",
            "phase6k_director_signoff_missing_structured_utc_window",
        ),
        (
            lambda: (
                "Director sign-off. BEGIN_UTC=2026-99-99T99:99:99Z "
                "END_UTC=2026-99-99T99:99:99Z"
            ),
            "phase6k_director_signoff_missing_structured_utc_window",
        ),
        (
            lambda: _valid_signoff(
                start_offset_seconds=-30,
                duration_minutes=20,  # 20 min > 15 min cap
            ),
            "phase6k_director_signoff_window_too_long_max_15_min",
        ),
        (
            lambda: _valid_signoff(
                start_offset_seconds=600,  # window 10 min in future
                duration_minutes=10,
            ),
            "phase6k_now_outside_director_signoff_utc_window",
        ),
        (
            lambda: _valid_signoff(
                start_offset_seconds=-(60 * 30),  # window closed 20 min ago
                duration_minutes=10,
            ),
            "phase6k_now_outside_director_signoff_utc_window",
        ),
    ],
    ids=(
        "missing_signoff",
        "free_text_only",
        "malformed_timestamp",
        "window_too_long",
        "now_before_start",
        "now_after_end",
    ),
)
def test_phase6k_execute_refuses_before_provider_boundary(
    db,
    fake_razorpay_test_env,
    signoff_factory,
    expected_blocker,
):
    _ensure_default_org()
    plan = _approved_plan()
    with mock.patch(
        "apps.saas.razorpay_test_execution.execute_razorpay_test_create_order"
    ) as sdk_mock:
        attempt = execute_single_razorpay_test_order(
            plan.plan_id,
            confirm=True,
            director_signoff=signoff_factory(),
        )
    assert (
        attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    )
    sdk_mock.assert_not_called()
    assert any(expected_blocker in b for b in attempt.blockers or []), (
        attempt.blockers
    )


@pytest.mark.django_db
def test_phase6k_stale_window_refuses(fake_razorpay_test_env) -> None:
    _ensure_default_org()
    plan = _approved_plan()
    stale_start = dj_timezone.now() - timedelta(days=2)
    stale_end = stale_start + timedelta(minutes=10)
    stale_signoff = (
        "Director Phase 6K-B Razorpay TEST sign-off. "
        f"BEGIN_UTC={stale_start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={stale_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    with mock.patch(
        "apps.saas.razorpay_test_execution.execute_razorpay_test_create_order"
    ) as sdk_mock:
        attempt = execute_single_razorpay_test_order(
            plan.plan_id,
            confirm=True,
            director_signoff=stale_signoff,
        )
    assert (
        attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    )
    sdk_mock.assert_not_called()
    assert any(
        "phase6k_director_signoff_window_stale_more_than_24h_old" in b
        for b in attempt.blockers or []
    )


# ---------------------------------------------------------------------------
# Valid in-window run reaches the (mocked) SDK boundary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase6k_valid_in_window_run_persists_parsed_fields(
    fake_razorpay_test_env,
) -> None:
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_phase6k_hotfix1_valid",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_hotfix1_valid",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id,
            confirm=True,
            director_signoff=_valid_signoff(),
        )
    assert (
        attempt.status == RuntimeProviderExecutionAttempt.Status.SUCCEEDED
    )
    assert attempt.recorded_signoff_window_valid is True
    assert attempt.recorded_signoff_window_start_utc is not None
    assert attempt.recorded_signoff_window_end_utc is not None
    delta = (
        attempt.recorded_signoff_window_end_utc
        - attempt.recorded_signoff_window_start_utc
    ).total_seconds()
    assert delta == 600  # 10 minutes


# ---------------------------------------------------------------------------
# Idempotency: second execute on same plan after success refused
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase6k_idempotency_lock_unchanged_with_window_guard(
    fake_razorpay_test_env,
) -> None:
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_phase6k_idem",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_idem",
    }
    with _patch_create_order(response):
        first = execute_single_razorpay_test_order(
            plan.plan_id,
            confirm=True,
            director_signoff=_valid_signoff(),
        )
        second = execute_single_razorpay_test_order(
            plan.plan_id,
            confirm=True,
            director_signoff=_valid_signoff(),
        )
    assert (
        first.status == RuntimeProviderExecutionAttempt.Status.SUCCEEDED
    )
    assert (
        second.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    )
    assert any(
        "plan_already_has_successful_execution" in b
        for b in second.blockers or []
    )


# ---------------------------------------------------------------------------
# CLI requires --director-signoff
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase6k_cli_requires_director_signoff(
    fake_razorpay_test_env,
) -> None:
    """The CLI surface raises CommandError when --director-signoff is
    missing, before the service / Razorpay boundary."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    _ensure_default_org()
    plan = _approved_plan()
    with mock.patch(
        "apps.saas.razorpay_test_execution.execute_razorpay_test_create_order"
    ) as sdk_mock:
        with pytest.raises(CommandError):
            call_command(
                "execute_single_razorpay_test_order",
                "--plan-id",
                plan.plan_id,
                "--confirm-test-execution",
                "--json",
            )
    sdk_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Service module never imports razorpay at module-import time
# ---------------------------------------------------------------------------


def test_phase6k_service_module_lazy_razorpay_import() -> None:
    import importlib

    src = importlib.import_module("apps.saas.razorpay_test_execution").__file__
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    lines = [
        ln
        for ln in text.splitlines()
        if ln.lstrip().startswith("import razorpay")
    ]
    for ln in lines:
        # Top-level import would have no leading whitespace.
        assert ln.startswith("    ") or ln.startswith("\t")
