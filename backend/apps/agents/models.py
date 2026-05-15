from __future__ import annotations

from django.db import models


class Agent(models.Model):
    """Blueprint Sections 6, 7, 8 — AI/human agent identity + scoreboard."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WARNING = "warning", "Warning"
        PAUSED = "paused", "Paused"

    id = models.CharField(primary_key=True, max_length=32)
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    health = models.IntegerField(default=100)
    reward = models.IntegerField(default=0)
    penalty = models.IntegerField(default=0)
    last_action = models.CharField(max_length=240, blank=True, default="")
    critical = models.BooleanField(default=False)
    group = models.CharField(max_length=80, default="Department")
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.name}"


# Phase 9A — Customer Success / Reorder Agent V1. Import here so Django
# discovers the model and migrations live in apps/agents/migrations/.
from .customer_success.models import CustomerSuccessSnapshot  # noqa: E402, F401

# Phase 9B — RTO Prevention Agent V1. Same pattern.
from .rto_prevention.models import RtoRiskSnapshot  # noqa: E402, F401

# Phase 9C — CFO Agent V1 (business-level daily financial snapshot).
from .cfo.models import CfoFinancialSnapshot  # noqa: E402, F401
