from __future__ import annotations

from django.db import models


class Lead(models.Model):
    """Blueprint Section 5.1. ID matches the frontend's `LD-NNNNN` format.

    Phase 2E adds optional Meta Lead Ads provenance fields so a lead ingested
    via the Meta webhook (``/api/webhooks/meta/leads/``) carries the original
    leadgen / page / form / ad / campaign ids back to the dashboard for
    attribution.
    """

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
    # Phase 2E — Meta Lead Ads provenance.
    meta_leadgen_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    meta_page_id = models.CharField(max_length=64, blank=True, default="")
    meta_form_id = models.CharField(max_length=64, blank=True, default="")
    meta_ad_id = models.CharField(max_length=64, blank=True, default="")
    meta_campaign_id = models.CharField(max_length=64, blank=True, default="")
    source_detail = models.CharField(max_length=120, blank=True, default="")
    raw_source_payload = models.JSONField(default=dict, blank=True)
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


class MetaLeadEvent(models.Model):
    """Idempotency log for incoming Meta Lead Ads webhooks (Phase 2E).

    PK is Meta's ``leadgen_id`` so duplicate webhook deliveries hit
    ``IntegrityError`` and the handler short-circuits with a 200/duplicate
    response. ``status`` records whether we successfully ingested the row
    or fell back to a soft error so operators can replay or audit later.
    """

    class Status(models.TextChoices):
        OK = "ok", "ok"
        ERROR = "error", "error"

    leadgen_id = models.CharField(primary_key=True, max_length=128)
    page_id = models.CharField(max_length=64, blank=True, default="")
    form_id = models.CharField(max_length=64, blank=True, default="")
    ad_id = models.CharField(max_length=64, blank=True, default="")
    campaign_id = models.CharField(max_length=64, blank=True, default="")
    lead_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OK)
    error_message = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-received_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"meta:{self.leadgen_id}:{self.status}"
