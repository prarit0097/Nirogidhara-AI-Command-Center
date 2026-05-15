"""Phase 9A — Customer Success / Reorder Agent V1 deterministic scoring.

All functions in this module are pure given their inputs and emit no
side effects. The Celery task layer is responsible for persistence
and audit emission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import Order

from .models import CustomerSuccessSnapshot


AGENT_NAME = "customer_success_reorder_v1"
MODEL_USED = "deterministic_v1"

REORDER_WINDOW_DAYS = (20, 30)
LATE_REORDER_DAYS = (31, 45)
LAPSED_AFTER_DAYS = 45
COMPLAINT_LOOKBACK_DAYS = 14
ACTIVE_ORDER_STAGES = {
    Order.Stage.NEW_LEAD.value,
    Order.Stage.INTERESTED.value,
    Order.Stage.PAYMENT_LINK_SENT.value,
    Order.Stage.ORDER_PUNCHED.value,
    Order.Stage.CONFIRMATION_PENDING.value,
    Order.Stage.CONFIRMED.value,
    Order.Stage.DISPATCHED.value,
    Order.Stage.OUT_FOR_DELIVERY.value,
}
RTO_STAGES = {Order.Stage.RTO.value}
DELIVERED_STAGES = {Order.Stage.DELIVERED.value}


@dataclass
class Signals:
    """Deterministic input bundle for the scoring functions."""

    delivered_count: int = 0
    reorder_count: int = 0
    rto_count: int = 0
    last_delivery_at: datetime | None = None
    last_complaint_at: datetime | None = None
    has_active_order: bool = False
    risk_reasons: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "delivered_count": self.delivered_count,
            "reorder_count": self.reorder_count,
            "rto_count": self.rto_count,
            "last_delivery_at": (
                self.last_delivery_at.isoformat()
                if self.last_delivery_at is not None
                else None
            ),
            "last_complaint_at": (
                self.last_complaint_at.isoformat()
                if self.last_complaint_at is not None
                else None
            ),
            "has_active_order": self.has_active_order,
            "risk_reasons": list(self.risk_reasons),
        }


def compute_lifecycle_stage(days_since_delivery: int) -> str:
    """Map days-since-delivery to a lifecycle stage.

    Boundary mapping (inclusive lower, inclusive upper):
        0-2   -> fresh_delivery
        3-7   -> early_usage
        8-19  -> mid_usage
        20-30 -> reorder_window
        31-45 -> late_reorder
        46+   -> lapsed
    """
    if days_since_delivery <= 2:
        return CustomerSuccessSnapshot.LifecycleStage.FRESH_DELIVERY.value
    if days_since_delivery <= 7:
        return CustomerSuccessSnapshot.LifecycleStage.EARLY_USAGE.value
    if days_since_delivery <= 19:
        return CustomerSuccessSnapshot.LifecycleStage.MID_USAGE.value
    if REORDER_WINDOW_DAYS[0] <= days_since_delivery <= REORDER_WINDOW_DAYS[1]:
        return CustomerSuccessSnapshot.LifecycleStage.REORDER_WINDOW.value
    if LATE_REORDER_DAYS[0] <= days_since_delivery <= LATE_REORDER_DAYS[1]:
        return CustomerSuccessSnapshot.LifecycleStage.LATE_REORDER.value
    return CustomerSuccessSnapshot.LifecycleStage.LAPSED.value


def compute_score(signals: Signals) -> int:
    """Clamp deterministic score into the [0, 100] range."""
    base = 60
    base += min(signals.delivered_count * 5, 30)
    base += min(signals.reorder_count * 10, 20)
    base -= min(signals.rto_count * 10, 20)
    if signals.last_complaint_at is not None:
        base -= 15
    return max(0, min(100, base))


def _complaint_within(signals: Signals, now: datetime) -> bool:
    if signals.last_complaint_at is None:
        return False
    return (now - signals.last_complaint_at).days <= COMPLAINT_LOOKBACK_DAYS


def compute_signals(customer: Customer, *, now: datetime | None = None) -> Signals:
    """Build the deterministic Signals bundle for a customer."""
    now = now or timezone.now()
    orders = Order.objects.filter(phone=customer.phone)
    delivered = orders.filter(stage__in=DELIVERED_STAGES).order_by("-created_at")
    delivered_count = delivered.count()
    reorder_count = max(delivered_count - 1, 0)
    rto_count = orders.filter(stage__in=RTO_STAGES).count()
    last_delivery_at = (
        delivered.first().created_at if delivered.exists() else None
    )
    has_active_order = orders.filter(stage__in=ACTIVE_ORDER_STAGES).exists()
    complaint_event = (
        AuditEvent.objects.filter(
            Q(kind__startswith="complaint.")
            | Q(kind="whatsapp.support_complaint_ack")
            | Q(kind="whatsapp.handoff.call_skipped")
        )
        .filter(
            Q(payload__customer_id=customer.id)
            | Q(payload__phone=customer.phone)
            | Q(payload__phone_suffix=customer.phone[-4:])
        )
        .filter(occurred_at__gte=now - timedelta(days=COMPLAINT_LOOKBACK_DAYS))
        .order_by("-occurred_at")
        .first()
    )
    last_complaint_at = complaint_event.occurred_at if complaint_event else None
    risk_reasons: list[str] = []
    if rto_count >= 2:
        risk_reasons.append("repeat_rto")
    if last_complaint_at is not None:
        risk_reasons.append("recent_complaint")
    days_since_delivery = (
        (now - last_delivery_at).days if last_delivery_at is not None else 9999
    )
    if days_since_delivery > LAPSED_AFTER_DAYS and reorder_count == 0:
        risk_reasons.append("lapsed_no_reorder")
    return Signals(
        delivered_count=delivered_count,
        reorder_count=reorder_count,
        rto_count=rto_count,
        last_delivery_at=last_delivery_at,
        last_complaint_at=last_complaint_at,
        has_active_order=has_active_order,
        risk_reasons=risk_reasons,
    )


def _days_since_delivery(signals: Signals, now: datetime) -> int:
    if signals.last_delivery_at is None:
        return 9999
    return (now - signals.last_delivery_at).days


def _reorder_candidate(
    signals: Signals, *, days_since_delivery: int, now: datetime
) -> bool:
    if not (
        REORDER_WINDOW_DAYS[0] <= days_since_delivery <= REORDER_WINDOW_DAYS[1]
    ):
        return False
    if signals.has_active_order:
        return False
    if _complaint_within(signals, now):
        return False
    return True


def _at_risk(
    signals: Signals, *, days_since_delivery: int, now: datetime
) -> bool:
    if days_since_delivery > LAPSED_AFTER_DAYS and signals.reorder_count == 0:
        return True
    if signals.rto_count >= 2:
        return True
    if _complaint_within(signals, now):
        return True
    return False


def choose_recommendation(snapshot: CustomerSuccessSnapshot) -> tuple[str, str]:
    """Return (kind, short factual rationale)."""
    if snapshot.reorder_candidate:
        kind = (
            CustomerSuccessSnapshot.RecommendationKind.SEND_REORDER_REMINDER.value
        )
        text = (
            f"Day {snapshot.days_since_delivery} post-delivery, "
            f"{snapshot.signals.get('delivered_count', 0)} prior delivery, "
            "no active reorder."
        )
        return kind, text
    if snapshot.lifecycle_stage in {
        CustomerSuccessSnapshot.LifecycleStage.LATE_REORDER.value,
        CustomerSuccessSnapshot.LifecycleStage.LAPSED.value,
    } and snapshot.at_risk:
        kind = (
            CustomerSuccessSnapshot.RecommendationKind.SEND_WINBACK_OFFER.value
        )
        text = (
            f"{snapshot.lifecycle_stage} ({snapshot.days_since_delivery} days); "
            f"risk: {','.join(snapshot.risk_reasons) or 'lapsed'}."
        )
        return kind, text
    if (
        snapshot.lifecycle_stage
        == CustomerSuccessSnapshot.LifecycleStage.EARLY_USAGE.value
    ):
        kind = (
            CustomerSuccessSnapshot.RecommendationKind.SEND_USAGE_REMINDER.value
        )
        text = f"Day {snapshot.days_since_delivery} post-delivery; early usage."
        return kind, text
    return (
        CustomerSuccessSnapshot.RecommendationKind.MONITOR_ONLY.value,
        f"{snapshot.lifecycle_stage}; no action recommended.",
    )


def build_snapshot(
    customer: Customer,
    signals: Signals,
    *,
    now: datetime | None = None,
    sandbox: bool = False,
) -> CustomerSuccessSnapshot:
    """Build an unsaved snapshot. The caller persists + links AgentRun."""
    now = now or timezone.now()
    days = _days_since_delivery(signals, now)
    snapshot = CustomerSuccessSnapshot(
        customer=customer,
        score=compute_score(signals),
        lifecycle_stage=compute_lifecycle_stage(days),
        days_since_delivery=days,
        in_reorder_window=(
            REORDER_WINDOW_DAYS[0] <= days <= REORDER_WINDOW_DAYS[1]
        ),
        reorder_candidate=_reorder_candidate(
            signals, days_since_delivery=days, now=now
        ),
        at_risk=_at_risk(signals, days_since_delivery=days, now=now),
        risk_reasons=list(signals.risk_reasons),
        signals=signals.to_payload(),
        sandbox=sandbox,
    )
    kind, text = choose_recommendation(snapshot)
    snapshot.recommendation_kind = kind
    snapshot.recommendation_text = text
    return snapshot
