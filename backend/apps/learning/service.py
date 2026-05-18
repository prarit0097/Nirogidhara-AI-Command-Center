"""Phase 11D — Learning Loop Gate V1 service module.

Pure functions that drive the LearningProposal lifecycle. Every
transition writes one ``AuditEvent``. **No auto-execution** — every
state change requires an explicit Director CLI call (or, for CAIO
auto-creation, the pending-duplicate guard).

Idempotency: a CAIO auto-create that matches an existing PENDING
proposal of the same ``(source_agent, proposal_type)`` pair returns
the existing row without creating a duplicate.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import LearningProposal


logger = logging.getLogger(__name__)


AUDIT_KIND_CREATED = "learning.proposal.created"
AUDIT_KIND_APPROVED = "learning.proposal.approved"
AUDIT_KIND_REJECTED = "learning.proposal.rejected"
AUDIT_KIND_IMPLEMENTED = "learning.proposal.implemented"
AUDIT_KIND_CANCELLED = "learning.proposal.cancelled"
AUDIT_KIND_SKIPPED_SANDBOX = "learning.proposal.skipped_sandbox"


class LearningProposalStateError(Exception):
    """Raised when a transition is attempted from an incompatible status."""


def _summary_payload(proposal: LearningProposal) -> dict[str, Any]:
    return {
        "phase": "11D",
        "proposal_id": proposal.pk,
        "proposal_type": proposal.proposal_type,
        "status": proposal.status,
        "source_agent": proposal.source_agent,
        "impact_scope": proposal.impact_scope,
        "title": proposal.title[:120],
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_proposal(
    *,
    source_agent: str,
    proposal_type: str,
    title: str,
    proposed_change_text: str,
    impact_scope: str = LearningProposal.ImpactScope.MEDIUM.value,
    evidence: dict[str, Any] | None = None,
    caio_snapshot=None,
) -> tuple[LearningProposal, bool]:
    """Idempotently create a LearningProposal.

    If a PENDING proposal with the same ``(source_agent, proposal_type)``
    already exists, return ``(existing, False)`` without creating a
    duplicate. Otherwise create a new row, write the
    ``learning.proposal.created`` audit event, and return
    ``(new, True)``.
    """
    source_agent = (source_agent or "").strip()
    proposed_change_text = (proposed_change_text or "").strip()
    if not source_agent:
        raise LearningProposalStateError("source_agent is required")
    if not proposed_change_text:
        raise LearningProposalStateError(
            "proposed_change_text cannot be blank"
        )
    if proposal_type not in LearningProposal.ProposalType.values:
        raise LearningProposalStateError(
            f"invalid proposal_type: {proposal_type!r}"
        )
    if impact_scope not in LearningProposal.ImpactScope.values:
        raise LearningProposalStateError(
            f"invalid impact_scope: {impact_scope!r}"
        )

    existing = (
        LearningProposal.objects.filter(
            source_agent=source_agent,
            proposal_type=proposal_type,
            status=LearningProposal.Status.PENDING.value,
        )
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return existing, False

    proposal = LearningProposal.objects.create(
        source_agent=source_agent,
        proposal_type=proposal_type,
        title=title[:200],
        proposed_change_text=proposed_change_text,
        impact_scope=impact_scope,
        evidence=dict(evidence or {}),
        caio_snapshot=caio_snapshot,
    )
    write_event(
        kind=AUDIT_KIND_CREATED,
        text=(
            f"Learning proposal {proposal.pk} created "
            f"({proposal.proposal_type}, impact={proposal.impact_scope})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            **_summary_payload(proposal),
            "caio_snapshot_id": proposal.caio_snapshot_id,
        },
    )
    return proposal, True


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _require_status(
    proposal: LearningProposal, expected: str, action: str
) -> None:
    if proposal.status != expected:
        raise LearningProposalStateError(
            f"cannot {action}: proposal {proposal.pk} is in status "
            f"'{proposal.status}', expected '{expected}'"
        )


def approve_proposal(
    *,
    proposal_id: int,
    operator_name: str,
    director_note: str = "",
) -> LearningProposal:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise LearningProposalStateError("operator_name is required")
    proposal = LearningProposal.objects.filter(pk=proposal_id).first()
    if proposal is None:
        raise LearningProposalStateError(
            f"learning proposal {proposal_id} not found"
        )
    _require_status(
        proposal, LearningProposal.Status.PENDING.value, "approve"
    )
    proposal.status = LearningProposal.Status.APPROVED.value
    proposal.director_decision = "approved"
    proposal.director_note = director_note or ""
    proposal.reviewed_by = operator_name[:120]
    proposal.reviewed_at = timezone.now()
    proposal.save(
        update_fields=[
            "status",
            "director_decision",
            "director_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            f"Learning proposal {proposal.pk} approved by {operator_name}."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            **_summary_payload(proposal),
            "reviewed_by": operator_name,
            "director_note": (director_note or "")[:240],
        },
    )
    return proposal


def reject_proposal(
    *,
    proposal_id: int,
    operator_name: str,
    director_note: str = "",
) -> LearningProposal:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise LearningProposalStateError("operator_name is required")
    proposal = LearningProposal.objects.filter(pk=proposal_id).first()
    if proposal is None:
        raise LearningProposalStateError(
            f"learning proposal {proposal_id} not found"
        )
    _require_status(
        proposal, LearningProposal.Status.PENDING.value, "reject"
    )
    proposal.status = LearningProposal.Status.REJECTED.value
    proposal.director_decision = "rejected"
    proposal.director_note = director_note or ""
    proposal.reviewed_by = operator_name[:120]
    proposal.reviewed_at = timezone.now()
    proposal.save(
        update_fields=[
            "status",
            "director_decision",
            "director_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=(
            f"Learning proposal {proposal.pk} rejected by {operator_name}."
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            **_summary_payload(proposal),
            "reviewed_by": operator_name,
            "director_note": (director_note or "")[:240],
        },
    )
    return proposal


def implement_proposal(
    *,
    proposal_id: int,
    operator_name: str,
    implementation_note: str,
) -> LearningProposal:
    """Record Director's manual implementation. NEVER auto-applies."""
    operator_name = (operator_name or "").strip()
    implementation_note = (implementation_note or "").strip()
    if not operator_name:
        raise LearningProposalStateError("operator_name is required")
    if not implementation_note:
        raise LearningProposalStateError(
            "implementation_note cannot be blank — Director must record "
            "what was actually done."
        )
    proposal = LearningProposal.objects.filter(pk=proposal_id).first()
    if proposal is None:
        raise LearningProposalStateError(
            f"learning proposal {proposal_id} not found"
        )
    _require_status(
        proposal, LearningProposal.Status.APPROVED.value, "implement"
    )
    proposal.status = LearningProposal.Status.IMPLEMENTED.value
    proposal.implementation_note = implementation_note
    proposal.implemented_at = timezone.now()
    proposal.implemented_by = operator_name[:120]
    proposal.save(
        update_fields=[
            "status",
            "implementation_note",
            "implemented_at",
            "implemented_by",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_KIND_IMPLEMENTED,
        text=(
            f"Learning proposal {proposal.pk} implemented by {operator_name}."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            **_summary_payload(proposal),
            "implemented_by": operator_name,
            "implementation_note_excerpt": implementation_note[:240],
        },
    )
    return proposal


def cancel_proposal(
    *,
    proposal_id: int,
    operator_name: str,
    reason: str = "",
) -> LearningProposal:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise LearningProposalStateError("operator_name is required")
    proposal = LearningProposal.objects.filter(pk=proposal_id).first()
    if proposal is None:
        raise LearningProposalStateError(
            f"learning proposal {proposal_id} not found"
        )
    if proposal.status not in {
        LearningProposal.Status.PENDING.value,
        LearningProposal.Status.APPROVED.value,
    }:
        raise LearningProposalStateError(
            f"cannot cancel: proposal {proposal.pk} is in status "
            f"'{proposal.status}'"
        )
    proposal.status = LearningProposal.Status.CANCELLED.value
    proposal.director_note = reason or proposal.director_note
    proposal.reviewed_by = operator_name[:120]
    proposal.reviewed_at = timezone.now()
    proposal.save(
        update_fields=[
            "status",
            "director_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_KIND_CANCELLED,
        text=(
            f"Learning proposal {proposal.pk} cancelled by {operator_name}."
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            **_summary_payload(proposal),
            "reviewed_by": operator_name,
            "reason": (reason or "")[:240],
        },
    )
    return proposal


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_pending_proposals() -> QuerySet[LearningProposal]:
    return LearningProposal.objects.filter(
        status=LearningProposal.Status.PENDING.value
    ).order_by("-created_at")


def get_proposals_by_status(status: str) -> QuerySet[LearningProposal]:
    return LearningProposal.objects.filter(status=status).order_by(
        "-created_at"
    )


def get_proposals_summary() -> dict[str, Any]:
    qs = LearningProposal.objects.all()
    counts = {choice.value: 0 for choice in LearningProposal.Status}
    high_impact_pending = 0
    for row in qs.values("status", "impact_scope"):
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        if (
            row["status"] == LearningProposal.Status.PENDING.value
            and row["impact_scope"]
            == LearningProposal.ImpactScope.HIGH.value
        ):
            high_impact_pending += 1
    return {
        "pending": counts[LearningProposal.Status.PENDING.value],
        "approved": counts[LearningProposal.Status.APPROVED.value],
        "rejected": counts[LearningProposal.Status.REJECTED.value],
        "implemented": counts[LearningProposal.Status.IMPLEMENTED.value],
        "cancelled": counts[LearningProposal.Status.CANCELLED.value],
        "high_impact_pending": high_impact_pending,
        "total": qs.count(),
    }


# ---------------------------------------------------------------------------
# CAIO integration — auto-create proposals from RED findings
# ---------------------------------------------------------------------------


def _has_compliance_violation(snapshot) -> bool:
    if int(getattr(snapshot, "compliance_risk_call_count", 0) or 0) > 0:
        return True
    flags = dict(getattr(snapshot, "agent_anomaly_flags", {}) or {})
    for codes in flags.values():
        if "compliance_violation" in (codes or []):
            return True
    return False


def create_proposals_from_audit(
    snapshot, *, sandbox: bool = False
) -> dict[str, Any]:
    """Auto-create LearningProposals from a CaioAuditSnapshot.

    Returns ``{"created_count": N, "reused_count": M, "skipped": bool,
    "proposals": [...]}``.

    Sandbox guard: when ``sandbox=True``, this function writes a
    ``learning.proposal.skipped_sandbox`` audit event and returns
    ``{"skipped": True, "created_count": 0, "reused_count": 0,
    "proposals": []}`` without creating any rows.
    """
    if sandbox:
        write_event(
            kind=AUDIT_KIND_SKIPPED_SANDBOX,
            text=(
                "Learning proposal creation skipped (sandbox mode "
                "active) — CAIO snapshot evaluated but no proposals "
                "written."
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phase": "11D",
                "caio_snapshot_id": getattr(snapshot, "pk", None),
                "severity": getattr(snapshot, "severity", None),
                "reason": "sandbox_mode",
            },
        )
        return {
            "skipped": True,
            "created_count": 0,
            "reused_count": 0,
            "proposals": [],
        }

    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []

    def _track(result: tuple[LearningProposal, bool]) -> None:
        proposal, was_new = result
        bucket = created if was_new else reused
        bucket.append(
            {
                "id": proposal.pk,
                "proposal_type": proposal.proposal_type,
                "impact_scope": proposal.impact_scope,
                "status": proposal.status,
            }
        )

    snapshot_id = getattr(snapshot, "pk", None)
    severity = getattr(snapshot, "severity", "")
    weak_learning = list(
        getattr(snapshot, "weak_learning_indicators", []) or []
    )
    risk_labels = list(
        getattr(snapshot, "compliance_risk_agent_labels", []) or []
    )

    # (a) Compliance violation → high-impact compliance remediation.
    if _has_compliance_violation(snapshot):
        evidence = {
            "caio_snapshot_id": snapshot_id,
            "severity": severity,
            "compliance_risk_call_count": int(
                getattr(snapshot, "compliance_risk_call_count", 0) or 0
            ),
            "compliance_risk_agent_labels": risk_labels[:10],
        }
        _track(
            create_proposal(
                source_agent="caio_v1",
                proposal_type=(
                    LearningProposal.ProposalType.COMPLIANCE_REMEDIATION.value
                ),
                title="Compliance violation detected in recent calls",
                impact_scope=LearningProposal.ImpactScope.HIGH.value,
                evidence=evidence,
                proposed_change_text=(
                    "Review call recordings flagged for forbidden phrases "
                    "(guarantee / cure / medicine / doctor / clinically "
                    "proven / 100% / fda). Provide coaching to flagged "
                    "agents. Update calling script to replace forbidden "
                    "language with approved Claim Vault phrases. Verify "
                    "agents understand which medical claims are NOT "
                    "permitted per Master Blueprint §26."
                ),
                caio_snapshot=snapshot,
            )
        )

    # (b) Declining call quality → script review.
    if "declining_call_quality" in weak_learning:
        _track(
            create_proposal(
                source_agent="caio_v1",
                proposal_type=(
                    LearningProposal.ProposalType.SCRIPT_REVIEW.value
                ),
                title="Call quality declining — script review recommended",
                impact_scope=LearningProposal.ImpactScope.MEDIUM.value,
                evidence={
                    "caio_snapshot_id": snapshot_id,
                    "severity": severity,
                    "call_quality_trend": getattr(
                        snapshot, "call_quality_trend", ""
                    ),
                },
                proposed_change_text=(
                    "Composite call quality score has dropped > 5% week-"
                    "over-week. Review the calling script for product "
                    "knowledge gaps, objection handling weakness, and "
                    "missing greetings/closings. Compare recent "
                    "Phase 11B raw_signals to identify which dimension "
                    "regressed most."
                ),
                caio_snapshot=snapshot,
            )
        )

    # (c) No recent calls → process review.
    if "no_recent_calls" in weak_learning:
        _track(
            create_proposal(
                source_agent="caio_v1",
                proposal_type=(
                    LearningProposal.ProposalType.PROCESS_IMPROVEMENT.value
                ),
                title="No calls made in last 7 days — calling process needs review",
                impact_scope=LearningProposal.ImpactScope.MEDIUM.value,
                evidence={
                    "caio_snapshot_id": snapshot_id,
                    "severity": severity,
                    "weak_learning": weak_learning,
                },
                proposed_change_text=(
                    "Phase 9E Calling Team Leader reports 0 calls in the "
                    "last 7 days. Verify: lead pipeline is feeding the "
                    "dialer, calling agents are staffed, Vapi assistant "
                    "is healthy, no upstream process gate has paused "
                    "outbound. If intentional pause, mark this proposal "
                    "as cancelled with reason."
                ),
                caio_snapshot=snapshot,
            )
        )

    # (d) Zero agent utterances pattern → agent coaching.
    if "all_agent_utterances_missing" in weak_learning:
        _track(
            create_proposal(
                source_agent="caio_v1",
                proposal_type=(
                    LearningProposal.ProposalType.AGENT_COACHING.value
                ),
                title="Agent(s) with zero utterances detected in > 50% of scored calls",
                impact_scope=LearningProposal.ImpactScope.MEDIUM.value,
                evidence={
                    "caio_snapshot_id": snapshot_id,
                    "severity": severity,
                    "weak_learning": weak_learning,
                },
                proposed_change_text=(
                    "More than 50% of scored calls in the last 30 days "
                    "had zero agent utterances. Either the transcript "
                    "speaker classification is wrong, OR agents are "
                    "silent on calls. Audit raw transcripts for several "
                    "affected calls, verify the agent-side `who` "
                    "classifier in Phase 11B matches the Vapi role "
                    "values, and coach any silent agents."
                ),
                caio_snapshot=snapshot,
            )
        )

    return {
        "skipped": False,
        "created_count": len(created),
        "reused_count": len(reused),
        "proposals": created + reused,
    }


__all__ = (
    "AUDIT_KIND_CREATED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_IMPLEMENTED",
    "AUDIT_KIND_CANCELLED",
    "AUDIT_KIND_SKIPPED_SANDBOX",
    "LearningProposalStateError",
    "create_proposal",
    "approve_proposal",
    "reject_proposal",
    "implement_proposal",
    "cancel_proposal",
    "get_pending_proposals",
    "get_proposals_by_status",
    "get_proposals_summary",
    "create_proposals_from_audit",
)
