"""Phase 5D — WhatsApp lifecycle signal receivers.

Listens to Order / Payment / Shipment ``post_save`` signals and routes
the corresponding business events into the lifecycle automation
service. The receivers are intentionally tiny — all gates (consent /
template / Claim Vault / approval matrix / CAIO / idempotency) live in
:mod:`apps.whatsapp.lifecycle`.

Locked rules:

- ``WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False`` short-circuits inside
  the lifecycle service (the receiver still fires but the dispatch is
  recorded as ``skipped``).
- The dispatch is wrapped in ``transaction.on_commit`` so the signal
  never holds a write transaction open while we hit the WhatsApp send
  pipeline.
- The lifecycle service is idempotent on the
  ``lifecycle:{action}:{type}:{id}:{event}`` key, so a re-fire of the
  same Order ``stage`` change can never produce two sends.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.crm.models import Customer


logger = logging.getLogger(__name__)


def _safe_dispatch(
    object_type: str,
    object_id: str,
    event_kind: str,
    *,
    customer_id: str = "",
    variables: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Schedule a lifecycle dispatch on commit, never raise."""
    payload_metadata = dict(metadata or {})
    payload_variables = dict(variables or {})

    def _send():
        try:
            from .tasks import send_whatsapp_lifecycle_message_task

            send_whatsapp_lifecycle_message_task.delay(
                object_type,
                object_id,
                event_kind,
                customer_id=customer_id,
                variables=payload_variables,
                metadata=payload_metadata,
            )
        except Exception as exc:  # noqa: BLE001 - never break business write
            logger.warning(
                "WhatsApp lifecycle dispatch failed for %s:%s/%s: %s",
                object_type,
                object_id,
                event_kind,
                exc,
            )

    try:
        from django.conf import settings

        if bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)):
            _send()
            return
        transaction.on_commit(_send)
    except Exception:  # noqa: BLE001 - defensive
        pass


def _customer_for_phone(phone: str) -> Customer | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    return (
        Customer.objects.filter(phone__iexact=phone).first()
        or Customer.objects.filter(phone__iexact=f"+{digits}").first()
        or Customer.objects.filter(phone__icontains=digits[-10:]).first()
    )


@receiver(post_save, sender="orders.Order", dispatch_uid="whatsapp.lifecycle.order")
def _on_order_saved(sender, instance, created, **_):
    """Order moved to Confirmation Pending → confirmation reminder."""
    # Only fire on the explicit move into confirmation_pending.
    try:
        from apps.orders.models import Order
    except Exception:  # pragma: no cover
        return
    if instance.stage != Order.Stage.CONFIRMATION_PENDING:
        return
    customer = _customer_for_phone(instance.phone or "")
    _safe_dispatch(
        "order",
        instance.id,
        "moved_to_confirmation",
        customer_id=getattr(customer, "id", "") or "",
        variables={
            "customer_name": instance.customer_name,
            "context": instance.product or "",
            "product": instance.product or "",
            "amount": int(instance.amount or 0),
            "order_id": instance.id,
        },
        metadata={"source": "post_save", "stage": instance.stage},
    )


@receiver(post_save, sender="payments.Payment", dispatch_uid="whatsapp.lifecycle.payment")
def _on_payment_saved(sender, instance, created, **_):
    """Payment link created OR payment pending → reminder."""
    if not created or instance.status != "Pending":
        return
    customer = _customer_for_phone(instance.customer_phone or "")
    _safe_dispatch(
        "payment",
        instance.id,
        "link_created",
        customer_id=getattr(customer, "id", "") or "",
        variables={
            "customer_name": instance.customer or "",
            "context": instance.payment_url or "",
            "amount": int(instance.amount or 0),
            "order_id": instance.order_id or "",
            "payment_url": instance.payment_url or "",
        },
        metadata={"source": "post_save", "gateway": instance.gateway},
    )


@receiver(post_save, sender="shipments.Shipment", dispatch_uid="whatsapp.lifecycle.shipment")
def _on_shipment_saved(sender, instance, created, **_):
    """Shipment status transitions → matching template trigger."""
    status_norm = (instance.status or "").lower()
    delhivery_status = (instance.delhivery_status or "").lower()
    risk_flag = (instance.risk_flag or "").lower()

    event_kind = ""
    if "out for delivery" in status_norm or "out_for_delivery" in delhivery_status:
        event_kind = "out_for_delivery"
    elif status_norm in {"delivered", "completed"} or delhivery_status == "delivered":
        event_kind = "delivered"
    elif risk_flag == "ndr" or "ndr" in delhivery_status:
        event_kind = "ndr"
    elif risk_flag == "rto" or "rto" in delhivery_status:
        event_kind = "rto_initiated"
    if not event_kind:
        return

    customer = None
    try:
        from apps.orders.models import Order

        order = Order.objects.filter(pk=instance.order_id).first()
        if order is not None:
            customer = _customer_for_phone(order.phone or "")
    except Exception:  # noqa: BLE001
        customer = None

    _safe_dispatch(
        "shipment",
        instance.awb,
        event_kind,
        customer_id=getattr(customer, "id", "") or "",
        variables={
            "customer_name": instance.customer or "",
            "context": instance.tracking_url or instance.awb,
            "awb": instance.awb,
            "tracking_url": instance.tracking_url or "",
            "product": getattr(customer, "product_interest", "") or "",
        },
        metadata={
            "source": "post_save",
            "status": instance.status,
            "delhivery_status": instance.delhivery_status,
            "risk_flag": instance.risk_flag,
        },
    )


__all__ = ()
