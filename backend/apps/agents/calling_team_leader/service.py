"""Phase 9E — Calling Team Leader Agent V1 deterministic aggregation.

All functions in this module are pure given the database state at
the moment of the call and emit no side effects. The Celery task
layer is responsible for persistence and audit emission.

Field-availability notes (V1):
- ``Call.agent`` is a ``CharField(max_length=80)``. Per-agent metrics
  ARE supported by this model. The
  ``_HAS_AGENT_ATTRIBUTION_FIELD`` flag keeps the alternate
  "no_agent_attribution_field" code path reachable for forward
  compatibility AND for tests.
- ``Call.duration`` is a ``CharField`` storing "m:ss" or "mm:ss"
  format (default "0:00"). :func:`_parse_duration_seconds` converts
  that string to an integer second count.
- ``Call.status`` ∈ {Live, Queued, Completed, Missed, Failed}. The
  V1 rule treats ``status="Completed"`` as the canonical
  "answered" signal.
- ``Call.outcome`` does NOT exist; ``outcome_breakdown`` therefore
  groups by ``status`` instead.
- Transcript backlog = calls created > 24h ago with no
  ``CallTranscriptLine`` rows linked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

from apps.calls.models import Call, CallTranscriptLine

from .models import CallingTeamLeaderSnapshot


AGENT_NAME = "calling_team_leader_v1"
MODEL_USED = "deterministic_v1"

WINDOW_DAYS = 30
TRANSCRIPT_BACKLOG_AGE_HOURS = 24

# V1 "answered" rule.
ANSWERED_STATUSES = (Call.Status.COMPLETED.value,)

# Anomaly thresholds (deterministic V1).
LOW_CONNECTION_RATE_THRESHOLD = 0.30
LOW_CONNECTION_RATE_MIN_VOLUME = 10
TRANSCRIPT_BACKLOG_THRESHOLD = 20
AGENT_CONCENTRATION_SHARE_THRESHOLD = 0.70
AGENT_CONCENTRATION_MIN_VOLUME = 10

# V1 model field availability — Call.agent is a CharField. The flag
# keeps the "no_agent_attribution_field" branch reachable for tests
# and for future schema changes; we never delete the field by accident.
_HAS_AGENT_ATTRIBUTION_FIELD = True


@dataclass
class CallingSignals:
    """Deterministic input bundle for snapshot construction."""

    snapshot_at: datetime
    call_count_24h: int = 0
    call_count_7d: int = 0
    call_count_30d: int = 0
    answered_count_30d: int = 0
    connection_rate_30d: float = 0.0
    avg_duration_seconds_30d: float = 0.0
    outcome_breakdown: dict[str, int] = field(default_factory=dict)
    agent_breakdown: list[dict[str, Any]] = field(default_factory=list)
    transcript_backlog_count: int = 0
    has_agent_field: bool = True
    alerts: list[str] = field(default_factory=list)
    alert_text: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at.isoformat(),
            "call_count_24h": self.call_count_24h,
            "call_count_7d": self.call_count_7d,
            "call_count_30d": self.call_count_30d,
            "answered_count_30d": self.answered_count_30d,
            "connection_rate_30d": self.connection_rate_30d,
            "avg_duration_seconds_30d": self.avg_duration_seconds_30d,
            "outcome_breakdown": dict(self.outcome_breakdown),
            "agent_breakdown": list(self.agent_breakdown),
            "transcript_backlog_count": self.transcript_backlog_count,
            "has_agent_field": self.has_agent_field,
            "alerts": list(self.alerts),
            "alert_text": self.alert_text,
        }


def _cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def _parse_duration_seconds(value: str) -> int:
    """Parse a ``Call.duration`` string into seconds.

    Accepts ``"m:ss"``, ``"mm:ss"``, ``"h:mm:ss"``. Returns 0 on any
    parse error rather than raising, so a single bad row cannot
    poison the daily aggregation.
    """
    if not value:
        return 0
    parts = value.strip().split(":")
    try:
        if len(parts) == 1:
            return max(0, int(parts[0]))
        if len(parts) == 2:
            minutes, seconds = parts
            return max(0, int(minutes) * 60 + int(seconds))
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return max(0, int(hours) * 3600 + int(minutes) * 60 + int(seconds))
    except (TypeError, ValueError):
        return 0
    return 0


def compute_call_counts(*, now: datetime | None = None) -> dict[str, int]:
    now = now or timezone.now()
    return {
        "call_count_24h": Call.objects.filter(
            created_at__gte=_cutoff(now, 1)
        ).count(),
        "call_count_7d": Call.objects.filter(
            created_at__gte=_cutoff(now, 7)
        ).count(),
        "call_count_30d": Call.objects.filter(
            created_at__gte=_cutoff(now, WINDOW_DAYS)
        ).count(),
    }


def compute_connection_stats_30d(
    *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or timezone.now()
    cutoff = _cutoff(now, WINDOW_DAYS)
    total = Call.objects.filter(created_at__gte=cutoff).count()
    answered = Call.objects.filter(
        created_at__gte=cutoff, status__in=ANSWERED_STATUSES
    ).count()
    rate = round(answered / total, 4) if total > 0 else 0.0
    return {
        "answered_count_30d": answered,
        "connection_rate_30d": rate,
    }


def compute_avg_duration_30d(*, now: datetime | None = None) -> float:
    now = now or timezone.now()
    cutoff = _cutoff(now, WINDOW_DAYS)
    durations = Call.objects.filter(
        created_at__gte=cutoff, status__in=ANSWERED_STATUSES
    ).values_list("duration", flat=True)
    seconds_list = [_parse_duration_seconds(d) for d in durations]
    seconds_list = [s for s in seconds_list if s > 0]
    if not seconds_list:
        return 0.0
    return round(sum(seconds_list) / len(seconds_list), 2)


def compute_outcome_breakdown_30d(
    *, now: datetime | None = None
) -> dict[str, int]:
    """Group by ``Call.status`` (Call has no separate ``outcome``)."""
    now = now or timezone.now()
    cutoff = _cutoff(now, WINDOW_DAYS)
    rows = (
        Call.objects.filter(created_at__gte=cutoff)
        .values("status")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    return {row["status"]: int(row["count"] or 0) for row in rows}


def compute_agent_breakdown_30d(
    *,
    top_n: int = 10,
    now: datetime | None = None,
    has_agent_field: bool | None = None,
) -> list[dict[str, Any]]:
    """Group by ``Call.agent`` (CharField).

    Returns an empty list when ``has_agent_field`` is False, mirroring
    the path used when the underlying model does not expose an agent
    attribution column. The deterministic V1 implementation looks up
    the model flag, but callers can override (used by tests).
    """
    if has_agent_field is None:
        has_agent_field = _HAS_AGENT_ATTRIBUTION_FIELD
    if not has_agent_field:
        return []
    now = now or timezone.now()
    cutoff = _cutoff(now, WINDOW_DAYS)
    rows = (
        Call.objects.filter(created_at__gte=cutoff)
        .values("agent")
        .annotate(call_count=Count("id"))
        .order_by("-call_count")[: max(0, top_n)]
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        agent_label = (row.get("agent") or "").strip() or "unattributed"
        total = int(row.get("call_count") or 0)
        # Connection rate + avg duration per agent.
        answered_qs = Call.objects.filter(
            created_at__gte=cutoff,
            agent=row.get("agent") or "",
            status__in=ANSWERED_STATUSES,
        )
        answered = answered_qs.count()
        connection_rate = (
            round(answered / total, 4) if total > 0 else 0.0
        )
        durations = list(answered_qs.values_list("duration", flat=True))
        seconds_list = [
            _parse_duration_seconds(d) for d in durations
        ]
        seconds_list = [s for s in seconds_list if s > 0]
        avg_duration = (
            round(sum(seconds_list) / len(seconds_list), 2)
            if seconds_list
            else 0.0
        )
        output.append(
            {
                "agent_id": row.get("agent") or "",
                "agent_label": agent_label,
                "call_count": total,
                "connection_rate": connection_rate,
                "avg_duration_seconds": avg_duration,
            }
        )
    return output


def compute_transcript_backlog(
    *, now: datetime | None = None
) -> int:
    """Count Calls older than 24h with no transcript lines."""
    now = now or timezone.now()
    cutoff_24h = _cutoff(now, 1)
    transcribed_call_ids = (
        CallTranscriptLine.objects.filter(call__isnull=False)
        .values_list("call_id", flat=True)
        .distinct()
    )
    return (
        Call.objects.filter(created_at__lt=cutoff_24h)
        .exclude(pk__in=list(transcribed_call_ids))
        .count()
    )


def detect_anomalies(
    signals: CallingSignals, *, has_agent_field: bool | None = None
) -> list[str]:
    if has_agent_field is None:
        has_agent_field = signals.has_agent_field
    alerts: list[str] = []

    if (
        signals.call_count_30d >= LOW_CONNECTION_RATE_MIN_VOLUME
        and signals.connection_rate_30d < LOW_CONNECTION_RATE_THRESHOLD
    ):
        alerts.append(
            CallingTeamLeaderSnapshot.Alert.LOW_CONNECTION_RATE.value
        )

    if signals.transcript_backlog_count > TRANSCRIPT_BACKLOG_THRESHOLD:
        alerts.append(
            CallingTeamLeaderSnapshot.Alert.HIGH_TRANSCRIPT_BACKLOG.value
        )

    if signals.call_count_24h == 0 and signals.call_count_7d > 0:
        alerts.append(CallingTeamLeaderSnapshot.Alert.NO_CALLS_TODAY.value)

    if (
        has_agent_field
        and signals.agent_breakdown
        and signals.call_count_30d > AGENT_CONCENTRATION_MIN_VOLUME
    ):
        top = signals.agent_breakdown[0]
        top_count = int(top.get("call_count") or 0)
        if top_count > AGENT_CONCENTRATION_SHARE_THRESHOLD * signals.call_count_30d:
            alerts.append(
                CallingTeamLeaderSnapshot.Alert.AGENT_CONCENTRATION_RISK.value
            )

    if not has_agent_field:
        alerts.append(
            CallingTeamLeaderSnapshot.Alert.NO_AGENT_ATTRIBUTION_FIELD.value
        )

    # ``no_agent_attribution_field`` is informational, not a problem —
    # so ``all_clear`` can coexist with it but with no other alerts.
    non_informational = [
        a
        for a in alerts
        if a
        != CallingTeamLeaderSnapshot.Alert.NO_AGENT_ATTRIBUTION_FIELD.value
    ]
    if not non_informational:
        alerts.append(CallingTeamLeaderSnapshot.Alert.ALL_CLEAR.value)

    deduped: list[str] = []
    for code in alerts:
        if code not in deduped:
            deduped.append(code)
    return deduped


def _compose_alert_text(signals: CallingSignals) -> str:
    top_agent = (
        signals.agent_breakdown[0]["agent_label"]
        if signals.agent_breakdown
        else "—"
    )
    parts = [
        f"calls 24h={signals.call_count_24h}",
        f"7d={signals.call_count_7d}",
        f"30d={signals.call_count_30d}",
        f"connection={signals.connection_rate_30d:.2f}",
        f"avg_duration={signals.avg_duration_seconds_30d:.0f}s",
        f"backlog={signals.transcript_backlog_count}",
        f"top_agent={top_agent}",
        f"alerts={','.join(signals.alerts) or 'none'}",
    ]
    return "; ".join(parts)


def compute_signals(
    *, now: datetime | None = None, has_agent_field: bool | None = None
) -> CallingSignals:
    now = now or timezone.now()
    if has_agent_field is None:
        has_agent_field = _HAS_AGENT_ATTRIBUTION_FIELD
    counts = compute_call_counts(now=now)
    connection = compute_connection_stats_30d(now=now)
    avg_duration = compute_avg_duration_30d(now=now)
    outcomes = compute_outcome_breakdown_30d(now=now)
    agent_breakdown = compute_agent_breakdown_30d(
        now=now, has_agent_field=has_agent_field
    )
    transcript_backlog = compute_transcript_backlog(now=now)
    signals = CallingSignals(
        snapshot_at=now,
        call_count_24h=counts["call_count_24h"],
        call_count_7d=counts["call_count_7d"],
        call_count_30d=counts["call_count_30d"],
        answered_count_30d=connection["answered_count_30d"],
        connection_rate_30d=connection["connection_rate_30d"],
        avg_duration_seconds_30d=avg_duration,
        outcome_breakdown=outcomes,
        agent_breakdown=agent_breakdown,
        transcript_backlog_count=transcript_backlog,
        has_agent_field=has_agent_field,
    )
    signals.alerts = detect_anomalies(signals, has_agent_field=has_agent_field)
    signals.alert_text = _compose_alert_text(signals)
    return signals


def build_snapshot(
    signals: CallingSignals, *, sandbox: bool = False
) -> CallingTeamLeaderSnapshot:
    return CallingTeamLeaderSnapshot(
        snapshot_at=signals.snapshot_at,
        call_count_24h=signals.call_count_24h,
        call_count_7d=signals.call_count_7d,
        call_count_30d=signals.call_count_30d,
        answered_count_30d=signals.answered_count_30d,
        connection_rate_30d=signals.connection_rate_30d,
        avg_duration_seconds_30d=signals.avg_duration_seconds_30d,
        outcome_breakdown=dict(signals.outcome_breakdown),
        agent_breakdown=list(signals.agent_breakdown),
        transcript_backlog_count=signals.transcript_backlog_count,
        alerts=list(signals.alerts),
        alert_text=signals.alert_text,
        sandbox=sandbox,
    )
