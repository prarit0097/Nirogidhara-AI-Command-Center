from __future__ import annotations

from django.db import models


class LearningRecording(models.Model):
    """Blueprint Section 11 — human call recordings staged for AI training.

    The full QA → Compliance → CAIO → Sandbox → CEO approval pipeline is
    Phase 2; this model captures the row-shape the studio page expects today.
    """

    id = models.CharField(primary_key=True, max_length=32)
    agent = models.CharField(max_length=120)
    duration = models.CharField(max_length=16)
    date = models.CharField(max_length=40)
    stage = models.CharField(max_length=80)
    qa = models.IntegerField(null=True, blank=True)
    compliance = models.CharField(max_length=80, default="Pending")
    outcome = models.CharField(max_length=120, default="Awaiting review")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
