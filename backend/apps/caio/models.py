"""Phase 11C — CAIO Audit Agent V1 (recommendations-only).

CAIO has NO direct execution power (Master Blueprint §26 #2). It
monitors, audits, trains, suggests, checks hallucinations, checks
weak learning, checks compliance issues, and audits agents
including CEO AI. This module captures one immutable governance
snapshot per daily run.
"""
from __future__ import annotations

from django.db import models


class CaioAuditSnapshot(models.Model):
    """Deterministic V1 daily CAIO governance audit snapshot."""

    class Severity(models.TextChoices):
        GREEN = "green", "green"
        AMBER = "amber", "amber"
        RED = "red", "red"

    class Trend(models.TextChoices):
        UP = "up", "up"
        FLAT = "flat", "flat"
        DOWN = "down", "down"
        NO_DATA = "no_data", "no_data"

    snapshot_at = models.DateTimeField(db_index=True)
    window_days = models.IntegerField(default=30)

    severity = models.CharField(
        max_length=8,
        choices=Severity.choices,
        default=Severity.GREEN,
        db_index=True,
    )

    # Phase 11B — compliance + transcript health.
    compliance_risk_call_count = models.IntegerField(default=0)
    compliance_risk_agent_labels = models.JSONField(
        default=list, blank=True
    )
    transcript_backlog_count = models.IntegerField(default=0)
    call_quality_trend = models.CharField(
        max_length=10,
        choices=Trend.choices,
        default=Trend.NO_DATA,
    )

    # Phase 9 agent governance.
    agent_data_gaps = models.IntegerField(default=0)
    agent_data_gap_names = models.JSONField(default=list, blank=True)
    agent_anomaly_flags = models.JSONField(default=dict, blank=True)

    # Learning gap detection.
    weak_learning_indicators = models.JSONField(default=list, blank=True)

    # CEO AI cross-audit notes (text observations, NEVER customer-facing).
    ceo_audit_notes = models.JSONField(default=list, blank=True)

    # Director-facing internal briefing text.
    recommendation_text = models.TextField(blank=True, default="")

    # Provenance — which agents/modules were consulted.
    audited_agents = models.JSONField(default=list, blank=True)

    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="caio_audit_snapshots",
    )
    sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-snapshot_at",)
        indexes = (
            models.Index(
                fields=("-snapshot_at",),
                name="caio_snap_at_idx",
            ),
            models.Index(
                fields=("severity",),
                name="caio_snap_severity_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"CaioAuditSnapshot {self.pk} - "
            f"{self.snapshot_at:%Y-%m-%d %H:%M} - {self.severity}"
        )
