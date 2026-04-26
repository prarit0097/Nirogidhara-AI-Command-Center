from __future__ import annotations

from django.db import models


class CeoBriefing(models.Model):
    """Singleton-ish: latest briefing wins. Blueprint Section 6.2.

    Phase 2 will replace the seeded briefing with a generated one (LLM call
    over yesterday's KPIs); the storage shape stays identical.
    """

    date = models.CharField(max_length=40)
    headline = models.CharField(max_length=240)
    summary = models.TextField()
    alerts = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)


class CeoRecommendation(models.Model):
    briefing = models.ForeignKey(CeoBriefing, on_delete=models.CASCADE, related_name="recommendations")
    id_str = models.CharField(max_length=32)
    title = models.CharField(max_length=240)
    reason = models.TextField()
    impact = models.CharField(max_length=120)
    requires = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order",)


class CaioAudit(models.Model):
    """Blueprint Section 6.3 — audit findings the CAIO Agent surfaces.

    CAIO never executes business actions; this table is read-only from the
    governance UI's perspective in this phase.
    """

    class Severity(models.TextChoices):
        CRITICAL = "Critical", "Critical"
        HIGH = "High", "High"
        MEDIUM = "Medium", "Medium"
        LOW = "Low", "Low"

    agent = models.CharField(max_length=120)
    issue = models.CharField(max_length=240)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    suggestion = models.TextField()
    status = models.CharField(max_length=80, default="Open")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order",)
