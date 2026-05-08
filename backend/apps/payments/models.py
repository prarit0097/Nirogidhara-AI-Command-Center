from __future__ import annotations

from django.db import models
from django.utils import timezone


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


class RazorpaySandboxPaidStatusLedger(models.Model):
    """Phase 6P — sandbox-only paid-status ledger row.

    This is the **only** model Phase 6P is allowed to mutate. It is
    NOT ``apps.payments.Payment`` and NOT ``apps.orders.Order``.

    The ledger is a 1:1 derivation of an approved Phase 6O
    :class:`RazorpaySandboxStatusReview`. Phase 6P CLI may transition
    its ``current_state`` between sandbox values. Phase 6P NEVER
    writes to real business tables, NEVER calls Razorpay, NEVER sends
    a customer notification.
    """

    review = models.OneToOneField(
        RazorpaySandboxStatusReview,
        on_delete=models.PROTECT,
        related_name="sandbox_paid_status_ledger",
    )
    razorpay_webhook_event = models.ForeignKey(
        RazorpayWebhookEvent,
        on_delete=models.PROTECT,
        related_name="sandbox_paid_status_ledger_rows",
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

    sandbox_payment_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    sandbox_order_effect = models.CharField(
        max_length=64, blank=True, default=""
    )
    current_state = models.CharField(
        max_length=64, blank=True, default="initial", db_index=True
    )
    previous_state = models.CharField(max_length=64, blank=True, default="")
    mutation_count = models.PositiveIntegerField(default=0)
    last_attempt = models.ForeignKey(
        "RazorpaySandboxPaidStatusMutationAttempt",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_last_attempt_for",
    )

    synthetic_eligible = models.BooleanField(default=True)
    # Locked-False — Phase 6P never flips any of these to True.
    business_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_order_mutation_was_made = models.BooleanField(default=False)
    real_payment_mutation_was_made = models.BooleanField(default=False)
    customer_notification_sent = models.BooleanField(
        default=False, db_index=True
    )
    provider_call_attempted = models.BooleanField(default=False)

    rollback_required = models.BooleanField(default=True)
    rolled_back = models.BooleanField(default=False, db_index=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("event_name", "current_state")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6P-Ledger[{self.current_state}] {self.event_name} "
            f"(review={self.review_id})"
        )


class RazorpaySandboxPaidStatusMutationAttempt(models.Model):
    """Phase 6P — one CLI-triggered sandbox mutation attempt.

    Each attempt records the request to apply (or roll back) the
    sandbox status mapping into the ledger. Phase 6P NEVER mutates
    ``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` /
    ``Customer`` / ``Lead`` from this row. Locked safety booleans
    below stay ``False`` for every Phase 6P-created row.
    """

    class Status(models.TextChoices):
        PREPARED = "prepared", "Prepared"
        BLOCKED = "blocked", "Blocked"
        EXECUTED = "executed", "Executed"
        ROLLED_BACK = "rolled_back", "Rolled back"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    class RequestedAction(models.TextChoices):
        APPLY_SANDBOX_STATUS = (
            "apply_sandbox_status",
            "Apply sandbox status",
        )
        ROLLBACK_SANDBOX_STATUS = (
            "rollback_sandbox_status",
            "Rollback sandbox status",
        )

    review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        on_delete=models.PROTECT,
        related_name="sandbox_paid_status_mutation_attempts",
    )
    ledger = models.ForeignKey(
        RazorpaySandboxPaidStatusLedger,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mutation_attempts",
    )
    razorpay_webhook_event = models.ForeignKey(
        RazorpayWebhookEvent,
        on_delete=models.PROTECT,
        related_name="sandbox_paid_status_mutation_attempts",
    )
    source_event_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    event_name = models.CharField(max_length=128, db_index=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PREPARED,
        db_index=True,
    )
    requested_action = models.CharField(
        max_length=32,
        choices=RequestedAction.choices,
        default=RequestedAction.APPLY_SANDBOX_STATUS,
    )
    proposed_payment_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_effect = models.CharField(
        max_length=64, blank=True, default=""
    )

    before_state = models.JSONField(default=dict, blank=True)
    after_state = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)
    confirmation_provided = models.BooleanField(default=False)
    director_signoff_text = models.CharField(max_length=200, blank=True, default="")

    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6p_attempt_requests",
    )
    executed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6p_attempts_executed",
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6p_attempts_rolled_back",
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6p_attempts_archived",
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    idempotency_key = models.CharField(
        max_length=160, unique=True, db_index=True
    )

    # Locked-False safety booleans. Phase 6P never flips any of these
    # to True. Asserted by ``assert_phase6p_no_real_business_mutation``.
    business_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_order_mutation_was_made = models.BooleanField(default=False)
    real_payment_mutation_was_made = models.BooleanField(default=False)
    customer_notification_sent = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("status", "event_name")),
            models.Index(fields=("-created_at", "status")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6P-Attempt[{self.status}] {self.requested_action} "
            f"review={self.review_id}"
        )


class RazorpayPaymentOrderWorkflowGate(models.Model):
    """Phase 6Q — audit-only Payment → Order workflow safety gate.

    Each gate row evaluates whether a future payment-to-order
    workflow would be safe to start after a Phase 6P sandbox proof.
    Phase 6Q **never** mutates real ``Order`` / ``Payment`` /
    ``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead`` /
    ``WhatsAppMessage`` / ``WhatsAppConversation`` rows. It NEVER
    calls Razorpay, NEVER sends a customer notification, NEVER flips
    an env flag. Approving a gate only flips ``status`` to
    ``approved_for_future_phase6r``.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BLOCKED = "blocked", "Blocked"
        PENDING_MANUAL_REVIEW = (
            "pending_manual_review",
            "Pending manual review",
        )
        APPROVED_FOR_FUTURE_PHASE6R = (
            "approved_for_future_phase6r",
            "Approved for future Phase 6R",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    source_attempt = models.ForeignKey(
        RazorpaySandboxPaidStatusMutationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_order_workflow_gates",
    )
    source_ledger = models.ForeignKey(
        RazorpaySandboxPaidStatusLedger,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_order_workflow_gates",
    )
    source_review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_order_workflow_gates",
    )
    razorpay_webhook_event = models.ForeignKey(
        RazorpayWebhookEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_order_workflow_gates",
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
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")

    proposed_payment_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_effect = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_workflow_action = models.CharField(
        max_length=128, blank=True, default=""
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Phase 6P proof verification.
    phase6p_execution_verified = models.BooleanField(default=False)
    phase6p_rollback_verified = models.BooleanField(default=False)

    synthetic_eligible = models.BooleanField(default=False)
    manual_review_required = models.BooleanField(default=True)

    # Locked-False safety booleans. Phase 6Q never flips any of these
    # to True. Asserted by ``assert_phase6q_no_real_business_mutation``.
    workflow_mutation_allowed_in_phase6q = models.BooleanField(default=False)
    real_order_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_payment_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    shipment_mutation_was_made = models.BooleanField(default=False)
    discount_mutation_was_made = models.BooleanField(default=False)
    customer_notification_sent = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)
    rollback_required = models.BooleanField(default=True)

    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
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
        related_name="phase6q_gate_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6q_gate_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6q_gate_archives",
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

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6Q-Gate[{self.status}] {self.event_name} "
            f"(attempt={self.source_attempt_id})"
        )


class RazorpayPaymentDispatchReadinessGate(models.Model):
    """Phase 6R — audit-only Payment → WhatsApp/Courier readiness gate.

    Each readiness gate evaluates whether a future production phase
    could safely prepare WhatsApp customer notification + courier
    dispatch readiness for a paid/order workflow. Phase 6R **never**
    sends a WhatsApp message, **never** queues an outbound, **never**
    calls Meta Cloud, **never** calls Delhivery, **never** creates a
    shipment, **never** mutates real ``Order`` / ``Payment`` /
    ``Customer`` / ``Lead`` / ``WhatsAppMessage`` /
    ``WhatsAppLifecycleEvent`` rows. Approving a readiness gate only
    flips ``status`` to ``approved_for_future_phase6s``.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BLOCKED = "blocked", "Blocked"
        PENDING_MANUAL_REVIEW = (
            "pending_manual_review",
            "Pending manual review",
        )
        APPROVED_FOR_FUTURE_PHASE6S = (
            "approved_for_future_phase6s",
            "Approved for future Phase 6S",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    source_workflow_gate = models.ForeignKey(
        RazorpayPaymentOrderWorkflowGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_readiness_gates",
    )
    source_attempt = models.ForeignKey(
        RazorpaySandboxPaidStatusMutationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_readiness_gates",
    )
    source_ledger = models.ForeignKey(
        RazorpaySandboxPaidStatusLedger,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_readiness_gates",
    )
    source_review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_readiness_gates",
    )
    razorpay_webhook_event = models.ForeignKey(
        RazorpayWebhookEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_readiness_gates",
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
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")

    proposed_payment_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_effect = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_whatsapp_action = models.CharField(
        max_length=128, blank=True, default=""
    )
    proposed_courier_action = models.CharField(
        max_length=128, blank=True, default=""
    )
    proposed_dispatch_readiness_action = models.CharField(
        max_length=128, blank=True, default=""
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Phase 6Q + 6P + 6O proof verification.
    phase6q_gate_approved = models.BooleanField(default=False)
    phase6p_execution_verified = models.BooleanField(default=False)
    phase6p_rollback_verified = models.BooleanField(default=False)

    synthetic_eligible = models.BooleanField(default=False)
    manual_review_required = models.BooleanField(default=True)

    # Locked-False safety booleans. Phase 6R never flips any of these
    # to True. Asserted by ``assert_phase6r_no_live_send_or_courier_mutation``.
    dispatch_readiness_allowed_in_phase6r = models.BooleanField(default=False)
    real_order_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_payment_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    shipment_mutation_was_made = models.BooleanField(default=False)
    shipment_created = models.BooleanField(default=False, db_index=True)
    whatsapp_message_created = models.BooleanField(
        default=False, db_index=True
    )
    whatsapp_message_queued = models.BooleanField(
        default=False, db_index=True
    )
    customer_notification_sent = models.BooleanField(default=False)
    meta_cloud_call_attempted = models.BooleanField(default=False)
    delhivery_call_attempted = models.BooleanField(default=False)
    razorpay_call_attempted = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)
    rollback_required = models.BooleanField(default=True)

    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)
    whatsapp_readiness_checklist = models.JSONField(default=list, blank=True)
    courier_readiness_checklist = models.JSONField(default=list, blank=True)
    dispatch_readiness_checklist = models.JSONField(default=list, blank=True)
    rollback_plan = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")

    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6r_readiness_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6r_readiness_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6r_readiness_archives",
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

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6R-Readiness[{self.status}] {self.event_name} "
            f"(workflow_gate={self.source_workflow_gate_id})"
        )


class RazorpayPaymentDispatchPilotPlan(models.Model):
    """Phase 6S — planning-only Limited Internal Dispatch Pilot Plan.

    Each pilot plan evaluates whether a future limited internal live
    payment → dispatch pilot could be safely designed after an approved
    Phase 6R readiness gate. Phase 6S **never** executes a pilot,
    **never** sends a WhatsApp message, **never** queues an outbound,
    **never** calls Meta Cloud, **never** calls Delhivery, **never**
    calls Razorpay, **never** creates a shipment / AWB, **never**
    mutates real ``Order`` / ``Payment`` / ``Customer`` / ``Lead`` /
    ``WhatsAppMessage`` / ``WhatsAppLifecycleEvent`` rows. Approving a
    pilot plan only flips ``status`` to
    ``approved_for_future_phase6t``.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BLOCKED = "blocked", "Blocked"
        PENDING_MANUAL_REVIEW = (
            "pending_manual_review",
            "Pending manual review",
        )
        APPROVED_FOR_FUTURE_PHASE6T = (
            "approved_for_future_phase6t",
            "Approved for future Phase 6T",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    class PilotMode(models.TextChoices):
        PLANNING_ONLY = "planning_only", "Planning only"
        INTERNAL_STAFF_ONLY = "internal_staff_only", "Internal staff only"

    source_readiness_gate = models.ForeignKey(
        RazorpayPaymentDispatchReadinessGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_pilot_plans",
    )
    source_workflow_gate = models.ForeignKey(
        RazorpayPaymentOrderWorkflowGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_pilot_plans",
    )
    source_attempt = models.ForeignKey(
        RazorpaySandboxPaidStatusMutationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_pilot_plans",
    )
    source_ledger = models.ForeignKey(
        RazorpaySandboxPaidStatusLedger,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_pilot_plans",
    )
    source_review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_pilot_plans",
    )
    razorpay_webhook_event = models.ForeignKey(
        RazorpayWebhookEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_dispatch_pilot_plans",
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
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")

    proposed_pilot_scope = models.CharField(
        max_length=128, blank=True, default=""
    )
    proposed_payment_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_status = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_order_effect = models.CharField(
        max_length=64, blank=True, default=""
    )
    proposed_whatsapp_action = models.CharField(
        max_length=128, blank=True, default=""
    )
    proposed_courier_action = models.CharField(
        max_length=128, blank=True, default=""
    )
    proposed_dispatch_action = models.CharField(
        max_length=128, blank=True, default=""
    )

    pilot_mode = models.CharField(
        max_length=32,
        choices=PilotMode.choices,
        default=PilotMode.PLANNING_ONLY,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    internal_only = models.BooleanField(default=True)
    max_pilot_orders = models.PositiveIntegerField(default=1)
    max_amount_paise = models.PositiveIntegerField(default=100)
    allowed_customer_scope = models.CharField(
        max_length=64, blank=True, default="internal_staff_only"
    )
    allowed_staff_cohort = models.JSONField(default=list, blank=True)
    allowed_event_names = models.JSONField(default=list, blank=True)
    whatsapp_template_candidates = models.JSONField(default=list, blank=True)
    courier_precheck_candidates = models.JSONField(default=list, blank=True)
    dispatch_precheck_candidates = models.JSONField(default=list, blank=True)
    kill_switch_requirements = models.JSONField(default=dict, blank=True)
    approval_requirements = models.JSONField(default=dict, blank=True)
    rollback_plan = models.JSONField(default=dict, blank=True)
    abort_criteria = models.JSONField(default=list, blank=True)
    verification_checklist = models.JSONField(default=list, blank=True)

    manual_review_required = models.BooleanField(default=True)

    # Locked-False safety booleans. Phase 6S never flips any of these
    # to True. Asserted by
    # ``assert_phase6s_no_live_execution_or_provider_call``.
    pilot_execution_allowed_in_phase6s = models.BooleanField(default=False)
    live_send_allowed_in_phase6s = models.BooleanField(default=False)
    courier_booking_allowed_in_phase6s = models.BooleanField(default=False)
    provider_call_allowed_in_phase6s = models.BooleanField(default=False)
    real_order_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_payment_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    shipment_mutation_was_made = models.BooleanField(default=False)
    shipment_created = models.BooleanField(default=False, db_index=True)
    awb_created = models.BooleanField(default=False, db_index=True)
    whatsapp_message_created = models.BooleanField(
        default=False, db_index=True
    )
    whatsapp_message_queued = models.BooleanField(
        default=False, db_index=True
    )
    customer_notification_sent = models.BooleanField(default=False)
    meta_cloud_call_attempted = models.BooleanField(default=False)
    delhivery_call_attempted = models.BooleanField(default=False)
    razorpay_call_attempted = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)
    rollback_required = models.BooleanField(default=True)

    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")

    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6s_pilot_plan_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6s_pilot_plan_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6s_pilot_plan_archives",
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

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6S-PilotPlan[{self.status}] {self.event_name} "
            f"(readiness={self.source_readiness_gate_id})"
        )


class RazorpayPhase6FinalAuditLock(models.Model):
    """Phase 6T - final Phase 6 audit-lock / decision-gate record.

    This row composes the Phase 6N -> Phase 6S safety chain and records
    whether a future controlled pilot execution phase may be considered.
    Phase 6T never executes a pilot, never calls providers, never sends
    WhatsApp, and never mutates real business rows.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BLOCKED = "blocked", "Blocked"
        PENDING_MANUAL_REVIEW = (
            "pending_manual_review",
            "Pending manual review",
        )
        LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW = (
            "locked_for_future_controlled_pilot_review",
            "Locked for future controlled pilot review",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    source_pilot_plan = models.ForeignKey(
        RazorpayPaymentDispatchPilotPlan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_readiness_gate = models.ForeignKey(
        RazorpayPaymentDispatchReadinessGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_workflow_gate = models.ForeignKey(
        RazorpayPaymentOrderWorkflowGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_attempt = models.ForeignKey(
        RazorpaySandboxPaidStatusMutationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_ledger = models.ForeignKey(
        RazorpaySandboxPaidStatusLedger,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_event_record = models.ForeignKey(
        RazorpayWebhookEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase6_final_audit_locks",
    )
    source_event_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    event_name = models.CharField(max_length=128, db_index=True)
    provider_environment = models.CharField(max_length=16, default="test")
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")

    status = models.CharField(
        max_length=64,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    phase6n_verified = models.BooleanField(default=False)
    phase6o_verified = models.BooleanField(default=False)
    phase6p_verified = models.BooleanField(default=False)
    phase6q_verified = models.BooleanField(default=False)
    phase6r_verified = models.BooleanField(default=False)
    phase6s_verified = models.BooleanField(default=False)
    full_chain_verified = models.BooleanField(default=False)
    final_audit_passed = models.BooleanField(default=False)

    director_signoff_required = models.BooleanField(default=True)
    kill_switch_required = models.BooleanField(default=True)
    rollback_required = models.BooleanField(default=True)
    future_execution_allowed_by_phase6t = models.BooleanField(default=False)
    controlled_pilot_execution_allowed_in_phase6t = models.BooleanField(
        default=False
    )
    manual_review_required = models.BooleanField(default=True)
    internal_only = models.BooleanField(default=True)
    max_pilot_orders = models.PositiveIntegerField(default=1)
    max_amount_paise = models.PositiveIntegerField(default=100)

    real_order_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_payment_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    shipment_mutation_was_made = models.BooleanField(default=False)
    shipment_created = models.BooleanField(default=False, db_index=True)
    awb_created = models.BooleanField(default=False, db_index=True)
    whatsapp_message_created = models.BooleanField(
        default=False, db_index=True
    )
    whatsapp_message_queued = models.BooleanField(
        default=False, db_index=True
    )
    customer_notification_sent = models.BooleanField(default=False)
    meta_cloud_call_attempted = models.BooleanField(default=False)
    delhivery_call_attempted = models.BooleanField(default=False)
    razorpay_call_attempted = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)
    env_flag_flip_detected = models.BooleanField(default=False)
    raw_secret_exposed = models.BooleanField(default=False)
    full_pii_exposed = models.BooleanField(default=False)

    phase6n_snapshot = models.JSONField(default=dict, blank=True)
    phase6o_snapshot = models.JSONField(default=dict, blank=True)
    phase6p_snapshot = models.JSONField(default=dict, blank=True)
    phase6q_snapshot = models.JSONField(default=dict, blank=True)
    phase6r_snapshot = models.JSONField(default=dict, blank=True)
    phase6s_snapshot = models.JSONField(default=dict, blank=True)
    final_attestation = models.JSONField(default=dict, blank=True)
    director_signoff_contract = models.JSONField(default=dict, blank=True)
    kill_switch_contract = models.JSONField(default=dict, blank=True)
    rollback_contract = models.JSONField(default=dict, blank=True)
    abort_criteria = models.JSONField(default=list, blank=True)
    operator_checklist = models.JSONField(default=list, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)

    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6t_final_audit_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase6t_final_audit_archives",
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

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase6T-FinalAudit[{self.status}] {self.event_name} "
            f"(plan={self.source_pilot_plan_id})"
        )


class RazorpayControlledPilotExecutionGate(models.Model):
    """Phase 7B - controlled pilot execution gate (gate-only).

    A Phase 7B gate row references a locked Phase 6T final audit lock
    chain and tracks the prepare / dry-run / rollback dry-run / approve
    lifecycle that *would* later be considered by a future Phase 7C
    review. Phase 7B **never** executes a pilot, **never** calls
    Razorpay / Meta Cloud / Delhivery / Vapi, **never** sends or queues
    a WhatsApp message, **never** creates a shipment / AWB, **never**
    mutates real ``Order`` / ``Payment`` / ``Shipment`` /
    ``DiscountOfferLog`` / ``Customer`` / ``Lead`` rows. Approving a
    gate only flips ``status`` to
    ``approved_for_future_phase7c_execution_review``.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BLOCKED = "blocked", "Blocked"
        PENDING_MANUAL_REVIEW = (
            "pending_manual_review",
            "Pending manual review",
        )
        APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW = (
            "approved_for_future_phase7c_execution_review",
            "Approved for future Phase 7C execution review",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    source_final_audit_lock = models.ForeignKey(
        RazorpayPhase6FinalAuditLock,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_pilot_plan = models.ForeignKey(
        RazorpayPaymentDispatchPilotPlan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_readiness_gate = models.ForeignKey(
        RazorpayPaymentDispatchReadinessGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_workflow_gate = models.ForeignKey(
        RazorpayPaymentOrderWorkflowGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_attempt = models.ForeignKey(
        RazorpaySandboxPaidStatusMutationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_ledger = models.ForeignKey(
        RazorpaySandboxPaidStatusLedger,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )
    source_event_record = models.ForeignKey(
        RazorpayWebhookEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_pilot_execution_gates",
    )

    source_event_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    event_name = models.CharField(max_length=128, db_index=True)
    provider_environment = models.CharField(max_length=16, default="test")
    amount_paise = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True, default="")

    status = models.CharField(
        max_length=64,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    phase6t_lock_verified = models.BooleanField(default=False)
    phase6s_pilot_plan_verified = models.BooleanField(default=False)
    phase6r_readiness_verified = models.BooleanField(default=False)
    phase6q_workflow_gate_verified = models.BooleanField(default=False)
    phase6p_attempt_verified = models.BooleanField(default=False)
    phase6o_review_verified = models.BooleanField(default=False)
    phase6m_event_verified = models.BooleanField(default=False)
    full_chain_verified = models.BooleanField(default=False)

    dry_run_passed = models.BooleanField(default=False, db_index=True)
    rollback_dry_run_passed = models.BooleanField(default=False, db_index=True)

    manual_review_required = models.BooleanField(default=True)
    internal_only = models.BooleanField(default=True)
    max_pilot_orders = models.PositiveIntegerField(default=1)
    max_amount_paise = models.PositiveIntegerField(default=100)

    # Locked-False safety booleans. Phase 7B never flips any of these
    # to True. Asserted by ``assert_phase7b_no_unauthorised_provider_call``.
    controlled_pilot_execution_allowed_in_phase7b = models.BooleanField(
        default=False
    )
    live_execution_allowed_in_phase7b = models.BooleanField(default=False)
    provider_call_allowed_in_phase7b = models.BooleanField(default=False)
    business_mutation_allowed_in_phase7b = models.BooleanField(default=False)
    customer_notification_allowed_in_phase7b = models.BooleanField(
        default=False
    )
    whatsapp_send_allowed_in_phase7b = models.BooleanField(default=False)
    whatsapp_queue_allowed_in_phase7b = models.BooleanField(default=False)
    courier_booking_allowed_in_phase7b = models.BooleanField(default=False)
    shipment_creation_allowed_in_phase7b = models.BooleanField(default=False)
    awb_creation_allowed_in_phase7b = models.BooleanField(default=False)
    frontend_execution_allowed_in_phase7b = models.BooleanField(default=False)
    api_execution_allowed_in_phase7b = models.BooleanField(default=False)
    real_order_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_payment_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    shipment_mutation_was_made = models.BooleanField(default=False)
    shipment_created = models.BooleanField(default=False, db_index=True)
    awb_created = models.BooleanField(default=False, db_index=True)
    whatsapp_message_created = models.BooleanField(
        default=False, db_index=True
    )
    whatsapp_message_queued = models.BooleanField(
        default=False, db_index=True
    )
    customer_notification_sent = models.BooleanField(default=False)
    meta_cloud_call_attempted = models.BooleanField(default=False)
    delhivery_call_attempted = models.BooleanField(default=False)
    razorpay_call_attempted = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)
    env_flag_flip_detected = models.BooleanField(default=False)
    raw_secret_exposed = models.BooleanField(default=False)
    full_pii_exposed = models.BooleanField(default=False)

    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")

    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7b_controlled_pilot_gate_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7b_controlled_pilot_gate_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7b_controlled_pilot_gate_archives",
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

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7B-PilotGate[{self.status}] {self.event_name} "
            f"(lock={self.source_final_audit_lock_id})"
        )


class RazorpayControlledPilotGateDryRunRecord(models.Model):
    """Phase 7B dry-run record. Re-validates the Phase 6T -> 6M chain
    against current DB state. Never calls a provider; never mutates
    business rows; never flips an env flag.
    """

    gate = models.ForeignKey(
        RazorpayControlledPilotExecutionGate,
        on_delete=models.CASCADE,
        related_name="dry_run_records",
    )
    verified_at = models.DateTimeField(default=timezone.now, db_index=True)
    phase6t_verified = models.BooleanField(default=False)
    phase6s_verified = models.BooleanField(default=False)
    phase6r_verified = models.BooleanField(default=False)
    phase6q_verified = models.BooleanField(default=False)
    phase6p_verified = models.BooleanField(default=False)
    phase6o_verified = models.BooleanField(default=False)
    phase6m_verified = models.BooleanField(default=False)
    chain_pass = models.BooleanField(default=False, db_index=True)
    evaluated_safety_invariants = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("gate", "-created_at")),
            models.Index(fields=("chain_pass", "-created_at")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7B-DryRun[gate={self.gate_id} pass={self.chain_pass}]"
        )


class RazorpayControlledPilotGateRollbackDryRunRecord(models.Model):
    """Phase 7B rollback dry-run record. Rehearses the synthetic gate-
    state revert path that a future Phase 7C execution would need.
    Phase 7B has no real artefact to revert; this record is purely
    declarative. Never calls a provider; never flips an env flag.
    """

    class DryRunStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    gate = models.ForeignKey(
        RazorpayControlledPilotExecutionGate,
        on_delete=models.CASCADE,
        related_name="rollback_dry_run_records",
    )
    verified_at = models.DateTimeField(default=timezone.now, db_index=True)
    dry_run_status = models.CharField(
        max_length=16,
        choices=DryRunStatus.choices,
        default=DryRunStatus.PENDING,
        db_index=True,
    )
    rehearsal_steps = models.JSONField(default=list, blank=True)
    env_flag_snapshot = models.JSONField(default=dict, blank=True)
    evaluated_safety_invariants = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("gate", "-created_at")),
            models.Index(fields=("dry_run_status", "-created_at")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7B-RollbackDryRun[gate={self.gate_id} "
            f"status={self.dry_run_status}]"
        )


class RazorpayControlledPilotExecutionAttempt(models.Model):
    """Phase 7D - Razorpay-only one-shot internal TEST execution attempt.

    A single controlled Razorpay TEST-mode ``Orders.create()`` execution
    attempt linked to one approved Phase 7B
    :class:`RazorpayControlledPilotExecutionGate` row. This model
    records safe summaries only and **never** mutates real ``Order`` /
    ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` / ``Customer`` /
    ``Lead`` rows. Phase 7D never sends WhatsApp, never calls Meta
    Cloud / Delhivery / Vapi, never creates a shipment / AWB, never
    creates a payment link, never captures, and never refunds.
    Approving an attempt only flips ``status`` to
    ``approved_for_one_shot_run``. Even after approval, the actual
    ``execute_*`` CLI requires three Phase 7D env flags + non-empty
    Director sign-off + RAZORPAY_KEY_ID starting with ``rzp_test_`` +
    RuntimeKillSwitch enabled + source-chain green; only then ONE
    Razorpay TEST ``Orders.create()`` is issued.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BLOCKED = "blocked", "Blocked"
        PENDING_DIRECTOR_SIGNOFF = (
            "pending_director_signoff",
            "Pending Director sign-off",
        )
        APPROVED_FOR_ONE_SHOT_RUN = (
            "approved_for_one_shot_run",
            "Approved for one-shot run",
        )
        EXECUTED = "executed", "Executed"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"
        ARCHIVED = "archived", "Archived"

    class RollbackStatus(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    source_phase7b_gate = models.ForeignKey(
        RazorpayControlledPilotExecutionGate,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_phase6t_lock = models.ForeignKey(
        RazorpayPhase6FinalAuditLock,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_pilot_plan = models.ForeignKey(
        RazorpayPaymentDispatchPilotPlan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_readiness_gate = models.ForeignKey(
        RazorpayPaymentDispatchReadinessGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_workflow_gate = models.ForeignKey(
        RazorpayPaymentOrderWorkflowGate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_sandbox_attempt = models.ForeignKey(
        RazorpaySandboxPaidStatusMutationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_sandbox_review = models.ForeignKey(
        RazorpaySandboxStatusReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )
    source_event_record = models.ForeignKey(
        RazorpayWebhookEvent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7d_execution_attempts",
    )

    status = models.CharField(
        max_length=64,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    provider_environment = models.CharField(max_length=16, default="test")
    amount_paise = models.PositiveIntegerField(default=100)
    currency = models.CharField(max_length=8, default="INR")
    receipt = models.CharField(max_length=128, blank=True, default="")

    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    safe_request_summary = models.JSONField(default=dict, blank=True)
    safe_response_summary = models.JSONField(default=dict, blank=True)
    provider_object_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    provider_status = models.CharField(max_length=64, blank=True, default="")

    rollback_status = models.CharField(
        max_length=16,
        choices=RollbackStatus.choices,
        default=RollbackStatus.PENDING,
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rollback_reason = models.TextField(blank=True, default="")

    director_signoff_text = models.TextField(blank=True, default="")
    kill_switch_snapshot = models.JSONField(default=dict, blank=True)
    env_flag_snapshot_at_start = models.JSONField(default=dict, blank=True)
    env_flag_snapshot_at_end = models.JSONField(default=dict, blank=True)
    before_counts = models.JSONField(default=dict, blank=True)
    after_counts = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    safety_invariants = models.JSONField(default=dict, blank=True)

    # Locked-False safety booleans. Phase 7D never flips any of these
    # to True. Asserted by ``assert_phase7d_no_business_mutation``.
    business_mutation_was_made = models.BooleanField(default=False)
    payment_link_created = models.BooleanField(default=False)
    payment_captured = models.BooleanField(default=False)
    payment_refunded = models.BooleanField(default=False)
    customer_notification_sent = models.BooleanField(default=False)
    whatsapp_message_created = models.BooleanField(
        default=False, db_index=True
    )
    whatsapp_message_queued = models.BooleanField(
        default=False, db_index=True
    )
    whatsapp_lifecycle_event_created = models.BooleanField(default=False)
    meta_cloud_call_attempted = models.BooleanField(default=False)
    delhivery_call_attempted = models.BooleanField(default=False)
    shipment_created = models.BooleanField(default=False, db_index=True)
    awb_created = models.BooleanField(default=False, db_index=True)
    real_order_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    real_payment_mutation_was_made = models.BooleanField(
        default=False, db_index=True
    )
    customer_mutation_was_made = models.BooleanField(default=False)
    lead_mutation_was_made = models.BooleanField(default=False)
    discount_offer_log_mutation_was_made = models.BooleanField(default=False)
    mcp_tool_called = models.BooleanField(default=False)
    kill_switch_disabled_during_attempt = models.BooleanField(default=False)
    env_flag_flipped_outside_window = models.BooleanField(default=False)
    raw_secret_exposed = models.BooleanField(default=False)
    full_pii_exposed = models.BooleanField(default=False)

    # Allowed-True booleans (single-attempt only).
    provider_call_attempted = models.BooleanField(default=False)
    razorpay_call_attempted = models.BooleanField(default=False)
    idempotency_lock_acquired = models.BooleanField(default=False)
    rollback_recorded = models.BooleanField(default=False)
    director_signoff_present = models.BooleanField(default=False)

    # Phase 7D-Hotfix-1: structured Director sign-off UTC window
    # parsed at execute-time. NULL on every pre-Hotfix-1 row (do NOT
    # backfill). NULL on rows where parsing failed before the
    # validator was called.
    recorded_signoff_window_valid = models.BooleanField(
        null=True, blank=True
    )
    recorded_signoff_window_start_utc = models.DateTimeField(
        null=True, blank=True
    )
    recorded_signoff_window_end_utc = models.DateTimeField(
        null=True, blank=True
    )

    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7d_execution_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7d_execution_reviews",
    )
    executed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7d_execution_executors",
    )
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7d_execution_archives",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=200, blank=True, default="")
    executed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archive_reason = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("provider_object_id", "-created_at")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7D-Attempt[{self.status}] gate={self.source_phase7b_gate_id}"
        )


class RazorpayControlledPilotExecutionRollback(models.Model):
    """Phase 7D rollback record per attempt.

    Phase 7D rollback is **record-only**: Razorpay TEST orders cannot
    be deleted. Rolling back records the contract (`rolled_back_at`,
    rollback reason) and never re-issues a provider call. The Phase 7D
    service NEVER edits any ``.env*`` file; restoration of the three
    Phase 7D window flags to ``False`` is operator-controlled and
    verified externally.
    """

    class DryRunStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    attempt = models.ForeignKey(
        RazorpayControlledPilotExecutionAttempt,
        on_delete=models.CASCADE,
        related_name="rollback_records",
    )
    verified_at = models.DateTimeField(default=timezone.now, db_index=True)
    rollback_status = models.CharField(
        max_length=16,
        choices=DryRunStatus.choices,
        default=DryRunStatus.PENDING,
        db_index=True,
    )
    rollback_reason = models.TextField(blank=True, default="")
    env_flag_presence_at_rollback = models.JSONField(default=dict, blank=True)
    evaluated_safety_invariants = models.JSONField(default=dict, blank=True)
    provider_object_id_recorded = models.CharField(
        max_length=64, blank=True, default=""
    )
    recovery_notes = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("attempt", "-created_at")),
            models.Index(fields=("rollback_status", "-created_at")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7D-Rollback[attempt={self.attempt_id} "
            f"status={self.rollback_status}]"
        )


class RazorpayWhatsAppInternalNotificationGate(models.Model):
    """Phase 7E - Controlled Internal WhatsApp Notification Readiness Gate.

    Gate-only and CLI-only for review state changes. Phase 7E
    references an executed-and-rolled-back Phase 7D attempt and turns
    it into an audit-only readiness contract for a future Phase 7F /
    Phase 7E-Live decision. Approval flips status to
    ``approved_for_future_phase7f_or_7e_send_review`` only - it does
    NOT enable any send path.

    Phase 7E **never** sends a WhatsApp message, **never** queues an
    outbound, **never** calls Meta Cloud, **never** calls Delhivery /
    Vapi, **never** creates a shipment / AWB / payment link, **never**
    captures, **never** refunds, **never** mutates real ``Order`` /
    ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` / ``Customer`` /
    ``Lead`` rows, **never** sends a customer notification, and
    **never** edits any ``.env*`` file.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_MANUAL_REVIEW = (
            "pending_manual_review",
            "Pending manual review",
        )
        APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW = (
            "approved_for_future_phase7f_or_7e_send_review",
            "Approved for future Phase 7F or 7E send review",
        )
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"
        BLOCKED = "blocked", "Blocked"

    class SourcePhase7DSignoffWindowValidationStatus(models.TextChoices):
        VALID_STRUCTURED_WINDOW = (
            "valid_structured_window",
            "Valid structured window",
        )
        FAILED_OR_LEGACY_FREE_TEXT = (
            "failed_or_legacy_free_text",
            "Failed or legacy free text",
        )
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    source_phase7d_attempt = models.ForeignKey(
        RazorpayControlledPilotExecutionAttempt,
        on_delete=models.PROTECT,
        related_name="phase7e_notification_gates",
    )
    source_phase7b_gate = models.ForeignKey(
        RazorpayControlledPilotExecutionGate,
        on_delete=models.PROTECT,
        related_name="phase7e_notification_gates",
    )
    source_phase6t_lock = models.ForeignKey(
        RazorpayPhase6FinalAuditLock,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phase7e_notification_gates",
    )

    status = models.CharField(
        max_length=64,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Internal cohort metadata (last-4 only; never full E.164).
    target_internal_cohort_phone_suffix_last4 = models.CharField(
        max_length=4, blank=True, default=""
    )
    target_internal_cohort_member_id = models.CharField(
        max_length=64, blank=True, default=""
    )

    # Proposed templates / variable keys (NOT values; NOT PII).
    proposed_template_action_keys = models.JSONField(
        default=list, blank=True
    )
    proposed_template_names_resolved = models.JSONField(
        default=list, blank=True
    )
    proposed_variable_keys = models.JSONField(default=list, blank=True)

    # Claim-Vault grounding state (set by dry-run).
    claim_vault_grounded = models.BooleanField(
        default=False, db_index=True
    )
    claim_vault_blockers = models.JSONField(default=list, blank=True)

    # Dry-run / rollback-dry-run flags (set by their respective commands).
    dry_run_passed = models.BooleanField(default=False, db_index=True)
    dry_run_failed_reasons = models.JSONField(default=list, blank=True)
    rollback_dry_run_passed = models.BooleanField(
        default=False, db_index=True
    )
    rollback_dry_run_failed_reasons = models.JSONField(
        default=list, blank=True
    )

    # Source Phase 7D sign-off window state (recorded but not blocking;
    # Phase 7E approval handles legacy free-text via acknowledgement).
    source_phase7d_signoff_window_validation_status = models.CharField(
        max_length=48,
        choices=SourcePhase7DSignoffWindowValidationStatus.choices,
        default=(
            SourcePhase7DSignoffWindowValidationStatus.NOT_APPLICABLE
        ),
    )
    source_phase7d_window_violation_acknowledged = models.BooleanField(
        default=False
    )
    source_phase7d_window_violation_ack_at = models.DateTimeField(
        null=True, blank=True
    )

    # Phase 7E review-only window parsed from the new Director sign-off
    # at approve time (NOT the source Phase 7D sign-off).
    phase7e_future_review_signoff_window_start_utc = models.DateTimeField(
        null=True, blank=True
    )
    phase7e_future_review_signoff_window_end_utc = models.DateTimeField(
        null=True, blank=True
    )
    phase7e_future_review_signoff_window_valid = models.BooleanField(
        default=False
    )

    # Director sign-off raw text (stored; serializer NEVER returns).
    director_signoff_text = models.TextField(blank=True, default="")

    # Snapshots and counts.
    kill_switch_snapshot_at_each_step = models.JSONField(
        default=dict, blank=True
    )
    env_flag_snapshot_at_each_step = models.JSONField(
        default=dict, blank=True
    )
    safety_invariants_snapshot = models.JSONField(default=dict, blank=True)
    before_counts = models.JSONField(default=dict, blank=True)
    after_counts = models.JSONField(default=dict, blank=True)

    # Idempotency / blockers / next action.
    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    next_action = models.CharField(max_length=128, blank=True, default="")
    reject_reason = models.TextField(blank=True, default="")
    archive_reason = models.TextField(blank=True, default="")

    # Reviewers + timestamps.
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7e_gate_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7e_gate_reviews",
    )
    rejected_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7e_gate_rejections",
    )
    archived_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phase7e_gate_archives",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phase7e_notification_gates",
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phase7e_notification_gates",
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("source_phase7d_attempt", "-created_at")),
            models.Index(fields=("claim_vault_grounded", "status")),
            models.Index(
                fields=(
                    "phase7e_future_review_signoff_window_valid",
                    "status",
                )
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7E-NotifGate[id={self.pk} "
            f"attempt={self.source_phase7d_attempt_id} "
            f"status={self.status}]"
        )


class RazorpayWhatsAppInternalNotificationDryRunRecord(models.Model):
    """Phase 7E - dry-run / rollback-dry-run rehearsal record.

    Mirrors the Phase 7B dry-run record pattern so multiple
    rehearsals can stack against one gate. Each record proves that
    no business row leaked between rehearsals.
    """

    class Kind(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        ROLLBACK_DRY_RUN = "rollback_dry_run", "Rollback dry run"

    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    gate = models.ForeignKey(
        RazorpayWhatsAppInternalNotificationGate,
        on_delete=models.CASCADE,
        related_name="dry_run_records",
    )
    kind = models.CharField(
        max_length=24, choices=Kind.choices, db_index=True
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, db_index=True
    )
    idempotency_key = models.CharField(
        max_length=200, unique=True, db_index=True
    )
    safety_invariants_snapshot = models.JSONField(default=dict, blank=True)
    before_counts = models.JSONField(default=dict, blank=True)
    after_counts = models.JSONField(default=dict, blank=True)
    claim_vault_grounded = models.BooleanField(default=False)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("gate", "kind", "-created_at")),
            models.Index(fields=("status", "-created_at")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"Phase7E-DryRun[gate={self.gate_id} kind={self.kind} "
            f"status={self.status}]"
        )
