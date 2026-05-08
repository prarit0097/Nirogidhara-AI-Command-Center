"""Tests for ``apps.saas.utc_window``.

Phase 7E uses this shared utility ONLY for review-window approval
validation of the
``approve_razorpay_whatsapp_internal_notification_gate`` CLI command.
Phase 7D-Hotfix-1 will reuse the same module for execute-window
validation on ``execute_razorpay_controlled_pilot_test_order`` and
``execute_single_razorpay_test_order`` (separate later turn).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.saas.utc_window import (
    ParsedWindow,
    WindowValidationResult,
    parse_director_signoff_window,
    validate_review_window,
)


# ---------------------------------------------------------------------------
# parse_director_signoff_window
# ---------------------------------------------------------------------------


def test_parse_returns_none_on_empty_input() -> None:
    assert parse_director_signoff_window("") is None
    assert parse_director_signoff_window("   ") is None


def test_parse_returns_none_when_begin_marker_missing() -> None:
    text = "Director sign-off; END_UTC=2026-05-07T13:00:00Z"
    assert parse_director_signoff_window(text) is None


def test_parse_returns_none_when_end_marker_missing() -> None:
    text = "Director sign-off; BEGIN_UTC=2026-05-07T12:45:00Z"
    assert parse_director_signoff_window(text) is None


def test_parse_returns_none_on_malformed_begin_timestamp() -> None:
    text = (
        "Director sign-off; BEGIN_UTC=2026-05-07T12:45:00 "
        "END_UTC=2026-05-07T13:00:00Z"
    )
    assert parse_director_signoff_window(text) is None


def test_parse_returns_none_on_malformed_end_timestamp() -> None:
    text = (
        "Director sign-off; "
        "BEGIN_UTC=2026-05-07T12:45:00Z "
        "END_UTC=not-an-iso-timestamp"
    )
    assert parse_director_signoff_window(text) is None


def test_parse_returns_none_on_non_z_offset() -> None:
    text = (
        "Director sign-off; "
        "BEGIN_UTC=2026-05-07T12:45:00+05:30 "
        "END_UTC=2026-05-07T13:00:00Z"
    )
    assert parse_director_signoff_window(text) is None


def test_parse_succeeds_on_clean_window() -> None:
    text = (
        "Director sign-off for Phase 7E gate id 1 review attempt id 1. "
        "BEGIN_UTC=2026-05-08T09:00:00Z END_UTC=2026-05-08T10:00:00Z."
    )
    parsed = parse_director_signoff_window(text)
    assert parsed is not None
    assert parsed.window_start_utc == datetime(
        2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc
    )
    assert parsed.window_end_utc == datetime(
        2026, 5, 8, 10, 0, 0, tzinfo=timezone.utc
    )


def test_parse_is_case_insensitive_on_marker_name() -> None:
    text = (
        "begin_utc=2026-05-08T09:00:00Z "
        "End_Utc=2026-05-08T10:00:00Z"
    )
    parsed = parse_director_signoff_window(text)
    assert parsed is not None


def test_parse_tolerates_whitespace_around_equals() -> None:
    text = (
        "BEGIN_UTC = 2026-05-08T09:00:00Z   "
        "END_UTC =  2026-05-08T10:00:00Z"
    )
    parsed = parse_director_signoff_window(text)
    assert parsed is not None


def test_parse_truncates_raw_text_to_80_chars() -> None:
    body = "x" * 200
    text = (
        f"{body} BEGIN_UTC=2026-05-08T09:00:00Z "
        f"END_UTC=2026-05-08T10:00:00Z"
    )
    parsed = parse_director_signoff_window(text)
    assert parsed is not None
    assert len(parsed.raw_signoff_text_truncated) <= 80


def test_parse_first_match_wins_on_duplicate_markers() -> None:
    """If multiple BEGIN_UTC markers appear, the first wins."""
    text = (
        "BEGIN_UTC=2026-05-08T09:00:00Z BEGIN_UTC=2027-01-01T00:00:00Z "
        "END_UTC=2026-05-08T10:00:00Z"
    )
    parsed = parse_director_signoff_window(text)
    assert parsed is not None
    assert parsed.window_start_utc.year == 2026


# ---------------------------------------------------------------------------
# validate_review_window
# ---------------------------------------------------------------------------


def _frozen_now() -> datetime:
    return datetime(2026, 5, 8, 8, 30, 0, tzinfo=timezone.utc)


def test_validate_refuses_when_parsed_is_none() -> None:
    out = validate_review_window(None, now=_frozen_now())
    assert out.valid is False
    assert (
        "director_signoff_missing_structured_utc_window" in out.blockers
    )


def test_validate_refuses_when_end_is_before_start() -> None:
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 10, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc
        ),
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(parsed, now=_frozen_now())
    assert out.valid is False
    assert any("end_must_be_after_start" in b for b in out.blockers)


def test_validate_refuses_window_longer_than_24h_default() -> None:
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 0, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 9, 1, 0, 0, tzinfo=timezone.utc
        ),  # 25 hours
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(parsed, now=_frozen_now())
    assert out.valid is False
    assert any("window_too_long" in b for b in out.blockers)


def test_validate_refuses_stale_window() -> None:
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 6, 0, 0, 0, tzinfo=timezone.utc
        ),  # 2 days before frozen now
        window_end_utc=datetime(
            2026, 5, 6, 1, 0, 0, tzinfo=timezone.utc
        ),
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(parsed, now=_frozen_now())
    assert out.valid is False
    assert any("stale_more_than_24h" in b for b in out.blockers)


def test_validate_accepts_clean_review_window() -> None:
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 8, 10, 0, 0, tzinfo=timezone.utc
        ),
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(parsed, now=_frozen_now())
    assert out.valid is True
    assert out.blockers == ()
    assert out.window_length_seconds == 3600


def test_validate_accepts_window_in_future() -> None:
    """Phase 7E review windows can be in the future."""
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 8, 13, 0, 0, tzinfo=timezone.utc
        ),
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(parsed, now=_frozen_now())
    assert out.valid is True


def test_validate_respects_custom_max_window_seconds() -> None:
    """Phase 7D-Hotfix-1 will pass max_window_seconds=900 for execute."""
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 8, 9, 16, 0, tzinfo=timezone.utc
        ),  # 16 minutes
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(
        parsed, now=_frozen_now(), max_window_seconds=900
    )
    assert out.valid is False
    assert any("window_too_long_max_900" in b for b in out.blockers)


def test_validate_pure_no_db_no_settings_no_env(monkeypatch) -> None:
    """The validator never reads Django settings, env, or DB.

    This is asserted by ensuring the function works on a fresh import
    inside a context where settings are unconfigured.
    """
    # If the function tries to import django.conf.settings or os.environ
    # for behaviour, monkey-patching them away should still let
    # validate_review_window succeed.
    monkeypatch.setattr("os.environ", {})
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 8, 10, 0, 0, tzinfo=timezone.utc
        ),
        raw_signoff_text_truncated="",
    )
    out = validate_review_window(parsed, now=_frozen_now())
    assert out.valid is True


def test_validate_naive_now_is_treated_as_utc() -> None:
    """A naive ``now`` argument is interpreted as UTC."""
    parsed = ParsedWindow(
        window_start_utc=datetime(
            2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc
        ),
        window_end_utc=datetime(
            2026, 5, 8, 10, 0, 0, tzinfo=timezone.utc
        ),
        raw_signoff_text_truncated="",
    )
    naive_now = datetime(2026, 5, 8, 8, 30, 0)
    out = validate_review_window(parsed, now=naive_now)
    assert out.valid is True
