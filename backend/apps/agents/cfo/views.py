"""Phase 9C — CFO Agent V1 read-only API.

Admin+ only. Strictly read-only — POST/PATCH/DELETE return 405.
"""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_governance.models import AgentRun

from .models import CfoFinancialSnapshot


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


def _serialize_snapshot(snapshot: CfoFinancialSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "snapshotAt": snapshot.snapshot_at,
        "revenue24h": str(snapshot.revenue_24h),
        "revenue7d": str(snapshot.revenue_7d),
        "revenue30d": str(snapshot.revenue_30d),
        "orderCount24h": snapshot.order_count_24h,
        "orderCount7d": snapshot.order_count_7d,
        "orderCount30d": snapshot.order_count_30d,
        "paidCount": snapshot.paid_count,
        "partialCount": snapshot.partial_count,
        "pendingCount": snapshot.pending_count,
        "paidAmount": str(snapshot.paid_amount),
        "partialAmount": str(snapshot.partial_amount),
        "pendingAmount": str(snapshot.pending_amount),
        "averageOrderValue": str(snapshot.average_order_value),
        "rtoCount30d": snapshot.rto_count_30d,
        "rtoLossAmount30d": str(snapshot.rto_loss_amount_30d),
        "newCustomerCount30d": snapshot.new_customer_count_30d,
        "returningCustomerCount30d": snapshot.returning_customer_count_30d,
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


class CfoSnapshotsListView(APIView):
    """``GET /api/v1/cfo/snapshots/?page=&page_size=``."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        page = _parse_int(request.query_params.get("page"), 1, lo=1, hi=10_000)
        page_size = _parse_int(
            request.query_params.get("page_size"), 50, lo=1, hi=200
        )
        qs = CfoFinancialSnapshot.objects.all().order_by("-snapshot_at")
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


class CfoSnapshotDetailView(APIView):
    """``GET /api/v1/cfo/snapshots/<id>/``."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk: int):
        snapshot = CfoFinancialSnapshot.objects.filter(pk=pk).first()
        if snapshot is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(_serialize_snapshot(snapshot))


class CfoLatestSnapshotView(APIView):
    """``GET /api/v1/cfo/latest/`` returns the freshest snapshot."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        snapshot = (
            CfoFinancialSnapshot.objects.order_by("-snapshot_at").first()
        )
        last_run = (
            AgentRun.objects.filter(agent=AgentRun.Agent.CFO)
            .order_by("-created_at")
            .first()
        )
        return Response(
            {
                "agent": "cfo_v1",
                "snapshot": _serialize_snapshot(snapshot)
                if snapshot
                else None,
                "lastAgentRunAt": last_run.created_at if last_run else None,
                "lastAgentRunStatus": last_run.status if last_run else "",
            }
        )
