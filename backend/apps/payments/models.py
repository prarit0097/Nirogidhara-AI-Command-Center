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
