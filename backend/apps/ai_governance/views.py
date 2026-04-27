from __future__ import annotations

from typing import Callable

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from . import prompt_versions, sandbox, services
from .approval_matrix import APPROVAL_MATRIX
from .budgets import calculate_agent_spend, get_agent_budget
from .models import (
    AgentBudget,
    AgentRun,
    CaioAudit,
    CeoBriefing,
    PromptVersion,
    SandboxState,
)
from .serializers import (
    AgentBudgetSerializer,
    AgentRunCreateSerializer,
    AgentRunSerializer,
    CaioAuditSerializer,
    CeoBriefingSerializer,
    PromptVersionCreateSerializer,
    PromptVersionRollbackSerializer,
    PromptVersionSerializer,
    SandboxPatchSerializer,
    SandboxStateSerializer,
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


def _redact_broker_url(broker_url: str) -> str:
    """Hide credentials in a redis:// URL before sending it to the frontend."""
    if not broker_url or "@" not in broker_url:
        return broker_url or ""
    scheme, _, rest = broker_url.partition("://")
    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"


class SchedulerStatusView(APIView):
    """Phase 3C — read-only Celery + AI fallback + cost snapshot.

    Admin/director only. Surfaces the state the Scheduler Status page
    needs to show: Celery configured, Redis URL configured, IST schedule,
    primary provider + model, fallback chain, last daily briefing run,
    last CAIO sweep, last cost in USD, last fallback flag.
    """

    permission_classes = [_AdminAndUpAlways]

    def get(self, _request):
        from django.conf import settings

        celery_eager = bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", True))
        broker = getattr(settings, "CELERY_BROKER_URL", "") or ""
        redis_configured = bool(
            broker and broker.startswith(("redis://", "rediss://"))
        )
        timezone_name = getattr(settings, "AI_TIMEZONE", "Asia/Kolkata")
        provider = (
            getattr(settings, "AI_PROVIDER", "disabled") or "disabled"
        ).lower()
        primary_model = getattr(settings, "AI_MODEL", "") or ""
        fallbacks = list(getattr(settings, "AI_PROVIDER_FALLBACKS", []) or [])
        if not fallbacks:
            fallbacks = [provider]

        last_ceo = (
            AgentRun.objects.filter(agent="ceo").order_by("-created_at").first()
        )
        last_caio = (
            AgentRun.objects.filter(agent="caio").order_by("-created_at").first()
        )
        last_cost_run = (
            AgentRun.objects.filter(status=AgentRun.Status.SUCCESS)
            .order_by("-completed_at")
            .first()
        )

        return Response(
            {
                "celeryConfigured": True,
                "celeryEagerMode": celery_eager,
                "redisConfigured": redis_configured,
                "brokerUrl": _redact_broker_url(broker),
                "timezone": timezone_name,
                "morningSchedule": {
                    "hour": int(
                        getattr(settings, "AI_DAILY_BRIEFING_MORNING_HOUR", 9)
                    ),
                    "minute": int(
                        getattr(settings, "AI_DAILY_BRIEFING_MORNING_MINUTE", 0)
                    ),
                },
                "eveningSchedule": {
                    "hour": int(
                        getattr(settings, "AI_DAILY_BRIEFING_EVENING_HOUR", 18)
                    ),
                    "minute": int(
                        getattr(settings, "AI_DAILY_BRIEFING_EVENING_MINUTE", 0)
                    ),
                },
                "lastDailyBriefingRun": (
                    AgentRunSerializer(last_ceo).data if last_ceo else None
                ),
                "lastCaioSweepRun": (
                    AgentRunSerializer(last_caio).data if last_caio else None
                ),
                "aiProvider": provider,
                "primaryModel": primary_model,
                "fallbacks": fallbacks,
                "lastCostUsd": (
                    str(last_cost_run.cost_usd)
                    if last_cost_run and last_cost_run.cost_usd is not None
                    else None
                ),
                "lastFallbackUsed": (
                    bool(last_cost_run.fallback_used) if last_cost_run else False
                ),
            }
        )


# ----- Phase 3D — PromptVersion + AgentBudget + SandboxState views -----


class PromptVersionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Phase 3D — admin/director only. POST creates a draft version; the
    :action:`activate` and :action:`rollback` actions move the active flag.
    """

    queryset = PromptVersion.objects.all()
    serializer_class = PromptVersionSerializer
    pagination_class = None
    permission_classes = [_AdminAndUpAlways]

    def list(self, request):
        agent = request.query_params.get("agent")
        qs = self.queryset.all()
        if agent:
            qs = qs.filter(agent=agent)
        return Response(
            PromptVersionSerializer(qs.order_by("agent", "-created_at"), many=True).data
        )

    def create(self, request):
        payload = PromptVersionCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            pv = prompt_versions.create_prompt_version(
                agent=payload.validated_data["agent"],
                version=payload.validated_data["version"],
                title=payload.validated_data.get("title", ""),
                system_policy=payload.validated_data.get("systemPolicy", ""),
                role_prompt=payload.validated_data.get("rolePrompt", ""),
                instruction_payload=payload.validated_data.get("instructionPayload"),
                metadata=payload.validated_data.get("metadata"),
                by_user=request.user,
            )
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError as _VE

            raise _VE({"detail": str(exc)}) from exc
        return Response(
            PromptVersionSerializer(pv).data, status=status.HTTP_201_CREATED
        )

    @staticmethod
    def _activate_view(request, pk):
        try:
            pv = prompt_versions.activate_prompt_version(
                prompt_version_id=pk, by_user=request.user
            )
        except PromptVersion.DoesNotExist as exc:
            raise NotFound(f"PromptVersion {pk} not found") from exc
        return Response(PromptVersionSerializer(pv).data)

    @staticmethod
    def _rollback_view(request, pk):
        payload = PromptVersionRollbackSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            pv = prompt_versions.rollback_prompt_version(
                target_version_id=pk,
                reason=payload.validated_data["reason"],
                by_user=request.user,
            )
        except PromptVersion.DoesNotExist as exc:
            raise NotFound(f"PromptVersion {pk} not found") from exc
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError as _VE

            raise _VE({"detail": str(exc)}) from exc
        return Response(PromptVersionSerializer(pv).data)


class PromptVersionActivateView(APIView):
    permission_classes = [_AdminAndUpAlways]

    def post(self, request, pk):
        return PromptVersionViewSet._activate_view(request, pk)


class PromptVersionRollbackView(APIView):
    permission_classes = [_AdminAndUpAlways]

    def post(self, request, pk):
        return PromptVersionViewSet._rollback_view(request, pk)


class AgentBudgetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Phase 3D — admin/director only. POST upserts by ``agent`` so the
    operator can set/update a budget without juggling primary keys.
    """

    queryset = AgentBudget.objects.all()
    serializer_class = AgentBudgetSerializer
    pagination_class = None
    permission_classes = [_AdminAndUpAlways]

    def create(self, request):
        # Support upsert: pre-existing row + new POST → update in place
        # rather than 400 on the unique constraint.
        agent = (request.data or {}).get("agent")
        instance = AgentBudget.objects.filter(agent=agent).first() if agent else None
        if instance is None:
            ser = AgentBudgetSerializer(data=request.data)
        else:
            ser = AgentBudgetSerializer(instance, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        instance = ser.save()
        body = AgentBudgetSerializer(instance).data
        body["dailySpendUsd"] = str(
            calculate_agent_spend(agent=instance.agent, period="daily")
        )
        body["monthlySpendUsd"] = str(
            calculate_agent_spend(agent=instance.agent, period="monthly")
        )
        return Response(body, status=status.HTTP_201_CREATED)

    def list(self, request):
        out = []
        for budget in self.queryset.all():
            row = AgentBudgetSerializer(budget).data
            row["dailySpendUsd"] = str(
                calculate_agent_spend(agent=budget.agent, period="daily")
            )
            row["monthlySpendUsd"] = str(
                calculate_agent_spend(agent=budget.agent, period="monthly")
            )
            out.append(row)
        return Response(out)

    def partial_update(self, request, pk=None):
        try:
            instance = self.queryset.get(pk=pk)
        except AgentBudget.DoesNotExist as exc:
            raise NotFound(f"AgentBudget {pk} not found") from exc
        ser = AgentBudgetSerializer(instance, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        body = AgentBudgetSerializer(instance).data
        body["dailySpendUsd"] = str(
            calculate_agent_spend(agent=instance.agent, period="daily")
        )
        body["monthlySpendUsd"] = str(
            calculate_agent_spend(agent=instance.agent, period="monthly")
        )
        return Response(body)


class ApprovalMatrixView(APIView):
    """Phase 3E — read-only approval matrix policy snapshot.

    Reads only. Returns the ``apps.ai_governance.approval_matrix`` table
    as JSON. Public so the frontend Settings page can render it without
    auth — the data is policy, not secrets.
    """

    permission_classes: list = []  # public read

    def get(self, _request):
        return Response(
            {
                "version": "phase-3e",
                "actions": [dict(row) for row in APPROVAL_MATRIX],
            }
        )


class SandboxStatusView(APIView):
    """Phase 3D — read or flip the global sandbox toggle.

    GET returns the singleton state. PATCH flips ``isEnabled`` and writes
    an ``ai.sandbox.{enabled,disabled}`` audit event. Both paths are
    admin/director only.
    """

    permission_classes = [_AdminAndUpAlways]

    def get(self, _request):
        state = sandbox.get_state()
        return Response(SandboxStateSerializer(state).data)

    def patch(self, request):
        payload = SandboxPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        state = sandbox.set_sandbox_enabled(
            enabled=payload.validated_data["isEnabled"],
            note=payload.validated_data.get("note", ""),
            by_user=request.user,
        )
        return Response(SandboxStateSerializer(state).data)
