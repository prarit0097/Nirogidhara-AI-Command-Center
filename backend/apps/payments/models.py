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
