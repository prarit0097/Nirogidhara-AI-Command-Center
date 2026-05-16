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
    orders_by_id: dict[str, Order] = {
        order.id: order
        for order in Order.objects.filter(id__in=order_ids)
    }

    # Phase 10A Hotfix-1: collect every candidate phone (Payment +
    # Order) so we can join Customer + WhatsApp + Call against the
    # widest possible set, and surface a phone-source breadcrumb.
    phones_seen: set[str] = set()
    for payment in payments:
        phone = (payment.customer_phone or "").strip()
        if phone:
            phones_seen.add(phone)
    for order in orders_by_id.values():
        phone = (order.phone or "").strip()
        if phone:
            phones_seen.add(phone)

    customers_by_phone: dict[str, Customer] = {
        customer.phone: customer
        for customer in Customer.objects.filter(phone__in=phones_seen)
    }

    # Name-based fallback: only fetch customers by name for payments
    # whose phone chain so far failed. Phase 10A Hotfix-1 keeps the
    # query small by gathering candidate names first.
    names_seen: set[str] = set()
    matched_phones = set(customers_by_phone.keys())
    for payment in payments:
        payment_phone = (payment.customer_phone or "").strip()
        order = orders_by_id.get(payment.order_id)
        order_phone = (order.phone or "").strip() if order else ""
        if payment_phone in matched_phones or order_phone in matched_phones:
            continue
        candidate_name = (payment.customer or "").strip()
        if not candidate_name and order is not None:
            candidate_name = (order.customer_name or "").strip()
        if candidate_name:
            names_seen.add(candidate_name)
    customers_by_name: dict[str, Customer] = {}
    if names_seen:
        for customer in Customer.objects.filter(name__in=names_seen):
            customers_by_name.setdefault(customer.name, customer)

    def _resolve_customer(
        payment_obj: Payment, order_obj: Order | None
    ) -> Customer | None:
        payment_phone_local = (payment_obj.customer_phone or "").strip()
        if payment_phone_local and payment_phone_local in customers_by_phone:
            return customers_by_phone[payment_phone_local]
        order_phone_local = (order_obj.phone or "").strip() if order_obj else ""
        if order_phone_local and order_phone_local in customers_by_phone:
            return customers_by_phone[order_phone_local]
        candidate_name_local = (payment_obj.customer or "").strip()
        if candidate_name_local and candidate_name_local in customers_by_name:
            return customers_by_name[candidate_name_local]
        if order_obj is not None:
            order_name_local = (order_obj.customer_name or "").strip()
            if order_name_local and order_name_local in customers_by_name:
                return customers_by_name[order_name_local]
        return None

    # Pre-compute last outbound WhatsApp per resolved customer so we
    # never N+1 the join when many payments share a customer.
    last_whatsapp_by_customer: dict[int | str, datetime] = {}
    last_call_by_phone: dict[str, dict[str, Any]] = {}

    rows: list[dict[str, Any]] = []
    for payment in payments:
        order = orders_by_id.get(payment.order_id)
        if state_filter:
            order_state_value = (
                (order.state or "") if order is not None else ""
            )
            if order_state_value.lower() != state_filter.lower():
                continue

        payment_phone = (payment.customer_phone or "").strip()
        order_phone = (order.phone or "").strip() if order else ""
        customer = _resolve_customer(payment, order)
        customer_phone = (customer.phone or "").strip() if customer else ""

        if payment_phone:
            picked_phone, phone_source = payment_phone, "payment"
        elif order_phone:
            picked_phone, phone_source = order_phone, "order"
        elif customer_phone:
            picked_phone, phone_source = customer_phone, "customer"
        else:
            picked_phone, phone_source = None, "none"

        wa_at: datetime | None = None
        if customer is not None:
            if customer.pk in last_whatsapp_by_customer:
                wa_at = last_whatsapp_by_customer[customer.pk]
            else:
                wa_at = (
                    WhatsAppMessage.objects.filter(
                        customer=customer,
                        direction=(
                            WhatsAppMessage.Direction.OUTBOUND.value
                        ),
                    )
                    .order_by("-created_at")
                    .values_list("created_at", flat=True)
                    .first()
                )
                last_whatsapp_by_customer[customer.pk] = wa_at

        call_info: dict[str, Any] | None = None
        if picked_phone:
            if picked_phone in last_call_by_phone:
                call_info = last_call_by_phone[picked_phone]
            else:
                latest_call = (
                    Call.objects.filter(phone=picked_phone)
                    .order_by("-created_at")
                    .only("created_at", "status")
                    .first()
                )
                if latest_call is not None:
                    call_info = {
                        "created_at": latest_call.created_at,
                        "status": latest_call.status,
                    }
                last_call_by_phone[picked_phone] = call_info  # type: ignore[assignment]

        customer_name = payment.customer or (
            order.customer_name if order is not None else ""
        )
        if not customer_name and customer is not None:
            customer_name = customer.name

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
                "customer_phone": picked_phone,
                "phone_source": phone_source,
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
