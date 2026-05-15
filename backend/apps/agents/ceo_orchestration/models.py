"""Phase 9F — CeoOrchestrationSnapshot model.

One row per task invocation. Snapshots are immutable — the daily
Celery task writes a new row each run rather than mutating. The five
agent FKs are nullable so a missing upstream snapshot can be
represented as a ``data_gap`` rather than crashing the synthesis.
"""
from __future__ import annotations

from django.db import models


class CeoOrchestrationSnapshot(models.Model):
    """Deterministic V1 cross-agent synthesis snapshot."""

    class HealthTier(models.TextChoices):
        CRITICAL = "critical", "critical"
        POOR = "poor", "poor"
        FAIR = "fair", "fair"
        GOOD = "good", "good"
        EXCELLENT = "excellent", "excellent"

    class Alert(models.TextChoices):
        DATA_GAP = "data_gap", "data_gap"
        ALL_CLEAR = "all_clear", "all_clear"

    snapshot_at = models.DateTimeField(db_index=True)
    business_health_score = models.IntegerField(default=0)
    health_tier = models.CharField(
        max_length=12,
        choices=HealthTier.choices,
        default=HealthTier.FAIR,
        db_index=True,
    )

    customer_success_snapshot = models.ForeignKey(
        "agents.CustomerSuccessSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ceo_orchestration_snapshots",
    )
    rto_snapshot = models.ForeignKey(
        "agents.RtoRiskSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ceo_orchestration_snapshots",
    )
    cfo_snapshot = models.ForeignKey(
        "agents.CfoFinancialSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ceo_orchestration_snapshots",
    )
    data_analyst_snapshot = models.ForeignKey(
        "agents.DataAnalystSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ceo_orchestration_snapshots",
    )
    calling_team_leader_snapshot = models.ForeignKey(
        "agents.CallingTeamLeaderSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ceo_orchestration_snapshots",
    )

    cross_cutting_alerts = models.JSONField(default=list, blank=True)
    top_3_priorities = models.JSONField(default=list, blank=True)
    agent_status_summary = models.JSONField(default=dict, blank=True)
    briefing_text = models.TextField(blank=True, default="")
    alerts = models.JSONField(default=list, blank=True)

    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ceo_orchestration_snapshots",
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
                name="ceo_orch_snap_at_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"CeoOrchestrationSnapshot {self.pk} - "
            f"{self.snapshot_at:%Y-%m-%d %H:%M} - "
            f"score={self.business_health_score} tier={self.health_tier}"
        )
