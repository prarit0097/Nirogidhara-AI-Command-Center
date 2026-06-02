"""Phase 16I — dict serializers (camelCase out). No PII beyond safe display."""
from __future__ import annotations

from typing import Any

from .models import AiCopilotReviewEvent, AiCopilotSuggestion


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
