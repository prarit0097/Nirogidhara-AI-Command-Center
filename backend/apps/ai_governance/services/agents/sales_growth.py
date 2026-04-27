"""Sales Growth agent runtime — conversion + discount + advance experiments.

Reads only. Aggregates call outcomes, order-stage distribution, advance-
payment ratios, and discount usage so the LLM can recommend experiments.
Never auto-applies a discount or runs a campaign; suggestions only — and
discounts above 20% require CEO AI / Prarit approval per Master Blueprint
§8 (the prompt's role block reminds the model of this).
"""
from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count, Sum

from apps.ai_governance.models import AgentRun
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.calls.models import Call
from apps.orders.models import Order
from apps.payments.models import Payment


def build_input_payload() -> dict[str, Any]:
    orders_by_stage = dict(
        Order.objects.values("stage")
        .annotate(n=Count("id"))
        .values_list("stage", "n")
    )
    avg_discount = (
        Order.objects.aggregate(avg=Avg("discount_pct"))["avg"] or 0
    )
    advance_ratio = {
        "with_advance": Order.objects.filter(advance_paid=True).count(),
        "without_advance": Order.objects.filter(advance_paid=False).count(),
    }
    discount_buckets = list(
        Order.objects.values("discount_pct")
        .annotate(n=Count("id"))
        .order_by("discount_pct")
    )

    call_status = dict(
        Call.objects.values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    call_sentiment = dict(
        Call.objects.values("sentiment")
        .annotate(n=Count("id"))
        .values_list("sentiment", "n")
    )

    payment_status = dict(
        Payment.objects.values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    advance_total = (
        Payment.objects.filter(type=Payment.Type.ADVANCE).aggregate(
            s=Sum("amount")
        )["s"]
        or 0
    )

    return {
        "orders_by_stage": orders_by_stage,
        "avg_discount_pct": round(avg_discount or 0, 2),
        "advance_ratio": advance_ratio,
        "discount_distribution": discount_buckets,
        "call_status": call_status,
        "call_sentiment": call_sentiment,
        "payment_status_breakdown": payment_status,
        "advance_collected_total": int(advance_total),
    }


def run(triggered_by: str = "") -> AgentRun:
    return run_readonly_agent_analysis(
        agent="sales_growth",
        input_payload=build_input_payload(),
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )


__all__ = ("build_input_payload", "run")
