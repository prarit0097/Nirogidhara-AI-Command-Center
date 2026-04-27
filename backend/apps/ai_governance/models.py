from __future__ import annotations

from django.db import models


class CeoBriefing(models.Model):
    """Singleton-ish: latest briefing wins. Blueprint Section 6.2.

    Phase 3+ will replace the seeded briefing with a generated one (LLM call
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


class AgentRun(models.Model):
    """Phase 3A — every dispatch to an LLM-backed agent is logged here.

    The model captures the prompt version, raw input slice, raw output, the
    provider/model that ran it, and timing/cost so operators can audit every
    decision the AI surfaces. Phase 3A always runs in read-only / dry-run
    mode: an AgentRun never directly mutates business state. Phase 5 builds
    the approval-matrix middleware that turns vetted suggestions into
    actions.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        SUCCESS = "success", "success"
        FAILED = "failed", "failed"
        SKIPPED = "skipped", "skipped"

    class Agent(models.TextChoices):
        CEO = "ceo", "ceo"
        CAIO = "caio", "caio"
        ADS = "ads", "ads"
        RTO = "rto", "rto"
        SALES_GROWTH = "sales_growth", "sales_growth"
        MARKETING = "marketing", "marketing"
        CFO = "cfo", "cfo"
        COMPLIANCE = "compliance", "compliance"

    id = models.CharField(primary_key=True, max_length=32)
    agent = models.CharField(max_length=24, choices=Agent.choices)
    prompt_version = models.CharField(max_length=24, default="v1.0")
    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=16, default="disabled")
    model = models.CharField(max_length=64, blank=True, default="")
    latency_ms = models.IntegerField(default=0)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    error_message = models.TextField(blank=True, default="")
    dry_run = models.BooleanField(default=True)
    triggered_by = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("agent",)),
            models.Index(fields=("status",)),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.agent} · {self.status}"
