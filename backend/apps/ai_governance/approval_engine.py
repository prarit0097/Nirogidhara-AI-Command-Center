"""Phase 4C — Approval Matrix Middleware enforcement.

Reads the policy table in :mod:`apps.ai_governance.approval_matrix` and
enforces it via :class:`ApprovalRequest` rows. Every business action
classified ``approval_required`` / ``director_override`` /
``human_escalation`` MUST flow through this module before a service
performs the write.

LOCKED Phase 4C decisions:
- This module is the single source of truth for "may this action proceed
  right now?". Views / services call :func:`enforce_or_queue` (or one of
  the typed helpers) instead of duplicating policy.
- The middleware NEVER silently executes complex business writes. When a
  policy demands approval / override / escalation, it persists an
  :class:`ApprovalRequest` and returns it to the caller. Execution is
  the caller's job — and only along an already-tested service path.
- :func:`approve_request` flips status to ``approved`` and writes an
  audit row. It does **not** execute the underlying business write
  itself (Phase 4D will wire safe execution paths action-by-action).
- CAIO can never request an executable approval — see
  :func:`request_approval_for_agent_run`.
- All decisions write an :class:`ApprovalDecisionLog` + a Master Event
  Ledger ``ai.approval.*`` audit row.

Compliance hard stop (Master Blueprint §26):
- The Approved Claim Vault check still runs at the AgentRun layer; this
  module never lets a ``failed`` / ``skipped`` AgentRun be promoted.
- CAIO is hard-stopped at the AgentRun layer too — the engine refuses
  CAIO promotions explicitly as belt-and-braces.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .approval_matrix import APPROVAL_MATRIX, lookup_action
from .models import AgentRun, ApprovalDecisionLog, ApprovalRequest

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# Result dataclass returned by :func:`evaluate_action` / :func:`enforce_or_queue`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of an approval evaluation.

    ``allowed`` is the only field the caller needs to gate a business
    write. The rest is for telemetry, the audit ledger, and the
    eventual frontend display.
    """

    action: str
    mode: str
    approver: str
    status: str  # ``ApprovalRequest.Status``
    allowed: bool
    requires_human: bool
    reason: str
    policy: Mapping[str, Any]
    approval_request_id: str | None = None
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Policy lookups.
# ---------------------------------------------------------------------------


def get_policy_for_action(action: str) -> Mapping[str, Any] | None:
    """Look up a single matrix row by ``action``."""
    return lookup_action(action)


# ---------------------------------------------------------------------------
# Pure evaluation (read-only — no DB writes).
# ---------------------------------------------------------------------------


def evaluate_action(
    *,
    action: str,
    actor_role: str | None = None,
    actor_agent: str | None = None,
    payload: Mapping[str, Any] | None = None,
    target: Mapping[str, Any] | None = None,
) -> EvaluationResult:
    """Decide what would happen if this action were requested **right now**.

    Pure: never touches the DB, never creates an ApprovalRequest. Use
    this for the ``POST /api/ai/approvals/evaluate/`` preview endpoint
    and for views that want to surface "would this go through?" without
    persisting an audit trail yet.

    The semantics match :func:`enforce_or_queue` but no row is written.
    """
    role = (actor_role or "").lower().strip()
    payload_dict = dict(payload or {})
    target_dict = dict(target or {})

    policy = lookup_action(action)
    if policy is None:
        return EvaluationResult(
            action=action,
            mode="unknown",
            approver="unknown",
            status=ApprovalRequest.Status.BLOCKED,
            allowed=False,
            requires_human=False,
            reason=f"Unknown action '{action}'. Add it to the approval matrix first.",
            policy={},
            notes=("unknown_action",),
        )
    mode = str(policy["mode"])
    approver = str(policy["approver"])

    # CAIO can never become an executor. Belt-and-braces — the AgentRun
    # bridge already refuses CAIO, but we double-check here so any other
    # caller hits the same hard stop.
    if (actor_agent or "").lower() == "caio":
        return EvaluationResult(
            action=action,
            mode=mode,
            approver=approver,
            status=ApprovalRequest.Status.BLOCKED,
            allowed=False,
            requires_human=False,
            reason="CAIO never executes business actions (Master Blueprint §26 #5).",
            policy=policy,
            notes=("caio_no_execute",),
        )

    if mode == "auto":
        return EvaluationResult(
            action=action,
            mode=mode,
            approver=approver,
            status=ApprovalRequest.Status.AUTO_APPROVED,
            allowed=True,
            requires_human=False,
            reason="Auto-allowed by approval matrix.",
            policy=policy,
        )

    if mode == "auto_with_consent":
        if _has_consent(payload_dict, target_dict):
            return EvaluationResult(
                action=action,
                mode=mode,
                approver=approver,
                status=ApprovalRequest.Status.AUTO_APPROVED,
                allowed=True,
                requires_human=False,
                reason="Customer consent flag is True for the relevant channel.",
                policy=policy,
                notes=("consent_present",),
            )
        return EvaluationResult(
            action=action,
            mode=mode,
            approver=approver,
            status=ApprovalRequest.Status.PENDING,
            allowed=False,
            requires_human=True,
            reason="Customer consent missing — action queued for human review.",
            policy=policy,
            notes=("consent_missing",),
        )

    if mode == "approval_required":
        return EvaluationResult(
            action=action,
            mode=mode,
            approver=approver,
            status=ApprovalRequest.Status.PENDING,
            allowed=False,
            requires_human=True,
            reason=(
                f"Action requires {approver} approval. Caller role "
                f"'{role or 'unknown'}' is below approval authority."
            ),
            policy=policy,
            notes=("needs_approval",),
        )

    if mode == "director_override":
        director_override = bool(payload_dict.get("director_override"))
        override_reason = (payload_dict.get("override_reason") or "").strip()
        if role == "director" and director_override and override_reason:
            return EvaluationResult(
                action=action,
                mode=mode,
                approver=approver,
                status=ApprovalRequest.Status.AUTO_APPROVED,
                allowed=True,
                requires_human=False,
                reason="Director override applied with explicit reason.",
                policy=policy,
                notes=("director_override",),
            )
        return EvaluationResult(
            action=action,
            mode=mode,
            approver=approver,
            status=ApprovalRequest.Status.BLOCKED,
            allowed=False,
            requires_human=True,
            reason=(
                "Director override required: set actor_role='director', "
                "payload.director_override=True, and payload.override_reason."
            ),
            policy=policy,
            notes=("director_override_missing",),
        )

    if mode == "human_escalation":
        return EvaluationResult(
            action=action,
            mode=mode,
            approver=approver,
            status=ApprovalRequest.Status.ESCALATED,
            allowed=False,
            requires_human=True,
            reason="Action must be escalated to a human; no automated path.",
            policy=policy,
            notes=("human_escalation",),
        )

    # Unknown mode — fail closed.
    return EvaluationResult(
        action=action,
        mode=mode,
        approver=approver,
        status=ApprovalRequest.Status.BLOCKED,
        allowed=False,
        requires_human=False,
        reason=f"Unknown approval mode '{mode}' — refusing by default.",
        policy=policy,
        notes=("unknown_mode",),
    )


def _has_consent(
    payload: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    if payload.get("customer_consent") is True:
        return True
    if isinstance(target, Mapping):
        consent = target.get("consent")
        if isinstance(consent, Mapping):
            for value in consent.values():
                if value is True:
                    return True
    return False


# ---------------------------------------------------------------------------
# Persistent operations (DB writes + audit).
# ---------------------------------------------------------------------------


@transaction.atomic
def create_approval_request(
    *,
    action: str,
    payload: Mapping[str, Any] | None = None,
    actor_role: str | None = None,
    actor_agent: str | None = None,
    target: Mapping[str, Any] | None = None,
    reason: str | None = None,
    by_user: "User" | None = None,
    initial_status: str = ApprovalRequest.Status.PENDING,
) -> ApprovalRequest:
    """Persist an :class:`ApprovalRequest` row + write the request audit.

    Always snapshots the matrix row into ``policy_snapshot`` so later
    edits never rewrite the policy applied at the time of the request.
    """
    policy = lookup_action(action) or {}
    mode = str(policy.get("mode") or ApprovalRequest.Mode.APPROVAL_REQUIRED)
    approver = str(policy.get("approver") or "human")

    target_dict = dict(target or {})

    req = ApprovalRequest.objects.create(
        id=next_id("APR", ApprovalRequest, base=90000),
        action=action,
        mode=mode,
        approver=approver,
        status=initial_status,
        requested_by=by_user if by_user and getattr(by_user, "is_authenticated", False) else None,
        requested_by_agent=(actor_agent or "").lower(),
        target_app=str(target_dict.get("app") or ""),
        target_model=str(target_dict.get("model") or ""),
        target_object_id=str(target_dict.get("id") or ""),
        proposed_payload=dict(payload or {}),
        policy_snapshot=dict(policy),
        reason=reason or "",
        metadata={"actor_role": (actor_role or "").lower()},
    )

    ApprovalDecisionLog.objects.create(
        approval_request=req,
        old_status="",
        new_status=initial_status,
        decided_by=by_user if by_user and getattr(by_user, "is_authenticated", False) else None,
        note=reason or "",
        metadata={"event": "created", "actor_role": (actor_role or "").lower()},
    )

    audit_kind = {
        ApprovalRequest.Status.PENDING: "ai.approval.requested",
        ApprovalRequest.Status.AUTO_APPROVED: "ai.approval.auto_approved",
        ApprovalRequest.Status.BLOCKED: "ai.approval.blocked",
        ApprovalRequest.Status.ESCALATED: "ai.approval.escalated",
    }.get(initial_status, "ai.approval.requested")

    audit_tone = (
        AuditEvent.Tone.SUCCESS
        if initial_status == ApprovalRequest.Status.AUTO_APPROVED
        else AuditEvent.Tone.DANGER
        if initial_status == ApprovalRequest.Status.BLOCKED
        else AuditEvent.Tone.WARNING
        if initial_status == ApprovalRequest.Status.ESCALATED
        else AuditEvent.Tone.INFO
    )

    write_event(
        kind=audit_kind,
        text=(
            f"Approval {req.id} · {action} · mode={mode} · status={initial_status}"
        ),
        tone=audit_tone,
        payload={
            "approval_id": req.id,
            "action": action,
            "mode": mode,
            "approver": approver,
            "actor_role": (actor_role or "").lower(),
            "actor_agent": (actor_agent or "").lower(),
            "target": target_dict,
        },
    )
    return req


@transaction.atomic
def mark_auto_approved(
    *,
    action: str,
    payload: Mapping[str, Any] | None = None,
    actor_role: str | None = None,
    actor_agent: str | None = None,
    target: Mapping[str, Any] | None = None,
    by_user: "User" | None = None,
) -> ApprovalRequest:
    """Persist an already-approved ``auto`` row (audit trail only)."""
    return create_approval_request(
        action=action,
        payload=payload,
        actor_role=actor_role,
        actor_agent=actor_agent,
        target=target,
        reason="auto-approved by approval matrix",
        by_user=by_user,
        initial_status=ApprovalRequest.Status.AUTO_APPROVED,
    )


@transaction.atomic
def enforce_or_queue(
    *,
    action: str,
    payload: Mapping[str, Any] | None = None,
    actor_role: str | None = None,
    actor_agent: str | None = None,
    target: Mapping[str, Any] | None = None,
    reason: str | None = None,
    by_user: "User" | None = None,
) -> EvaluationResult:
    """Evaluate + persist. Returns an :class:`EvaluationResult` whose
    ``allowed`` field tells the caller whether to proceed *now*.

    If ``allowed`` is False, the caller MUST stop the business write —
    the engine has already persisted an :class:`ApprovalRequest` for the
    operator queue.
    """
    base = evaluate_action(
        action=action,
        actor_role=actor_role,
        actor_agent=actor_agent,
        payload=payload,
        target=target,
    )

    # Auto path → still log it so the queue shows what flowed through.
    if base.allowed and base.status == ApprovalRequest.Status.AUTO_APPROVED:
        req = mark_auto_approved(
            action=action,
            payload=payload,
            actor_role=actor_role,
            actor_agent=actor_agent,
            target=target,
            by_user=by_user,
        )
        return EvaluationResult(
            action=base.action,
            mode=base.mode,
            approver=base.approver,
            status=base.status,
            allowed=True,
            requires_human=False,
            reason=base.reason,
            policy=base.policy,
            approval_request_id=req.id,
            notes=base.notes,
        )

    # Anything else → queue with the right status (pending / blocked /
    # escalated) so the operator UI can show / decide.
    queued_status = (
        ApprovalRequest.Status.PENDING
        if base.status == ApprovalRequest.Status.PENDING
        else ApprovalRequest.Status.ESCALATED
        if base.status == ApprovalRequest.Status.ESCALATED
        else ApprovalRequest.Status.BLOCKED
    )
    req = create_approval_request(
        action=action,
        payload=payload,
        actor_role=actor_role,
        actor_agent=actor_agent,
        target=target,
        reason=reason or base.reason,
        by_user=by_user,
        initial_status=queued_status,
    )
    return EvaluationResult(
        action=base.action,
        mode=base.mode,
        approver=base.approver,
        status=queued_status,
        allowed=False,
        requires_human=True,
        reason=base.reason,
        policy=base.policy,
        approval_request_id=req.id,
        notes=base.notes,
    )


@transaction.atomic
def approve_request(
    *,
    request_id: str,
    user: "User",
    note: str | None = None,
) -> ApprovalRequest:
    """Approve a pending / escalated request. Director-only when policy
    requires ``director_override``.

    This function only flips status to ``approved`` and writes audit
    rows. It does NOT execute the underlying business write — Phase 4D
    will add explicit execution paths action-by-action.
    """
    req = ApprovalRequest.objects.select_for_update().get(pk=request_id)
    role = (getattr(user, "role", "") or "").lower()

    if req.mode == ApprovalRequest.Mode.DIRECTOR_OVERRIDE and role != "director":
        raise PermissionError(
            "Only the director can approve a director_override request."
        )
    if req.status not in (
        ApprovalRequest.Status.PENDING,
        ApprovalRequest.Status.ESCALATED,
    ):
        raise ValueError(
            f"Cannot approve a request currently in status '{req.status}'."
        )

    old = req.status
    req.status = ApprovalRequest.Status.APPROVED
    req.decided_by = user
    req.decided_at = timezone.now()
    req.decision_note = note or req.decision_note
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

    ApprovalDecisionLog.objects.create(
        approval_request=req,
        old_status=old,
        new_status=req.status,
        decided_by=user,
        note=note or "",
        metadata={"event": "approved", "actor_role": role},
    )
    write_event(
        kind="ai.approval.approved",
        text=f"Approval {req.id} · {req.action} · approved by {user.username}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "approval_id": req.id,
            "action": req.action,
            "decided_by": user.username,
            "actor_role": role,
        },
    )
    return req


@transaction.atomic
def reject_request(
    *,
    request_id: str,
    user: "User",
    note: str | None = None,
) -> ApprovalRequest:
    """Reject a pending / escalated request."""
    req = ApprovalRequest.objects.select_for_update().get(pk=request_id)
    role = (getattr(user, "role", "") or "").lower()

    if req.status not in (
        ApprovalRequest.Status.PENDING,
        ApprovalRequest.Status.ESCALATED,
    ):
        raise ValueError(
            f"Cannot reject a request currently in status '{req.status}'."
        )

    old = req.status
    req.status = ApprovalRequest.Status.REJECTED
    req.decided_by = user
    req.decided_at = timezone.now()
    req.decision_note = note or req.decision_note
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

    ApprovalDecisionLog.objects.create(
        approval_request=req,
        old_status=old,
        new_status=req.status,
        decided_by=user,
        note=note or "",
        metadata={"event": "rejected", "actor_role": role},
    )
    write_event(
        kind="ai.approval.rejected",
        text=f"Approval {req.id} · {req.action} · rejected by {user.username}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "approval_id": req.id,
            "action": req.action,
            "decided_by": user.username,
            "actor_role": role,
        },
    )
    return req


# ---------------------------------------------------------------------------
# AgentRun → ApprovalRequest bridge.
# ---------------------------------------------------------------------------


CAIO_AGENT_TOKEN: str = "caio"


@transaction.atomic
def request_approval_for_agent_run(
    *,
    agent_run: AgentRun,
    by_user: "User" | None = None,
    reason: str | None = None,
) -> ApprovalRequest:
    """Convert a successful, non-CAIO :class:`AgentRun` into an
    :class:`ApprovalRequest`.

    The function refuses CAIO outright and refuses any AgentRun whose
    status is not ``success``. The AgentRun's ``output_payload`` must
    contain ``action`` (a known matrix key) and ``proposedPayload`` (or
    ``proposed_payload``); otherwise a ``ValueError`` is raised.

    The new ApprovalRequest links back via ``metadata['agent_run_id']``
    and writes a ``ai.agent_run.approval_requested`` audit row.
    """
    if agent_run.agent.lower() == CAIO_AGENT_TOKEN:
        raise PermissionError("CAIO AgentRun cannot be promoted to an executable approval.")
    if agent_run.status != AgentRun.Status.SUCCESS:
        raise ValueError(
            f"Cannot promote AgentRun {agent_run.id} (status={agent_run.status})."
        )

    output = dict(agent_run.output_payload or {})
    action = (
        output.get("action")
        or output.get("intent")
        or output.get("approval_action")
    )
    proposed_payload = (
        output.get("proposedPayload")
        or output.get("proposed_payload")
        or output.get("payload")
    )
    if not action or not proposed_payload:
        raise ValueError(
            "AgentRun output must contain 'action' and 'proposedPayload' to "
            "request approval."
        )
    policy = lookup_action(str(action))
    if policy is None:
        raise ValueError(
            f"AgentRun proposed action '{action}' is not in the approval matrix."
        )

    req = create_approval_request(
        action=str(action),
        payload=proposed_payload,
        actor_role=(getattr(by_user, "role", "") or "").lower(),
        actor_agent=agent_run.agent,
        target=output.get("target"),
        reason=reason or output.get("reason") or "",
        by_user=by_user,
        initial_status=ApprovalRequest.Status.PENDING,
    )
    req.metadata = {**req.metadata, "agent_run_id": agent_run.id}
    req.save(update_fields=["metadata"])

    write_event(
        kind="ai.agent_run.approval_requested",
        text=(
            f"AgentRun {agent_run.id} promoted to approval {req.id} · action={action}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "approval_id": req.id,
            "agent_run_id": agent_run.id,
            "agent": agent_run.agent,
            "action": str(action),
            "by": getattr(by_user, "username", "") or "",
        },
    )
    return req


__all__ = (
    "EvaluationResult",
    "approve_request",
    "create_approval_request",
    "enforce_or_queue",
    "evaluate_action",
    "get_policy_for_action",
    "mark_auto_approved",
    "reject_request",
    "request_approval_for_agent_run",
)
