"""Phase 16I — dict serializers (camelCase out). No PII beyond safe display."""
from __future__ import annotations

from typing import Any

from .models import (
    AiActionWorkEvent,
    AiApprovedAction,
    AiApprovedActionEvent,
    AiCopilotReviewEvent,
    AiCopilotSuggestion,
    AiDirectorBriefingSnapshot,
    AiDirectorBriefingSnapshotEvent,
    AiWorkboardDepartmentMember,
)


def serialize_suggestion(s: AiCopilotSuggestion, *, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.pk,
        "suggestionType": s.suggestion_type,
        "sourceType": s.source_type,
        "sourceId": s.source_id,
        "title": s.title,
        "summary": s.summary,
        "recommendation": s.recommendation,
        "riskFlags": list(s.risk_flags or []),
        "confidenceScore": s.confidence_score,
        "aiMode": s.ai_mode,
        "status": s.status,
        "reviewerNote": s.reviewer_note,
        "providerCallMade": s.provider_call_made,
        "externalActionAllowed": s.external_action_allowed,
        "externalActionTaken": s.external_action_taken,
        "createdBy": s.created_by.username if s.created_by_id else None,
        "reviewedBy": s.reviewed_by.username if s.reviewed_by_id else None,
        "createdAt": s.created_at,
        "updatedAt": s.updated_at,
    }
    if detail:
        out["detail"] = dict(s.detail or {})
        out["events"] = [
            serialize_review_event(e)
            for e in s.events.all().order_by("-created_at")[:50]
        ]
    return out


def serialize_review_event(e: AiCopilotReviewEvent) -> dict[str, Any]:
    return {
        "id": e.pk,
        "suggestionId": e.suggestion_id,
        "action": e.action,
        "note": e.note,
        "actor": e.actor.username if e.actor_id else None,
        "createdAt": e.created_at,
    }


# ---------------------------------------------------------------------------
# Phase 16J — AI-Approved Internal Action Queue serializers
# ---------------------------------------------------------------------------


def serialize_action(a: AiApprovedAction, *, detail: bool = False, viewer=None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": a.pk,
        "sourceSuggestionId": a.source_suggestion_id,
        "actionType": a.action_type,
        "sourceType": a.source_type,
        "sourceId": a.source_id,
        "title": a.title,
        "description": a.description,
        "assignedTeam": a.assigned_team,
        "priority": a.priority,
        "status": a.status,
        "providerActionAttempted": a.provider_action_attempted,
        "providerActionTaken": a.provider_action_taken,
        "externalActionAllowed": a.external_action_allowed,
        "externalActionTaken": a.external_action_taken,
        "failureReason": a.failure_reason,
        "approvedBy": a.approved_by.username if a.approved_by_id else None,
        "appliedBy": a.applied_by.username if a.applied_by_id else None,
        "createdBy": a.created_by.username if a.created_by_id else None,
        "createdAt": a.created_at,
        "updatedAt": a.updated_at,
        "appliedAt": a.applied_at,
        # Phase 16K — department workboard / ownership / SLA
        "department": a.department,
        "workStatus": a.work_status,
        "assigneeUser": a.assignee_user.username if a.assignee_user_id else None,
        "dueAt": a.due_at,
        "slaStatus": _sla_status(a),
        "blockerReason": a.blocker_reason,
        "completedBy": a.completed_by.username if a.completed_by_id else None,
        "completedAt": a.completed_at,
        "lastActivityAt": a.last_activity_at,
    }
    if viewer is not None:
        # Phase 16L — safe per-action permission booleans for the frontend.
        from . import services

        out["permissions"] = services.action_permission_booleans(viewer, a)
    if detail:
        out["resultPayload"] = dict(a.result_payload or {})
        out["safetySnapshot"] = dict(a.safety_snapshot or {})
        out["events"] = [
            serialize_action_event(e)
            for e in a.events.all().order_by("-created_at")[:50]
        ]
        out["workEvents"] = [
            serialize_work_event(e)
            for e in a.work_events.all().order_by("-created_at")[:50]
        ]
    return out


def _sla_status(a: AiApprovedAction) -> str:
    from . import services

    return services.compute_sla_status(a)


# ---------------------------------------------------------------------------
# Phase 16L — department membership serializer
# ---------------------------------------------------------------------------


def serialize_department_member(m: AiWorkboardDepartmentMember) -> dict[str, Any]:
    return {
        "id": m.pk,
        "username": m.user.username if m.user_id else None,
        "userId": m.user_id,
        "department": m.department,
        "isActive": m.is_active,
        "canClaim": m.can_claim,
        "canWork": m.can_work,
        "canComplete": m.can_complete,
        "createdBy": m.created_by.username if m.created_by_id else None,
        "createdAt": m.created_at,
        "updatedAt": m.updated_at,
    }


def serialize_work_event(e: AiActionWorkEvent) -> dict[str, Any]:
    return {
        "id": e.pk,
        "actionId": e.action_id,
        "eventType": e.event_type,
        "note": e.note,
        "actor": e.actor.username if e.actor_id else None,
        "metadata": dict(e.metadata or {}),
        "createdAt": e.created_at,
    }


def serialize_action_event(e: AiApprovedActionEvent) -> dict[str, Any]:
    return {
        "id": e.pk,
        "actionId": e.action_id,
        "eventType": e.event_type,
        "note": e.note,
        "actor": e.actor.username if e.actor_id else None,
        "createdAt": e.created_at,
    }


# ---------------------------------------------------------------------------
# Phase 16O — Director Briefing Snapshot serializers
# ---------------------------------------------------------------------------


def serialize_briefing_snapshot_event(e: AiDirectorBriefingSnapshotEvent) -> dict[str, Any]:
    return {
        "id": e.pk,
        "snapshotId": e.snapshot_id,
        "eventType": e.event_type,
        "note": e.note,
        "actor": e.actor.username if e.actor_id else None,
        "metadata": dict(e.metadata or {}),
        "createdAt": e.created_at,
    }


def serialize_briefing_snapshot(s: AiDirectorBriefingSnapshot, *, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.pk,
        "title": s.title,
        "windowDays": s.window_days,
        "status": s.status,
        "aiMode": s.ai_mode,
        "readonly": s.readonly,
        "internalOnly": s.internal_only,
        "providerCallMade": s.provider_call_made,
        "externalActionTaken": s.external_action_taken,
        "liveAutonomousLocked": s.live_autonomous_locked,
        "directorNote": s.director_note,
        "createdBy": s.created_by.username if s.created_by_id else None,
        "acknowledgedBy": s.acknowledged_by.username if s.acknowledged_by_id else None,
        "acknowledgedAt": s.acknowledged_at,
        "createdAt": s.created_at,
        "updatedAt": s.updated_at,
        # Lightweight headline counts (always present for the list view).
        "attentionItems": dict(s.attention_items or {}),
    }
    if detail:
        out["executiveSummary"] = list(s.executive_summary or [])
        out["recommendations"] = list(s.recommendations or [])
        out["blockedLiveActions"] = list(s.blocked_live_actions or [])
        out["safetySnapshot"] = dict(s.safety_snapshot or {})
        out["briefingPayload"] = dict(s.briefing_payload or {})
        out["events"] = [
            serialize_briefing_snapshot_event(e)
            for e in s.events.all().order_by("-created_at")[:100]
        ]
    return out
