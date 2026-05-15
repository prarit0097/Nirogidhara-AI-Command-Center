"""Phase 9D — DataAnalystSnapshot model.

One row per task invocation. Snapshots are immutable — the daily
Celery task writes a new row each run rather than mutating.
"""
from __future__ import annotations

from django.db import models


class DataAnalystSnapshot(models.Model):
    """Deterministic V1 operational / funnel analytics snapshot."""

    class Alert(models.TextChoices):
        CONVERSION_DROP = "conversion_drop", "conversion_drop"
        GEOGRAPHIC_CONCENTRATION_SHIFT = (
            "geographic_concentration_shift",
            "geographic_concentration_shift",
        )
        DEAD_END_CALLS = "dead_end_calls", "dead_end_calls"
        LEAD_VOLUME_DROP = "lead_volume_drop", "lead_volume_drop"
        ALL_CLEAR = "all_clear", "all_clear"

    snapshot_at = models.DateTimeField(db_index=True)

    lead_count_30d = models.IntegerField(default=0)
    call_count_30d = models.IntegerField(default=0)
    confirmed_order_count_30d = models.IntegerField(default=0)
    delivered_order_count_30d = models.IntegerField(default=0)
    reorder_count_30d = models.IntegerField(default=0)

    lead_to_call_rate = models.FloatField(default=0.0)
    call_to_confirmed_rate = models.FloatField(default=0.0)
    confirmed_to_delivered_rate = models.FloatField(default=0.0)
    delivered_to_reorder_rate = models.FloatField(default=0.0)

    top_states = models.JSONField(default=list, blank=True)
    day_of_week_counts = models.JSONField(default=dict, blank=True)

    alerts = models.JSONField(default=list, blank=True)
    alert_text = models.TextField(blank=True, default="")
    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="data_analyst_snapshots",
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
                name="da_snap_at_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"DataAnalystSnapshot {self.pk} - "
            f"{self.snapshot_at:%Y-%m-%d %H:%M} - "
            f"orders={self.confirmed_order_count_30d} "
            f"alerts={len(self.alerts or [])}"
        )
