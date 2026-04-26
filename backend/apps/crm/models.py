from __future__ import annotations

from django.db import models


class Lead(models.Model):
    """Blueprint Section 5.1. ID matches the frontend's `LD-NNNNN` format."""

    class Status(models.TextChoices):
        NEW = "New", "New"
        AI_CALLING_STARTED = "AI Calling Started", "AI Calling Started"
        INTERESTED = "Interested", "Interested"
        CALLBACK_REQUIRED = "Callback Required", "Callback Required"
        PAYMENT_LINK_SENT = "Payment Link Sent", "Payment Link Sent"
        ORDER_PUNCHED = "Order Punched", "Order Punched"
        NOT_INTERESTED = "Not Interested", "Not Interested"
        INVALID = "Invalid", "Invalid"

    class Quality(models.TextChoices):
        HOT = "Hot", "Hot"
        WARM = "Warm", "Warm"
        COLD = "Cold", "Cold"

    id = models.CharField(primary_key=True, max_length=32)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24)
    state = models.CharField(max_length=60)
    city = models.CharField(max_length=80)
    language = models.CharField(max_length=40)
    source = models.CharField(max_length=60)
    campaign = models.CharField(max_length=120)
    product_interest = models.CharField(max_length=80)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW)
    quality = models.CharField(max_length=8, choices=Quality.choices, default=Quality.WARM)
    quality_score = models.IntegerField(default=0)
    assignee = models.CharField(max_length=80, blank=True, default="")
    duplicate = models.BooleanField(default=False)
    created_at_label = models.CharField(max_length=40, default="just now")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=("status",)), models.Index(fields=("state",)))

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.name}"


class Customer(models.Model):
    """Blueprint Section 5.2 (Customer 360)."""

    id = models.CharField(primary_key=True, max_length=32)
    lead = models.OneToOneField(Lead, on_delete=models.SET_NULL, null=True, related_name="customer")
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24)
    state = models.CharField(max_length=60)
    city = models.CharField(max_length=80)
    language = models.CharField(max_length=40)
    product_interest = models.CharField(max_length=80)
    disease_category = models.CharField(max_length=80, default="")
    lifestyle_notes = models.TextField(blank=True, default="")
    objections = models.JSONField(default=list, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    risk_flags = models.JSONField(default=list, blank=True)
    reorder_probability = models.IntegerField(default=0)
    satisfaction = models.IntegerField(default=0)
    consent_call = models.BooleanField(default=True)
    consent_whatsapp = models.BooleanField(default=True)
    consent_marketing = models.BooleanField(default=False)

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.name}"
