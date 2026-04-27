from __future__ import annotations

from django.db import models


class Shipment(models.Model):
    """Blueprint Section 5.6 — Delhivery AWB + tracking lifecycle."""

    awb = models.CharField(primary_key=True, max_length=40)
    order_id = models.CharField(max_length=32, db_index=True)
    customer = models.CharField(max_length=120)
    state = models.CharField(max_length=60)
    city = models.CharField(max_length=80)
    status = models.CharField(max_length=80, default="Manifested")
    eta = models.CharField(max_length=40, default="")
    courier = models.CharField(max_length=40, default="Delhivery")
    created_at = models.DateTimeField(auto_now_add=True)

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
