"""Phase 16I — AI Copilot API.

All endpoints require authentication; generate + review require director/admin.
NOTHING here calls a live AI/LLM provider or takes an external action: a
suggestion is generated deterministically, sanitized, and stored for human
review. `provider_call_made` / `external_action_allowed` / `external_action_taken`
stay False on every suggestion.
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.signals import write_event

from . import services
from .models import (
    AiApprovedAction,
    AiCopilotSuggestion,
    AiWorkboardDepartmentMember,
)
from .permissions import AuthenticatedReadAdminWrite, IsDirectorAdmin
from .serializers import (
    serialize_action,
    serialize_department_member,
    serialize_review_event,
    serialize_suggestion,
)

_VALID_ACTION_TYPES = {c for c, _ in AiApprovedAction.ActionType.choices}
_VALID_ACTION_STATUSES = {c for c, _ in AiApprovedAction.Status.choices}
_VALID_DEPARTMENTS = {c for c, _ in AiApprovedAction.Department.choices if c}
_VALID_WORK_STATUSES = {c for c, _ in AiApprovedAction.WorkStatus.choices}

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


# ===========================================================================
# Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer
# ===========================================================================


def _resolve_user(raw):
    if not raw:
        return None
    try:
        from apps.accounts.models import User

        return User.objects.filter(pk=raw).first()
    except Exception:  # noqa: BLE001
        return None


def _parse_due_at(raw):
    if not raw:
        return None
    try:
        from django.utils.dateparse import parse_datetime

        return parse_datetime(str(raw))
    except Exception:  # noqa: BLE001
        return None


class AiWorkboardView(APIView):
    """``GET /api/v1/ai-copilot/workboard/`` — department action workboard."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        q = request.query_params
        limit = _parse_int(q.get("limit"), 200, lo=1, hi=500)
        rows = services.list_department_workboard(
            department=q.get("department") or "",
            work_status=q.get("workStatus") or "",
            priority=q.get("priority") or "",
            sla_status=q.get("slaStatus") or "",
            assignee=q.get("assignee") or "",
            search=q.get("search") or "",
            limit=limit,
        )
        return Response({
            "items": [serialize_action(a, viewer=request.user) for a in rows],
            "total": AiApprovedAction.objects.count(),
            "departments": sorted(_VALID_DEPARTMENTS),
            "workStatuses": sorted(_VALID_WORK_STATUSES),
            "myPermissions": services.get_user_work_permissions(request.user),
        })


class AiWorkboardSummaryView(APIView):
    """``GET /api/v1/ai-copilot/workboard/summary/`` — workboard counts."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        return Response(services.get_department_summary())


class AiWorkboardDirectorAttentionView(APIView):
    """``GET /api/v1/ai-copilot/workboard/director-attention/``."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        items = [
            {**serialize_action(a, viewer=request.user), "attentionReason": reason}
            for a, reason in services.get_director_attention_queue()
        ]
        return Response({"items": items, "total": len(items)})


# ===========================================================================
# Phase 16M — Workboard Analytics + SLA Throughput Dashboard
# ===========================================================================


class AiWorkboardAnalyticsView(APIView):
    """``GET /api/v1/ai-copilot/workboard/analytics/`` — read-only analytics.

    Derives summary / department / member / SLA / blocker / throughput
    analytics from the existing workboard data. GET-only; never mutates a row,
    never calls a provider, never takes an external action. POST/PATCH/DELETE
    are not implemented → DRF returns 405.
    """

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        window_days = _parse_int(
            request.query_params.get("windowDays"), 14, lo=1, hi=90
        )
        return Response(services.get_workboard_analytics(window_days=window_days))


# --- Phase 16L — My Work queue (any authenticated user) ---


class AiMyWorkView(APIView):
    """``GET /api/v1/ai-copilot/workboard/my/`` — the current user's own work."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = request.query_params
        limit = _parse_int(q.get("limit"), 200, lo=1, hi=500)
        rows = services.list_my_work(
            request.user, work_status=q.get("workStatus") or "", limit=limit
        )
        return Response({
            "items": [serialize_action(a, viewer=request.user) for a in rows],
            "total": len(rows),
            "myPermissions": services.get_user_work_permissions(request.user),
        })


class AiMyWorkSummaryView(APIView):
    """``GET /api/v1/ai-copilot/workboard/my/summary/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.get_my_work_summary(request.user))


class AiMyWorkPermissionsView(APIView):
    """``GET /api/v1/ai-copilot/workboard/my-permissions/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.get_user_work_permissions(request.user))


# --- Phase 16L — department membership management (Director/Admin only) ---


class AiDepartmentMembersView(APIView):
    """``GET`` list / ``POST`` create scoped department memberships."""

    permission_classes = [IsDirectorAdmin]

    def get(self, request):
        qs = AiWorkboardDepartmentMember.objects.select_related("user", "created_by")
        dept = request.query_params.get("department")
        if dept:
            qs = qs.filter(department=dept)
        active = request.query_params.get("active")
        if active in {"true", "false"}:
            qs = qs.filter(is_active=(active == "true"))
        qs = qs.order_by("-created_at")[: _parse_int(request.query_params.get("limit"), 200)]
        return Response({
            "items": [serialize_department_member(m) for m in qs],
            "departments": sorted(_VALID_DEPARTMENTS),
        })

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        target = _resolve_user(data.get("userId"))
        if target is None:
            return Response({"detail": "user_not_found", "field": "userId"}, status=400)
        department = str(data.get("department", "") or "")
        if department not in _VALID_DEPARTMENTS:
            return Response(
                {"detail": "invalid_department", "field": "department",
                 "allowed": sorted(_VALID_DEPARTMENTS)}, status=400,
            )
        try:
            member, created = services.create_department_membership(
                user=target, department=department, created_by=request.user,
                can_claim=bool(data.get("canClaim", True)),
                can_work=bool(data.get("canWork", True)),
                can_complete=bool(data.get("canComplete", True)),
            )
        except services.WorkPermissionError as exc:
            return Response({"detail": "membership_create_failed", "reason": str(exc)}, status=400)
        write_event(
            kind="ai_copilot.workboard.member_added",
            text=f"AI workboard membership #{member.pk} ({member.department})",
            payload={
                "member_id": member.pk, "department": member.department,
                "target_user": target.username, "created": created,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(serialize_department_member(member), status=201 if created else 200)


class _AiMemberStateBase(APIView):
    """Activate / deactivate a department membership (Director/Admin only)."""

    permission_classes = [IsDirectorAdmin]
    _active = True
    _kind = ""

    def post(self, request, pk: int):
        member = AiWorkboardDepartmentMember.objects.filter(pk=pk).first()
        if member is None:
            return Response({"detail": "not_found"}, status=404)
        if self._active:
            services.activate_department_membership(member)
        else:
            services.deactivate_department_membership(member)
        write_event(
            kind=self._kind,
            text=f"AI workboard membership #{member.pk} {'activated' if self._active else 'deactivated'}",
            payload={
                "member_id": member.pk, "department": member.department,
                "is_active": member.is_active, "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(serialize_department_member(member))


class AiDepartmentMemberActivateView(_AiMemberStateBase):
    _active = True
    _kind = "ai_copilot.workboard.member_activated"


class AiDepartmentMemberDeactivateView(_AiMemberStateBase):
    _active = False
    _kind = "ai_copilot.workboard.member_deactivated"


# --- Workboard transitions ---


class _AiWorkboardTransitionMixin:
    """Shared audit + response logic for workboard transitions."""

    _kind = ""

    def _finish(self, request, action):
        write_event(
            kind=self._kind,
            text=f"AI workboard action #{action.pk} → {action.work_status}",
            payload={
                "action_id": action.pk, "work_status": action.work_status,
                "department": action.department,
                "external_action_taken": False, "provider_action_taken": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        action.refresh_from_db()
        return Response(serialize_action(action, detail=True, viewer=request.user))


class _AiWorkboardTransitionBase(APIView, _AiWorkboardTransitionMixin):
    """Admin-only workboard transition base (assign / reassign)."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        a = AiApprovedAction.objects.filter(pk=pk).first()
        if a is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            self._run(a, data=data, user=request.user)
        except services.AiActionError as exc:
            return Response({"detail": "workboard_action_failed", "reason": str(exc)}, status=409)
        return self._finish(request, a)

    def _run(self, action, *, data, user):  # pragma: no cover - overridden
        raise NotImplementedError


class _AiWorkboardScopedTransitionBase(APIView, _AiWorkboardTransitionMixin):
    """Scoped transition base — any authenticated user, gated by service rules.

    Director/Admin pass through; a non-admin must be the assignee (or an active
    department member for ``claim``). The real authorization decision lives in
    ``services.can_user_work_action`` so the rule is unit-tested in one place.
    """

    permission_classes = [IsAuthenticated]
    _operation = ""

    def post(self, request, pk: int):
        a = AiApprovedAction.objects.filter(pk=pk).first()
        if a is None:
            return Response({"detail": "not_found"}, status=404)
        allowed, reason = services.can_user_work_action(request.user, a, self._operation)
        if not allowed:
            return Response({"detail": "work_permission_denied", "reason": reason}, status=403)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            self._run(a, data=data, user=request.user)
        except services.AiActionError as exc:
            return Response({"detail": "workboard_action_failed", "reason": str(exc)}, status=409)
        return self._finish(request, a)

    def _run(self, action, *, data, user):  # pragma: no cover - overridden
        raise NotImplementedError


class AiActionAssignView(_AiWorkboardTransitionBase):
    _kind = "ai_copilot.workboard.assigned"

    def _run(self, action, *, data, user):
        services.assign_action(
            action, department=str(data.get("department", "") or ""),
            assignee=_resolve_user(data.get("assigneeUserId")),
            due_at=_parse_due_at(data.get("dueAt")),
            actor=user, note=str(data.get("note", "") or ""),
        )


class AiActionReassignView(_AiWorkboardTransitionBase):
    _kind = "ai_copilot.workboard.reassigned"

    def _run(self, action, *, data, user):
        services.reassign_action(
            action, department=str(data.get("department", "") or ""),
            assignee=_resolve_user(data.get("assigneeUserId")),
            actor=user, note=str(data.get("note", "") or ""),
        )


class AiActionClaimView(_AiWorkboardScopedTransitionBase):
    _kind = "ai_copilot.workboard.claimed"
    _operation = "claim"

    def _run(self, action, *, data, user):
        services.claim_action(action, user=user, note=str(data.get("note", "") or ""))


class AiActionStartView(_AiWorkboardScopedTransitionBase):
    _kind = "ai_copilot.workboard.started"
    _operation = "start"

    def _run(self, action, *, data, user):
        services.start_action(action, actor=user, note=str(data.get("note", "") or ""))


class AiActionBlockView(_AiWorkboardScopedTransitionBase):
    _kind = "ai_copilot.workboard.blocked"
    _operation = "block"

    def _run(self, action, *, data, user):
        services.block_action(action, reason=str(data.get("reason", "") or ""), actor=user)


class AiActionUnblockView(_AiWorkboardScopedTransitionBase):
    _kind = "ai_copilot.workboard.unblocked"
    _operation = "unblock"

    def _run(self, action, *, data, user):
        services.unblock_action(action, actor=user, note=str(data.get("note", "") or ""))


class AiActionCompleteInternalView(_AiWorkboardScopedTransitionBase):
    _kind = "ai_copilot.workboard.completed_internal"
    _operation = "complete"

    def _run(self, action, *, data, user):
        services.complete_internal_action(action, actor=user, note=str(data.get("note", "") or ""))


class AiActionNotesView(_AiWorkboardScopedTransitionBase):
    _kind = "ai_copilot.workboard.note_added"
    _operation = "note"

    def _run(self, action, *, data, user):
        services.add_action_note(
            action, note=str(data.get("note", "") or ""),
            actor=user, director_review=bool(data.get("directorReview", False)),
        )
