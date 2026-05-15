"""Phase 9C — CFO Agent V1 deterministic aggregation.

All functions in this module are pure given the database state at
the moment of the call and emit no side effects. The Celery task
layer is responsible for persistence and audit emission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone

from apps.crm.models import Customer
from apps.orders.models import Order
from apps.payments.models import Payment

from .models import CfoFinancialSnapshot


AGENT_NAME = "cfo_v1"
MODEL_USED = "deterministic_v1"

ROLLING_WINDOWS_DAYS = (1, 7, 30)
RTO_SPIKE_RATE_THRESHOLD = Decimal("0.15")
PAID_PARTIAL_STATUSES = (
    Payment.Status.PAID.value,
    Payment.Status.PARTIAL.value,
)


@dataclass
class FinancialSignals:
    """Deterministic input bundle for snapshot construction."""

    snapshot_at: datetime
    revenue_24h: Decimal = Decimal("0")
    revenue_7d: Decimal = Decimal("0")
    revenue_30d: Decimal = Decimal("0")
    order_count_24h: int = 0
    order_count_7d: int = 0
    order_count_30d: int = 0
    paid_count: int = 0
    partial_count: int = 0
    pending_count: int = 0
    paid_amount: Decimal = Decimal("0")
    partial_amount: Decimal = Decimal("0")
    pending_amount: Decimal = Decimal("0")
    average_order_value: Decimal = Decimal("0")
    rto_count_30d: int = 0
    rto_loss_amount_30d: Decimal = Decimal("0")
    new_customer_count_30d: int = 0
    returning_customer_count_30d: int = 0
    alerts: list[str] = field(default_factory=list)
    alert_text: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at.isoformat(),
            "revenue_24h": str(self.revenue_24h),
            "revenue_7d": str(self.revenue_7d),
            "revenue_30d": str(self.revenue_30d),
            "order_count_24h": self.order_count_24h,
            "order_count_7d": self.order_count_7d,
            "order_count_30d": self.order_count_30d,
            "paid_count": self.paid_count,
            "partial_count": self.partial_count,
            "pending_count": self.pending_count,
            "paid_amount": str(self.paid_amount),
            "partial_amount": str(self.partial_amount),
            "pending_amount": str(self.pending_amount),
            "average_order_value": str(self.average_order_value),
            "rto_count_30d": self.rto_count_30d,
            "rto_loss_amount_30d": str(self.rto_loss_amount_30d),
            "new_customer_count_30d": self.new_customer_count_30d,
            "returning_customer_count_30d": (
                self.returning_customer_count_30d
            ),
            "alerts": list(self.alerts),
            "alert_text": self.alert_text,
        }


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def compute_rolling_revenue(
    *, window_days: int, now: datetime | None = None
) -> Decimal:
    now = now or timezone.now()
    cutoff = now - timedelta(days=window_days)
    agg = (
        Payment.objects.filter(
            status=Payment.Status.PAID.value,
            created_at__gte=cutoff,
        )
        .aggregate(total=Sum("amount"))
    )
    return _to_decimal(agg.get("total"))


def compute_rolling_order_count(
    *, window_days: int, now: datetime | None = None
) -> int:
    now = now or timezone.now()
    cutoff = now - timedelta(days=window_days)
    return Order.objects.filter(created_at__gte=cutoff).count()


def compute_payment_breakdown(
    *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or timezone.now()
    cutoff = now - timedelta(days=30)
    rows = (
        Payment.objects.filter(created_at__gte=cutoff)
        .values("status")
        .annotate(count=Count("id"), amount=Sum("amount"))
    )
    breakdown = {
        "paid_count": 0,
        "partial_count": 0,
        "pending_count": 0,
        "paid_amount": Decimal("0"),
        "partial_amount": Decimal("0"),
        "pending_amount": Decimal("0"),
    }
    status_to_key = {
        Payment.Status.PAID.value: "paid",
        Payment.Status.PARTIAL.value: "partial",
        Payment.Status.PENDING.value: "pending",
    }
    for row in rows:
        key = status_to_key.get(row["status"])
        if key is None:
            continue
        breakdown[f"{key}_count"] = int(row["count"] or 0)
        breakdown[f"{key}_amount"] = _to_decimal(row["amount"])
    return breakdown


def compute_aov_30d(*, now: datetime | None = None) -> Decimal:
    now = now or timezone.now()
    cutoff = now - timedelta(days=30)
    agg = (
        Order.objects.filter(created_at__gte=cutoff)
        .aggregate(total=Sum("amount"), count=Count("id"))
    )
    total = _to_decimal(agg.get("total"))
    count = int(agg.get("count") or 0)
    if count == 0:
        return Decimal("0")
    return (total / count).quantize(Decimal("0.01"))


def compute_rto_impact_30d(
    *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or timezone.now()
    cutoff = now - timedelta(days=30)
    agg = (
        Order.objects.filter(
            stage=Order.Stage.RTO.value, created_at__gte=cutoff
        )
        .aggregate(count=Count("id"), amount=Sum("amount"))
    )
    return {
        "rto_count_30d": int(agg.get("count") or 0),
        "rto_loss_amount_30d": _to_decimal(agg.get("amount")),
    }


def compute_customer_mix_30d(
    *, now: datetime | None = None
) -> dict[str, int]:
    """Bucket customers with at least one order in the last 30 days.

    ``new`` = customer's *first* Delivered/in-flight order falls in the
    30-day window. ``returning`` = customer had at least one order
    *before* the window AND at least one order in the window.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=30)
    in_window_phones = set(
        Order.objects.filter(created_at__gte=cutoff).values_list(
            "phone", flat=True
        )
    )
    if not in_window_phones:
        return {"new_customer_count_30d": 0, "returning_customer_count_30d": 0}
    pre_window_phones = set(
        Order.objects.filter(
            phone__in=in_window_phones, created_at__lt=cutoff
        ).values_list("phone", flat=True)
    )
    returning = in_window_phones & pre_window_phones
    new = in_window_phones - returning
    # Only count phones that also have a Customer record. Lead-only
    # orders without a Customer row are ignored to avoid double-counting
    # CRM data quality issues.
    customer_phones = set(
        Customer.objects.filter(phone__in=in_window_phones).values_list(
            "phone", flat=True
        )
    )
    return {
        "new_customer_count_30d": len(new & customer_phones),
        "returning_customer_count_30d": len(returning & customer_phones),
    }


def detect_anomalies(signals: FinancialSignals) -> list[str]:
    alerts: list[str] = []
    seven_day_avg = signals.revenue_7d / Decimal("7") if signals.revenue_7d else Decimal("0")
    if seven_day_avg > 0 and signals.revenue_24h < (
        seven_day_avg * Decimal("0.5")
    ):
        alerts.append(CfoFinancialSnapshot.Alert.REVENUE_DROP_24H.value)
    if signals.order_count_30d > 0:
        rto_rate = Decimal(signals.rto_count_30d) / Decimal(
            signals.order_count_30d
        )
        if rto_rate > RTO_SPIKE_RATE_THRESHOLD:
            alerts.append(CfoFinancialSnapshot.Alert.RTO_SPIKE.value)
    if signals.pending_count > signals.paid_count:
        alerts.append(
            CfoFinancialSnapshot.Alert.HIGH_PENDING_PAYMENTS.value
        )
    if signals.order_count_24h == 0 and signals.order_count_7d > 0:
        alerts.append(CfoFinancialSnapshot.Alert.LOW_ORDER_VOLUME.value)
    if not alerts:
        alerts.append(CfoFinancialSnapshot.Alert.ALL_CLEAR.value)
    return alerts


def _compose_alert_text(signals: FinancialSignals) -> str:
    parts = [
        f"24h revenue ₹{signals.revenue_24h}",
        f"30d revenue ₹{signals.revenue_30d}",
        f"30d orders {signals.order_count_30d}",
        f"AOV ₹{signals.average_order_value}",
        f"RTO {signals.rto_count_30d} (₹{signals.rto_loss_amount_30d})",
        f"new {signals.new_customer_count_30d} / returning "
        f"{signals.returning_customer_count_30d}",
        f"alerts={','.join(signals.alerts) or 'none'}",
    ]
    return "; ".join(parts)


def compute_signals(now: datetime | None = None) -> FinancialSignals:
    now = now or timezone.now()
    breakdown = compute_payment_breakdown(now=now)
    rto = compute_rto_impact_30d(now=now)
    mix = compute_customer_mix_30d(now=now)
    signals = FinancialSignals(
        snapshot_at=now,
        revenue_24h=compute_rolling_revenue(window_days=1, now=now),
        revenue_7d=compute_rolling_revenue(window_days=7, now=now),
        revenue_30d=compute_rolling_revenue(window_days=30, now=now),
        order_count_24h=compute_rolling_order_count(
            window_days=1, now=now
        ),
        order_count_7d=compute_rolling_order_count(
            window_days=7, now=now
        ),
        order_count_30d=compute_rolling_order_count(
            window_days=30, now=now
        ),
        paid_count=breakdown["paid_count"],
        partial_count=breakdown["partial_count"],
        pending_count=breakdown["pending_count"],
        paid_amount=breakdown["paid_amount"],
        partial_amount=breakdown["partial_amount"],
        pending_amount=breakdown["pending_amount"],
        average_order_value=compute_aov_30d(now=now),
        rto_count_30d=rto["rto_count_30d"],
        rto_loss_amount_30d=rto["rto_loss_amount_30d"],
        new_customer_count_30d=mix["new_customer_count_30d"],
        returning_customer_count_30d=mix["returning_customer_count_30d"],
    )
    signals.alerts = detect_anomalies(signals)
    signals.alert_text = _compose_alert_text(signals)
    return signals


def build_snapshot(
    signals: FinancialSignals, *, sandbox: bool = False
) -> CfoFinancialSnapshot:
    return CfoFinancialSnapshot(
        snapshot_at=signals.snapshot_at,
        revenue_24h=signals.revenue_24h,
        revenue_7d=signals.revenue_7d,
        revenue_30d=signals.revenue_30d,
        order_count_24h=signals.order_count_24h,
        order_count_7d=signals.order_count_7d,
        order_count_30d=signals.order_count_30d,
        paid_count=signals.paid_count,
        partial_count=signals.partial_count,
        pending_count=signals.pending_count,
        paid_amount=signals.paid_amount,
        partial_amount=signals.partial_amount,
        pending_amount=signals.pending_amount,
        average_order_value=signals.average_order_value,
        rto_count_30d=signals.rto_count_30d,
        rto_loss_amount_30d=signals.rto_loss_amount_30d,
        new_customer_count_30d=signals.new_customer_count_30d,
        returning_customer_count_30d=signals.returning_customer_count_30d,
        alerts=list(signals.alerts),
        alert_text=signals.alert_text,
        sandbox=sandbox,
    )
