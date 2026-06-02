"""Phase 16I — AI Copilot API.

All endpoints require authentication; generate + review require director/admin.
NOTHING here calls a live AI/LLM provider or takes an external action: a
suggestion is generated deterministically, sanitized, and stored for human
review. `provider_call_made` / `external_action_allowed` / `external_action_taken`
stay False on every suggestion.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.signals import write_event

from . import services
from .models import AiApprovedAction, AiCopilotSuggestion
from .permissions import AuthenticatedReadAdminWrite
from .serializers import (
    serialize_action,
    serialize_review_event,
    serialize_suggestion,
)

_VALID_ACTION_TYPES = {c for c, _ in AiApprovedAction.ActionType.choices}
_VALID_ACTION_STATUSES = {c for c, _ in AiApprovedAction.Status.choices}

_VALID_TYPES = set(services.SUGGESTION_TYPES)
_VALID_SOURCE_TYPES = {c for c, _ in AiCopilotSuggestion.SourceType.choices}
_VALID_REVIEW_ACTIONS = {"approve", "reject", "comment", "apply_internal"}


def _parse_int(raw, default: int, *, lo: int = 1, hi: int = 200) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class AiCopilotStatusView(APIView):
    """``GET /api/v1/ai-copilot/status/`` — AI mode + safety status."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        return Response(services.get_ai_copilot_status())


class AiCopilotSuggestionsView(APIView):
    """``GET`` list suggestions / ``POST`` generate is on the /generate/ route."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        qs = AiCopilotSuggestion.objects.all().order_by("-created_at")
        s_type = request.query_params.get("type")
        if s_type:
            qs = qs.filter(suggestion_type=s_type)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        source_type = request.query_params.get("source")
        if source_type:
            qs = qs.filter(source_type=source_type)
        limit = _parse_int(request.query_params.get("limit"), 50, lo=1, hi=200)
        items = [serialize_suggestion(s) for s in qs[:limit]]
        return Response({"items": items, "total": qs.count()})


class AiCopilotGenerateView(APIView):
    """``POST /api/v1/ai-copilot/suggestions/generate/`` — director/admin."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        s_type = str(data.get("suggestionType", "") or "")
        if s_type not in _VALID_TYPES:
            return Response(
                {"detail": "invalid_suggestion_type", "field": "suggestionType",
                 "allowed": sorted(_VALID_TYPES)},
                status=400,
            )
        source_type = str(data.get("sourceType", "") or "manual")
        if source_type not in _VALID_SOURCE_TYPES:
            return Response(
                {"detail": "invalid_source_type", "field": "sourceType",
                 "allowed": sorted(_VALID_SOURCE_TYPES)},
                status=400,
            )
        source_id = str(data.get("sourceId", "") or "")
        text = str(data.get("text", "") or "")[:8000]

        try:
            suggestion = services.create_ai_suggestion(
                suggestion_type=s_type, source_type=source_type,
                source_id=source_id, text=text, created_by=request.user,
            )
        except ValueError as exc:
            return Response({"detail": "generation_failed", "reason": str(exc)}, status=400)

        write_event(
            kind="ai_copilot.suggestion.generated",
            text=f"AI copilot suggestion #{suggestion.pk} ({suggestion.suggestion_type}) generated",
            payload={
                "suggestion_id": suggestion.pk,
                "suggestion_type": suggestion.suggestion_type,
                "source_type": suggestion.source_type,
                "ai_mode": suggestion.ai_mode,
                "provider_call_made": False,
                "external_action_allowed": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(serialize_suggestion(suggestion, detail=True), status=201)


class AiCopilotSuggestionDetailView(APIView):
    """``GET /api/v1/ai-copilot/suggestions/<id>/`` — detail + events."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        s = AiCopilotSuggestion.objects.filter(pk=pk).first()
        if s is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(serialize_suggestion(s, detail=True))


class AiCopilotReviewView(APIView):
    """``POST /api/v1/ai-copilot/suggestions/<id>/review/`` — director/admin."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        s = AiCopilotSuggestion.objects.filter(pk=pk).first()
        if s is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        action = str(data.get("action", "") or "")
        if action not in _VALID_REVIEW_ACTIONS:
            return Response(
                {"detail": "invalid_action", "field": "action",
                 "allowed": sorted(_VALID_REVIEW_ACTIONS)},
                status=400,
            )
        try:
            services.review_ai_suggestion(
                s, action=action, note=str(data.get("note", "") or ""),
                reviewed_by=request.user,
            )
        except services.AiCopilotReviewError as exc:
            return Response({"detail": "review_failed", "reason": str(exc)}, status=400)

        write_event(
            kind="ai_copilot.suggestion.reviewed",
            text=f"AI copilot suggestion #{s.pk} reviewed: {action}",
            payload={
                "suggestion_id": s.pk, "action": action, "status": s.status,
                "external_action_taken": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        s.refresh_from_db()
        return Response(serialize_suggestion(s, detail=True))


# ===========================================================================
# Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge
# ===========================================================================


class AiActionQueueView(APIView):
    """``GET /api/v1/ai-copilot/actions/`` — list the internal action queue."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        status_filter = request.query_params.get("status") or ""
        action_type = request.query_params.get("type") or ""
        limit = _parse_int(request.query_params.get("limit"), 100, lo=1, hi=200)
        qs = services.list_ai_action_queue(
            status=status_filter, action_type=action_type, limit=limit
        )
        return Response({
            "items": [serialize_action(a) for a in qs],
            "total": AiApprovedAction.objects.count(),
        })


class AiActionFromSuggestionView(APIView):
    """``POST /api/v1/ai-copilot/actions/from-suggestion/`` — director/admin."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        suggestion = AiCopilotSuggestion.objects.filter(
            pk=data.get("suggestionId")
        ).first()
        if suggestion is None:
            return Response(
                {"detail": "suggestion_not_found", "field": "suggestionId"}, status=400
            )
        action_type = str(data.get("actionType", "") or "")
        if action_type not in _VALID_ACTION_TYPES:
            return Response(
                {"detail": "invalid_action_type", "field": "actionType",
                 "allowed": sorted(_VALID_ACTION_TYPES)},
                status=400,
            )
        try:
            action = services.create_action_from_approved_suggestion(
                suggestion=suggestion,
                action_type=action_type,
                title=str(data.get("title", "") or ""),
                description=str(data.get("description", "") or ""),
                assigned_team=str(data.get("assignedTeam", "") or ""),
                priority=str(data.get("priority", "") or "normal"),
                created_by=request.user,
            )
        except services.AiActionError as exc:
            reason = str(exc)
            status_code = 409 if reason.startswith("suggestion_not_approved") else 400
            return Response({"detail": "action_create_failed", "reason": reason}, status=status_code)

        write_event(
            kind="ai_copilot.action.created",
            text=f"AI internal action #{action.pk} ({action.action_type}) queued",
            payload={
                "action_id": action.pk, "action_type": action.action_type,
                "source_suggestion_id": suggestion.pk,
                "external_action_allowed": False, "provider_action_taken": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(serialize_action(action, detail=True), status=201)


class AiActionDetailView(APIView):
    """``GET /api/v1/ai-copilot/actions/<id>/`` — detail + events."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        a = AiApprovedAction.objects.filter(pk=pk).first()
        if a is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(serialize_action(a, detail=True))


class _AiActionTransitionBase(APIView):
    """Shared apply/reject/cancel handler base."""

    permission_classes = [AuthenticatedReadAdminWrite]
    _service = None
    _kind = ""

    def post(self, request, pk: int):
        a = AiApprovedAction.objects.filter(pk=pk).first()
        if a is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        note = str(data.get("note", "") or "")
        try:
            self._run(a, note=note, user=request.user)
        except services.AiActionError as exc:
            return Response({"detail": "action_failed", "reason": str(exc)}, status=409)
        write_event(
            kind=self._kind,
            text=f"AI internal action #{a.pk} → {a.status}",
            payload={
                "action_id": a.pk, "status": a.status,
                "external_action_taken": False, "provider_action_taken": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        a.refresh_from_db()
        return Response(serialize_action(a, detail=True))

    def _run(self, action, *, note, user):  # pragma: no cover - overridden
        raise NotImplementedError


class AiActionApplyView(_AiActionTransitionBase):
    """``POST .../actions/<id>/apply/`` — apply the internal action (DB-only)."""

    _kind = "ai_copilot.action.applied"

    def _run(self, action, *, note, user):
        services.apply_internal_action(action, applied_by=user, note=note)


class AiActionRejectView(_AiActionTransitionBase):
    """``POST .../actions/<id>/reject/``."""

    _kind = "ai_copilot.action.rejected"

    def _run(self, action, *, note, user):
        services.reject_internal_action(action, actor=user, note=note)


class AiActionCancelView(_AiActionTransitionBase):
    """``POST .../actions/<id>/cancel/``."""

    _kind = "ai_copilot.action.cancelled"

    def _run(self, action, *, note, user):
        services.cancel_internal_action(action, actor=user, note=note)


class AiActionSummaryView(APIView):
    """``GET /api/v1/ai-copilot/actions/summary/`` — queue status counts."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        return Response(services.get_ai_action_summary())
