from __future__ import annotations

from django.db import models


class Call(models.Model):
    """Blueprint Section 5.3 — call attempts, outcomes, sentiment, compliance.

    Phase 2D adds Vapi integration fields: ``provider`` selects which voice
    backend ran the call (``manual`` for human callers, ``vapi`` for the AI
    voice agent). ``provider_call_id`` stores the gateway's external id so
    webhook handlers can look the row up by reference. ``summary`` /
    ``recording_url`` capture post-call analysis. ``handoff_flags`` is the
    list of compliance / safety triggers (medical_emergency,
    side_effect_complaint, very_angry_customer, human_requested,
    low_confidence, legal_or_refund_threat) detected by Vapi or our own
    analyzer; any non-empty entry routes the customer to a human caller.
    ``ended_at`` + ``error_message`` capture call termination state.
    """

    class Status(models.TextChoices):
        LIVE = "Live", "Live"
        QUEUED = "Queued", "Queued"
        COMPLETED = "Completed", "Completed"
        MISSED = "Missed", "Missed"
        FAILED = "Failed", "Failed"

    class Sentiment(models.TextChoices):
        POSITIVE = "Positive", "Positive"
        NEUTRAL = "Neutral", "Neutral"
        HESITANT = "Hesitant", "Hesitant"
        ANNOYED = "Annoyed", "Annoyed"

    class Provider(models.TextChoices):
        MANUAL = "manual", "manual"
        VAPI = "vapi", "vapi"

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
    # Phase 2D — Vapi integration fields.
    provider = models.CharField(
        max_length=16, choices=Provider.choices, default=Provider.MANUAL
    )
    provider_call_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    summary = models.TextField(blank=True, default="")
    recording_url = models.URLField(blank=True, default="")
    handoff_flags = models.JSONField(default=list, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Phase 6B — Default Org Data Backfill (nullable).
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="calls",
        db_index=True,
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="calls",
        db_index=True,
    )

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
    """One line of a call transcript. Phase 2D accepts both the legacy
    ``ActiveCall`` parent (for the AI Calling Console's live pane) and the
    new ``Call`` parent (for Vapi-recorded post-call transcripts). Exactly
    one of the two is set per row.
    """

    active_call = models.ForeignKey(
        ActiveCall,
        on_delete=models.CASCADE,
        related_name="transcript_lines",
        null=True,
        blank=True,
    )
    call = models.ForeignKey(
        Call,
        on_delete=models.CASCADE,
        related_name="transcript_lines",
        null=True,
        blank=True,
    )
    order = models.PositiveIntegerField(default=0)
    who = models.CharField(max_length=40)
    text = models.TextField()

    class Meta:
        ordering = ("order",)


class WebhookEvent(models.Model):
    """Idempotency log for Vapi webhooks. Phase 2D.

    Mirrors ``payments.WebhookEvent`` so each integration owns its own
    idempotency table — keeps the audit trail per-vendor clean.
    """

    event_id = models.CharField(primary_key=True, max_length=128)
    provider = models.CharField(max_length=16, default="vapi")
    event_type = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.provider}:{self.event_type}:{self.event_id}"
