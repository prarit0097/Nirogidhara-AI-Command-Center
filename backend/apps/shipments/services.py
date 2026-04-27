"""Shipment + RTO rescue write services. Phase 2A: mock courier only.

Real Delhivery AWB creation is Phase 2B. We mint a fake AWB matching the
existing seed pattern (``DLH<8 digits>``) so frontend tracking views render
without any code change.
"""
from __future__ import annotations

import secrets
from typing import Any

from django.db import transaction

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order

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


def _mint_awb() -> str:
    """Generate a unique mock AWB. Retries on the (vanishingly rare) collision."""
    for _ in range(10):
        candidate = f"DLH{secrets.randbelow(99_999_999):08d}"
        if not Shipment.objects.filter(awb=candidate).exists():
            return candidate
    raise RuntimeError("Could not mint a unique AWB after 10 attempts")


@transaction.atomic
def create_mock_shipment(*, order: Order, by_user: "User") -> Shipment:
    """Create a shipment + 5-step timeline. Updates parent order's awb + stage."""
    awb = _mint_awb()
    shipment = Shipment.objects.create(
        awb=awb,
        order_id=order.id,
        customer=order.customer_name,
        state=order.state,
        city=order.city,
        status="Pickup Scheduled",
        eta="3 days",
        courier="Delhivery",
    )
    WorkflowStep.objects.bulk_create(
        [WorkflowStep(shipment=shipment, **step) for step in _DEFAULT_TIMELINE]
    )

    # Sync parent order — only set awb (don't auto-transition stage; that's the
    # caller's choice via /orders/{id}/transition/).
    order.awb = awb
    order.save(update_fields=["awb"])

    write_event(
        kind="shipment.created",
        text=f"Shipment {awb} created for order {order.id} (mock Delhivery)",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "awb": awb,
            "order_id": order.id,
            "by": getattr(by_user, "username", ""),
        },
    )
    return shipment


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
