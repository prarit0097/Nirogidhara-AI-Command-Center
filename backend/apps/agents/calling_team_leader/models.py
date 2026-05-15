"""Phase 9E — CallingTeamLeaderSnapshot model.

One row per task invocation. Snapshots are immutable — the daily
Celery task writes a new row each run rather than mutating.
"""
from __future__ import annotations

from django.db import models


class CallingTeamLeaderSnapshot(models.Model):
    """Deterministic V1 call-performance snapshot."""

    class Alert(models.TextChoices):
        LOW_CONNECTION_RATE = "low_connection_rate", "low_connection_rate"
        HIGH_TRANSCRIPT_BACKLOG = (
            "high_transcript_backlog",
            "high_transcript_backlog",
        )
        NO_CALLS_TODAY = "no_calls_today", "no_calls_today"
        AGENT_CONCENTRATION_RISK = (
            "agent_concentration_risk",
            "agent_concentration_risk",
        )
        NO_AGENT_ATTRIBUTION_FIELD = (
            "no_agent_attribution_field",
            "no_agent_attribution_field",
        )
        ALL_CLEAR = "all_clear", "all_clear"

    snapshot_at = models.DateTimeField(db_index=True)

    call_count_24h = models.IntegerField(default=0)
    call_count_7d = models.IntegerField(default=0)
    call_count_30d = models.IntegerField(default=0)
    answered_count_30d = models.IntegerField(default=0)
    connection_rate_30d = models.FloatField(default=0.0)
    avg_duration_seconds_30d = models.FloatField(default=0.0)

    outcome_breakdown = models.JSONField(default=dict, blank=True)
    agent_breakdown = models.JSONField(default=list, blank=True)
    transcript_backlog_count = models.IntegerField(default=0)

    alerts = models.JSONField(default=list, blank=True)
    alert_text = models.TextField(blank=True, default="")
    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="calling_team_leader_snapshots",
    )
    sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "agents"
        ordering = ("-snapshot_at",)
        indexes = (
            models.Index(
                fields=("-snapshot_at",),
                name="ctl_snap_at_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"CallingTeamLeaderSnapshot {self.pk} - "
            f"{self.snapshot_at:%Y-%m-%d %H:%M} - "
            f"calls30d={self.call_count_30d} "
            f"alerts={len(self.alerts or [])}"
        )
