"""RTO Prevention agent runtime — at-risk orders + rescue recommendations.

Reads only. Pulls high-risk orders, NDR / RTO shipments, and rescue-attempt
outcomes. The LLM suggests rescue actions (channel, timing, message
template) but never auto-cancels or auto-rescues — those flow through the
Phase 5 approval-matrix middleware.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Q

from apps.ai_governance.models import AgentRun
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.orders.models import Order
from apps.shipments.models import RescueAttempt, Shipment


def build_input_payload() -> dict[str, Any]:
    risky_orders = list(
        Order.objects.filter(rto_risk__in=["High", "Medium"])
        .order_by("-rto_score")[:20]
        .values(
            "id",
            "stage",
            "rto_risk",
            "rto_score",
            "state",
            "city",
            "amount",
            "advance_paid",
            "rescue_status",
        )
    )
    risk_summary = dict(
        Order.objects.values("rto_risk")
        .annotate(n=Count("id"))
        .values_list("rto_risk", "n")
    )

    risky_shipments = list(
        Shipment.objects.filter(
            Q(status__icontains="RTO")
            | Q(status__icontains="NDR")
            | Q(risk_flag__in=["NDR", "RTO"])
        )
        .order_by("-updated_at")[:20]
        .values("awb", "order_id", "status", "risk_flag", "city", "state")
    )

    rescue_outcomes = dict(
        RescueAttempt.objects.values("outcome")
        .annotate(n=Count("id"))
        .values_list("outcome", "n")
    )

    recent_rescues = list(
        RescueAttempt.objects.order_by("-attempted_at")[:15].values(
            "id", "order_id", "channel", "outcome", "notes"
        )
    )

    return {
        "risk_summary": risk_summary,
        "high_risk_orders": risky_orders,
        "risky_shipments": risky_shipments,
        "rescue_outcomes": rescue_outcomes,
        "recent_rescue_attempts": recent_rescues,
    }


def run(triggered_by: str = "") -> AgentRun:
    return run_readonly_agent_analysis(
        agent="rto",
        input_payload=build_input_payload(),
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )


__all__ = ("build_input_payload", "run")
