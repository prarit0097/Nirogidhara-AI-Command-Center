"""Phase 9B — RTO Prevention Agent V1 deterministic scoring.

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
from apps.shipments.models import Shipment

from .models import RtoRiskSnapshot


AGENT_NAME = "rto_prevention_v1"
MODEL_USED = "deterministic_v1"

COMPLAINT_LOOKBACK_DAYS = 14
HIGH_VALUE_ORDER_THRESHOLD_INR = 5000
ORDER_AGE_WINDOW_DAYS = 30
STALE_ORDER_DAYS = 14
IN_FLIGHT_STAGES = {
    Order.Stage.CONFIRMED.value,
    Order.Stage.DISPATCHED.value,
    Order.Stage.OUT_FOR_DELIVERY.value,
}
TERMINAL_STAGES = {
    Order.Stage.DELIVERED.value,
    Order.Stage.RTO.value,
    Order.Stage.CANCELLED.value,
}
# Shipment.delhivery_status values that indicate a failed delivery
# attempt. Stored verbatim from the Delhivery webhook payload.
FAILED_DELIVERY_STATUS_KEYWORDS = (
    "ndr",
    "undelivered",
    "rto initiated",
    "reattempt",
    "failed delivery",
)


@dataclass
class Signals:
    """Deterministic input bundle for the scoring functions."""

    rto_count: int = 0
    complaint_count_14d: int = 0
    delivered_count: int = 0
    payment_status: str = ""
    order_amount: int = 0
    days_since_order: int = 0
    failed_attempts_on_current_shipment: int = 0
    has_shipment: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "rto_count": self.rto_count,
            "complaint_count_14d": self.complaint_count_14d,
            "delivered_count": self.delivered_count,
            "payment_status": self.payment_status,
            "order_amount": self.order_amount,
            "days_since_order": self.days_since_order,
            "failed_attempts_on_current_shipment": (
                self.failed_attempts_on_current_shipment
            ),
            "has_shipment": self.has_shipment,
        }


def _customer_for_order(order: Order) -> Customer | None:
    return Customer.objects.filter(phone=order.phone).first()


def _failed_attempts_for_order(order: Order) -> tuple[int, bool]:
    """Return ``(failed_attempts, has_shipment)``.

    Phase 9B V1 derives failed attempts from
    ``Shipment.delhivery_status``. A status containing any keyword from
    :data:`FAILED_DELIVERY_STATUS_KEYWORDS` counts as one failed
    attempt — V1 is deterministic and conservative; a future phase can
    swap in a per-attempt counter if Delhivery webhook history is
    persisted explicitly.
    """
    shipment = (
        Shipment.objects.filter(order_id=order.id).order_by("-created_at").first()
    )
    if shipment is None:
        return 0, False
    status_text = " ".join(
        [
            (shipment.status or "").lower(),
            (shipment.delhivery_status or "").lower(),
            (shipment.risk_flag or "").lower(),
        ]
    )
    failed = any(keyword in status_text for keyword in FAILED_DELIVERY_STATUS_KEYWORDS)
    return (1 if failed else 0), True


def compute_signals(
    order: Order, *, now: datetime | None = None
) -> Signals:
    """Build the deterministic Signals bundle for an order."""
    now = now or timezone.now()
    customer_orders = Order.objects.filter(phone=order.phone)
    rto_count = customer_orders.filter(stage=Order.Stage.RTO.value).count()
    delivered_count = customer_orders.filter(
        stage=Order.Stage.DELIVERED.value
    ).count()
    complaint_count_14d = (
        AuditEvent.objects.filter(
            Q(kind__startswith="complaint.")
            | Q(kind="whatsapp.support_complaint_ack")
        )
        .filter(
            Q(payload__phone=order.phone)
            | Q(payload__phone_suffix=order.phone[-4:])
            | Q(payload__order_id=order.id)
        )
        .filter(occurred_at__gte=now - timedelta(days=COMPLAINT_LOOKBACK_DAYS))
        .count()
    )
    failed_attempts, has_shipment = _failed_attempts_for_order(order)
    days_since_order = (now - order.created_at).days if order.created_at else 0
    return Signals(
        rto_count=rto_count,
        complaint_count_14d=complaint_count_14d,
        delivered_count=delivered_count,
        payment_status=order.payment_status or "",
        order_amount=int(order.amount or 0),
        days_since_order=max(0, days_since_order),
        failed_attempts_on_current_shipment=failed_attempts,
        has_shipment=has_shipment,
    )


def compute_lifecycle_stage(order: Order, signals: Signals) -> str:
    if signals.failed_attempts_on_current_shipment >= 1:
        return RtoRiskSnapshot.LifecycleStage.DELIVERY_AT_RISK.value
    if signals.has_shipment:
        return RtoRiskSnapshot.LifecycleStage.IN_TRANSIT.value
    return RtoRiskSnapshot.LifecycleStage.PRE_DISPATCH.value


def compute_risk_score(signals: Signals) -> int:
    """Clamp deterministic score into the [0, 100] range."""
    base = 30
    base += min(signals.rto_count * 15, 45)
    base += min(signals.complaint_count_14d * 10, 20)
    if signals.payment_status != Order.PaymentStatus.PAID.value:
        base += 15
    if signals.order_amount > HIGH_VALUE_ORDER_THRESHOLD_INR:
        base += 10
    base += min(signals.days_since_order, 10)
    base -= min(signals.delivered_count * 5, 20)
    base += 15 * max(0, signals.failed_attempts_on_current_shipment)
    return max(0, min(100, base))


def compute_risk_tier(score: int) -> str:
    if score <= 39:
        return RtoRiskSnapshot.RiskTier.LOW.value
    if score <= 59:
        return RtoRiskSnapshot.RiskTier.MEDIUM.value
    if score <= 79:
        return RtoRiskSnapshot.RiskTier.HIGH.value
    return RtoRiskSnapshot.RiskTier.CRITICAL.value


_TIER_TO_RECOMMENDATION = {
    RtoRiskSnapshot.RiskTier.LOW.value: (
        RtoRiskSnapshot.RecommendationKind.MONITOR_ONLY.value
    ),
    RtoRiskSnapshot.RiskTier.MEDIUM.value: (
        RtoRiskSnapshot.RecommendationKind.SEND_CONFIRMATION_REMINDER.value
    ),
    RtoRiskSnapshot.RiskTier.HIGH.value: (
        RtoRiskSnapshot.RecommendationKind.SEND_PRE_DELIVERY_CALL_REQUEST.value
    ),
    RtoRiskSnapshot.RiskTier.CRITICAL.value: (
        RtoRiskSnapshot.RecommendationKind.ESCALATE_TO_TEAM_LEAD.value
    ),
}


def _build_risk_reasons(signals: Signals) -> list[str]:
    reasons: list[str] = []
    if signals.rto_count >= 1:
        reasons.append("high_rto_history")
    if signals.complaint_count_14d > 0:
        reasons.append("recent_complaint")
    if signals.payment_status != Order.PaymentStatus.PAID.value:
        reasons.append("cod_payment")
    if signals.order_amount > HIGH_VALUE_ORDER_THRESHOLD_INR:
        reasons.append("high_value_order")
    if signals.days_since_order > STALE_ORDER_DAYS:
        reasons.append("stale_order")
    if signals.failed_attempts_on_current_shipment >= 1:
        reasons.append("multiple_failed_attempts")
    return reasons


def choose_recommendation(snapshot: RtoRiskSnapshot) -> tuple[str, str]:
    """Return (kind, short factual rationale)."""
    kind = _TIER_TO_RECOMMENDATION.get(
        snapshot.risk_tier,
        RtoRiskSnapshot.RecommendationKind.MONITOR_ONLY.value,
    )
    reasons = ",".join(snapshot.risk_reasons) or "no_specific_risk"
    text = (
        f"Day {snapshot.days_since_order} post-order, "
        f"{snapshot.lifecycle_stage}, "
        f"tier={snapshot.risk_tier}, "
        f"reasons=[{reasons}]."
    )
    return kind, text


def build_snapshot(
    order: Order,
    signals: Signals,
    *,
    now: datetime | None = None,
    sandbox: bool = False,
) -> RtoRiskSnapshot:
    """Build an unsaved snapshot. The caller persists + links AgentRun."""
    now = now or timezone.now()
    score = compute_risk_score(signals)
    tier = compute_risk_tier(score)
    stage = compute_lifecycle_stage(order, signals)
    reasons = _build_risk_reasons(signals)
    snapshot = RtoRiskSnapshot(
        order=order,
        customer=_customer_for_order(order),
        risk_score=score,
        risk_tier=tier,
        lifecycle_stage=stage,
        days_since_order=signals.days_since_order,
        failed_delivery_attempts=signals.failed_attempts_on_current_shipment,
        risk_reasons=reasons,
        signals=signals.to_payload(),
        sandbox=sandbox,
    )
    kind, text = choose_recommendation(snapshot)
    snapshot.recommendation_kind = kind
    snapshot.recommendation_text = text
    return snapshot
