"""Phase 9C — CfoFinancialSnapshot model.

One row per task invocation. Snapshots are immutable — the daily
Celery task writes a new row each run rather than mutating.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models


_ZERO = Decimal("0")


class CfoFinancialSnapshot(models.Model):
    """Deterministic V1 business-level daily financial snapshot."""

    class Alert(models.TextChoices):
        REVENUE_DROP_24H = "revenue_drop_24h", "revenue_drop_24h"
        RTO_SPIKE = "rto_spike", "rto_spike"
        HIGH_PENDING_PAYMENTS = (
            "high_pending_payments",
            "high_pending_payments",
        )
        LOW_ORDER_VOLUME = "low_order_volume", "low_order_volume"
        ALL_CLEAR = "all_clear", "all_clear"

    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cfo_financial_snapshots",
    )
    snapshot_at = models.DateTimeField(db_index=True)

    revenue_24h = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )
    revenue_7d = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )
    revenue_30d = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )

    order_count_24h = models.IntegerField(default=0)
    order_count_7d = models.IntegerField(default=0)
    order_count_30d = models.IntegerField(default=0)

    paid_count = models.IntegerField(default=0)
    partial_count = models.IntegerField(default=0)
    pending_count = models.IntegerField(default=0)
    paid_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )
    partial_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )
    pending_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )

    average_order_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )

    rto_count_30d = models.IntegerField(default=0)
    rto_loss_amount_30d = models.DecimalField(
        max_digits=14, decimal_places=2, default=_ZERO
    )

    new_customer_count_30d = models.IntegerField(default=0)
    returning_customer_count_30d = models.IntegerField(default=0)

    alerts = models.JSONField(default=list, blank=True)
    alert_text = models.TextField(blank=True, default="")
    agent_run = models.ForeignKey(
        "ai_governance.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cfo_financial_snapshots",
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
                name="cfo_snap_at_idx",
            ),
            models.Index(
                fields=("organization", "-snapshot_at"),
                name="cfo_snap_org_at_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"CfoFinancialSnapshot {self.pk} - "
            f"{self.snapshot_at:%Y-%m-%d %H:%M} - "
            f"rev24h={self.revenue_24h} alerts={len(self.alerts or [])}"
        )
