"""Phase 9A — CustomerSuccessSnapshot model.

One row per (customer, agent run). Snapshots are immutable — the
daily Celery task writes a new row each run rather than mutating.
"""
from __future__ import annotations

from django.db import models


class CustomerSuccessSnapshot(models.Model):
    """Deterministic V1 customer-success scoring snapshot."""

    class LifecycleStage(models.TextChoices):
        FRESH_DELIVERY = "fresh_delivery", "fresh_delivery"
        EARLY_USAGE = "early_usage", "early_usage"
        MID_USAGE = "mid_usage", "mid_usage"
        REORDER_WINDOW = "reorder_window", "reorder_window"
        LATE_REORDER = "late_reorder", "late_reorder"
        LAPSED = "lapsed", "lapsed"

    class RecommendationKind(models.TextChoices):
        SEND_USAGE_REMINDER = "send_usage_reminder", "send_usage_reminder"
        SEND_REORDER_REMINDER = "send_reorder_reminder", "send_reorder_reminder"
        SEND_WINBACK_OFFER = "send_winback_offer", "send_winback_offer"
        MONITOR_ONLY = "monitor_only", "monitor_only"

    customer = models.ForeignKey(
        "crm.Customer",
        on_delete=models.CASCADE,
        related_name="customer_success_snapshots",
    )
    score = models.IntegerField(default=0)
    lifecycle_stage = models.CharField(
        max_length=24,
        choices=LifecycleStage.choices,
        db_index=True,
    )
    days_since_delivery = models.IntegerField(default=0)
    in_reorder_window = models.BooleanField(default=False)
    reorder_candidate = models.BooleanField(default=False, db_index=True)
    at_risk = models.BooleanField(default=False, db_index=True)
    risk_reasons = models.JSONField(default=list, blank=True)
    signals = models.JSONField(default=dict, blank=True)
    recommendation_kind = models.CharField(
        max_length=24,
        choices=RecommendationKind.choices,
        default=RecommendationKind.MONITOR_ONLY,
    )
    recommendation_text = models.TextField(blank=True, default="")
    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_success_snapshots",
    )
    sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "agents"
        ordering = ("-created_at",)
        indexes = (
            models.Index(
                fields=("customer", "-created_at"),
                name="cs_snap_cust_created_idx",
            ),
            models.Index(
                fields=("lifecycle_stage",),
                name="cs_snap_lifecycle_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"CustomerSuccessSnapshot {self.pk} - "
            f"{self.customer_id} - {self.lifecycle_stage} - {self.score}"
        )
