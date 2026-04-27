"""Compliance & Medical Safety agent runtime.

Reads only. Surfaces Claim Vault coverage gaps, recent handoff flags from
calls, and risky AI outputs the LLM should review. The prompt builder
(``apps.ai_governance.prompting``) attaches the full Claim Vault to the
prompt automatically because the compliance agent always needs vault
grounding — when the vault is empty the run fails closed with
``ClaimVaultMissing`` rather than dispatching a hallucinated reply.

This module never generates new medical claims. Approved claims live in
``apps.compliance.Claim`` only and require Doctor + Compliance human
reviewer sign-off.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count

from apps.ai_governance.models import AgentRun, CaioAudit
from apps.ai_governance.services import run_readonly_agent_analysis
from apps.calls.models import Call
from apps.compliance.models import Claim


def build_input_payload() -> dict[str, Any]:
    claims_summary = list(
        Claim.objects.values(
            "product", "doctor", "compliance", "version"
        )
    )
    pending_claims = list(
        Claim.objects.filter(compliance__icontains="pending")
        .values("product", "doctor", "compliance", "version")
    )

    handoff_breakdown: dict[str, int] = {}
    for call in Call.objects.exclude(handoff_flags=[])[:200]:
        for flag in call.handoff_flags or []:
            handoff_breakdown[flag] = handoff_breakdown.get(flag, 0) + 1

    audits_critical = list(
        CaioAudit.objects.filter(severity__in=["Critical", "High"]).values(
            "agent", "issue", "severity", "suggestion", "status"
        )
    )

    risky_failed_runs = list(
        AgentRun.objects.filter(status=AgentRun.Status.FAILED)
        .order_by("-created_at")[:10]
        .values("id", "agent", "error_message")
    )

    return {
        "claim_vault_coverage": claims_summary,
        "claims_pending_review": pending_claims,
        "handoff_flag_counts": handoff_breakdown,
        "critical_caio_audits": audits_critical,
        "recent_failed_runs": risky_failed_runs,
    }


def run(triggered_by: str = "") -> AgentRun:
    return run_readonly_agent_analysis(
        agent="compliance",
        input_payload=build_input_payload(),
        triggered_by=triggered_by or "scheduler",
        dry_run=True,
    )


__all__ = ("build_input_payload", "run")
