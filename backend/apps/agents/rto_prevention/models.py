"""Phase 9B — RtoRiskSnapshot model.

One row per (order, agent run). Snapshots are immutable — the daily
Celery task writes a new row each run rather than mutating.
"""
from __future__ import annotations

from django.db import models


class RtoRiskSnapshot(models.Model):
    """Deterministic V1 RTO risk scoring snapshot for in-flight orders."""

    class RiskTier(models.TextChoices):
        LOW = "low", "low"
        MEDIUM = "medium", "medium"
        HIGH = "high", "high"
        CRITICAL = "critical", "critical"

    class LifecycleStage(models.TextChoices):
        PRE_DISPATCH = "pre_dispatch", "pre_dispatch"
        IN_TRANSIT = "in_transit", "in_transit"
        DELIVERY_AT_RISK = "delivery_at_risk", "delivery_at_risk"

    class RecommendationKind(models.TextChoices):
        MONITOR_ONLY = "monitor_only", "monitor_only"
        SEND_CONFIRMATION_REMINDER = (
            "send_confirmation_reminder",
            "send_confirmation_reminder",
        )
        SEND_PRE_DELIVERY_CALL_REQUEST = (
            "send_pre_delivery_call_request",
            "send_pre_delivery_call_request",
        )
        ESCALATE_TO_TEAM_LEAD = (
            "escalate_to_team_lead",
            "escalate_to_team_lead",
        )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="rto_risk_snapshots",
    )
    customer = models.ForeignKey(
        "crm.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rto_risk_snapshots",
    )
    risk_score = models.IntegerField(default=0)
    risk_tier = models.CharField(
        max_length=12,
        choices=RiskTier.choices,
        db_index=True,
    )
    lifecycle_stage = models.CharField(
        max_length=24,
        choices=LifecycleStage.choices,
    )
    days_since_order = models.IntegerField(default=0)
    failed_delivery_attempts = models.IntegerField(default=0)
    risk_reasons = models.JSONField(default=list, blank=True)
    signals = models.JSONField(default=dict, blank=True)
    recommendation_kind = models.CharField(
        max_length=32,
        choices=RecommendationKind.choices,
        default=RecommendationKind.MONITOR_ONLY,
        db_index=True,
    )
    recommendation_text = models.TextField(blank=True, default="")
    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rto_risk_snapshots",
    )
    sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "agents"
        ordering = ("-created_at",)
        indexes = (
            models.Index(
                fields=("order", "-created_at"),
                name="rto_snap_order_created_idx",
            ),
            models.Index(
                fields=("risk_tier",),
                name="rto_snap_risk_tier_idx",
            ),
            models.Index(
                fields=("recommendation_kind",),
                name="rto_snap_rec_kind_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"RtoRiskSnapshot {self.pk} - "
            f"{self.order_id} - {self.risk_tier} - {self.risk_score}"
        )
