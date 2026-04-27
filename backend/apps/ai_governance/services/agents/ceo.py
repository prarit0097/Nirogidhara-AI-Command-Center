"""CEO AI runtime — daily briefing generator.

Pulls counts from leads / orders / payments / shipments / calls / Meta
attribution / rewards and asks the LLM to surface the top KPIs, recommended
actions, and alerts. The output is a structured JSON the prompt schema
documents:

    {"summary": str, "recommendations": [...], "alerts": [...]}

Side effects:
- One ``AgentRun`` row (always — even on skipped/failed).
- One ``ai.ceo_brief.generated`` AuditEvent on success.
- The ``CeoBriefing`` row is updated only when ``status == success`` AND
  the model returned at least a non-empty ``summary``. Skipped (provider
  disabled) and failed runs leave the existing briefing untouched.

This module never executes the recommendations — they are surfaced for
Prarit / CEO-AI approval middleware (Phase 5) to act on.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Q

from apps.ai_governance.models import AgentRun, CeoBriefing, CeoRecommendation
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.calls.models import Call
from apps.crm.models import Lead
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.rewards.models import RewardPenalty
from apps.shipments.models import Shipment


def build_input_payload() -> dict[str, Any]:
    """Aggregate the daily KPIs the CEO agent reasons over."""
    leads_total = Lead.objects.count()
    leads_meta = Lead.objects.exclude(meta_leadgen_id="").count()
    orders_total = Order.objects.count()
    orders_by_stage = dict(
        Order.objects.values("stage")
        .annotate(n=Count("id"))
        .values_list("stage", "n")
    )
    payments_total = Payment.objects.count()
    payments_paid = Payment.objects.filter(status=Payment.Status.PAID).count()
    payments_failed = Payment.objects.filter(
        status__in=[
            Payment.Status.FAILED,
            Payment.Status.CANCELLED,
            Payment.Status.EXPIRED,
        ]
    ).count()

    shipments_total = Shipment.objects.count()
    shipments_delivered = Shipment.objects.filter(status="Delivered").count()
    shipments_rto = Shipment.objects.filter(
        Q(status__icontains="RTO") | Q(risk_flag="RTO")
    ).count()

    calls_total = Call.objects.count()
    calls_failed = Call.objects.filter(status=Call.Status.FAILED).count()
    calls_with_handoff = Call.objects.exclude(handoff_flags=[]).count()

    top_risks = list(
        Order.objects.filter(rto_risk__in=["High", "Medium"])
        .order_by("-rto_score")[:5]
        .values("id", "rto_risk", "rto_score", "state", "city", "amount")
    )

    # ``net`` is a derived property on RewardPenalty, so we read columns and
    # compute it in Python rather than relying on values() to expose it.
    reward_top = []
    for row in RewardPenalty.objects.all()[:50]:
        reward_top.append(
            {
                "name": row.name,
                "reward": row.reward,
                "penalty": row.penalty,
                "net": row.net,
            }
        )
    reward_top.sort(key=lambda r: r["net"], reverse=True)
    reward_top = reward_top[:5]

    return {
        "kpi_window": "all-time",
        "leads": {"total": leads_total, "from_meta": leads_meta},
        "orders": {"total": orders_total, "by_stage": orders_by_stage},
        "payments": {
            "total": payments_total,
            "paid": payments_paid,
            "failed_or_cancelled": payments_failed,
        },
        "shipments": {
            "total": shipments_total,
            "delivered": shipments_delivered,
            "rto": shipments_rto,
        },
        "calls": {
            "total": calls_total,
            "failed": calls_failed,
            "with_handoff_flag": calls_with_handoff,
        },
        "top_rto_risks": top_risks,
        "reward_leaderboard": reward_top,
    }


def _maybe_update_briefing(run: AgentRun) -> None:
    """Replace the latest CeoBriefing row only when the run produced usable output."""
    if run.status != AgentRun.Status.SUCCESS:
        return
    output = run.output_payload or {}
    summary = (output.get("summary") or "").strip()
    if not summary:
        return

    headline = (output.get("headline") or summary[:240])[:240]
    alerts = output.get("alerts") or []
    recommendations = output.get("recommendations") or []
    if not isinstance(alerts, list):
        alerts = [str(alerts)]
    if not isinstance(recommendations, list):
        recommendations = []

    briefing = CeoBriefing.objects.create(
        date="Generated today",
        headline=headline,
        summary=summary,
        alerts=[str(a)[:240] for a in alerts][:10],
    )
    for index, rec in enumerate(recommendations[:10]):
        if not isinstance(rec, dict):
            continue
        CeoRecommendation.objects.create(
            briefing=briefing,
            id_str=str(rec.get("id") or f"rec-{index + 1}")[:32],
            title=str(rec.get("title") or "")[:240],
            reason=str(rec.get("reason") or "")[:1000],
            impact=str(rec.get("impact") or "")[:120],
            requires=str(rec.get("requires") or "")[:120],
            sort_order=index,
        )

    write_event(
        kind="ai.ceo_brief.generated",
        text=f"CEO daily briefing generated · run {run.id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "run_id": run.id,
            "briefing_id": briefing.id,
            "recommendations": len(recommendations[:10]),
        },
    )


def run(triggered_by: str = "") -> AgentRun:
    """Build payload → dispatch CEO agent → optionally refresh CeoBriefing."""
    payload = build_input_payload()
    agent_run = run_readonly_agent_analysis(
        agent="ceo",
        input_payload=payload,
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )
    _maybe_update_briefing(agent_run)
    return agent_run


__all__ = ("build_input_payload", "run")
