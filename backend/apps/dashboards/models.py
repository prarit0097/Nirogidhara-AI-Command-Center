from __future__ import annotations

from django.db import models


class DashboardMetric(models.Model):
    """One row per top-line KPI card on the Command Center Dashboard.

    `key` matches the property name the frontend expects in
    `getDashboardMetrics()` (`leadsToday`, `netProfit`, `rtoRisk`, etc.).
    """

    key = models.CharField(primary_key=True, max_length=64)
    value = models.IntegerField(default=0)
    delta_pct = models.FloatField(null=True, blank=True)
    completed = models.IntegerField(null=True, blank=True)
    pending = models.IntegerField(null=True, blank=True)
    alerts = models.IntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "key")
