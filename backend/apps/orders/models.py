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

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=("stage",)), models.Index(fields=("rto_risk",)))

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.product} · {self.stage}"
