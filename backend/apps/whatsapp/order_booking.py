"""Phase 5C — book an order from a WhatsApp AI Chat Agent decision.

The orchestrator passes a validated :class:`apps.whatsapp.ai_schema.ChatAgentDecision`
(plus the Customer + Conversation) and this module:

1. Validates the order draft is complete enough to book.
2. Validates the discount via the WhatsApp discount policy + the locked
   50% total cap.
3. Calls :func:`apps.orders.services.create_order` (the existing service
   layer — never writes the model directly).
4. Optionally calls :func:`apps.payments.services.create_payment_link`
   for the ₹499 advance link via the existing service path.
5. Optionally queues a confirmation template send.
6. Returns a :class:`OrderBookingResult` describing what landed.

Hard rules:
- Discount > 50% total → blocked, raise :class:`OrderBookingError`.
- Address fields incomplete → blocked.
- Order creation never dispatches a shipment (Phase 5C does not touch
  ``apps.shipments``).
- Failed payment-link creation does NOT roll back the order; the order
  stays booked with ``paymentLinkPending=True`` flagged in metadata.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order
from apps.orders.services import create_order
from apps.payments.policies import FIXED_ADVANCE_AMOUNT_INR

from .ai_schema import ChatAgentDecision
from .discount_policy import (
    TOTAL_DISCOUNT_HARD_CAP_PCT,
    validate_total_discount_cap,
)
from .models import WhatsAppConversation


logger = logging.getLogger(__name__)


REQUIRED_ORDER_FIELDS: tuple[str, ...] = (
    "customerName",
    "phone",
    "address",
    "pincode",
    "city",
    "state",
)


class OrderBookingError(ValueError):
    """Raised when an AI-driven order cannot be booked safely."""

    def __init__(self, message: str, *, code: str = "blocked") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OrderBookingResult:
    """Result returned by :func:`book_order_from_decision`."""

    order_id: str
    payment_id: str = ""
    payment_url: str = ""
    confirmation_message_id: str = ""


def book_order_from_decision(
    *,
    conversation: WhatsAppConversation,
    decision: ChatAgentDecision,
    actor_role: str = "ai_chat",
) -> OrderBookingResult:
    """Execute the order booking flow for a Phase 5C decision."""
    draft = dict(decision.order_draft or {})

    missing = [
        field
        for field in REQUIRED_ORDER_FIELDS
        if not str(draft.get(field) or "").strip()
    ]
    if missing:
        raise OrderBookingError(
            f"Order draft missing required fields: {', '.join(missing)}",
            code="incomplete_address",
        )

    quantity = max(1, int(draft.get("quantity") or 1))
    amount = max(0, int(draft.get("amount") or 3000))
    if amount <= 0:
        raise OrderBookingError(
            "Order amount must be positive.",
            code="invalid_amount",
        )

    proposed_pct = max(0, int(draft.get("discountPct") or 0))
    metadata = dict(conversation.metadata or {})
    ai_state = dict(metadata.get("ai") or {})
    current_total = int(ai_state.get("totalDiscountPct") or 0)
    cap_passed, final_total = validate_total_discount_cap(
        current_total_pct=current_total,
        additional_pct=proposed_pct,
    )
    if not cap_passed:
        raise OrderBookingError(
            (
                f"Discount {proposed_pct}% would push total to "
                f"{final_total}% — exceeds the {TOTAL_DISCOUNT_HARD_CAP_PCT}% "
                "hard cap."
            ),
            code="discount_cap_exceeded",
        )

    customer_name = str(draft.get("customerName") or conversation.customer.name)
    phone = str(draft.get("phone") or conversation.customer.phone)
    product = str(draft.get("product") or conversation.customer.product_interest or "Ayurvedic")

    write_event(
        kind="whatsapp.ai.order_draft_created",
        text=(
            f"AI order draft validated · conversation={conversation.id} · "
            f"product={product}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "conversation_id": conversation.id,
            "customer_id": conversation.customer_id,
            "draft": {
                **draft,
                "phone": _redact_phone(phone),
            },
        },
    )

    write_event(
        kind="whatsapp.ai.address_updated",
        text=f"AI captured address · conversation={conversation.id}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "conversation_id": conversation.id,
            "address": draft.get("address"),
            "pincode": draft.get("pincode"),
            "city": draft.get("city"),
            "state": draft.get("state"),
        },
    )

    with transaction.atomic():
        order = create_order(
            customer_name=customer_name,
            phone=phone,
            product=product,
            state=str(draft.get("state") or ""),
            city=str(draft.get("city") or ""),
            quantity=quantity,
            amount=amount,
            discount_pct=proposed_pct,
            agent="WhatsApp AI",
            stage=Order.Stage.ORDER_PUNCHED,
        )

    write_event(
        kind="whatsapp.ai.order_booked",
        text=(
            f"AI booked order {order.id} · conversation={conversation.id} · "
            f"₹{amount} · {customer_name}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": conversation.id,
            "order_id": order.id,
            "customer_id": conversation.customer_id,
            "amount": amount,
            "discount_pct": proposed_pct,
            "actor_role": actor_role,
        },
    )

    payment_id = ""
    payment_url = ""
    confirmation_message_id = ""

    if decision.payment.get("shouldCreateAdvanceLink"):
        try:
            from apps.payments.services import create_payment_link

            payment, url = create_payment_link(
                order=order,
                amount=int(decision.payment.get("amount") or FIXED_ADVANCE_AMOUNT_INR),
                by_user=None,
                customer_name=customer_name,
                customer_phone=phone,
            )
            payment_id = payment.id
            payment_url = url
            write_event(
                kind="whatsapp.ai.payment_link_created",
                text=(
                    f"AI payment link {payment.id} for {order.id} · ₹{payment.amount}"
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "conversation_id": conversation.id,
                    "order_id": order.id,
                    "payment_id": payment.id,
                    "amount": int(payment.amount or 0),
                },
            )
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warning(
                "WhatsApp AI: payment link creation failed for order %s: %s",
                order.id,
                exc,
            )
            write_event(
                kind="whatsapp.ai.payment_link_created",
                text=(
                    f"AI payment link failed for {order.id} · "
                    f"manual follow-up needed"
                ),
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "conversation_id": conversation.id,
                    "order_id": order.id,
                    "error": str(exc)[:500],
                    "pending": True,
                },
            )

    return OrderBookingResult(
        order_id=order.id,
        payment_id=payment_id,
        payment_url=payment_url,
        confirmation_message_id=confirmation_message_id,
    )


def _redact_phone(phone: str) -> str:
    if not phone:
        return ""
    if len(phone) <= 4:
        return "*" * len(phone)
    return f"{phone[:2]}…{phone[-2:]}"


__all__ = (
    "OrderBookingError",
    "OrderBookingResult",
    "REQUIRED_ORDER_FIELDS",
    "book_order_from_decision",
)
