"""Phase 11C — CAIO Audit Agent V1 read-only API.

All views are GET-only; POST / PATCH / DELETE return 405. Admin /
director / owner / superuser only. None of these views ever mutate
business state or trigger outbound side effects.
"""
from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CaioAuditSnapshot


class _AdminCaioPermission(BasePermission):
    """Admin / director / owner / superuser only."""

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = getattr(user, "role", "") or ""
        return role.lower() in {"admin", "director", "owner"}


def _serialize(row: CaioAuditSnapshot) -> dict:
    return {
        "id": row.pk,
        "snapshotAt": row.snapshot_at.isoformat() if row.snapshot_at else None,
        "windowDays": int(row.window_days or 0),
        "severity": row.severity,
        "complianceRiskCallCount": int(row.compliance_risk_call_count or 0),
        "complianceRiskAgentLabels": list(
            row.compliance_risk_agent_labels or []
        ),
        "transcriptBacklogCount": int(row.transcript_backlog_count or 0),
        "callQualityTrend": row.call_quality_trend,
        "agentDataGaps": int(row.agent_data_gaps or 0),
        "agentDataGapNames": list(row.agent_data_gap_names or []),
        "agentAnomalyFlags": dict(row.agent_anomaly_flags or {}),
        "weakLearningIndicators": list(row.weak_learning_indicators or []),
        "ceoAuditNotes": list(row.ceo_audit_notes or []),
        "recommendationText": row.recommendation_text,
        "auditedAgents": list(row.audited_agents or []),
        "sandbox": bool(row.sandbox),
        "agentRunId": row.agent_run_id,
    }


class CaioSnapshotsListView(APIView):
    """``GET /api/v1/caio/snapshots/?limit=N``."""

    permission_classes = [_AdminCaioPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 30)
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(200, limit))
        rows = list(CaioAuditSnapshot.objects.all()[:limit])
        return Response(
            {"count": len(rows), "results": [_serialize(r) for r in rows]}
        )


class CaioSnapshotLatestView(APIView):
    """``GET /api/v1/caio/snapshots/latest/`` — most recent snapshot."""

    permission_classes = [_AdminCaioPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, _request):
        row = CaioAuditSnapshot.objects.first()
        if row is None:
            raise NotFound("No CAIO audit snapshots yet.")
        return Response(_serialize(row))


class CaioSnapshotDetailView(APIView):
    """``GET /api/v1/caio/snapshots/<int:pk>/``."""

    permission_classes = [_AdminCaioPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, _request, pk: int):
        row = CaioAuditSnapshot.objects.filter(pk=pk).first()
        if row is None:
            raise NotFound(f"CAIO audit snapshot {pk} not found.")
        return Response(_serialize(row))
