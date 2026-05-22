"""Phase 9F — CEO AI Orchestration V1 read-only API.

Phase 15B adds a slimmer ``sidebar-status/`` endpoint that returns
only the minimum allow-listed metadata the Sidebar badge needs —
``status``, ``label``, ``healthScore``, ``tier``, ``ageMinutes``,
``targetRoute``. The full ``briefingText`` / ``crossCuttingAlerts``
/ ``agentStatusSummary`` payload the Phase 9F ``snapshots/latest/``
endpoint returns is intentionally NOT in the sidebar response so a
client fetching the badge cannot incidentally read the Director's
full internal briefing body.
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone
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


class CeoOrchestrationSidebarStatusView(APIView):
    """Phase 15B — minimal sidebar-badge payload.

    Returns the Director-facing CEO briefing status in a small,
    allow-listed shape:
      - ``status`` ∈ {"ready", "stale", "critical", "missing"}
      - ``label`` — short human-readable string for the badge
      - ``latestSnapshotId``
      - ``latestSnapshotAt`` (ISO-8601)
      - ``ageMinutes``
      - ``healthScore`` (0-100)
      - ``tier`` (Phase 9F HealthTier choice)
      - ``targetRoute`` (always ``/ceo-ai`` — the existing CEO page)

    Hard guarantees:
      - GET-only. POST/PUT/PATCH/DELETE return 405.
      - Admin/director/superuser/owner only.
      - NEVER returns ``briefingText``, ``crossCuttingAlerts``,
        ``top3Priorities``, ``agentStatusSummary``, raw provider
        payloads, prompt body, secrets, tokens, phones, or PII.
      - NEVER triggers a new orchestration run, never enqueues a
        Celery task, never invokes any provider client. It is a pure
        SELECT + small computed-status response.
    """

    permission_classes = [_AdminPermission]

    # Stale threshold — Phase 9F's beat task runs daily at 13:00 IST,
    # so any snapshot older than ~36h means we've missed >1 full run.
    # Conservative threshold; surface as "stale" so the Director
    # knows to inspect why the daily sweep didn't write a fresh row.
    _STALE_AFTER_MINUTES = 36 * 60

    def get(self, request):
        snapshot = (
            CeoOrchestrationSnapshot.objects.order_by("-snapshot_at").first()
        )

        if snapshot is None:
            return Response(
                {
                    "status": "missing",
                    "label": "No briefing yet",
                    "latestSnapshotId": None,
                    "latestSnapshotAt": None,
                    "ageMinutes": None,
                    "healthScore": None,
                    "tier": None,
                    "targetRoute": "/ceo-ai",
                }
            )

        # Compute age in minutes from ``snapshot_at`` (the canonical
        # "when did the orchestration synthesise this" timestamp).
        now = timezone.now()
        age_seconds = max(0, int((now - snapshot.snapshot_at).total_seconds()))
        age_minutes = age_seconds // 60

        tier = snapshot.health_tier or "fair"

        # Phase 15B status precedence:
        #   1. critical tier always wins regardless of age.
        #   2. stale if older than the threshold.
        #   3. ready otherwise.
        if tier == CeoOrchestrationSnapshot.HealthTier.CRITICAL:
            status_label = "critical"
            label = "Briefing flags critical"
        elif age_minutes >= self._STALE_AFTER_MINUTES:
            status_label = "stale"
            label = "Briefing stale"
        else:
            status_label = "ready"
            label = "Briefing ready"

        return Response(
            {
                "status": status_label,
                "label": label,
                "latestSnapshotId": snapshot.pk,
                "latestSnapshotAt": snapshot.snapshot_at.isoformat(),
                "ageMinutes": age_minutes,
                "healthScore": snapshot.business_health_score,
                "tier": tier,
                "targetRoute": "/ceo-ai",
            }
        )
