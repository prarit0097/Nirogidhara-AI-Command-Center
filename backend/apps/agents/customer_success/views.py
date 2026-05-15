"""Phase 9A — Customer Success / Reorder Agent V1 read-only API.

Admin+ only. No POST/PATCH/DELETE for snapshots. Pagination is
handled inline (default 50/page, max 200).
"""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_governance.models import AgentRun

from .models import CustomerSuccessSnapshot


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


def _serialize_snapshot(snapshot: CustomerSuccessSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "customerId": snapshot.customer_id,
        "score": snapshot.score,
        "lifecycleStage": snapshot.lifecycle_stage,
        "daysSinceDelivery": snapshot.days_since_delivery,
        "inReorderWindow": snapshot.in_reorder_window,
        "reorderCandidate": snapshot.reorder_candidate,
        "atRisk": snapshot.at_risk,
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


class CustomerSuccessSnapshotsListView(APIView):
    """``GET /api/v1/customer-success/snapshots/?stage=&kind=&page=&page_size=``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        page = _parse_int(request.query_params.get("page"), 1, lo=1, hi=10_000)
        page_size = _parse_int(
            request.query_params.get("page_size"), 50, lo=1, hi=200
        )
        stage = (request.query_params.get("stage") or "").strip()
        kind = (request.query_params.get("kind") or "").strip()
        qs = CustomerSuccessSnapshot.objects.all().order_by("-created_at")
        if stage in CustomerSuccessSnapshot.LifecycleStage.values:
            qs = qs.filter(lifecycle_stage=stage)
        if kind in CustomerSuccessSnapshot.RecommendationKind.values:
            qs = qs.filter(recommendation_kind=kind)
        total = qs.count()
        offset = (page - 1) * page_size
        items = list(qs[offset : offset + page_size])
        return Response(
            {
                "items": [_serialize_snapshot(s) for s in items],
                "total": total,
                "page": page,
                "pageSize": page_size,
                "filters": {"stage": stage or None, "kind": kind or None},
            }
        )


class CustomerSuccessSnapshotDetailView(APIView):
    """``GET /api/v1/customer-success/snapshots/<id>/``."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk: int):
        snapshot = CustomerSuccessSnapshot.objects.filter(pk=pk).first()
        if snapshot is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(_serialize_snapshot(snapshot))


class CustomerSuccessCohortsView(APIView):
    """``GET /api/v1/customer-success/cohorts/``.

    Returns cohort counts derived from the most recent snapshot per
    customer (the daily task writes one fresh row per customer per
    run). Also surfaces last agent-run timestamp and top reorder
    candidates so the dashboard does not need to filter twice.
    """

    permission_classes = [_AdminPermission]

    def get(self, request):
        # Python-side rollup keeps the query engine-agnostic. The daily
        # sweep only writes a few hundred rows; an N-row scan is fine
        # and avoids a Postgres-only ``DISTINCT ON`` branch.
        seen: set[str] = set()
        stage_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        reorder_count = 0
        at_risk_count = 0
        for snap in CustomerSuccessSnapshot.objects.order_by("-created_at"):
            if snap.customer_id in seen:
                continue
            seen.add(snap.customer_id)
            stage_counts[snap.lifecycle_stage] = (
                stage_counts.get(snap.lifecycle_stage, 0) + 1
            )
            kind_counts[snap.recommendation_kind] = (
                kind_counts.get(snap.recommendation_kind, 0) + 1
            )
            if snap.reorder_candidate:
                reorder_count += 1
            if snap.at_risk:
                at_risk_count += 1
        last_run = (
            AgentRun.objects.filter(agent=AgentRun.Agent.CUSTOMER_SUCCESS)
            .order_by("-created_at")
            .first()
        )
        top_reorder = list(
            CustomerSuccessSnapshot.objects.filter(reorder_candidate=True)
            .order_by("-score", "-created_at")[:10]
        )
        return Response(
            {
                "agent": "customer_success_reorder_v1",
                "stageCounts": stage_counts,
                "recommendationCounts": kind_counts,
                "reorderCandidateCount": reorder_count,
                "atRiskCount": at_risk_count,
                "lastAgentRunAt": last_run.created_at if last_run else None,
                "lastAgentRunStatus": last_run.status if last_run else "",
                "topReorderCandidates": [
                    {
                        "id": s.pk,
                        "customerIdMasked": _mask_customer_id(s.customer_id),
                        "score": s.score,
                        "daysSinceDelivery": s.days_since_delivery,
                    }
                    for s in top_reorder
                ],
            }
        )

def _mask_customer_id(customer_id: str) -> str:
    if not customer_id:
        return ""
    if len(customer_id) <= 4:
        return "***"
    return f"{customer_id[:3]}***{customer_id[-3:]}"
