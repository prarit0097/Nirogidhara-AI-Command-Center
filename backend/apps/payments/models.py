from __future__ import annotations

from django.db import models


class Payment(models.Model):
    """Blueprint Section 5.5 — Razorpay/PayU mock records.

    Real gateway calls are Phase 2. This model captures the receipt-side fields
    the frontend reconciliation board needs.
    """

    class Gateway(models.TextChoices):
        RAZORPAY = "Razorpay", "Razorpay"
        PAYU = "PayU", "PayU"

    class Status(models.TextChoices):
        PAID = "Paid", "Paid"
        PENDING = "Pending", "Pending"
        FAILED = "Failed", "Failed"
        REFUNDED = "Refunded", "Refunded"

    class Type(models.TextChoices):
        ADVANCE = "Advance", "Advance"
        FULL = "Full", "Full"

    id = models.CharField(primary_key=True, max_length=32)
    order_id = models.CharField(max_length=32, db_index=True)
    customer = models.CharField(max_length=120)
    amount = models.IntegerField(default=0)
    gateway = models.CharField(max_length=16, choices=Gateway.choices, default=Gateway.RAZORPAY)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.ADVANCE)
    time = models.CharField(max_length=40, default="just now")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.amount} · {self.gateway}"
