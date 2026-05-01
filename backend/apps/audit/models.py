from __future__ import annotations

from django.db import models


class AuditEvent(models.Model):
    """Master Event Ledger entry. See blueprint Sections 12.5 and 18.

    Every important state change in the system writes a row here. The live
    activity feed (`/api/dashboard/activity/`) reads from this table, so signal
    receivers across apps push entries on lead/order/payment/shipment changes.
    """

    class Tone(models.TextChoices):
        SUCCESS = "success", "Success"
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    icon = models.CharField(max_length=32, default="activity")
    text = models.CharField(max_length=512)
    tone = models.CharField(max_length=16, choices=Tone.choices, default=Tone.INFO)
    kind = models.CharField(max_length=64, db_index=True, default="event")
    payload = models.JSONField(default=dict, blank=True)

    # Phase 6B — Default Org Data Backfill (nullable).
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        db_index=True,
    )

    class Meta:
        ordering = ("-occurred_at",)
        indexes = (models.Index(fields=("-occurred_at", "kind")),)

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.kind}] {self.text}"
