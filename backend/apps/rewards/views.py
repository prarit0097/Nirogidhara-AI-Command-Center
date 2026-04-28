"""Phase 4B — Reward / Penalty Engine endpoints.

Public reads:
- ``GET  /api/rewards/`` — agent-level leaderboard (backwards-compatible).

Admin/director-only:
- ``GET  /api/rewards/events/``  — per-order scoring events.
- ``GET  /api/rewards/summary/`` — top-line totals + last sweep snapshot.
- ``POST /api/rewards/sweep/``   — run a sweep (optionally a single order).
"""
from __future__ import annotations

from typing import Any

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission
from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.rewards import engine

from .models import RewardPenalty, RewardPenaltyEvent
from .serializers import (
    RewardPenaltyEventSerializer,
    RewardPenaltySerializer,
    RewardPenaltySweepRequestSerializer,
)


class RewardPenaltyViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Backwards-compatible list endpoint at ``/api/rewards/``.

    Phase 4B aggregates events into rows here via
    :func:`engine.rebuild_agent_leaderboard`. Pre-existing seeded human
    rows are still returned for the legacy view.
    """

    queryset = RewardPenalty.objects.all()
    serializer_class = RewardPenaltySerializer
    pagination_class = None


class _AdminAndUpAlways(RoleBasedPermission):
    """Tighten the role check so reads also require admin/director."""

    allowed_roles = ADMIN_AND_UP

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        return getattr(request.user, "role", None) in self.allowed_roles


class RewardPenaltyEventListView(APIView):
    """Per-order scoring events. Admin/director only.

    Query params:
    - ``agent`` — filter by agent name (substring, case-insensitive).
    - ``orderId`` — filter by order id (exact match).
    - ``eventType`` — ``reward`` / ``penalty`` / ``mixed``.
    - ``limit`` — cap result size (default 200).
    """

    permission_classes = [_AdminAndUpAlways]

    def get(self, request):
        qs = RewardPenaltyEvent.objects.all().order_by("-calculated_at")
        agent = request.query_params.get("agent")
        if agent:
            qs = qs.filter(agent_name__icontains=agent)
        order_id = request.query_params.get("orderId")
        if order_id:
            qs = qs.filter(order_id_snapshot=order_id)
        event_type = request.query_params.get("eventType")
        if event_type:
            qs = qs.filter(event_type=event_type)
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 200), 1000))
        except (TypeError, ValueError):
            limit = 200
        qs = qs[:limit]
        return Response(RewardPenaltyEventSerializer(qs, many=True).data)


class RewardPenaltySummaryView(APIView):
    """Top-line summary of the latest sweep state. Admin/director only."""

    permission_classes = [_AdminAndUpAlways]

    def get(self, _request):
        events_qs = RewardPenaltyEvent.objects.all()
        total_reward = sum(int(e.reward_score or 0) for e in events_qs)
        total_penalty = sum(int(e.penalty_score or 0) for e in events_qs)
        net_score = total_reward - total_penalty
        evaluated_orders = events_qs.values("order_id_snapshot").distinct().count()

        # Latest sweep audit row.
        last_sweep = (
            AuditEvent.objects.filter(kind="ai.reward_penalty.sweep_completed")
            .order_by("-occurred_at")
            .first()
        )

        # Aggregate missing-data warnings for fast surface in the dashboard.
        missing: list[str] = []
        for event in events_qs.exclude(missing_data=[])[:50]:
            for code in event.missing_data:
                missing.append(f"{event.order_id_snapshot}:{code}")

        return Response(
            {
                "evaluatedOrders": evaluated_orders,
                "totalReward": total_reward,
                "totalPenalty": total_penalty,
                "netScore": net_score,
                "lastSweepAt": (
                    last_sweep.occurred_at.isoformat() if last_sweep else None
                ),
                "lastSweepPayload": (
                    last_sweep.payload if last_sweep else None
                ),
                "missingDataWarnings": missing,
                "agentLeaderboard": RewardPenaltySerializer(
                    RewardPenalty.objects.all().order_by(
                        "sort_order", "name"
                    ),
                    many=True,
                ).data,
            }
        )


class RewardPenaltySweepView(APIView):
    """Trigger a reward / penalty sweep. Admin/director only."""

    permission_classes = [_AdminAndUpAlways]

    def post(self, request):
        payload = RewardPenaltySweepRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        triggered_by = (
            getattr(request.user, "username", "") or "manual-sweep"
        )

        order_id = payload.validated_data.get("orderId") or ""
        dry_run = bool(payload.validated_data.get("dryRun") or False)

        if order_id:
            try:
                order = Order.objects.get(pk=order_id)
            except Order.DoesNotExist as exc:
                raise NotFound(f"Order {order_id} not found") from exc
            _, _, summary = engine.calculate_for_order(
                order, triggered_by=triggered_by, dry_run=dry_run
            )
            if not dry_run:
                engine.rebuild_agent_leaderboard(triggered_by=triggered_by)
                summary.leaderboard_updated = True
            return Response(summary.as_dict(), status=status.HTTP_200_OK)

        summary = engine.calculate_for_all_eligible_orders(
            start_date=payload.validated_data.get("startDate"),
            end_date=payload.validated_data.get("endDate"),
            triggered_by=triggered_by,
            dry_run=dry_run,
        )
        return Response(summary.as_dict(), status=status.HTTP_200_OK)
