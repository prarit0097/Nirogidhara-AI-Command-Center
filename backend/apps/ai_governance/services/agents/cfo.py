"""CFO AI runtime — net delivered profit signals.

Reads only. Aggregates revenue, discount leakage, payment status, delivered
vs RTO ratios. The LLM returns recommendations only — never modifies any
financial state. Master Blueprint §10: reward / penalty is based on
**delivered profitable orders**, not orders punched.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count, Sum

from apps.ai_governance.models import AgentRun
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment


def build_input_payload() -> dict[str, Any]:
    revenue_total = Order.objects.aggregate(s=Sum("amount"))["s"] or 0
    avg_order_value = Order.objects.aggregate(a=Avg("amount"))["a"] or 0
    discount_leakage = (
        Order.objects.aggregate(s=Sum("discount_pct"))["s"] or 0
    )
    delivered_count = Order.objects.filter(stage=Order.Stage.DELIVERED).count()
    rto_count = Order.objects.filter(stage=Order.Stage.RTO).count()

    payment_breakdown = dict(
        Payment.objects.values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    revenue_by_gateway = dict(
        Payment.objects.filter(status=Payment.Status.PAID)
        .values("gateway")
        .annotate(s=Sum("amount"))
        .values_list("gateway", "s")
    )

    shipments_total = Shipment.objects.count()

    return {
        "revenue_total": int(revenue_total),
        "avg_order_value": round(avg_order_value or 0, 2),
        "total_discount_pct_punched": int(discount_leakage),
        "delivered_count": delivered_count,
        "rto_count": rto_count,
        "delivery_to_rto_ratio": (
            round(delivered_count / rto_count, 2) if rto_count else None
        ),
        "payment_status_breakdown": payment_breakdown,
        "revenue_paid_by_gateway": revenue_by_gateway,
        "shipments_total": shipments_total,
    }


def run(triggered_by: str = "") -> AgentRun:
    return run_readonly_agent_analysis(
        agent="cfo",
        input_payload=build_input_payload(),
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )


__all__ = ("build_input_payload", "run")
