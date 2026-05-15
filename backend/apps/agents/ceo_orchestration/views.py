"""Phase 9F — CEO AI Orchestration V1 read-only API."""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_governance.models import AgentRun

from .models import CeoOrchestrationSnapshot


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


def _serialize_snapshot(snapshot: CeoOrchestrationSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "snapshotAt": snapshot.snapshot_at,
        "businessHealthScore": snapshot.business_health_score,
        "healthTier": snapshot.health_tier,
        "customerSuccessSnapshotId": snapshot.customer_success_snapshot_id,
        "rtoSnapshotId": snapshot.rto_snapshot_id,
        "cfoSnapshotId": snapshot.cfo_snapshot_id,
        "dataAnalystSnapshotId": snapshot.data_analyst_snapshot_id,
        "callingTeamLeaderSnapshotId": (
            snapshot.calling_team_leader_snapshot_id
        ),
        "crossCuttingAlerts": list(snapshot.cross_cutting_alerts or []),
        "top3Priorities": list(snapshot.top_3_priorities or []),
        "agentStatusSummary": dict(snapshot.agent_status_summary or {}),
        "briefingText": snapshot.briefing_text,
        "alerts": list(snapshot.alerts or []),
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


class CeoOrchestrationSnapshotsListView(APIView):
    """``GET /api/v1/ceo-orchestration/snapshots/?page=&page_size=``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        page = _parse_int(request.query_params.get("page"), 1, lo=1, hi=10_000)
        page_size = _parse_int(
            request.query_params.get("page_size"), 30, lo=1, hi=200
        )
        qs = CeoOrchestrationSnapshot.objects.all().order_by("-snapshot_at")
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


class CeoOrchestrationSnapshotLatestView(APIView):
    """``GET /api/v1/ceo-orchestration/snapshots/latest/``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        snapshot = (
            CeoOrchestrationSnapshot.objects.order_by("-snapshot_at").first()
        )
        last_run = (
            AgentRun.objects.filter(agent=AgentRun.Agent.CEO)
            .order_by("-created_at")
            .first()
        )
        return Response(
            {
                "agent": "ceo_orchestration_v1",
                "snapshot": _serialize_snapshot(snapshot)
                if snapshot
                else None,
                "lastAgentRunAt": last_run.created_at if last_run else None,
                "lastAgentRunStatus": last_run.status if last_run else "",
            }
        )


class CeoOrchestrationSnapshotDetailView(APIView):
    """``GET /api/v1/ceo-orchestration/snapshots/<id>/``."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk: int):
        snapshot = CeoOrchestrationSnapshot.objects.filter(pk=pk).first()
        if snapshot is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(_serialize_snapshot(snapshot))
