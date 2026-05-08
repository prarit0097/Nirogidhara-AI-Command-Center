"""Shared UTC window parser + validator for Director sign-off text.

This module is **pure**: it has no Django settings access, no DB
access, no env access, no logging. It accepts inputs and returns
results.

Phase 7E uses this module **only for review-window approval
validation** of the
``approve_razorpay_whatsapp_internal_notification_gate`` CLI command.
Phase 7E never sends a WhatsApp message, never queues an outbound,
never calls Meta Cloud / Delhivery / Vapi, never creates a shipment
/ AWB / payment link, never captures / refunds, never mutates real
business rows.

Phase 7D-Hotfix-1 (separate later turn) extends this module with
``validate_execution_window`` (max_window_seconds=900) and modifies
``execute_razorpay_controlled_pilot_test_order`` and
``execute_single_razorpay_test_order`` to call it. Phase 7E does
**not** modify those execute commands; this is a hard scope rule.

Marker format the parser accepts (case-insensitive on the marker
name; whitespace-tolerant; ISO-8601 UTC timestamp ending in 'Z'):

    BEGIN_UTC=YYYY-MM-DDTHH:MM:SSZ
    END_UTC=YYYY-MM-DDTHH:MM:SSZ

Surrounding free-text (Director sign-off body, gate id reference,
acknowledgement tokens) is preserved by the caller and is NOT
parsed by this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_MAX_REVIEW_WINDOW_SECONDS_DEFAULT = 24 * 60 * 60  # 24h for Phase 7E
_STALE_WINDOW_MAX_AGE_SECONDS_DEFAULT = 24 * 60 * 60  # 24h


_BEGIN_MARKER = re.compile(
    r"BEGIN_UTC\s*=\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)",
    re.IGNORECASE,
)
_END_MARKER = re.compile(
    r"END_UTC\s*=\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedWindow:
    """A successfully-parsed Director sign-off UTC window.

    The caller decides whether to persist ``raw_signoff_text_truncated``;
    this module truncates to 80 chars to bound exposure but does not
    mask PII. The Phase 7E gate row never persists this field directly
    in any serializer response.
    """

    window_start_utc: datetime
    window_end_utc: datetime
    raw_signoff_text_truncated: str


@dataclass(frozen=True)
class WindowValidationResult:
    """Result of a window validation check.

    ``valid=True`` means every assertion passed. ``valid=False`` means
    at least one entry in ``blockers`` describes the failure mode.
    """

    valid: bool
    blockers: tuple[str, ...]
    window_start_utc: Optional[datetime]
    window_end_utc: Optional[datetime]
    window_length_seconds: int


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_iso_utc(value: str) -> Optional[datetime]:
    """Parse a strict ISO-8601 UTC timestamp ending in 'Z'.

    Returns ``None`` on any malformation; never raises.
    """
    if not value or not value.endswith("Z"):
        return None
    try:
        # ``fromisoformat`` does not accept the trailing 'Z' until
        # Python 3.11; replace with the explicit UTC offset for
        # backward compatibility.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        return None
    return parsed.astimezone(timezone.utc)


def parse_director_signoff_window(
    signoff_text: str,
) -> Optional[ParsedWindow]:
    """Parse ``BEGIN_UTC=...`` and ``END_UTC=...`` markers from a
    Director sign-off body.

    Returns ``None`` if either marker is missing or malformed.
    Never raises.
    """
    if not signoff_text:
        return None
    begin_match = _BEGIN_MARKER.search(signoff_text)
    end_match = _END_MARKER.search(signoff_text)
    if begin_match is None or end_match is None:
        return None
    start = _parse_iso_utc(begin_match.group(1))
    end = _parse_iso_utc(end_match.group(1))
    if start is None or end is None:
        return None
    truncated = signoff_text.strip()[:80]
    return ParsedWindow(
        window_start_utc=start,
        window_end_utc=end,
        raw_signoff_text_truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _now_utc(now: Optional[datetime]) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    return datetime.now(tz=timezone.utc)


def validate_review_window(
    parsed: Optional[ParsedWindow],
    *,
    now: Optional[datetime] = None,
    max_window_seconds: int = _MAX_REVIEW_WINDOW_SECONDS_DEFAULT,
    stale_window_max_age_seconds: int = (
        _STALE_WINDOW_MAX_AGE_SECONDS_DEFAULT
    ),
) -> WindowValidationResult:
    """Validate a parsed review window for Phase 7E approve.

    Phase 7E review windows may be up to 24h. ``now`` defaults to
    the current UTC time but is overridable for tests.

    Phase 7D-Hotfix-1 will add a separate ``validate_execution_window``
    helper with ``max_window_seconds=900`` (15 minutes) for execute
    commands.
    """
    blockers: list[str] = []
    if parsed is None:
        blockers.append("director_signoff_missing_structured_utc_window")
        return WindowValidationResult(
            valid=False,
            blockers=tuple(blockers),
            window_start_utc=None,
            window_end_utc=None,
            window_length_seconds=0,
        )

    start = parsed.window_start_utc
    end = parsed.window_end_utc
    length_seconds = int((end - start).total_seconds())
    current = _now_utc(now)

    if length_seconds <= 0:
        blockers.append(
            "director_signoff_window_end_must_be_after_start"
        )
    if length_seconds > max_window_seconds:
        blockers.append(
            f"director_signoff_window_too_long_max_{max_window_seconds}_seconds"
        )
    if start < current - _delta_seconds(stale_window_max_age_seconds):
        blockers.append(
            "director_signoff_window_stale_more_than_24h_old"
        )

    return WindowValidationResult(
        valid=not blockers,
        blockers=tuple(blockers),
        window_start_utc=start,
        window_end_utc=end,
        window_length_seconds=max(length_seconds, 0),
    )


def _delta_seconds(seconds: int):
    """Return a ``timedelta`` for the given seconds.

    Wrapped in a helper so tests can monkey-patch deterministic
    behaviour without importing ``datetime.timedelta`` directly into
    the public surface.
    """
    from datetime import timedelta

    return timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


__all__ = (
    "ParsedWindow",
    "WindowValidationResult",
    "parse_director_signoff_window",
    "validate_review_window",
)
