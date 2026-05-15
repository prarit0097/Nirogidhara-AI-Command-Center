"""Phase 9D — Data Analyst Agent V1 deterministic aggregation.

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

from apps.calls.models import Call
from apps.crm.models import Lead
from apps.orders.models import Order

from .models import DataAnalystSnapshot


AGENT_NAME = "data_analyst_v1"
MODEL_USED = "deterministic_v1"

WINDOW_DAYS = 30

# A confirmed-or-beyond order satisfies the funnel step "lead -> call ->
# confirmed". Anything past Confirmation Pending counts. Delivered /
# RTO / Cancelled are excluded for the "confirmed" step because they
# represent a separate funnel cohort, but DELIVERED additionally
# satisfies the next step's filter on its own.
CONFIRMED_OR_BEYOND_STAGES = (
    Order.Stage.CONFIRMED.value,
    Order.Stage.DISPATCHED.value,
    Order.Stage.OUT_FOR_DELIVERY.value,
    Order.Stage.DELIVERED.value,
)
DELIVERED_STAGES = (Order.Stage.DELIVERED.value,)

# Anomaly thresholds (deterministic V1).
CONVERSION_DROP_RATE_THRESHOLD = 0.10
CONVERSION_DROP_MIN_UPSTREAM = 5
GEO_SHIFT_TOP_STATE_SHARE = 0.70
GEO_SHIFT_TOP_STATE_MIN_COUNT = 10
DEAD_END_CALLS_RATE_THRESHOLD = 0.05

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class AnalystSignals:
    """Deterministic input bundle for snapshot construction."""

    snapshot_at: datetime
    lead_count_30d: int = 0
    call_count_30d: int = 0
    confirmed_order_count_30d: int = 0
    delivered_order_count_30d: int = 0
    reorder_count_30d: int = 0
    lead_to_call_rate: float = 0.0
    call_to_confirmed_rate: float = 0.0
    confirmed_to_delivered_rate: float = 0.0
    delivered_to_reorder_rate: float = 0.0
    top_states: list[dict[str, Any]] = field(default_factory=list)
    day_of_week_counts: dict[str, int] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    alert_text: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at.isoformat(),
            "lead_count_30d": self.lead_count_30d,
            "call_count_30d": self.call_count_30d,
            "confirmed_order_count_30d": self.confirmed_order_count_30d,
            "delivered_order_count_30d": self.delivered_order_count_30d,
            "reorder_count_30d": self.reorder_count_30d,
            "lead_to_call_rate": self.lead_to_call_rate,
            "call_to_confirmed_rate": self.call_to_confirmed_rate,
            "confirmed_to_delivered_rate": self.confirmed_to_delivered_rate,
            "delivered_to_reorder_rate": self.delivered_to_reorder_rate,
            "top_states": list(self.top_states),
            "day_of_week_counts": dict(self.day_of_week_counts),
            "alerts": list(self.alerts),
            "alert_text": self.alert_text,
        }


def _cutoff(now: datetime | None = None) -> datetime:
    return (now or timezone.now()) - timedelta(days=WINDOW_DAYS)


def compute_funnel_counts(
    *, now: datetime | None = None
) -> dict[str, int]:
    cutoff = _cutoff(now)
    lead_count = Lead.objects.filter(created_at__gte=cutoff).count()
    call_count = Call.objects.filter(created_at__gte=cutoff).count()
    confirmed = Order.objects.filter(
        created_at__gte=cutoff, stage__in=CONFIRMED_OR_BEYOND_STAGES
    ).count()
    delivered = Order.objects.filter(
        created_at__gte=cutoff, stage__in=DELIVERED_STAGES
    ).count()
    # An in-window order is a reorder unless it is the customer's
    # earliest-ever order. We enumerate phones with at least one
    # in-window order, look up each phone's earliest order overall,
    # and:
    #   - if the earliest order falls inside the window, that one
    #     order is the customer's first ever and is NOT a reorder
    #     (other in-window orders are);
    #   - otherwise every in-window order for that phone is a reorder.
    in_window_phones = set(
        Order.objects.filter(created_at__gte=cutoff).values_list(
            "phone", flat=True
        )
    )
    reorder = 0
    for phone in in_window_phones:
        in_window = Order.objects.filter(
            phone=phone, created_at__gte=cutoff
        ).count()
        earliest = (
            Order.objects.filter(phone=phone).order_by("created_at").first()
        )
        if earliest is None:
            continue
        if earliest.created_at >= cutoff:
            reorder += max(0, in_window - 1)
        else:
            reorder += in_window
    return {
        "lead_count_30d": lead_count,
        "call_count_30d": call_count,
        "confirmed_order_count_30d": confirmed,
        "delivered_order_count_30d": delivered,
        "reorder_count_30d": reorder,
    }


def compute_conversion_rates(counts: dict[str, int]) -> dict[str, float]:
    def _rate(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    return {
        "lead_to_call_rate": _rate(
            counts.get("call_count_30d", 0),
            counts.get("lead_count_30d", 0),
        ),
        "call_to_confirmed_rate": _rate(
            counts.get("confirmed_order_count_30d", 0),
            counts.get("call_count_30d", 0),
        ),
        "confirmed_to_delivered_rate": _rate(
            counts.get("delivered_order_count_30d", 0),
            counts.get("confirmed_order_count_30d", 0),
        ),
        "delivered_to_reorder_rate": _rate(
            counts.get("reorder_count_30d", 0),
            counts.get("delivered_order_count_30d", 0),
        ),
    }


def compute_top_states_30d(
    *, n: int = 5, now: datetime | None = None
) -> list[dict[str, Any]]:
    cutoff = _cutoff(now)
    rows = (
        Order.objects.filter(created_at__gte=cutoff)
        .values("state")
        .annotate(order_count=Count("id"), revenue=Sum("amount"))
        .order_by("-order_count")[: max(0, n)]
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        state = row["state"] or ""
        if not state:
            continue
        revenue = row["revenue"] or 0
        output.append(
            {
                "state": state,
                "order_count": int(row["order_count"] or 0),
                "revenue": str(Decimal(str(revenue))),
            }
        )
    return output


def compute_day_of_week_counts_30d(
    *, now: datetime | None = None
) -> dict[str, int]:
    cutoff = _cutoff(now)
    buckets: dict[str, int] = {key: 0 for key in _WEEKDAY_KEYS}
    for created_at in Order.objects.filter(
        created_at__gte=cutoff
    ).values_list("created_at", flat=True):
        if created_at is None:
            continue
        buckets[_WEEKDAY_KEYS[created_at.weekday()]] += 1
    return buckets


def detect_anomalies(signals: AnalystSignals) -> list[str]:
    alerts: list[str] = []

    if signals.lead_count_30d == 0:
        alerts.append(DataAnalystSnapshot.Alert.LEAD_VOLUME_DROP.value)

    rate_drops = (
        (signals.lead_to_call_rate, signals.lead_count_30d),
        (signals.call_to_confirmed_rate, signals.call_count_30d),
        (
            signals.confirmed_to_delivered_rate,
            signals.confirmed_order_count_30d,
        ),
        (
            signals.delivered_to_reorder_rate,
            signals.delivered_order_count_30d,
        ),
    )
    for rate, upstream in rate_drops:
        if upstream > CONVERSION_DROP_MIN_UPSTREAM and rate < CONVERSION_DROP_RATE_THRESHOLD:
            alerts.append(DataAnalystSnapshot.Alert.CONVERSION_DROP.value)
            break

    if signals.top_states:
        top = signals.top_states[0]
        top_count = int(top.get("order_count") or 0)
        total = sum(
            int(row.get("order_count") or 0) for row in signals.top_states
        )
        if total > 0 and top_count > GEO_SHIFT_TOP_STATE_MIN_COUNT:
            share = top_count / total
            if share > GEO_SHIFT_TOP_STATE_SHARE:
                alerts.append(
                    DataAnalystSnapshot.Alert.GEOGRAPHIC_CONCENTRATION_SHIFT.value
                )

    if (
        signals.call_count_30d > 0
        and signals.call_to_confirmed_rate < DEAD_END_CALLS_RATE_THRESHOLD
    ):
        alerts.append(DataAnalystSnapshot.Alert.DEAD_END_CALLS.value)

    if not alerts:
        alerts.append(DataAnalystSnapshot.Alert.ALL_CLEAR.value)
    # Stable ordering, deduplicated.
    deduped: list[str] = []
    for code in alerts:
        if code not in deduped:
            deduped.append(code)
    return deduped


def _compose_alert_text(signals: AnalystSignals) -> str:
    top_state = signals.top_states[0]["state"] if signals.top_states else "—"
    parts = [
        f"leads {signals.lead_count_30d} -> calls {signals.call_count_30d}",
        f"confirmed {signals.confirmed_order_count_30d}",
        f"delivered {signals.delivered_order_count_30d}",
        f"reorders {signals.reorder_count_30d}",
        f"top_state={top_state}",
        f"alerts={','.join(signals.alerts) or 'none'}",
    ]
    return "; ".join(parts)


def compute_signals(now: datetime | None = None) -> AnalystSignals:
    now = now or timezone.now()
    counts = compute_funnel_counts(now=now)
    rates = compute_conversion_rates(counts)
    top_states = compute_top_states_30d(now=now)
    weekday_counts = compute_day_of_week_counts_30d(now=now)
    signals = AnalystSignals(
        snapshot_at=now,
        lead_count_30d=counts["lead_count_30d"],
        call_count_30d=counts["call_count_30d"],
        confirmed_order_count_30d=counts["confirmed_order_count_30d"],
        delivered_order_count_30d=counts["delivered_order_count_30d"],
        reorder_count_30d=counts["reorder_count_30d"],
        lead_to_call_rate=rates["lead_to_call_rate"],
        call_to_confirmed_rate=rates["call_to_confirmed_rate"],
        confirmed_to_delivered_rate=rates["confirmed_to_delivered_rate"],
        delivered_to_reorder_rate=rates["delivered_to_reorder_rate"],
        top_states=top_states,
        day_of_week_counts=weekday_counts,
    )
    signals.alerts = detect_anomalies(signals)
    signals.alert_text = _compose_alert_text(signals)
    return signals


def build_snapshot(
    signals: AnalystSignals, *, sandbox: bool = False
) -> DataAnalystSnapshot:
    return DataAnalystSnapshot(
        snapshot_at=signals.snapshot_at,
        lead_count_30d=signals.lead_count_30d,
        call_count_30d=signals.call_count_30d,
        confirmed_order_count_30d=signals.confirmed_order_count_30d,
        delivered_order_count_30d=signals.delivered_order_count_30d,
        reorder_count_30d=signals.reorder_count_30d,
        lead_to_call_rate=signals.lead_to_call_rate,
        call_to_confirmed_rate=signals.call_to_confirmed_rate,
        confirmed_to_delivered_rate=signals.confirmed_to_delivered_rate,
        delivered_to_reorder_rate=signals.delivered_to_reorder_rate,
        top_states=list(signals.top_states),
        day_of_week_counts=dict(signals.day_of_week_counts),
        alerts=list(signals.alerts),
        alert_text=signals.alert_text,
        sandbox=sandbox,
    )
