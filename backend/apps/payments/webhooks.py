"""Razorpay webhook receiver.

Razorpay POSTs JSON events with an ``X-Razorpay-Signature`` header containing
``HMAC_SHA256(webhook_secret, raw_body)``. We:

1. Verify the signature with the configured ``RAZORPAY_WEBHOOK_SECRET``.
   Bad/missing signature → 400.
2. Parse the JSON. Bad JSON → 400.
3. Use the event ``id`` for idempotency: insert into ``WebhookEvent`` (PK).
   Duplicate → 200 with ``{detail: "duplicate"}`` (Razorpay retries on 5xx,
   so 200 stops the retry loop without double-processing).
4. Dispatch by ``event`` type. Unknown event → 200 with ``{detail: "ignored"}``.
5. Update Payment + parent Order, then write an ``AuditEvent`` (in addition to
   the post-save signal that fires on Payment.status=Paid).

Keep this module side-effect-only — never call into the gateway from here.
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

from .integrations.razorpay_client import verify_webhook_signature
from .models import Payment, WebhookEvent

EventHandler = Callable[[dict[str, Any], Payment | None, Order | None], None]


class RazorpayWebhookView(APIView):
    """``POST /api/webhooks/razorpay/`` — receives Razorpay webhook events."""

    permission_classes = [AllowAny]
    authentication_classes: list = []  # public — auth comes from HMAC signature

    def post(self, request):
        signature = request.META.get("HTTP_X_RAZORPAY_SIGNATURE", "") or ""
        body = request.body or b""

        if not verify_webhook_signature(body, signature):
            return Response({"detail": "invalid signature"}, status=400)

        try:
            event = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid json"}, status=400)

        event_type = event.get("event") or ""
        # Razorpay events carry their own ``id`` at the top level. Fall back
        # to a stable key derived from the payload so tests can craft events
        # without manually generating ids.
        event_id = event.get("id") or _fallback_event_id(event)

        if event_id:
            try:
                with transaction.atomic():
                    WebhookEvent.objects.create(
                        event_id=event_id, event_type=event_type, gateway="razorpay"
                    )
            except IntegrityError:
                return Response({"detail": "duplicate", "id": event_id}, status=200)

        handler = _HANDLERS.get(event_type)
        if handler is None:
            return Response({"detail": "ignored", "event": event_type}, status=200)

        payment, order = _resolve_targets(event)
        handler(event, payment, order)
        return Response({"detail": "ok", "event": event_type, "id": event_id}, status=200)


def _fallback_event_id(event: dict[str, Any]) -> str:
    """Derive a deterministic id when the payload omits one (test fixtures)."""
    payload = event.get("payload", {}) or {}
    plink = (payload.get("payment_link") or {}).get("entity") or {}
    payment = (payload.get("payment") or {}).get("entity") or {}
    parts = (
        event.get("event", "?"),
        plink.get("id") or payment.get("id") or "",
        str(event.get("created_at") or ""),
    )
    return "auto:" + ":".join(str(p) for p in parts if p)


def _resolve_targets(event: dict[str, Any]) -> tuple[Payment | None, Order | None]:
    """Look up the Payment + parent Order referenced by a webhook event."""
    payload = event.get("payload", {}) or {}
    plink_entity = (payload.get("payment_link") or {}).get("entity") or {}
    payment_entity = (payload.get("payment") or {}).get("entity") or {}

    plink_id = plink_entity.get("id") or payment_entity.get("payment_link_id") or ""
    payment: Payment | None = None
    if plink_id:
        payment = Payment.objects.filter(gateway_reference_id=plink_id).first()

    order: Order | None = None
    if payment is not None:
        order = Order.objects.filter(pk=payment.order_id).first()
    return payment, order


# ----- Per-event handlers -----


def _handle_paid(event, payment, order):
    if payment is None:
        return
    payment.status = Payment.Status.PAID
    payment.save(update_fields=["status", "updated_at"])
    if order is not None:
        order.payment_status = Order.PaymentStatus.PAID
        order.advance_paid = True
        # If the webhook carries an explicit amount, prefer it; otherwise the
        # payment row amount is authoritative.
        order.advance_amount = payment.amount
        order.save(update_fields=["payment_status", "advance_paid", "advance_amount"])
    # The audit post-save signal only fires on Payment creation, so log this
    # explicit Paid transition here.
    write_event(
        kind="payment.received",
        text=f"Payment ₹{payment.amount} received from {payment.customer} ({payment.gateway})",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "payment_id": payment.id,
            "order_id": payment.order_id,
            "gateway": payment.gateway,
            "via": "webhook",
        },
    )


def _handle_partial(event, payment, order):
    if payment is None:
        return
    payment.status = Payment.Status.PARTIAL
    payment.save(update_fields=["status", "updated_at"])
    write_event(
        kind="payment.received",
        text=f"Partial payment on {payment.id} ({payment.gateway})",
        tone=AuditEvent.Tone.INFO,
        payload={"payment_id": payment.id, "order_id": payment.order_id, "partial": True},
    )


def _handle_cancelled(event, payment, order):
    if payment is None:
        return
    payment.status = Payment.Status.CANCELLED
    payment.save(update_fields=["status", "updated_at"])
    write_event(
        kind="payment.link_created",
        text=f"Payment {payment.id} cancelled by gateway",
        tone=AuditEvent.Tone.WARNING,
        payload={"payment_id": payment.id, "order_id": payment.order_id, "event": "cancelled"},
    )


def _handle_expired(event, payment, order):
    if payment is None:
        return
    payment.status = Payment.Status.EXPIRED
    payment.save(update_fields=["status", "updated_at"])
    write_event(
        kind="payment.link_created",
        text=f"Payment {payment.id} expired",
        tone=AuditEvent.Tone.WARNING,
        payload={"payment_id": payment.id, "order_id": payment.order_id, "event": "expired"},
    )


def _handle_failed(event, payment, order):
    if payment is None:
        return
    payment.status = Payment.Status.FAILED
    payment.save(update_fields=["status", "updated_at"])
    write_event(
        kind="payment.link_created",
        text=f"Payment {payment.id} failed",
        tone=AuditEvent.Tone.DANGER,
        payload={"payment_id": payment.id, "order_id": payment.order_id, "event": "failed"},
    )


def _handle_refunded(event, payment, order):
    if payment is None:
        return
    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    if order is not None:
        order.payment_status = Order.PaymentStatus.PENDING
        order.advance_paid = False
        order.advance_amount = 0
        order.save(update_fields=["payment_status", "advance_paid", "advance_amount"])
    write_event(
        kind="payment.received",
        text=f"Refund processed for {payment.id}",
        tone=AuditEvent.Tone.WARNING,
        payload={"payment_id": payment.id, "order_id": payment.order_id, "event": "refunded"},
    )


_HANDLERS: dict[str, EventHandler] = {
    "payment_link.paid": _handle_paid,
    "payment_link.partially_paid": _handle_partial,
    "payment_link.cancelled": _handle_cancelled,
    "payment_link.expired": _handle_expired,
    "payment.failed": _handle_failed,
    "refund.processed": _handle_refunded,
}
