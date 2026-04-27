"""Ads agent runtime — Meta attribution + creative recommendations.

Reads only. Aggregates Meta-attributed leads grouped by campaign / ad / form
and surfaces the conversion / quality picture so the LLM can suggest
creative or budget changes. Never auto-launches anything; suggestions only.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count

from apps.ai_governance.models import AgentRun
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.crm.models import Lead


def _grouped(field: str) -> list[dict[str, Any]]:
    qs = (
        Lead.objects.exclude(**{f"{field}": ""})
        .values(field)
        .annotate(leads=Count("id"), avg_quality=Avg("quality_score"))
        .order_by("-leads")[:15]
    )
    return [
        {
            "key": row[field],
            "leads": row["leads"],
            "avg_quality_score": round(row["avg_quality"] or 0, 2),
        }
        for row in qs
    ]


def build_input_payload() -> dict[str, Any]:
    meta_total = Lead.objects.exclude(meta_leadgen_id="").count()
    by_campaign = _grouped("meta_campaign_id")
    by_ad = _grouped("meta_ad_id")
    by_form = _grouped("meta_form_id")
    by_source = _grouped("source_detail")
    return {
        "meta_total_leads": meta_total,
        "by_campaign": by_campaign,
        "by_ad": by_ad,
        "by_form": by_form,
        "by_source_detail": by_source,
    }


def run(triggered_by: str = "") -> AgentRun:
    return run_readonly_agent_analysis(
        agent="ads",
        input_payload=build_input_payload(),
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )


__all__ = ("build_input_payload", "run")
