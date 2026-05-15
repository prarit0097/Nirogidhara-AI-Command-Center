"""Phase 9B — RTO Prevention Agent V1 read-only API.

Admin+ only. No POST/PATCH/DELETE for snapshots. Pagination is
handled inline (default 50/page, max 200).
"""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_governance.models import AgentRun

from .models import RtoRiskSnapshot


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


def _serialize_snapshot(snapshot: RtoRiskSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "orderId": snapshot.order_id,
        "customerId": snapshot.customer_id,
        "riskScore": snapshot.risk_score,
        "riskTier": snapshot.risk_tier,
        "lifecycleStage": snapshot.lifecycle_stage,
        "daysSinceOrder": snapshot.days_since_order,
        "failedDeliveryAttempts": snapshot.failed_delivery_attempts,
        "riskReasons": list(snapshot.risk_reasons or []),
        "signals": dict(snapshot.signals or {}),
        "recommendationKind": snapshot.recommendation_kind,
        "recommendationText": snapshot.recommendation_text,
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


class RtoPreventionSnapshotsListView(APIView):
    """``GET /api/v1/rto-prevention/snapshots/?tier=&kind=&stage=&page=&page_size=``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        page = _parse_int(request.query_params.get("page"), 1, lo=1, hi=10_000)
        page_size = _parse_int(
            request.query_params.get("page_size"), 50, lo=1, hi=200
        )
        tier = (request.query_params.get("tier") or "").strip()
        kind = (request.query_params.get("kind") or "").strip()
        stage = (request.query_params.get("stage") or "").strip()
        qs = RtoRiskSnapshot.objects.all().order_by("-created_at")
        if tier in RtoRiskSnapshot.RiskTier.values:
            qs = qs.filter(risk_tier=tier)
        if kind in RtoRiskSnapshot.RecommendationKind.values:
            qs = qs.filter(recommendation_kind=kind)
        if stage in RtoRiskSnapshot.LifecycleStage.values:
            qs = qs.filter(lifecycle_stage=stage)
        total = qs.count()
        offset = (page - 1) * page_size
        items = list(qs[offset : offset + page_size])
        return Response(
            {
                "items": [_serialize_snapshot(s) for s in items],
                "total": total,
                "page": page,
                "pageSize": page_size,
                "filters": {
                    "tier": tier or None,
                    "kind": kind or None,
                    "stage": stage or None,
                },
            }
        )


class RtoPreventionSnapshotDetailView(APIView):
    """``GET /api/v1/rto-prevention/snapshots/<id>/``."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk: int):
        snapshot = RtoRiskSnapshot.objects.filter(pk=pk).first()
        if snapshot is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(_serialize_snapshot(snapshot))


class RtoPreventionCohortsView(APIView):
    """``GET /api/v1/rto-prevention/cohorts/``.

    Returns cohort counts derived from the most recent snapshot per
    order. Also surfaces last agent-run timestamp and the top 10
    critical-tier orders so the dashboard does not need to filter
    twice.
    """

    permission_classes = [_AdminPermission]

    def get(self, request):
        # Python-side rollup keeps the query engine-agnostic. The
        # daily sweep only writes a few hundred rows; an N-row scan is
        # fine and avoids a Postgres-only ``DISTINCT ON`` branch.
        seen: set[int] = set()
        tier_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        stage_counts: dict[str, int] = {}
        for snap in RtoRiskSnapshot.objects.order_by("-created_at"):
            if snap.order_id in seen:
                continue
            seen.add(snap.order_id)
            tier_counts[snap.risk_tier] = (
                tier_counts.get(snap.risk_tier, 0) + 1
            )
            kind_counts[snap.recommendation_kind] = (
                kind_counts.get(snap.recommendation_kind, 0) + 1
            )
            stage_counts[snap.lifecycle_stage] = (
                stage_counts.get(snap.lifecycle_stage, 0) + 1
            )
        last_run = (
            AgentRun.objects.filter(agent=AgentRun.Agent.RTO_PREVENTION)
            .order_by("-created_at")
            .first()
        )
        top_critical = list(
            RtoRiskSnapshot.objects.filter(
                risk_tier=RtoRiskSnapshot.RiskTier.CRITICAL.value
            ).order_by("-risk_score", "-created_at")[:10]
        )
        return Response(
            {
                "agent": "rto_prevention_v1",
                "tierCounts": tier_counts,
                "recommendationCounts": kind_counts,
                "stageCounts": stage_counts,
                "lastAgentRunAt": last_run.created_at if last_run else None,
                "lastAgentRunStatus": last_run.status if last_run else "",
                "topCriticalOrders": [
                    {
                        "id": s.pk,
                        "orderIdMasked": _mask_order_id(s.order_id),
                        "riskScore": s.risk_score,
                        "daysSinceOrder": s.days_since_order,
                    }
                    for s in top_critical
                ],
            }
        )


def _mask_order_id(order_id: str) -> str:
    if not order_id:
        return ""
    if len(order_id) <= 4:
        return "***"
    return f"{order_id[:3]}***{order_id[-3:]}"
