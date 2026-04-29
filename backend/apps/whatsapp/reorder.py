"""Phase 5E — Day-20 reorder reminder cadence.

Sweeps delivered orders that crossed the Day-20 threshold and queues a
``whatsapp.reorder_day20_reminder`` lifecycle event for each. The
existing Phase 5A pipeline does the actual send (consent + approved-
template + Claim Vault + approval matrix + CAIO + idempotency); this
module is purely the eligibility filter + dispatch loop.

Eligibility rules (LOCKED):
- ``Order.stage == "Delivered"``.
- The shipment was delivered ~20 days ago (default window: between 20
  and 27 days). The lifecycle layer is idempotent on
  ``lifecycle:whatsapp.reorder_day20_reminder:order:{id}:day20`` so a
  re-run on Day 21/22 will collapse into the same row.
- The customer has WhatsApp consent (Phase 5A consent gate handles
  this server-side; we still pre-filter to avoid unnecessary lifecycle
  rows).
- A reorder reminder has not already been queued for this order
  (idempotency key prevents duplicates regardless).
- Phase 5E flag ``WHATSAPP_REORDER_DAY20_ENABLED=true`` (default OFF;
  production opts in after Mock + OpenAI verification).

The sweep does NOT offer a discount upfront. Per Phase 5E lock,
discount only opens if the customer raises a price objection in the
follow-up chat.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.crm.models import Customer
from apps.orders.models import Order

from .lifecycle import REORDER_DAY20_ACTION, queue_lifecycle_message
from .models import WhatsAppLifecycleEvent


logger = logging.getLogger(__name__)


DAY20_LOWER_BOUND_DAYS: int = 20
DAY20_UPPER_BOUND_DAYS: int = 27  # cap re-evaluations after a week


@dataclass(frozen=True)
class Day20SweepResult:
    """Outcome of :func:`run_day20_reorder_sweep`."""

    eligible: int
    queued: int
    skipped: int
    blocked: int
    failed: int
    dry_run: bool

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "eligible": self.eligible,
            "queued": self.queued,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "failed": self.failed,
            "dryRun": self.dry_run,
        }


def _eligible_orders(now=None) -> Iterable[Order]:
    """Return delivered orders whose Day-20 window is open.

    ``Order`` does not carry a separate ``delivered_at`` timestamp; we
    fall back to ``Order.created_at`` plus the standard transit window.
    For the very first VPS deploy, ``Shipment.updated_at`` (when status
    flipped to "Delivered") is the more accurate signal, but the orders
    surface is the canonical truth — so we match by stage + age.
    """
    now = now or timezone.now()
    lower = now - timedelta(days=DAY20_UPPER_BOUND_DAYS)
    upper = now - timedelta(days=DAY20_LOWER_BOUND_DAYS)
    qs = (
        Order.objects.filter(stage=Order.Stage.DELIVERED)
        .filter(created_at__gte=lower, created_at__lte=upper)
        .order_by("created_at")
    )
    return qs


def _order_already_reminded(order: Order) -> bool:
    """Idempotency pre-check — avoid even building the customer payload."""
    return WhatsAppLifecycleEvent.objects.filter(
        action_key=REORDER_DAY20_ACTION,
        object_type=WhatsAppLifecycleEvent.ObjectType.ORDER,
        object_id=order.id,
    ).exists()


def _customer_for_order(order: Order) -> Customer | None:
    if not order.phone:
        return None
    digits = "".join(ch for ch in order.phone if ch.isdigit())
    if not digits:
        return None
    return (
        Customer.objects.filter(phone__iexact=order.phone).first()
        or Customer.objects.filter(phone__iexact=f"+{digits}").first()
        or Customer.objects.filter(phone__icontains=digits[-10:]).first()
    )


def run_day20_reorder_sweep(*, dry_run: bool = False) -> Day20SweepResult:
    """Iterate eligible orders and queue Day-20 reorder reminders.

    Returns a structured summary so the management command + tests can
    assert on counts. Lifecycle gates (consent / template / Claim Vault
    / approval matrix / CAIO / idempotency) still fire on each
    ``queue_lifecycle_message`` call.
    """
    if not getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False) and not dry_run:
        return Day20SweepResult(
            eligible=0, queued=0, skipped=0, blocked=0, failed=0, dry_run=dry_run
        )

    eligible = 0
    queued = 0
    skipped = 0
    blocked = 0
    failed = 0

    for order in _eligible_orders():
        eligible += 1

        if _order_already_reminded(order):
            skipped += 1
            continue
        if dry_run:
            queued += 1
            continue

        customer = _customer_for_order(order)
        if customer is None or not getattr(customer, "consent_whatsapp", False):
            skipped += 1
            continue

        try:
            result = queue_lifecycle_message(
                object_type=WhatsAppLifecycleEvent.ObjectType.ORDER,
                object_id=order.id,
                event_kind="day20",
                customer=customer,
                variables={
                    "customer_name": order.customer_name or customer.name,
                    "context": order.product or "",
                    "product": order.product or "",
                    "order_id": order.id,
                },
                metadata={
                    "source": "day20_sweep",
                    "order_id": order.id,
                    "delivered_age_days": (
                        timezone.now() - (order.created_at or timezone.now())
                    ).days,
                },
            )
        except Exception as exc:  # noqa: BLE001 - never break the sweep
            logger.warning(
                "Day-20 reorder dispatch failed for order %s: %s", order.id, exc
            )
            failed += 1
            continue
        if result.status == WhatsAppLifecycleEvent.Status.SENT:
            queued += 1
        elif result.status == WhatsAppLifecycleEvent.Status.QUEUED:
            queued += 1
        elif result.status == WhatsAppLifecycleEvent.Status.BLOCKED:
            blocked += 1
        else:
            skipped += 1

    return Day20SweepResult(
        eligible=eligible,
        queued=queued,
        skipped=skipped,
        blocked=blocked,
        failed=failed,
        dry_run=dry_run,
    )


__all__ = (
    "DAY20_LOWER_BOUND_DAYS",
    "DAY20_UPPER_BOUND_DAYS",
    "Day20SweepResult",
    "run_day20_reorder_sweep",
)
