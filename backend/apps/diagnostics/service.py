"""Phase 10A — Diagnostics service layer.

Pure read-only aggregation helpers. Every function here reads from
the database only; nothing in this module mutates state, calls a
provider, or sends a customer-facing message.

Discovered field shape (validated by reading the source files
before writing this module):

- ``payments.Payment``: ``id``, ``order_id``, ``customer`` (customer
  name string), ``customer_phone``, ``amount`` (integer rupees),
  ``status`` ∈ {Paid / Pending / Failed / Refunded / Cancelled /
  Expired / Partial}, ``payment_url`` (URLField), ``gateway`` /
  ``gateway_reference_id``, ``created_at`` / ``updated_at``.
- ``orders.Order``: ``id``, ``customer_name``, ``phone``, ``state``
  (geographic), ``stage`` (lifecycle), ``payment_status``,
  ``amount``, ``created_at``.
- ``crm.Customer``: ``id``, ``name``, ``phone``, etc.
- ``whatsapp.WhatsAppMessage``: FK ``customer``, ``direction`` ∈
  {inbound / outbound / system}, ``created_at``. Used to find the
  last outbound WhatsApp event timestamp for a customer.
- ``calls.Call``: ``phone``, ``status`` ∈ {Live / Queued / Completed
  / Missed / Failed}, ``sentiment``, ``created_at``. No dedicated
  ``outcome`` column — ``status`` is the closest action-relevant
  signal and is surfaced as ``last_call_outcome``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.calls.models import Call
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.whatsapp.models import WhatsAppMessage


DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if value <= 0:
        return None
    return min(value, MAX_LIMIT)


def _days_since(created_at: datetime, now: datetime) -> int:
    if created_at is None:
        return 0
    return max(0, (now - created_at).days)


def list_pending_payments_drilldown(
    *,
    include_partial: bool = True,
    limit: int | None = DEFAULT_LIMIT,
    state_filter: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return all Pending (+ optionally Partial) payments with context.

    Sorted by ``created_at`` ASC so the oldest pending records appear
    first. Joined fields are populated where the source row exists;
    a missing Order / Customer / Call / WhatsApp record contributes
    ``None`` rather than raising.

    READ-ONLY. This function never mutates any row and never calls a
    provider; the test suite asserts this with patched send /
    trigger / create entrypoints.
    """
    now = now or timezone.now()
    statuses = [Payment.Status.PENDING.value]
    if include_partial:
        statuses.append(Payment.Status.PARTIAL.value)
    qs = Payment.objects.filter(status__in=statuses).order_by("created_at")
    limit_value = _normalize_limit(limit)
    if limit_value is not None:
        qs = qs[:limit_value]
    payments = list(qs)
    if not payments:
        return []

    order_ids = list({p.order_id for p in payments if p.order_id})
    phones = list({p.customer_phone for p in payments if p.customer_phone})

    orders_by_id: dict[str, Order] = {
        order.id: order
        for order in Order.objects.filter(id__in=order_ids)
    }
    customers_by_phone: dict[str, Customer] = {
        customer.phone: customer
        for customer in Customer.objects.filter(phone__in=phones)
    }

    last_whatsapp_by_phone: dict[str, datetime] = {}
    for phone, customer in customers_by_phone.items():
        latest = (
            WhatsAppMessage.objects.filter(
                customer=customer,
                direction=WhatsAppMessage.Direction.OUTBOUND.value,
            )
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if latest is not None:
            last_whatsapp_by_phone[phone] = latest

    last_call_by_phone: dict[str, dict[str, Any]] = {}
    for phone in phones:
        latest_call = (
            Call.objects.filter(phone=phone)
            .order_by("-created_at")
            .only("created_at", "status")
            .first()
        )
        if latest_call is not None:
            last_call_by_phone[phone] = {
                "created_at": latest_call.created_at,
                "status": latest_call.status,
            }

    rows: list[dict[str, Any]] = []
    for payment in payments:
        order = orders_by_id.get(payment.order_id)
        if state_filter and order is not None:
            if (order.state or "").lower() != state_filter.lower():
                continue
        elif state_filter and order is None:
            continue
        wa_at = last_whatsapp_by_phone.get(payment.customer_phone)
        call_info = last_call_by_phone.get(payment.customer_phone)
        customer_name = payment.customer or (
            order.customer_name if order is not None else ""
        )
        rows.append(
            {
                "payment_id": payment.id,
                "payment_status": payment.status,
                "amount": payment.amount,
                "payment_link_url": payment.payment_url or None,
                "gateway_reference_id": (
                    payment.gateway_reference_id or None
                ),
                "created_at": payment.created_at,
                "days_since_creation": _days_since(
                    payment.created_at, now
                ),
                "order_id": payment.order_id,
                "order_state": order.state if order is not None else None,
                "order_status": order.stage if order is not None else None,
                "customer_name": customer_name,
                "customer_phone": payment.customer_phone,
                "last_whatsapp_at": wa_at,
                "last_call_at": (
                    call_info["created_at"] if call_info else None
                ),
                "last_call_outcome": (
                    call_info["status"] if call_info else None
                ),
            }
        )
    return rows
