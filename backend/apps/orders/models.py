from __future__ import annotations

from django.db import models


class Order(models.Model):
    """Blueprint Section 5.4 + 5.7. Stage drives the kanban + RTO views."""

    class Stage(models.TextChoices):
        NEW_LEAD = "New Lead", "New Lead"
        INTERESTED = "Interested", "Interested"
        PAYMENT_LINK_SENT = "Payment Link Sent", "Payment Link Sent"
        ORDER_PUNCHED = "Order Punched", "Order Punched"
        CONFIRMATION_PENDING = "Confirmation Pending", "Confirmation Pending"
        CONFIRMED = "Confirmed", "Confirmed"
        DISPATCHED = "Dispatched", "Dispatched"
        OUT_FOR_DELIVERY = "Out for Delivery", "Out for Delivery"
        DELIVERED = "Delivered", "Delivered"
        RTO = "RTO", "RTO"
        CANCELLED = "Cancelled", "Cancelled"

    class ConfirmationOutcome(models.TextChoices):
        PENDING = "", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        RESCUE_NEEDED = "rescue_needed", "Rescue Needed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        PAID = "Paid", "Paid"
        PARTIAL = "Partial", "Partial"
        PENDING = "Pending", "Pending"
        FAILED = "Failed", "Failed"

    class RtoRisk(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"

    id = models.CharField(primary_key=True, max_length=32)
    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24)
    product = models.CharField(max_length=120)
    quantity = models.IntegerField(default=1)
    amount = models.IntegerField(default=0)
    discount_pct = models.IntegerField(default=0)
    advance_paid = models.BooleanField(default=False)
    advance_amount = models.IntegerField(default=0)
    payment_status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    state = models.CharField(max_length=60)
    city = models.CharField(max_length=80)
    rto_risk = models.CharField(max_length=8, choices=RtoRisk.choices, default=RtoRisk.LOW)
    rto_score = models.IntegerField(default=0)
    agent = models.CharField(max_length=80, default="")
    stage = models.CharField(max_length=32, choices=Stage.choices, default=Stage.ORDER_PUNCHED)
    awb = models.CharField(max_length=40, blank=True, null=True)
    age_hours = models.IntegerField(default=0)
    created_at_label = models.CharField(max_length=40, default="just now")

    # Confirmation queue annotations (used by /api/confirmation/queue/).
    hours_waiting = models.IntegerField(default=0)
    address_confidence = models.IntegerField(default=0)
    confirmation_checklist = models.JSONField(default=dict, blank=True)

    # RTO board annotations.
    risk_reasons = models.JSONField(default=list, blank=True)
    rescue_status = models.CharField(max_length=40, default="")

    # Confirmation outcome (Phase 2A).
    confirmation_outcome = models.CharField(
        max_length=20,
        choices=ConfirmationOutcome.choices,
        default=ConfirmationOutcome.PENDING,
        blank=True,
    )
    confirmation_notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    # Phase 6B — Default Org Data Backfill (nullable; backfilled to
    # the seeded default org by the management command).
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
        db_index=True,
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=("stage",)), models.Index(fields=("rto_risk",)))

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.product} · {self.stage}"


class DiscountOfferLog(models.Model):
    """Phase 5E — append-only log of every discount offer attempt.

    Tracks the rescue / chat / call / confirmation / delivery / RTO discount
    flow end-to-end. Every attempt — accepted, rejected, blocked, skipped,
    or escalated to CEO review — writes a row so audit + reward / penalty
    + later analytics can reason about the cumulative cap math without
    replaying the audit ledger.

    Hard rule (Master Blueprint §26 + Phase 5E lock): cumulative discount
    across ALL stages on a single order MUST NEVER exceed 50%. The
    ``resulting_total_discount_pct`` field captures what the order would
    look like if this offer were applied; ``cap_remaining_pct`` records
    how many percent are still spendable after the offer.
    """

    class SourceChannel(models.TextChoices):
        WHATSAPP_AI = "whatsapp_ai", "whatsapp_ai"
        AI_CALL = "ai_call", "ai_call"
        CONFIRMATION = "confirmation", "confirmation"
        DELIVERY = "delivery", "delivery"
        RTO = "rto", "rto"
        OPERATOR = "operator", "operator"
        SYSTEM = "system", "system"

    class Stage(models.TextChoices):
        ORDER_BOOKING = "order_booking", "order_booking"
        CONFIRMATION = "confirmation", "confirmation"
        DELIVERY = "delivery", "delivery"
        RTO = "rto", "rto"
        REORDER = "reorder", "reorder"
        CUSTOMER_SUCCESS = "customer_success", "customer_success"

    class Status(models.TextChoices):
        OFFERED = "offered", "offered"
        ACCEPTED = "accepted", "accepted"
        REJECTED = "rejected", "rejected"
        BLOCKED = "blocked", "blocked"
        SKIPPED = "skipped", "skipped"
        NEEDS_CEO_REVIEW = "needs_ceo_review", "needs_ceo_review"

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discount_offers",
    )
    customer = models.ForeignKey(
        "crm.Customer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="discount_offers",
    )
    conversation = models.ForeignKey(
        "whatsapp.WhatsAppConversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discount_offers",
    )
    source_channel = models.CharField(
        max_length=24, choices=SourceChannel.choices
    )
    stage = models.CharField(max_length=24, choices=Stage.choices)
    trigger_reason = models.CharField(max_length=80)
    previous_discount_pct = models.IntegerField(default=0)
    offered_additional_pct = models.IntegerField(default=0)
    resulting_total_discount_pct = models.IntegerField(default=0)
    cap_remaining_pct = models.IntegerField(default=0)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OFFERED
    )
    blocked_reason = models.CharField(max_length=80, blank=True, default="")
    offered_by_agent = models.CharField(max_length=40, blank=True, default="")
    approval_request = models.ForeignKey(
        "ai_governance.ApprovalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discount_offers",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Phase 6B — Default Org Data Backfill (nullable). Branch is not
    # tracked separately on this row — it flows from the parent order.
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="discount_offers",
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("order", "-created_at")),
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("stage", "-created_at")),
            models.Index(fields=("source_channel", "-created_at")),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"discount_offer · {self.order_id} · {self.stage} · "
            f"+{self.offered_additional_pct}% → {self.resulting_total_discount_pct}% · "
            f"{self.status}"
        )
