"""Phase 9E — Calling Team Leader Agent V1 read-only API."""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_governance.models import AgentRun

from .models import CallingTeamLeaderSnapshot


class _AdminPermission(BasePermission):
    """Admin / director / superuser only."""

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = getattr(user, "role", "") or ""
        return role.lower() in {"admin", "director", "owner"}


def _serialize_snapshot(snapshot: CallingTeamLeaderSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "snapshotAt": snapshot.snapshot_at,
        "callCount24h": snapshot.call_count_24h,
        "callCount7d": snapshot.call_count_7d,
        "callCount30d": snapshot.call_count_30d,
        "answeredCount30d": snapshot.answered_count_30d,
        "connectionRate30d": snapshot.connection_rate_30d,
        "avgDurationSeconds30d": snapshot.avg_duration_seconds_30d,
        "outcomeBreakdown": dict(snapshot.outcome_breakdown or {}),
        "agentBreakdown": list(snapshot.agent_breakdown or []),
        "transcriptBacklogCount": snapshot.transcript_backlog_count,
        "alerts": list(snapshot.alerts or []),
        "alertText": snapshot.alert_text,
        "agentRunId": snapshot.agent_run_id,
        "sandbox": snapshot.sandbox,
        "createdAt": snapshot.created_at,
        "updatedAt": snapshot.updated_at,
    }


def _parse_int(raw, default: int, *, lo: int = 1, hi: int = 200) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class CallingTeamLeaderSnapshotsListView(APIView):
    """``GET /api/v1/calling-team-leader/snapshots/?page=&page_size=``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        page = _parse_int(request.query_params.get("page"), 1, lo=1, hi=10_000)
        page_size = _parse_int(
            request.query_params.get("page_size"), 30, lo=1, hi=200
        )
        qs = CallingTeamLeaderSnapshot.objects.all().order_by("-snapshot_at")
        total = qs.count()
        offset = (page - 1) * page_size
        items = list(qs[offset : offset + page_size])
        return Response(
            {
                "items": [_serialize_snapshot(s) for s in items],
                "total": total,
                "page": page,
                "pageSize": page_size,
            }
        )


class CallingTeamLeaderSnapshotLatestView(APIView):
    """``GET /api/v1/calling-team-leader/snapshots/latest/``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        snapshot = (
            CallingTeamLeaderSnapshot.objects.order_by("-snapshot_at").first()
        )
        last_run = (
            AgentRun.objects.filter(agent=AgentRun.Agent.CALLING_TEAM_LEADER)
            .order_by("-created_at")
            .first()
        )
        return Response(
            {
                "agent": "calling_team_leader_v1",
                "snapshot": _serialize_snapshot(snapshot)
                if snapshot
                else None,
                "lastAgentRunAt": last_run.created_at if last_run else None,
                "lastAgentRunStatus": last_run.status if last_run else "",
            }
        )


class CallingTeamLeaderSnapshotDetailView(APIView):
    """``GET /api/v1/calling-team-leader/snapshots/<id>/``."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk: int):
        snapshot = CallingTeamLeaderSnapshot.objects.filter(pk=pk).first()
        if snapshot is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(_serialize_snapshot(snapshot))
