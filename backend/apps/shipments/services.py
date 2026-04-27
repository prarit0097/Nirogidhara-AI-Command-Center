"""Shipment + RTO rescue write services.

Phase 2C: real Delhivery integration via the three-mode adapter at
``apps/shipments/integrations/delhivery_client.py``. The default
``DELHIVERY_MODE=mock`` keeps the AWB pattern (``DLH<8 digits>``) so the
existing seeded data and frontend tracking views keep rendering without any
code change. ``test`` and ``live`` modes route through the real Delhivery API.

Webhook updates (status transitions, NDR, RTO) are applied by
``apps/shipments/webhooks.py`` — those reuse helpers exposed below.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order

from .integrations.delhivery_client import (
    AwbResult,
    DelhiveryClientError,
    create_awb as _gateway_create_awb,
)
from .models import RescueAttempt, Shipment, WorkflowStep

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


_DEFAULT_TIMELINE: list[dict] = [
    {"order": 0, "step": "AWB Generated", "at": "Day 0", "done": True},
    {"order": 1, "step": "Pickup Scheduled", "at": "Day 0", "done": True},
    {"order": 2, "step": "In Transit", "at": "Day 1", "done": False},
    {"order": 3, "step": "Out for Delivery", "at": "Day 3", "done": False},
    {"order": 4, "step": "Delivered / RTO", "at": "Day 4", "done": False},
]


def _shipment_exists(awb: str) -> bool:
    return Shipment.objects.filter(awb=awb).exists()


@transaction.atomic
def create_shipment(*, order: Order, by_user: "User") -> Shipment:
    """Create a Delhivery shipment + 5-step timeline. Updates parent order's awb.

    Routes through the Delhivery adapter — ``mock`` mode mints a deterministic
    ``DLH<8 digits>`` AWB without touching the network; ``test``/``live`` modes
    hit the real Delhivery API. Raises ``DelhiveryClientError`` if the gateway
    misbehaves so the view can return 502/400.
    """
    try:
        result: AwbResult = _gateway_create_awb(
            order_id=order.id,
            customer_name=order.customer_name,
            customer_phone=order.phone,
            address_line=f"{order.city}, {order.state}",
            city=order.city,
            state=order.state,
            cod_amount=0 if order.advance_paid else max(order.amount - order.advance_amount, 0),
            payment_mode="Prepaid" if order.advance_paid else "COD",
            exists=_shipment_exists,
        )
    except DelhiveryClientError:
        # Re-raise so the view can return 502/400; never silently swallow.
        raise

    shipment = Shipment.objects.create(
        awb=result.awb,
        order_id=order.id,
        customer=order.customer_name,
        state=order.state,
        city=order.city,
        status=result.status or "Pickup Scheduled",
        eta="3 days",
        courier="Delhivery",
        delhivery_status=result.status or "Pickup Scheduled",
        tracking_url=result.tracking_url,
        raw_response=dict(result.raw or {}),
    )
    WorkflowStep.objects.bulk_create(
        [WorkflowStep(shipment=shipment, **step) for step in _DEFAULT_TIMELINE]
    )

    # Sync parent order — only set awb (don't auto-transition stage; that's the
    # caller's choice via /orders/{id}/transition/).
    order.awb = result.awb
    order.save(update_fields=["awb"])

    write_event(
        kind="shipment.created",
        text=f"Shipment {result.awb} created for order {order.id} (Delhivery)",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "awb": result.awb,
            "order_id": order.id,
            "tracking_url": result.tracking_url,
            "by": getattr(by_user, "username", ""),
        },
    )
    return shipment


# Back-compat alias — older callers (and a Phase 2A test) reference this name.
create_mock_shipment = create_shipment


@transaction.atomic
def create_rescue_attempt(
    *,
    order: Order,
    channel: str,
    by_user: "User",
    notes: str = "",
) -> RescueAttempt:
    if channel not in RescueAttempt.Channel.values:
        raise ValueError(f"Unknown rescue channel: {channel!r}")
    attempt = RescueAttempt.objects.create(
        id=next_id("RES", RescueAttempt, base=40000),
        order_id=order.id,
        channel=channel,
        outcome=RescueAttempt.Outcome.PENDING,
        notes=notes,
    )
    # Bubble pending status to the order's RTO board annotation.
    order.rescue_status = "Pending"
    order.save(update_fields=["rescue_status"])

    write_event(
        kind="rescue.attempted",
        text=f"Rescue {attempt.id} initiated for {order.id} via {channel}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "attempt_id": attempt.id,
            "order_id": order.id,
            "channel": channel,
            "by": getattr(by_user, "username", ""),
        },
    )
    return attempt


@transaction.atomic
def update_rescue_outcome(
    *,
    attempt: RescueAttempt,
    outcome: str,
    by_user: "User",
    notes: str = "",
) -> RescueAttempt:
    if outcome not in RescueAttempt.Outcome.values:
        raise ValueError(f"Unknown rescue outcome: {outcome!r}")
    attempt.outcome = outcome
    if notes:
        attempt.notes = (attempt.notes + "\n" + notes).strip() if attempt.notes else notes
    attempt.save(update_fields=["outcome", "notes"])

    # Bubble outcome to parent order.
    try:
        order = Order.objects.get(pk=attempt.order_id)
    except Order.DoesNotExist:
        order = None
    if order is not None:
        order.rescue_status = outcome
        order.save(update_fields=["rescue_status"])

    write_event(
        kind="rescue.updated",
        text=f"Rescue {attempt.id} outcome: {outcome}",
        tone=(
            AuditEvent.Tone.SUCCESS
            if outcome == RescueAttempt.Outcome.CONVINCED
            else AuditEvent.Tone.WARNING
            if outcome == RescueAttempt.Outcome.RETURNING
            else AuditEvent.Tone.INFO
        ),
        payload={
            "attempt_id": attempt.id,
            "order_id": attempt.order_id,
            "outcome": outcome,
            "by": getattr(by_user, "username", ""),
        },
    )
    return attempt
