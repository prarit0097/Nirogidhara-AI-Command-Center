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


class AiCallCampaignGate(models.Model):
    """Phase 12A — AI Calling Campaign Gate V1 (Director-approved Vapi outbound).

    One gate row per Director-approved outbound calling campaign. The
    gate authorises ``trigger_call_for_lead`` to fire for a vetted set
    of Leads inside a structured 30-minute UTC window. Mirrors the
    Phase 7E-Live-B safety pattern (draft → approved → executed) with
    an extra ``executing`` intermediate state because a campaign loops
    over multiple leads.

    NEVER sends WhatsApp, mutates Order/Payment/Shipment, or calls
    Razorpay/Meta Cloud/Delhivery. The only side effect on execute is
    calling ``apps.calls.services.trigger_call_for_lead`` per eligible
    Lead — and only when every guard (env flag + UTC window + kill
    switch + ``VAPI_MODE=live``) is satisfied.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        APPROVED = "approved", "approved"
        EXECUTING = "executing", "executing"
        COMPLETED = "completed", "completed"
        FAILED = "failed", "failed"
        CANCELLED = "cancelled", "cancelled"

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    ai_assistant_id = models.CharField(max_length=120, blank=True, default="")
    stage_filter = models.JSONField(default=list, blank=True)
    max_leads = models.IntegerField(default=20)
    leads_selected = models.JSONField(default=list, blank=True)
    leads_attempted = models.JSONField(default=list, blank=True)
    calls_attempted = models.IntegerField(default=0)
    calls_dispatched = models.IntegerField(default=0)
    calls_skipped = models.IntegerField(default=0)
    operator_name = models.CharField(max_length=120, blank=True, default="")
    operator_note = models.TextField(blank=True, default="")
    intent = models.TextField(blank=True, default="")
    director_signoff = models.TextField(blank=True, default="")
    recorded_signoff_window_start_utc = models.DateTimeField(
        null=True, blank=True
    )
    recorded_signoff_window_end_utc = models.DateTimeField(
        null=True, blank=True
    )
    recorded_signoff_window_valid = models.BooleanField(default=False)
    prepared_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    sandbox = models.BooleanField(default=False)
    # Recorded for audit at execute time so future replay knows which
    # backend (mock / test / live) the campaign ran against.
    vapi_mode_at_execute = models.CharField(
        max_length=20, blank=True, default=""
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("status",), name="aicc_status_idx"),
            models.Index(fields=("-prepared_at",), name="aicc_prepared_at_idx"),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiCallCampaignGate {self.pk} - {self.status}"


class CallOutcomeRecord(models.Model):
    """Phase 12B — Call Outcome Classifier V1 (recommendations-only).

    One row per classified Call. Idempotent via the OneToOne FK.
    The classifier reads transcript text deterministically (keyword
    match against Hinglish-aware signal lists) and proposes a
    `Lead.status` update — but NEVER applies the update without an
    explicit Director CLI command (`apply_call_outcome_updates`).

    Phase 12B never sends WhatsApp, makes a call, dispatches a
    shipment, or calls Razorpay / Meta Cloud / Delhivery. The only
    side effect outside this table is `Lead.status` mutation inside
    `apply_call_outcome_updates`, gated by `--confirm-outcome-apply`
    + `review_status="approved"`.
    """

    class DetectedOutcome(models.TextChoices):
        CONNECTED_CONVERTED = (
            "connected_converted",
            "connected_converted",
        )
        CONNECTED_CALLBACK = (
            "connected_callback",
            "connected_callback",
        )
        CONNECTED_NOT_INTERESTED = (
            "connected_not_interested",
            "connected_not_interested",
        )
        CONNECTED_UNCLEAR = (
            "connected_unclear",
            "connected_unclear",
        )
        NOT_CONNECTED = "not_connected", "not_connected"
        NO_TRANSCRIPT = "no_transcript", "no_transcript"

    class Confidence(models.TextChoices):
        HIGH = "high", "high"
        MEDIUM = "medium", "medium"
        LOW = "low", "low"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "pending"
        APPROVED = "approved", "approved"
        SKIPPED = "skipped", "skipped"
        APPLIED = "applied", "applied"

    call = models.OneToOneField(
        Call,
        on_delete=models.CASCADE,
        related_name="outcome_record",
    )
    campaign_gate = models.ForeignKey(
        AiCallCampaignGate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outcome_records",
    )
    lead_id = models.CharField(max_length=32, blank=True, default="")
    current_lead_status = models.CharField(
        max_length=32, blank=True, default=""
    )
    detected_outcome = models.CharField(
        max_length=32,
        choices=DetectedOutcome.choices,
        db_index=True,
    )
    suggested_lead_status = models.CharField(
        max_length=32, blank=True, default=""
    )
    confidence = models.CharField(
        max_length=8,
        choices=Confidence.choices,
        default=Confidence.LOW,
    )
    evidence = models.JSONField(default=dict, blank=True)
    review_status = models.CharField(
        max_length=12,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        db_index=True,
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.CharField(max_length=120, blank=True, default="")
    classified_at = models.DateTimeField()
    scoring_version = models.CharField(
        max_length=40, default="deterministic_v1"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-classified_at",)
        indexes = (
            models.Index(
                fields=("review_status",), name="cor_review_status_idx"
            ),
            models.Index(
                fields=("detected_outcome",),
                name="cor_detected_outcome_idx",
            ),
            models.Index(
                fields=("-classified_at",), name="cor_classified_at_idx"
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"CallOutcomeRecord {self.pk} - {self.detected_outcome} - "
            f"{self.review_status}"
        )


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
