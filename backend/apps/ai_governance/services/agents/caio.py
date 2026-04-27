"""CAIO runtime — audit / monitor / suggest. Never executes.

CAIO scans the AgentRun ledger, the Master Event Ledger, and the live
``CaioAudit`` table to surface drift, hallucination risk, low-confidence
calls, and compliance flags. The output is structured JSON the prompt
contract describes:

    {"summary": str, "recommendations": [...], "alerts": [...]}

Hard stop (Master Blueprint §26 #6.3 — "CAIO never executes"):
- This module reads only.
- ``run_readonly_agent_analysis`` enforces a second layer of refusal:
  any payload key in ``CAIO_FORBIDDEN_INTENTS`` (execute / apply /
  create_order / transition / ...) is rejected before the LLM is called.
- We never write CaioAudit rows from the LLM output. New CaioAudit rows
  are reserved for Phase 5 once the approval-matrix middleware exists.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count

from apps.ai_governance.models import AgentRun, CaioAudit
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.calls.models import Call
from apps.compliance.models import Claim


def build_input_payload() -> dict[str, Any]:
    """Slice the audit-relevant data CAIO needs."""
    recent_runs = list(
        AgentRun.objects.order_by("-created_at")[:25].values(
            "id",
            "agent",
            "status",
            "provider",
            "model",
            "latency_ms",
            "error_message",
            "created_at",
        )
    )
    status_breakdown = dict(
        AgentRun.objects.values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    failed_runs = list(
        AgentRun.objects.filter(status=AgentRun.Status.FAILED)
        .order_by("-created_at")[:10]
        .values("id", "agent", "error_message", "created_at")
    )

    audit_open = list(
        CaioAudit.objects.exclude(status="Resolved")
        .order_by("severity", "sort_order")[:20]
        .values("agent", "issue", "severity", "suggestion", "status")
    )

    handoff_calls = list(
        Call.objects.exclude(handoff_flags=[])
        .order_by("-updated_at")[:15]
        .values("id", "lead_id", "handoff_flags", "summary", "created_at")
    )

    claim_status = list(
        Claim.objects.values("product", "doctor", "compliance", "version")
    )

    return {
        "agent_runs_recent": [_iso(r) for r in recent_runs],
        "agent_runs_status_breakdown": status_breakdown,
        "agent_runs_failed_recent": [_iso(r) for r in failed_runs],
        "open_caio_audits": audit_open,
        "calls_with_handoff_flag": [_iso(r) for r in handoff_calls],
        "claim_vault_status": claim_status,
    }


def _iso(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce datetime values to ISO strings so they survive JSON encoding."""
    for key in ("created_at", "updated_at"):
        value = row.get(key)
        if value is not None and hasattr(value, "isoformat"):
            row[key] = value.isoformat()
    return row


def run(triggered_by: str = "") -> AgentRun:
    payload = build_input_payload()
    agent_run = run_readonly_agent_analysis(
        agent="caio",
        input_payload=payload,
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )
    if agent_run.status == AgentRun.Status.SUCCESS:
        write_event(
            kind="ai.caio_sweep.completed",
            text=f"CAIO audit sweep completed · run {agent_run.id}",
            tone=AuditEvent.Tone.INFO,
            payload={"run_id": agent_run.id},
        )
    return agent_run


__all__ = ("build_input_payload", "run")
