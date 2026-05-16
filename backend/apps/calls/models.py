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
    # Phase 11A — Transcript Ingestion Pipeline V1.
    # Set by ``apps.calls.transcript_ingestion`` after a successful Vapi
    # REST pull stores the per-utterance lines. Phase 9E Calling Team
    # Leader's transcript_backlog_count uses these denormalized fields
    # in preference to the more expensive ``exclude pk__in (...)`` query.
    transcript_ingested_at = models.DateTimeField(null=True, blank=True)
    transcript_line_count = models.IntegerField(default=0)
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


class CallQualityScore(models.Model):
    """Phase 11B — Call Quality Scorer V1 (deterministic, no LLM).

    One row per scored Call. The 5 dimension scores + the composite
    feed the Phase 11C CAIO Audit Agent. ``raw_signals`` holds the
    diagnostic counters CAIO uses to write its commentary (utterance
    counts, found keywords, greeting/closing booleans).

    Scoring is recommendations-only — this row NEVER triggers an
    outbound call, WhatsApp send, payment, or shipment, and NEVER
    mutates `Customer` / `Order` / `Payment` / `Lead` / `Shipment`.
    """

    class Flag(models.TextChoices):
        COMPLIANCE_VIOLATION = "compliance_violation", "compliance_violation"
        NO_GREETING = "no_greeting", "no_greeting"
        WEAK_PRODUCT_KNOWLEDGE = (
            "weak_product_knowledge",
            "weak_product_knowledge",
        )
        NO_OBJECTION_RESPONSE = (
            "no_objection_response",
            "no_objection_response",
        )
        SHORT_CALL = "short_call", "short_call"
        ZERO_AGENT_UTTERANCES = (
            "zero_agent_utterances",
            "zero_agent_utterances",
        )
        NO_TRANSCRIPT = "no_transcript", "no_transcript"

    call = models.OneToOneField(
        Call,
        on_delete=models.CASCADE,
        related_name="quality_score",
    )
    scored_at = models.DateTimeField()
    scoring_version = models.CharField(
        max_length=40, default="deterministic_v1"
    )
    line_count = models.IntegerField(default=0)
    # Denormalized snapshots so the summary API can group/avg cheaply.
    agent_label = models.CharField(max_length=80, blank=True, default="")
    duration_raw = models.CharField(max_length=16, blank=True, default="")

    connection_score = models.IntegerField(default=0)
    product_knowledge_score = models.IntegerField(default=0)
    compliance_score = models.IntegerField(default=0)
    objection_handling_score = models.IntegerField(default=0)
    tonality_score = models.IntegerField(default=0)
    composite_score = models.IntegerField(default=0)

    flags = models.JSONField(default=list, blank=True)
    # Diagnostic data the Phase 11C CAIO Audit Agent will consume —
    # never customer-facing.
    raw_signals = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-scored_at",)
        indexes = [
            models.Index(fields=["scored_at"], name="p11b_score_scored_at_idx"),
            models.Index(
                fields=["composite_score"],
                name="p11b_score_composite_idx",
            ),
            models.Index(
                fields=["agent_label"],
                name="p11b_score_agent_label_idx",
            ),
        ]


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
