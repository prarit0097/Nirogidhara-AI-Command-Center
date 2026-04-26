from __future__ import annotations

from django.db import models


class KPITrend(models.Model):
    """Generic KPI row that backs every chart on the analytics page.

    `series` distinguishes between funnel / revenue / state-rto / product
    rollups. Each row has whichever fields apply (the rest stay null) and is
    serialized into the loose shape the recharts components expect.
    """

    class Series(models.TextChoices):
        FUNNEL = "funnel", "Funnel"
        REVENUE = "revenue", "Revenue trend"
        STATE_RTO = "state_rto", "State RTO"
        PRODUCT_PERFORMANCE = "product_perf", "Product performance"

    series = models.CharField(max_length=24, choices=Series.choices, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    # Loose superset of the recharts shapes used in the frontend.
    d = models.CharField(max_length=40, blank=True, default="")
    stage = models.CharField(max_length=40, blank=True, default="")
    state = models.CharField(max_length=60, blank=True, default="")
    product = models.CharField(max_length=80, blank=True, default="")

    value = models.IntegerField(null=True, blank=True)
    revenue = models.IntegerField(null=True, blank=True)
    profit = models.IntegerField(null=True, blank=True)
    leads = models.IntegerField(null=True, blank=True)
    orders = models.IntegerField(null=True, blank=True)
    delivered = models.IntegerField(null=True, blank=True)
    rto = models.IntegerField(null=True, blank=True)
    rto_pct = models.FloatField(null=True, blank=True)
    net_profit = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ("series", "sort_order")
