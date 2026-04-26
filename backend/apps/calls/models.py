from __future__ import annotations

from django.db import models


class Call(models.Model):
    """Blueprint Section 5.3 — call attempts, outcomes, sentiment, compliance."""

    class Status(models.TextChoices):
        LIVE = "Live", "Live"
        QUEUED = "Queued", "Queued"
        COMPLETED = "Completed", "Completed"
        MISSED = "Missed", "Missed"

    class Sentiment(models.TextChoices):
        POSITIVE = "Positive", "Positive"
        NEUTRAL = "Neutral", "Neutral"
        HESITANT = "Hesitant", "Hesitant"
        ANNOYED = "Annoyed", "Annoyed"

    id = models.CharField(primary_key=True, max_length=32)
    lead_id = models.CharField(max_length=32, db_index=True)
    customer = models.CharField(max_length=120)
    phone = models.CharField(max_length=24)
    agent = models.CharField(max_length=80)
    language = models.CharField(max_length=40)
    duration = models.CharField(max_length=16, default="0:00")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    sentiment = models.CharField(max_length=12, choices=Sentiment.choices, default=Sentiment.NEUTRAL)
    script_compliance = models.IntegerField(default=100)
    payment_link_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class ActiveCall(models.Model):
    """Singleton model for the AI Calling Console's "live" pane.

    Storing it as a row keeps the same admin/seed workflow as the rest. The
    list endpoint always returns the most recent row.
    """

    id = models.CharField(primary_key=True, max_length=32)
    customer = models.CharField(max_length=120)
    phone = models.CharField(max_length=24)
    agent = models.CharField(max_length=80)
    language = models.CharField(max_length=40)
    duration = models.CharField(max_length=16, default="0:00")
    stage = models.CharField(max_length=80)
    sentiment = models.CharField(max_length=24)
    script_compliance = models.IntegerField(default=100)
    detected_objections = models.JSONField(default=list, blank=True)
    approved_claims_used = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)


class CallTranscriptLine(models.Model):
    call = models.ForeignKey(ActiveCall, on_delete=models.CASCADE, related_name="transcript_lines")
    order = models.PositiveIntegerField(default=0)
    who = models.CharField(max_length=40)
    text = models.TextField()

    class Meta:
        ordering = ("order",)
