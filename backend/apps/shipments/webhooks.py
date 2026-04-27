"""Delhivery tracking webhook receiver.

Delhivery POSTs JSON status events. The exact signature header isn't
documented per-account (some accounts use a shared token, some use
HMAC-SHA256). We verify the body using
``HMAC_SHA256(DELHIVERY_WEBHOOK_SECRET, raw_body)`` against an
``X-Delhivery-Signature`` header. A missing/invalid signature returns 400.

Idempotency reuses the ``payments.WebhookEvent`` table — its ``event_id`` PK
is gateway-agnostic. Duplicate inserts hit ``IntegrityError`` and the handler
short-circuits with ``200 / duplicate``.

Status mapping (lower-case keys from the wire payload):

==================  ====================  ============================
Delhivery event     Shipment.status       Order.stage / extras
==================  ====================  ============================
pickup_scheduled    Pickup Scheduled      —
picked_up           Picked Up             —
in_transit          In Transit            —
out_for_delivery    Out for Delivery      stage = OUT_FOR_DELIVERY
delivered           Delivered             stage = DELIVERED
ndr                 NDR                   risk_flag = NDR; rto_risk → HIGH
rto_initiated       RTO Initiated         stage = RTO; rescue_status set
rto_delivered       RTO Delivered         stage = RTO
==================  ====================  ============================

Every recognised status writes an explicit ``AuditEvent`` so the Master Event
Ledger captures the courier's view of the order in addition to the
``shipment.status_changed`` row that ``post_save`` already emits.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from django.db import IntegrityError, transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order
from apps.payments.models import WebhookEvent

from .integrations.delhivery_client import verify_webhook_signature
from .models import Shipment, WorkflowStep

EventHandler = Callable[[dict[str, Any], Shipment, Order | None], None]


# ----- Status mapping -----

_STATUS_MAP: dict[str, str] = {
    "pickup_scheduled": "Pickup Scheduled",
    "picked_up": "Picked Up",
    "in_transit": "In Transit",
    "out_for_delivery": "Out for Delivery",
    "delivered": "Delivered",
    "ndr": "NDR",
    "rto_initiated": "RTO Initiated",
    "rto_delivered": "RTO Delivered",
}


class DelhiveryWebhookView(APIView):
    """``POST /api/webhooks/delhivery/`` — Delhivery tracking events."""

    permission_classes = [AllowAny]
    authentication_classes: list = []  # public — auth comes from HMAC signature

    def post(self, request):
        signature = request.META.get("HTTP_X_DELHIVERY_SIGNATURE", "") or ""
        body = request.body or b""

        if not verify_webhook_signature(body, signature):
            return Response({"detail": "invalid signature"}, status=400)

        try:
            event = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid json"}, status=400)

        event_type = (event.get("event") or event.get("status") or "").lower()
        event_id = event.get("id") or _fallback_event_id(event)

        if event_id:
            try:
                with transaction.atomic():
                    WebhookEvent.objects.create(
                        event_id=event_id, event_type=event_type, gateway="delhivery"
                    )
            except IntegrityError:
                return Response({"detail": "duplicate", "id": event_id}, status=200)

        if event_type not in _STATUS_MAP:
            return Response({"detail": "ignored", "event": event_type}, status=200)

        awb = event.get("awb") or event.get("waybill") or ""
        shipment = Shipment.objects.filter(awb=awb).first() if awb else None
        if shipment is None:
            return Response({"detail": "shipment not found", "awb": awb}, status=200)

        order = Order.objects.filter(pk=shipment.order_id).first()
        _apply_status_update(event_type, event, shipment, order)
        return Response(
            {"detail": "ok", "event": event_type, "id": event_id, "awb": shipment.awb},
            status=200,
        )


# ----- helpers -----


def _fallback_event_id(event: dict[str, Any]) -> str:
    """Derive a deterministic id when the payload omits one (test fixtures)."""
    parts = (
        event.get("event") or event.get("status") or "?",
        event.get("awb") or event.get("waybill") or "",
        str(event.get("event_time") or event.get("timestamp") or ""),
    )
    return "auto:" + ":".join(str(p) for p in parts if p)


def _apply_status_update(
    event_type: str,
    event: dict[str, Any],
    shipment: Shipment,
    order: Order | None,
) -> None:
    """Single funnel for every recognised tracking event."""
    friendly = _STATUS_MAP[event_type]
    shipment.status = friendly
    shipment.delhivery_status = friendly
    if event.get("eta"):
        shipment.eta = str(event["eta"])
    # Persist the latest payload so disputes can be audited from the DB.
    shipment.raw_response = {**(shipment.raw_response or {}), "last_event": event}
    shipment.save(
        update_fields=["status", "delhivery_status", "eta", "raw_response", "updated_at"]
    )

    # Mark any matching timeline step as done so the UI reflects progress.
    _mark_timeline_step(shipment, friendly)

    handler = _HANDLERS.get(event_type)
    if handler is not None:
        handler(event, shipment, order)


def _mark_timeline_step(shipment: Shipment, friendly_status: str) -> None:
    """Best-effort: tick the step matching the latest status."""
    keyword = friendly_status.split()[0].lower()
    for step in shipment.timeline.all():
        if keyword in step.step.lower() and not step.done:
            step.done = True
            step.save(update_fields=["done"])
            break


def _handle_delivered(event: dict[str, Any], shipment: Shipment, order: Order | None) -> None:
    if order is not None:
        order.stage = Order.Stage.DELIVERED
        order.save(update_fields=["stage"])
    write_event(
        kind="shipment.delivered",
        text=f"AWB {shipment.awb} delivered · {shipment.city}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"awb": shipment.awb, "order_id": shipment.order_id, "via": "webhook"},
    )


def _handle_out_for_delivery(event: dict[str, Any], shipment: Shipment, order: Order | None) -> None:
    if order is not None and order.stage not in {
        Order.Stage.DELIVERED,
        Order.Stage.RTO,
        Order.Stage.CANCELLED,
    }:
        order.stage = Order.Stage.OUT_FOR_DELIVERY
        order.save(update_fields=["stage"])
    write_event(
        kind="shipment.status_changed",
        text=f"AWB {shipment.awb} out for delivery",
        tone=AuditEvent.Tone.INFO,
        payload={"awb": shipment.awb, "order_id": shipment.order_id, "via": "webhook"},
    )


def _handle_ndr(event: dict[str, Any], shipment: Shipment, order: Order | None) -> None:
    shipment.risk_flag = "NDR"
    shipment.save(update_fields=["risk_flag", "updated_at"])
    if order is not None:
        order.rto_risk = Order.RtoRisk.HIGH
        order.rescue_status = order.rescue_status or "NDR — Rescue Needed"
        order.save(update_fields=["rto_risk", "rescue_status"])
    write_event(
        kind="shipment.ndr",
        text=f"AWB {shipment.awb} NDR — delivery attempt failed",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "awb": shipment.awb,
            "order_id": shipment.order_id,
            "reason": event.get("reason", ""),
            "via": "webhook",
        },
    )


def _handle_rto_initiated(event: dict[str, Any], shipment: Shipment, order: Order | None) -> None:
    shipment.risk_flag = "RTO"
    shipment.save(update_fields=["risk_flag", "updated_at"])
    if order is not None:
        order.stage = Order.Stage.RTO
        order.rto_risk = Order.RtoRisk.HIGH
        order.rescue_status = order.rescue_status or "Returning"
        order.save(update_fields=["stage", "rto_risk", "rescue_status"])
    write_event(
        kind="shipment.rto_initiated",
        text=f"AWB {shipment.awb} RTO initiated",
        tone=AuditEvent.Tone.DANGER,
        payload={"awb": shipment.awb, "order_id": shipment.order_id, "via": "webhook"},
    )


def _handle_rto_delivered(event: dict[str, Any], shipment: Shipment, order: Order | None) -> None:
    shipment.risk_flag = "RTO"
    shipment.save(update_fields=["risk_flag", "updated_at"])
    if order is not None and order.stage != Order.Stage.RTO:
        order.stage = Order.Stage.RTO
        order.save(update_fields=["stage"])
    write_event(
        kind="shipment.rto_delivered",
        text=f"AWB {shipment.awb} returned to origin",
        tone=AuditEvent.Tone.WARNING,
        payload={"awb": shipment.awb, "order_id": shipment.order_id, "via": "webhook"},
    )


_HANDLERS: dict[str, EventHandler] = {
    "out_for_delivery": _handle_out_for_delivery,
    "delivered": _handle_delivered,
    "ndr": _handle_ndr,
    "rto_initiated": _handle_rto_initiated,
    "rto_delivered": _handle_rto_delivered,
}


__all__ = ("DelhiveryWebhookView",)
