"""Phase 11D — Learning Loop Gate V1 (Director-approved, human-reviewed).

V1 is a **paper trail** system. CAIO (Phase 11C) auto-creates
proposals from RED-severity findings. Director reviews via CLI,
approves or rejects, then implements the change manually outside the
platform and records the implementation note. The platform tracks
the full audit trail.

**Nothing is auto-applied.** `LearningProposal` rows never touch
`PromptVersion`, never trigger Vapi prompt updates, never modify any
agent's runtime configuration. Director is always the gate.

Phase 11D `LearningProposal` is DELIBERATELY separate from Phase 4C
`ApprovalRequest`:

- ``ApprovalRequest`` (ai_governance) handles AI-proposed business
  actions (WhatsApp sends, discounts, RTO actions) routed through
  the ``APPROVAL_MATRIX``. Auto-approval possible.
- ``LearningProposal`` (this) handles human-reviewed learning-change
  proposals (script edits, coaching, process fixes). Always requires
  Director approval; no auto-execute path.
"""
from __future__ import annotations

from django.db import models


class LearningProposal(models.Model):
    """One proposal per learning-change request. Director gates every transition."""

    class ProposalType(models.TextChoices):
        COMPLIANCE_REMEDIATION = (
            "compliance_remediation",
            "compliance_remediation",
        )
        SCRIPT_REVIEW = "script_review", "script_review"
        KNOWLEDGE_GAP = "knowledge_gap", "knowledge_gap"
        PROCESS_IMPROVEMENT = (
            "process_improvement",
            "process_improvement",
        )
        AGENT_COACHING = "agent_coaching", "agent_coaching"

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        APPROVED = "approved", "approved"
        REJECTED = "rejected", "rejected"
        IMPLEMENTED = "implemented", "implemented"
        CANCELLED = "cancelled", "cancelled"

    class ImpactScope(models.TextChoices):
        LOW = "low", "low"
        MEDIUM = "medium", "medium"
        HIGH = "high", "high"

    source_agent = models.CharField(max_length=80)
    proposal_type = models.CharField(
        max_length=40,
        choices=ProposalType.choices,
    )
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    impact_scope = models.CharField(
        max_length=8,
        choices=ImpactScope.choices,
        default=ImpactScope.MEDIUM,
    )

    # Evidence references — IDs and codes only, NEVER customer names/PII.
    evidence = models.JSONField(default=dict, blank=True)

    # INTERNAL ONLY. What Director should consider changing. NEVER
    # surfaced to customers.
    proposed_change_text = models.TextField()

    director_decision = models.CharField(
        max_length=12,
        choices=(
            ("pending", "pending"),
            ("approved", "approved"),
            ("rejected", "rejected"),
        ),
        default="pending",
    )
    director_note = models.TextField(blank=True, default="")
    reviewed_by = models.CharField(max_length=120, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    implementation_note = models.TextField(blank=True, default="")
    implemented_at = models.DateTimeField(null=True, blank=True)
    implemented_by = models.CharField(max_length=120, blank=True, default="")

    caio_snapshot = models.ForeignKey(
        "caio.CaioAuditSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="learning_proposals",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("status",), name="lp_status_idx"),
            models.Index(fields=("proposal_type",), name="lp_type_idx"),
            models.Index(
                fields=("-created_at",), name="lp_created_at_idx"
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"LearningProposal {self.pk} - {self.proposal_type} - {self.status}"
        )
