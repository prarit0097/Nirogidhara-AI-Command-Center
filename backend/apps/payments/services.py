"""Payment write services. Phase 2A: model + audit. Phase 2B: Razorpay link.

Real Razorpay sandbox/live calls are gated by ``settings.RAZORPAY_MODE`` —
default is ``mock`` so dev runs offline. The adapter lives in
``apps/payments/integrations/razorpay_client.py``; this module never imports
the razorpay SDK directly.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order

from .integrations.razorpay_client import (
    PaymentLinkResult,
    RazorpayClientError,
    create_payment_link as _gateway_create_payment_link,
)
from .models import Payment
from .policies import FIXED_ADVANCE_AMOUNT_INR, resolve_advance_amount

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


@transaction.atomic
def create_payment_link(
    *,
    order: Order,
    amount: int,
    by_user: "User",
    gateway: str = Payment.Gateway.RAZORPAY,
    type: str = Payment.Type.ADVANCE,
    customer_name: str = "",
    customer_phone: str = "",
    customer_email: str = "",
) -> tuple[Payment, str]:
    """Create a Payment row in Pending status and return ``(payment, url)``.

    The Payment row stores the gateway's plink id in ``gateway_reference_id``
    so webhook handlers can look it up by reference.
    """
    if gateway not in Payment.Gateway.values:
        raise ValueError(f"Unknown gateway: {gateway!r}")
    if type not in Payment.Type.values:
        raise ValueError(f"Unknown payment type: {type!r}")
    # Phase 3E — Advance payments default to ₹499 when amount is omitted/0.
    # Non-Advance types still require an explicit positive amount.
    if type == Payment.Type.ADVANCE:
        amount = resolve_advance_amount(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")

    # Default customer_name to the order's customer if the caller didn't pass one.
    customer_name = customer_name or order.customer_name

    # Reserve the Payment id first so we can include it in the gateway payload.
    payment_id = next_id("PAY", Payment, base=30200)

    # Currently only Razorpay routes through the integration adapter. Other
    # gateways (PayU) keep mock-only behaviour until Phase 2B-2.
    if gateway == Payment.Gateway.RAZORPAY:
        try:
            result: PaymentLinkResult = _gateway_create_payment_link(
                order_id=order.id,
                amount=amount,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
            )
        except RazorpayClientError:
            # Re-raise so the view can return 502/400; never silently swallow.
            raise
        plink_id = result.plink_id
        short_url = result.short_url
        raw = dict(result.raw or {})
    else:
        plink_id = f"payu_mock_{payment_id}"
        short_url = f"https://payu.example/pay/{payment_id}"
        raw = {"gateway": gateway, "mode": "mock"}

    payment = Payment.objects.create(
        id=payment_id,
        order_id=order.id,
        customer=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email,
        amount=amount,
        gateway=gateway,
        status=Payment.Status.PENDING,
        type=type,
        time="just now",
        gateway_reference_id=plink_id,
        payment_url=short_url,
        raw_response=raw,
    )

    write_event(
        kind="payment.link_created",
        text=f"Payment link {payment.id} created for {order.id} · ₹{amount} ({gateway})",
        tone=AuditEvent.Tone.INFO,
        payload={
            "payment_id": payment.id,
            "order_id": order.id,
            "gateway": gateway,
            "amount": amount,
            "gateway_reference_id": plink_id,
            "by": getattr(by_user, "username", ""),
        },
    )
    return payment, short_url
