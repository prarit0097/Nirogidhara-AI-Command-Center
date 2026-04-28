"""Order write services + state machine. Blueprint Sections 5.4 + 5.7 + 12.5.

The state machine is a single ``ALLOWED_TRANSITIONS`` dict. Invalid transitions
raise ``OrderTransitionError`` which views translate into HTTP 400.

Audit ledger:
- ``order.created`` and ``order.status_changed`` are fired by the existing
  post-save signal in ``apps/audit/signals.py``.
- ``confirmation.outcome`` is written explicitly here because the confirmation
  may NOT change ``stage`` (rescue_needed) — the signal would not fire.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import Order

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


class OrderTransitionError(ValueError):
    """Raised when a stage transition is not allowed by the state machine."""


# State machine — central source of truth. Keep narrow.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Order.Stage.NEW_LEAD: {Order.Stage.INTERESTED, Order.Stage.CANCELLED},
    Order.Stage.INTERESTED: {
        Order.Stage.PAYMENT_LINK_SENT,
        Order.Stage.ORDER_PUNCHED,
        Order.Stage.CANCELLED,
    },
    Order.Stage.PAYMENT_LINK_SENT: {Order.Stage.ORDER_PUNCHED, Order.Stage.CANCELLED},
    Order.Stage.ORDER_PUNCHED: {Order.Stage.CONFIRMATION_PENDING, Order.Stage.CANCELLED},
    Order.Stage.CONFIRMATION_PENDING: {Order.Stage.CONFIRMED, Order.Stage.CANCELLED},
    Order.Stage.CONFIRMED: {Order.Stage.DISPATCHED, Order.Stage.CANCELLED},
    Order.Stage.DISPATCHED: {Order.Stage.OUT_FOR_DELIVERY, Order.Stage.RTO},
    Order.Stage.OUT_FOR_DELIVERY: {Order.Stage.DELIVERED, Order.Stage.RTO},
    Order.Stage.DELIVERED: set(),  # terminal — reorder cycle in Phase 6
    Order.Stage.RTO: set(),  # terminal — reward/penalty in Phase 5
    Order.Stage.CANCELLED: set(),  # terminal
}


@transaction.atomic
def create_order(
    *,
    customer_name: str,
    phone: str,
    product: str,
    state: str,
    city: str,
    quantity: int = 1,
    amount: int = 3000,
    discount_pct: int = 0,
    advance_paid: bool = False,
    advance_amount: int = 0,
    payment_status: str = Order.PaymentStatus.PENDING,
    rto_risk: str = Order.RtoRisk.LOW,
    rto_score: int = 10,
    agent: str = "",
    stage: str = Order.Stage.ORDER_PUNCHED,
) -> Order:
    return Order.objects.create(
        id=next_id("NRG", Order, base=20500),
        customer_name=customer_name,
        phone=phone,
        product=product,
        quantity=quantity,
        amount=amount,
        discount_pct=discount_pct,
        advance_paid=advance_paid,
        advance_amount=advance_amount,
        payment_status=payment_status,
        state=state,
        city=city,
        rto_risk=rto_risk,
        rto_score=rto_score,
        agent=agent,
        stage=stage,
        created_at_label="just now",
    )


@transaction.atomic
def transition_order(order: Order, new_stage: str, *, by_user: "User", notes: str = "") -> Order:
    """Validate + apply a stage transition. Audit logged via post_save signal."""
    if new_stage == order.stage:
        return order
    allowed = ALLOWED_TRANSITIONS.get(order.stage, set())
    if new_stage not in allowed:
        raise OrderTransitionError(
            f"Cannot move from {order.stage} to {new_stage}. "
            f"Allowed: {sorted(allowed) or 'none (terminal stage)'}"
        )
    order.stage = new_stage
    if notes:
        # Append a note marker; we don't have a free-text notes field on Order
        # other than confirmation_notes. Keep notes available via AuditEvent payload.
        pass
    order.save(update_fields=["stage"])
    return order


def move_to_confirmation(order: Order, *, by_user: "User") -> Order:
    """Convenience helper for the most common transition."""
    return transition_order(order, Order.Stage.CONFIRMATION_PENDING, by_user=by_user)


@transaction.atomic
def record_confirmation_outcome(
    order: Order,
    *,
    outcome: str,
    by_user: "User",
    notes: str = "",
) -> Order:
    """Apply the confirmation call outcome.

    - ``confirmed`` → stage moves to CONFIRMED.
    - ``cancelled`` → stage moves to CANCELLED.
    - ``rescue_needed`` → stage stays CONFIRMATION_PENDING; ``rescue_status`` set.
    """
    if outcome not in {"confirmed", "rescue_needed", "cancelled"}:
        raise ValueError(f"Invalid confirmation outcome: {outcome!r}")
    if order.stage != Order.Stage.CONFIRMATION_PENDING:
        raise OrderTransitionError(
            f"Order {order.id} is not in Confirmation Pending (stage={order.stage})"
        )

    order.confirmation_outcome = outcome
    order.confirmation_notes = notes or order.confirmation_notes
    update_fields: list[str] = ["confirmation_outcome", "confirmation_notes"]

    if outcome == "confirmed":
        order.stage = Order.Stage.CONFIRMED
        update_fields.append("stage")
        order.rescue_status = ""
        update_fields.append("rescue_status")
        tone = AuditEvent.Tone.SUCCESS
    elif outcome == "cancelled":
        order.stage = Order.Stage.CANCELLED
        update_fields.append("stage")
        tone = AuditEvent.Tone.WARNING
    else:  # rescue_needed
        order.rescue_status = "Rescue Needed (confirmation)"
        update_fields.append("rescue_status")
        tone = AuditEvent.Tone.WARNING

    order.save(update_fields=update_fields)

    write_event(
        kind="confirmation.outcome",
        text=f"Order {order.id} confirmation outcome: {outcome}",
        tone=tone,
        payload={
            "order_id": order.id,
            "outcome": outcome,
            "stage": order.stage,
            "by": getattr(by_user, "username", ""),
        },
    )
    return order


# ---------------------------------------------------------------------------
# Phase 4E — Apply discount through approval execution layer.
# ---------------------------------------------------------------------------


class DiscountValidationError(ValueError):
    """Raised when ``apply_order_discount`` rejects a discount via policy."""


@transaction.atomic
def apply_order_discount(
    order: Order,
    *,
    discount_pct: int,
    actor: "User" | None = None,
    actor_role: str | None = None,
    reason: str = "",
    source: str = "approval_execution",
    approval_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a discount to an order via the locked Phase 3E policy.

    Phase 4E uses this from the Approved Action Execution Layer (handlers
    for ``discount.up_to_10`` and ``discount.11_to_20``). The function:

    - Validates via :func:`apps.orders.discounts.validate_discount`.
    - Mutates ONLY ``Order.discount_pct`` — never touches customer /
      payment / shipment / stage data.
    - Writes a ``discount.applied`` AuditEvent.
    - Returns a structured result the execute endpoint surfaces back to
      the operator UI.
    """
    from apps.orders.discounts import validate_discount

    if discount_pct is None:
        raise DiscountValidationError("discountPct is required.")
    try:
        new_pct = int(discount_pct)
    except (TypeError, ValueError) as exc:
        raise DiscountValidationError("discountPct must be an integer.") from exc

    role = (actor_role or getattr(actor, "role", "") or "").lower().strip()
    validation = validate_discount(
        new_pct,
        actor_role=role,
        approval_context=approval_context,
    )
    if not validation.allowed:
        raise DiscountValidationError(validation.reason)

    old_pct = int(order.discount_pct or 0)
    order.discount_pct = new_pct
    order.save(update_fields=["discount_pct"])

    write_event(
        kind="discount.applied",
        text=(
            f"Discount {old_pct}% → {new_pct}% applied to order {order.id} "
            f"({source})"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "order_id": order.id,
            "old_discount_pct": old_pct,
            "new_discount_pct": new_pct,
            "actor_role": role,
            "reason": reason,
            "source": source,
            "by": getattr(actor, "username", "") or "",
        },
    )
    return {
        "orderId": order.id,
        "oldDiscountPct": old_pct,
        "newDiscountPct": new_pct,
        "policyBand": validation.policy_band,
        "reason": reason,
        "source": source,
    }
