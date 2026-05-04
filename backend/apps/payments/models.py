from __future__ import annotations

from django.db import models


class Payment(models.Model):
    """Blueprint Section 5.5 — Razorpay/PayU records.

    Phase 2B adds the integration fields ``gateway_reference_id`` (the Razorpay
    ``plink_xxx`` id), ``payment_url`` (short URL returned by the gateway),
    ``customer_phone`` / ``customer_email`` (contact info forwarded to the
    gateway), and ``raw_response`` (the full payload for debugging).
    """

    class Gateway(models.TextChoices):
        RAZORPAY = "Razorpay", "Razorpay"
        PAYU = "PayU", "PayU"

    class Status(models.TextChoices):
        PAID = "Paid", "Paid"
        PENDING = "Pending", "Pending"
        FAILED = "Failed", "Failed"
        REFUNDED = "Refunded", "Refunded"
        CANCELLED = "Cancelled", "Cancelled"
        EXPIRED = "Expired", "Expired"
        PARTIAL = "Partial", "Partial"

    class Type(models.TextChoices):
        ADVANCE = "Advance", "Advance"
        FULL = "Full", "Full"

    id = models.CharField(primary_key=True, max_length=32)
    order_id = models.CharField(max_length=32, db_index=True)
    customer = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=24, blank=True, default="")
    customer_email = models.CharField(max_length=120, blank=True, default="")
    amount = models.IntegerField(default=0)
    gateway = models.CharField(max_length=16, choices=Gateway.choices, default=Gateway.RAZORPAY)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.ADVANCE)
    time = models.CharField(max_length=40, default="just now")
    # Phase 2B integration fields.
    gateway_reference_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    payment_url = models.URLField(blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Phase 6B — Default Org Data Backfill (nullable).
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments",
        db_index=True,
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments",
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.amount} · {self.gateway}"


class WebhookEvent(models.Model):
    """Idempotency log for incoming gateway webhooks. Phase 2B.

    Razorpay redelivers webhooks on failure; we use this table to make every
    handler idempotent — duplicate ``event_id`` insert raises ``IntegrityError``
    and the handler short-circuits with a 200/duplicate response.
    """

    event_id = models.CharField(primary_key=True, max_length=128)
    gateway = models.CharField(max_length=16, default="razorpay")
    event_type = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.gateway}:{self.event_type}:{self.event_id}"


class RazorpayWebhookEvent(models.Model):
    """Phase 6M — Razorpay test-mode webhook event record.

    Phase 6M handler stores SAFE event summaries only — no raw
    payload, no raw secrets, no full PII. ``business_mutation_was_made``
    and ``customer_notification_sent`` are asserted ``False`` at every
    save site.
    """

    class Environment(models.TextChoices):
        TEST = "test", "Test"
        LIVE = "live", "Live"
        UNKNOWN = "unknown", "Unknown"

    class IdempotencyStatus(models.TextChoices):
        FIRST_SEEN = "first_seen", "First seen"
        DUPLICATE = "duplicate", "Duplicate"
        MISSING_EVENT_ID = "missing_event_id", "Missing event id"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        BLOCKED = "blocked", "Blocked"
        VERIFIED = "verified", "Verified"
        STORED = "stored", "Stored"
        DUPLICATE = "duplicate", "Duplicate"
        IGNORED = "ignored", "Ignored"
        FAILED = "failed", "Failed"

    class ProcessingMode(models.TextChoices):
        TEST_MODE_RECORD_ONLY = (
            "test_mode_record_only",
            "Test mode record only",
        )
        FUTURE_MUTATION_DISABLED = (
            "future_mutation_disabled",
            "Future mutation disabled",
        )

    event_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    source_event_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    provider = models.CharField(max_length=24, default="razorpay")
    environment = models.CharField(
        max_length=16,
        choices=Environment.choices,
        default=Environment.TEST,
        db_index=True,
    )
    event_name = models.CharField(max_length=128, db_index=True)
    entity = models.CharField(max_length=64, blank=True, default="event")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_at_from_payload = models.DateTimeField(null=True, blank=True)
    signature_present = models.BooleanField(default=False)
    signature_valid = models.BooleanField(default=False, db_index=True)
    replay_window_valid = models.BooleanField(default=False)
    idempotency_status = models.CharField(
        max_length=24,
        choices=IdempotencyStatus.choices,
        default=IdempotencyStatus.FIRST_SEEN,
        db_index=True,
    )
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
        db_index=True,
    )
    processing_mode = models.CharField(
        max_length=32,
        choices=ProcessingMode.choices,
        default=ProcessingMode.TEST_MODE_RECORD_ONLY,
    )
    provider_order_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    provider_payment_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    provider_refund_id = models.CharField(max_length=64, blank=True, default="")
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")
    payment_status = models.CharField(max_length=32, blank=True, default="")
    order_status = models.CharField(max_length=32, blank=True, default="")
    contains = models.JSONField(default=list, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    safe_payload_summary = models.JSONField(default=dict, blank=True)
    scrubbed_keys = models.JSONField(default=list, blank=True)
    denied_reason = models.CharField(max_length=200, blank=True, default="")
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    business_mutation_attempted = models.BooleanField(default=False, db_index=True)
    business_mutation_was_made = models.BooleanField(default=False, db_index=True)
    customer_notification_attempted = models.BooleanField(default=False)
    customer_notification_sent = models.BooleanField(default=False, db_index=True)
    raw_secret_exposed = models.BooleanField(default=False)
    full_pii_exposed = models.BooleanField(default=False)
    request_headers_summary = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    audit_event_id = models.PositiveIntegerField(null=True, blank=True)
    duplicate_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-received_at",)
        indexes = (
            models.Index(fields=("event_name", "processing_status")),
            models.Index(fields=("-received_at", "processing_status")),
            models.Index(fields=("provider_order_id", "event_name")),
            models.Index(
                fields=(
                    "business_mutation_was_made",
                    "customer_notification_sent",
                )
            ),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("provider", "source_event_id"),
                condition=models.Q(source_event_id__gt=""),
                name="razorpay_webhook_unique_source_event_id",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"{self.event_name} ({self.processing_status}) "
            f"[{self.source_event_id or self.event_id or 'no-id'}]"
        )


class RazorpaySandboxStatusReview(models.Model):
    """Phase 6O — sandbox-only payment-status mapping review record.

    Created from a Phase 6M ``RazorpayWebhookEvent`` for review only.
    Phase 6O **never** mutates ``Order`` / ``Payment`` / ``Shipment`` /
    ``DiscountOfferLog`` and **never** sends a customer notification.
    The locked safety booleans below are persisted with ``False``
    defaults; the service layer asserts none of them ever flip to
    ``True`` in Phase 6O. Approving a review only changes ``status`` to
    ``approved_for_future_phase6p`` — it is permission to future Phase
    6P, not application of a mutation.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        PENDING_MANUAL_REVIEW = "pending_manual_review", "Pending manual review"
        APPROVED_FOR_FUTURE_PHASE6P = (
            "approved_for_future_phase6p",
            "Approved for future Phase 6P",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"
        BLOCKED = "blocked", "Blocked"

    razorpay_webhook_event = models.ForeignKey(
        RazorpayWebhookEvent,
        on_delete=models.PROTECT,
        related_name="sandbox_status_reviews",
    )
    source_event_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    event_name = models.CharField(max_length=128, db_index=True)
    provider_environment = models.CharField(max_length=16, default="test")
    provider_order_id = models.CharField(max_length=64, blank=True, default="")
    provider_payment_id = models.CharField(max_length=64, blank=True, default="")
    provider_payment_link_id = models.CharField(
        max_length=64, blank=True, default=""
    )
    provider_refund_id = models.CharField(max_length=64, blank=True, default="")
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")

    proposed_payment_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_effect = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_review_action = models.CharField(
        max_length=64, blank=True, default=""
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PROPOSED,
        db_index=True,
    )

    # Locked-False safety booleans. Phase 6O never flips any of these
    # to True. Asserted by ``assert_phase6o_no_business_mutation``.
    synthetic_eligible = models.BooleanField(default=False)
    manual_review_required = models.BooleanField(default=True)
    mutation_allowed_in_phase6o = models.BooleanField(default=False)
    business_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    customer_notification_sent = models.BooleanField(
        default=False, db_index=True
    )
    provider_call_attempted = models.BooleanField(default=False)
    shipment_effect_allowed = models.BooleanField(default=False)
    discount_effect_allowed = models.BooleanField(default=False)
    rollback_required = models.BooleanField(default=True)

    idempotency_key = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)
    manual_review_checklist = models.JSONField(default=list, blank=True)
    rollback_plan = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")

    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6o_review_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6o_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6o_review_archives",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archive_reason = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("status", "event_name")),
            models.Index(fields=("-created_at", "status")),
        )
        constraints = (
            # One review per (event, action) — re-preparing the same
            # mapping for the same source event is idempotent.
            models.UniqueConstraint(
                fields=("razorpay_webhook_event", "proposed_review_action"),
                name="razorpay_sandbox_review_unique_event_action",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6O[{self.status}] {self.event_name} "
            f"({self.source_event_id or 'no-id'})"
        )
