from __future__ import annotations

from django.db import models


class Shipment(models.Model):
    """Blueprint Section 5.6 — Delhivery AWB + tracking lifecycle.

    Phase 2C adds the integration fields ``delhivery_status`` (raw status from
    Delhivery's tracking webhook, kept verbatim for debugging), ``tracking_url``
    (customer-facing tracking URL when the gateway returns one),
    ``risk_flag`` (NDR / RTO indicator surfaced on RTO board) and
    ``raw_response`` (full payload for the most recent gateway exchange so
    operators can audit any disputed event).
    """

    awb = models.CharField(primary_key=True, max_length=40)
    order_id = models.CharField(max_length=32, db_index=True)
    customer = models.CharField(max_length=120)
    state = models.CharField(max_length=60)
    city = models.CharField(max_length=80)
    status = models.CharField(max_length=80, default="Manifested")
    eta = models.CharField(max_length=40, default="")
    courier = models.CharField(max_length=40, default="Delhivery")
    # Phase 2C integration fields.
    delhivery_status = models.CharField(max_length=64, blank=True, default="")
    tracking_url = models.URLField(blank=True, default="")
    risk_flag = models.CharField(max_length=24, blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Phase 6B — Default Org Data Backfill (nullable).
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
        db_index=True,
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"AWB {self.awb} · {self.status}"


class WorkflowStep(models.Model):
    """Tracking timeline rows — `Shipment.timeline` reverse FK target."""

    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="timeline")
    order = models.PositiveIntegerField(default=0)
    step = models.CharField(max_length=80)
    at = models.CharField(max_length=40, blank=True, default="")
    done = models.BooleanField(default=False)

    class Meta:
        ordering = ("order",)


class RescueAttempt(models.Model):
    """One row per RTO rescue attempt against an order. Blueprint Section 5.7."""

    class Channel(models.TextChoices):
        AI_CALL = "AI Call", "AI Call"
        HUMAN_CALL = "Human Call", "Human Call"
        WHATSAPP = "WhatsApp", "WhatsApp"
        SMS = "SMS", "SMS"

    class Outcome(models.TextChoices):
        PENDING = "Pending", "Pending"
        RESCUE_CALL_DONE = "Rescue Call Done", "Rescue Call Done"
        CONVINCED = "Convinced", "Convinced"
        RETURNING = "Returning", "Returning"
        NO_RESPONSE = "No Response", "No Response"

    id = models.CharField(primary_key=True, max_length=32)
    order_id = models.CharField(max_length=32, db_index=True)
    channel = models.CharField(max_length=24, choices=Channel.choices, default=Channel.AI_CALL)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, default=Outcome.PENDING)
    notes = models.TextField(blank=True, default="")
    attempted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-attempted_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.order_id} · {self.outcome}"


class Phase7GLiveRealCustomerDispatchGate(models.Model):
    """Phase 7G-Live one-shot real-customer Delhivery dispatch gate.

    CLI-only governance row. Approval authorizes exactly one real
    Delhivery AWB creation for exactly one confirmed Order within a
    structured Director UTC window. Rollback attempts the Delhivery
    cancellation API and records the result honestly — Delhivery may
    refuse cancellation if the AWB is already in transit.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        APPROVED = "approved", "approved"
        EXECUTED = "executed", "executed"
        FAILED = "failed", "failed"
        CANCELLED = "cancelled", "cancelled"
        ROLLBACK_RECORDED = "rollback_recorded", "rollback_recorded"

    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    target_order_id = models.CharField(max_length=32, db_index=True)
    operator_name = models.CharField(max_length=120, blank=True, default="")
    director_signoff_text_hash = models.CharField(
        max_length=64, blank=True, default=""
    )
    recorded_signoff_window_start_utc = models.DateTimeField(
        null=True, blank=True
    )
    recorded_signoff_window_end_utc = models.DateTimeField(
        null=True, blank=True
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    awb_number = models.CharField(max_length=64, blank=True, default="")
    delhivery_shipment_id = models.CharField(
        max_length=64, blank=True, default=""
    )
    cancellation_attempted_at = models.DateTimeField(null=True, blank=True)
    cancellation_result = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    next_action = models.CharField(max_length=160, blank=True, default="")

    payment_mutation_made = models.BooleanField(default=False)
    order_payment_status_changed = models.BooleanField(default=False)
    whatsapp_sent = models.BooleanField(default=False)
    razorpay_called = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "shipments"
        ordering = ("-created_at",)
        indexes = (
            models.Index(
                fields=("status", "-created_at"),
                name="p7gl_gate_status_created_idx",
            ),
            models.Index(
                fields=("target_order_id", "-created_at"),
                name="p7gl_gate_order_created_idx",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"phase7g-live gate {self.pk} - "
            f"{self.target_order_id} - {self.status}"
        )
