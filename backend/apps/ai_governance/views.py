from __future__ import annotations

from typing import Callable

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from . import services
from .models import AgentRun, CaioAudit, CeoBriefing
from .serializers import (
    AgentRunCreateSerializer,
    AgentRunSerializer,
    CaioAuditSerializer,
    CeoBriefingSerializer,
)
from .services.agents import ads, caio, ceo, cfo, compliance, rto, sales_growth


class CeoBriefingView(APIView):
    """Latest briefing only — frontend treats this as the daily brief."""

    def get(self, _request):
        briefing = CeoBriefing.objects.order_by("-updated_at").first()
        if briefing is None:
            return Response(
                {
                    "date": "",
                    "headline": "",
                    "summary": "",
                    "recommendations": [],
                    "alerts": [],
                }
            )
        return Response(CeoBriefingSerializer(briefing).data)


class CaioAuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = CaioAudit.objects.all()
    serializer_class = CaioAuditSerializer
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


class AgentRunViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Phase 3A — POST creates a dry-run AgentRun; GET list/detail are
    read-only audit views.

    Permissions: only ``admin`` or ``director`` can trigger a run because
    Phase 3A is still a pre-rollout sandbox. The list/detail endpoints
    follow the same role gate so audit data isn't leaked.
    """

    queryset = AgentRun.objects.all()
    serializer_class = AgentRunSerializer
    pagination_class = None
    permission_classes = [_AdminAndUpAlways]

    def create(self, request):
        payload = AgentRunCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        run = services.run_readonly_agent_analysis(
            agent=payload.validated_data["agent"],
            input_payload=dict(payload.validated_data.get("input") or {}),
            triggered_by=getattr(request.user, "username", "") or "",
            # Phase 3A always coerces to dry-run regardless of the wire flag.
            dry_run=True,
        )
        return Response(
            AgentRunSerializer(run).data, status=status.HTTP_201_CREATED
        )

    def retrieve(self, request, pk=None):
        try:
            run = AgentRun.objects.get(pk=pk)
        except AgentRun.DoesNotExist as exc:
            raise NotFound(f"AgentRun {pk} not found") from exc
        return Response(AgentRunSerializer(run).data)


# ----- Phase 3B — Per-agent runtime endpoints -----


class _AgentRuntimeBase(APIView):
    """Common scaffolding for the per-agent runtime POST endpoints.

    Subclasses set ``agent_module`` (the module exposing ``run(triggered_by)``)
    and ``agent_label`` (used in audit events). Every POST returns the
    persisted ``AgentRun`` and writes a wrapping ``ai.agent_runtime.completed``
    or ``ai.agent_runtime.failed`` audit row so the dashboard sees the
    runtime call separately from the underlying ``ai.agent_run.*`` events.
    """

    permission_classes = [_AdminAndUpAlways]
    agent_module: object | None = None
    agent_label: str = ""

    def post(self, request):
        if self.agent_module is None or not self.agent_label:
            raise NotImplementedError("agent_module / agent_label must be set")
        run_fn: Callable[..., AgentRun] = getattr(self.agent_module, "run")
        triggered_by = getattr(request.user, "username", "") or ""
        run = run_fn(triggered_by=triggered_by)

        kind = (
            "ai.agent_runtime.completed"
            if run.status != AgentRun.Status.FAILED
            else "ai.agent_runtime.failed"
        )
        tone = (
            AuditEvent.Tone.SUCCESS
            if run.status == AgentRun.Status.SUCCESS
            else AuditEvent.Tone.DANGER
            if run.status == AgentRun.Status.FAILED
            else AuditEvent.Tone.INFO
        )
        write_event(
            kind=kind,
            text=f"Agent runtime {self.agent_label} → run {run.id} · {run.status}",
            tone=tone,
            payload={
                "run_id": run.id,
                "agent": self.agent_label,
                "status": run.status,
                "triggered_by": triggered_by,
            },
        )
        return Response(
            AgentRunSerializer(run).data, status=status.HTTP_201_CREATED
        )


class CeoDailyBriefView(_AgentRuntimeBase):
    agent_module = ceo
    agent_label = "ceo"


class CaioAuditSweepView(_AgentRuntimeBase):
    agent_module = caio
    agent_label = "caio"


class AdsAnalyzeView(_AgentRuntimeBase):
    agent_module = ads
    agent_label = "ads"


class RtoAnalyzeView(_AgentRuntimeBase):
    agent_module = rto
    agent_label = "rto"


class SalesGrowthAnalyzeView(_AgentRuntimeBase):
    agent_module = sales_growth
    agent_label = "sales_growth"


class CfoAnalyzeView(_AgentRuntimeBase):
    agent_module = cfo
    agent_label = "cfo"


class ComplianceAnalyzeView(_AgentRuntimeBase):
    agent_module = compliance
    agent_label = "compliance"


class AgentRuntimeStatusView(APIView):
    """Read-only snapshot of the agent runtime — last AgentRun per agent."""

    permission_classes = [_AdminAndUpAlways]

    def get(self, _request):
        agents = (
            "ceo",
            "caio",
            "ads",
            "rto",
            "sales_growth",
            "cfo",
            "compliance",
        )
        last_runs: dict[str, dict] = {}
        for agent_name in agents:
            run = (
                AgentRun.objects.filter(agent=agent_name)
                .order_by("-created_at")
                .first()
            )
            last_runs[agent_name] = AgentRunSerializer(run).data if run else None
        return Response(
            {
                "phase": "3B",
                "dryRunOnly": True,
                "agents": list(agents),
                "lastRuns": last_runs,
            }
        )
