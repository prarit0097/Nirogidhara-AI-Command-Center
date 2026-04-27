"""Cross-app signal receivers that write to the Master Event Ledger.

Connecting receivers here (rather than in each app) keeps the audit module the
single owner of ``AuditEvent`` writes — apps emit ``post_save``/``post_delete``
naturally, audit translates them into ledger rows.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditEvent

ICON_BY_KIND: dict[str, str] = {
    # Existing (Phase 1).
    "lead.created": "user-plus",
    "order.created": "shopping-bag",
    "order.status_changed": "refresh-cw",
    "payment.received": "indian-rupee",
    "shipment.status_changed": "truck",
    "rto.flagged": "alert-triangle",
    "reward.assigned": "award",
    "compliance.flagged": "shield-alert",
    # Phase 2A — explicit writes from the service layer.
    "lead.updated": "user-cog",
    "lead.assigned": "user-check",
    "customer.upserted": "users",
    "confirmation.outcome": "check-circle-2",
    "payment.link_created": "link",
    "shipment.created": "package",
    "rescue.attempted": "phone-call",
    "rescue.updated": "phone-forwarded",
    # Phase 2C — Delhivery webhook outcomes.
    "shipment.delivered": "package-check",
    "shipment.ndr": "alert-octagon",
    "shipment.rto_initiated": "package-x",
    "shipment.rto_delivered": "rotate-ccw",
    # Phase 2D — Vapi voice events.
    "call.triggered": "phone-outgoing",
    "call.started": "phone-incoming",
    "call.completed": "phone-off",
    "call.failed": "phone-missed",
    "call.transcript": "file-text",
    "call.analysis": "sparkles",
    "call.handoff_flagged": "alert-triangle",
    # Phase 2E — Meta Lead Ads ingestion.
    "lead.meta_ingested": "facebook",
}


def write_event(*, kind: str, text: str, tone: str = AuditEvent.Tone.INFO, payload: dict | None = None) -> AuditEvent:
    return AuditEvent.objects.create(
        kind=kind,
        text=text,
        tone=tone,
        icon=ICON_BY_KIND.get(kind, "activity"),
        payload=payload or {},
    )


@receiver(post_save, sender="crm.Lead", dispatch_uid="audit.lead_created")
def _on_lead_saved(sender, instance, created, **_):
    if not created:
        return
    write_event(
        kind="lead.created",
        text=f"New lead {instance.name} ({instance.state}) via {instance.source}",
        tone=AuditEvent.Tone.INFO,
        payload={"lead_id": instance.id, "source": instance.source},
    )


@receiver(post_save, sender="orders.Order", dispatch_uid="audit.order_status")
def _on_order_saved(sender, instance, created, **_):
    if created:
        write_event(
            kind="order.created",
            text=f"Order {instance.id} punched · {instance.product} · ₹{instance.amount}",
            tone=AuditEvent.Tone.SUCCESS,
            payload={"order_id": instance.id, "stage": instance.stage},
        )
        return
    write_event(
        kind="order.status_changed",
        text=f"Order {instance.id} → {instance.stage}",
        tone=AuditEvent.Tone.INFO,
        payload={"order_id": instance.id, "stage": instance.stage},
    )


@receiver(post_save, sender="payments.Payment", dispatch_uid="audit.payment_received")
def _on_payment_saved(sender, instance, created, **_):
    if not created or instance.status != "Paid":
        return
    write_event(
        kind="payment.received",
        text=f"Payment ₹{instance.amount} received from {instance.customer} ({instance.gateway})",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"payment_id": instance.id, "order_id": instance.order_id},
    )


@receiver(post_save, sender="shipments.Shipment", dispatch_uid="audit.shipment_status")
def _on_shipment_saved(sender, instance, created, **_):
    write_event(
        kind="shipment.status_changed",
        text=f"AWB {instance.awb} · {instance.status} · {instance.city}",
        tone=AuditEvent.Tone.INFO,
        payload={"awb": instance.awb, "order_id": instance.order_id},
    )
