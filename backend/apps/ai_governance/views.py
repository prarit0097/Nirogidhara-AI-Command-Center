from __future__ import annotations

from typing import Callable

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from . import approval_engine, approval_execution, prompt_versions, sandbox, services
from .approval_matrix import APPROVAL_MATRIX
from .budgets import calculate_agent_spend, get_agent_budget
from .models import (
    AgentBudget,
    AgentRun,
    ApprovalRequest,
    CaioAudit,
    CeoBriefing,
    PromptVersion,
    SandboxState,
)
from .serializers import (
    AgentBudgetSerializer,
    AgentRunApprovalRequestSerializer,
    AgentRunCreateSerializer,
    AgentRunSerializer,
    ApprovalDecisionPayloadSerializer,
    ApprovalEvaluateRequestSerializer,
    ApprovalExecutePayloadSerializer,
    ApprovalRequestSerializer,
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
        # Phase 4C — record approval matrix usage for the audit trail.
        # The policy is ``approval_required``; admin/director already cleared
        # the role gate (this endpoint requires admin/director), so the
        # approval is effectively satisfied — we record it as auto-approved
        # so the operator queue shows the activation.
        approval_engine.mark_auto_approved(
            action="ai.prompt_version.activate",
            payload={"promptVersionId": pk},
            actor_role=getattr(request.user, "role", "") or "",
            target={"app": "ai_governance", "model": "PromptVersion", "id": pk},
            by_user=request.user,
        )
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


class PromptVersionRollbackHistoryView(APIView):
    """Phase 15A — read-only rollback history surface.

    Returns the latest rollback-related audit events (Phase 14F UI rows
    + Phase 3D service rows) in a sanitised shape. The endpoint NEVER
    mutates state, NEVER calls a provider, NEVER invokes
    rollback_prompt_version, and NEVER returns the underlying raw
    audit payload — only the safe-metadata allow-list below.

    Allow-listed audit kinds:
      - ``prompt_version.rollback.ui_changed`` (Phase 14F, UI source)
      - ``ai.prompt_version.rolled_back`` (Phase 3D service, also the
        backing row of every Phase 14F UI flip)
    Other audit kinds are intentionally excluded so unrelated audit
    payloads never leak into this surface.

    Sensitive data NEVER returned (defence in depth — the audit
    payloads themselves are already sanitised by the Phase 14F view
    + the Phase 3D service, but we re-filter here):
      - ``system_policy`` / ``role_prompt`` full bodies
      - ``instruction_payload`` raw JSON
      - Any token, secret, phone, email, address, raw payload key.
    """

    permission_classes = [_AdminAndUpAlways]

    _ALLOWED_KINDS: tuple[str, ...] = (
        "prompt_version.rollback.ui_changed",
        "ai.prompt_version.rolled_back",
    )

    # Hard cap so a malformed ``limit`` cannot drain the audit table.
    _MAX_LIMIT = 200
    _DEFAULT_LIMIT = 50

    @staticmethod
    def _safe_payload_slice(payload: dict | None) -> dict:
        """Extract only the safe-metadata keys we want to surface.

        Both Phase 14F UI rows + Phase 3D service rows use stable
        snake_case keys; this slice deliberately ignores everything
        else so a future writer that accidentally stuffs a sensitive
        field into the payload cannot leak it via this endpoint.
        """
        if not isinstance(payload, dict):
            return {}
        allowed = {
            "phase",
            "source",
            "action",
            "actor",
            "agent",
            "previous_active_version_id",
            "previous_version_id",
            "previous_version",
            "previous_version_label",
            "target_version_id",
            "target_version",
            "target_version_label",
            "reason",
            "by",
            "matrix_action",
            "matrix_status",
        }
        return {k: payload[k] for k in allowed if k in payload}

    @classmethod
    def _serialize_event(cls, event: AuditEvent) -> dict:
        """Compose the Phase 15A canonical history shape from an
        AuditEvent row."""
        payload = cls._safe_payload_slice(event.payload)

        # Phase 14F UI rows use ``previous_active_version_id``; Phase 3D
        # service rows use ``previous_version_id``. Normalise both into
        # the same camelCase field so the frontend renders uniformly.
        previous_version_id = payload.get(
            "previous_active_version_id"
        ) or payload.get("previous_version_id")
        previous_version_label = payload.get(
            "previous_version_label"
        ) or payload.get("previous_version")
        target_version_id = payload.get("target_version_id")
        target_version_label = payload.get(
            "target_version_label"
        ) or payload.get("target_version")
        agent = payload.get("agent") or ""

        # actor / source disambiguation by audit kind.
        if event.kind == "prompt_version.rollback.ui_changed":
            source = payload.get("source") or "settings_ui"
            status_label = "rolled_back"
            actor = payload.get("actor") or payload.get("by") or ""
        elif event.kind == "ai.prompt_version.rolled_back":
            source = payload.get("source") or "service"
            status_label = "rolled_back"
            actor = payload.get("by") or payload.get("actor") or ""
        else:  # pragma: no cover — _ALLOWED_KINDS guarantees one of the above
            source = "unknown"
            status_label = "unknown"
            actor = ""

        # Human-readable summary string the UI can render without
        # re-deriving from agent + version labels.
        if previous_version_label and target_version_label:
            summary = (
                f"{agent or 'agent'} rolled back from "
                f"{previous_version_label} to {target_version_label}"
            )
        elif target_version_label:
            summary = (
                f"{agent or 'agent'} rolled back to {target_version_label}"
            )
        else:
            summary = f"{agent or 'agent'} prompt rolled back"

        return {
            "id": event.id,
            "createdAt": event.occurred_at.isoformat(),
            "kind": event.kind,
            "tone": event.tone,
            "actor": actor,
            "agent": agent,
            "previousVersionId": previous_version_id,
            "previousVersionLabel": previous_version_label,
            "targetVersionId": target_version_id,
            "targetVersionLabel": target_version_label,
            "reason": payload.get("reason") or "",
            "matrixAction": payload.get("matrix_action") or "",
            "matrixStatus": payload.get("matrix_status") or "",
            "status": status_label,
            "source": source,
            "summary": summary,
        }

    def get(self, request):
        qs = AuditEvent.objects.filter(kind__in=self._ALLOWED_KINDS)

        # Filter — agent.
        agent = (request.query_params.get("agent") or "").strip()
        if agent:
            # AuditEvent.payload is JSONField — filter via the
            # canonical ``agent`` payload key.
            qs = qs.filter(payload__agent=agent)

        # Filter — kind (allow narrowing to just one source).
        kind_filter = (request.query_params.get("kind") or "").strip()
        if kind_filter:
            if kind_filter not in self._ALLOWED_KINDS:
                return Response(
                    {
                        "detail": (
                            "kind must be one of "
                            + ", ".join(repr(k) for k in self._ALLOWED_KINDS)
                            + "."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(kind=kind_filter)

        # Pagination — simple limit/offset; no DB-wide drain possible
        # because limit is capped at 200.
        try:
            limit = min(
                int(request.query_params.get("limit") or self._DEFAULT_LIMIT),
                self._MAX_LIMIT,
            )
        except (TypeError, ValueError):
            limit = self._DEFAULT_LIMIT
        try:
            offset = max(int(request.query_params.get("offset") or 0), 0)
        except (TypeError, ValueError):
            offset = 0

        total = qs.count()
        # Phase 15A — secondary ordering by ``-id`` so rows created
        # in the same millisecond (common on SQLite in tests + on
        # bursts of activity in prod) sort deterministically with
        # the newest-inserted row first.
        page = qs.order_by("-occurred_at", "-id")[offset : offset + limit]
        items = [self._serialize_event(event) for event in page]

        return Response(
            {
                "items": items,
                "count": total,
                "limit": limit,
                "offset": offset,
                "kindsIncluded": list(self._ALLOWED_KINDS),
            }
        )


class PromptVersionRollbackFromUiView(APIView):
    """Phase 14F — Settings-UI rollback wrapper around the Phase 3D
    ``rollback_prompt_version`` service.

    Adds a typed-phrase + reason gate matching the Phase 14D / 14E
    safety-modal pattern, records a Phase 4C ``mark_auto_approved``
    row for the matrix audit trail (the underlying matrix policy is
    ``approval_required`` + approver ``admin``; this endpoint already
    requires admin/director via ``_AdminAndUpAlways``, so the role
    gate is effectively the matrix gate — the auto-approved row is
    the audit-only record), and writes a dedicated
    ``prompt_version.rollback.ui_changed`` audit row on top of the
    legacy ``ai.prompt_version.rolled_back`` row that the service
    already emits.

    The legacy ``POST /api/ai/prompt-versions/<pk>/rollback/``
    endpoint (Phase 3D) is intentionally preserved for backwards
    compatibility with existing tests + the Governance page.
    """

    permission_classes = [_AdminAndUpAlways]

    _CONFIRMATION_PHRASE = "ROLLBACK PROMPT VERSION"
    _MIN_REASON_LENGTH = 10

    def post(self, request):
        agent = (request.data.get("agent") or "").strip()
        target_version_id = (
            request.data.get("targetVersionId")
            or request.data.get("target_version_id")
            or ""
        )
        target_version_id = str(target_version_id).strip()
        reason = (request.data.get("reason") or "").strip()
        confirmation = (request.data.get("confirmationPhrase") or "").strip()

        if not target_version_id:
            return Response(
                {"detail": "targetVersionId is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(reason) < self._MIN_REASON_LENGTH:
            return Response(
                {
                    "detail": (
                        f"A non-empty reason of at least "
                        f"{self._MIN_REASON_LENGTH} characters is required "
                        f"so the audit trail captures why the rollback "
                        f"happened."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if confirmation != self._CONFIRMATION_PHRASE:
            return Response(
                {
                    "detail": (
                        "Confirmation phrase did not match. Type "
                        f"'{self._CONFIRMATION_PHRASE}' exactly to proceed."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve target + cross-check agent (if supplied) BEFORE
        # mutating anything so a bad payload never leaves the DB in a
        # half-rolled-back state.
        try:
            target = PromptVersion.objects.get(pk=target_version_id)
        except PromptVersion.DoesNotExist as exc:
            raise NotFound(
                f"PromptVersion {target_version_id} not found"
            ) from exc

        if agent and target.agent != agent:
            return Response(
                {
                    "detail": (
                        f"targetVersionId {target_version_id} belongs to "
                        f"agent '{target.agent}', not '{agent}'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # No-op refusal: rolling back to the currently active version.
        if target.is_active:
            return Response(
                {
                    "detail": (
                        f"PromptVersion {target_version_id} is already the "
                        f"active version for agent '{target.agent}' — "
                        f"rollback would be a no-op."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous = prompt_versions.get_active_prompt_version(target.agent)
        previous_id = previous.id if previous else None

        # Phase 4C audit-trail record — matrix policy for
        # ai.prompt_version.activate covers rollback per the description
        # "Activate or rollback an AI prompt version." We mark
        # auto-approved (same pattern as activate) so the operator
        # queue shows the rollback action.
        approval_engine.mark_auto_approved(
            action="ai.prompt_version.activate",
            payload={
                "phase": "14F",
                "subAction": "rollback",
                "targetVersionId": target_version_id,
                "agent": target.agent,
                "previousActiveVersionId": previous_id,
            },
            actor_role=getattr(request.user, "role", "") or "",
            target={
                "app": "ai_governance",
                "model": "PromptVersion",
                "id": target_version_id,
            },
            by_user=request.user,
        )

        # Delegate to the existing Phase 3D service — same behaviour the
        # legacy /api/ai/prompt-versions/<pk>/rollback/ endpoint uses.
        result_pv = prompt_versions.rollback_prompt_version(
            target_version_id=target_version_id,
            reason=reason,
            by_user=request.user,
        )

        actor_label = (
            getattr(request.user, "username", "")
            or getattr(request.user, "email", "")
            or ""
        )
        # Phase 14F UI audit kind. Coexists with the legacy
        # ai.prompt_version.rolled_back row written by the service.
        write_event(
            kind="prompt_version.rollback.ui_changed",
            text=(
                f"Prompt rollback via Settings UI by {actor_label or 'admin'} "
                f"· agent={result_pv.agent} → v{result_pv.version}"
            ),
            tone=AuditEvent.Tone.WARNING,
            user=request.user,
            payload={
                "phase": "14F",
                "source": "settings_ui",
                "action": "prompt_version.rollback",
                "actor": actor_label,
                "agent": result_pv.agent,
                "previous_active_version_id": previous_id,
                "target_version_id": result_pv.id,
                "target_version_label": result_pv.version,
                "matrix_action": "ai.prompt_version.activate",
                "matrix_status": "auto_approved",
                "reason": reason[:280],
            },
        )

        return Response(
            {
                "ok": True,
                "status": "rolled_back",
                "agent": result_pv.agent,
                "previousActiveVersionId": previous_id,
                "targetVersionId": result_pv.id,
                "auditKind": "prompt_version.rollback.ui_changed",
                "promptVersion": PromptVersionSerializer(result_pv).data,
                "message": (
                    f"Rolled {result_pv.agent} back to version "
                    f"{result_pv.version}."
                ),
            }
        )


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
    """Phase 3D / 4C / 4E — read or flip the global sandbox toggle.

    GET returns the singleton state plus Phase 14E unambiguous fields
    (``statusLabel``, ``confirmationPhrases``) layered on top of the
    Phase 3D serializer shape.

    PATCH (Phase 3D legacy) flips ``isEnabled`` directly and routes
    disable through the Phase 4C approval matrix. Preserved unchanged
    for backward compatibility.

    POST (Phase 14E) takes a typed-phrase + reason payload from the
    Settings UI. Same Phase 4C matrix gate applies on disable; the new
    audit row ``sandbox.mode.ui_changed`` is written on top of the
    legacy ``ai.sandbox.{enabled,disabled}`` row that
    ``set_sandbox_enabled`` already emits.

    All three verbs are admin/director only via ``_AdminAndUpAlways``.
    """

    permission_classes = [_AdminAndUpAlways]

    # Phase 14E — unambiguous typed-phrase confirmations per action.
    _CONFIRMATION_PHRASE_ENABLE = "ENABLE SANDBOX MODE"
    _CONFIRMATION_PHRASE_DISABLE = "DISABLE SANDBOX MODE"
    _MIN_REASON_LENGTH = 10

    def _serialize(self, state: SandboxState) -> dict:
        """Phase 14E — canonical response shape.

        Returns every Phase 3D field for backward compatibility plus
        the new Phase 14E fields the Settings UI consumes.
        """
        base = SandboxStateSerializer(state).data
        # Phase 14E additions — must not collide with existing keys.
        base["sandboxEnabled"] = bool(state.is_enabled)
        base["statusLabel"] = "enabled" if state.is_enabled else "disabled"
        base["reason"] = state.note or ""
        base["updatedAt"] = (
            state.updated_at.isoformat() if state.updated_at else None
        )
        base["confirmationPhrases"] = {
            "enableSandboxMode": self._CONFIRMATION_PHRASE_ENABLE,
            "disableSandboxMode": self._CONFIRMATION_PHRASE_DISABLE,
        }
        return base

    def get(self, _request):
        state = sandbox.get_state()
        return Response(self._serialize(state))

    def patch(self, request):
        payload = SandboxPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        # Phase 4C — flipping sandbox OFF must go through the approval matrix
        # because it's a director_override action. ON stays low-risk and
        # auto-approved.
        if payload.validated_data["isEnabled"] is False:
            evaluation = approval_engine.enforce_or_queue(
                action="ai.sandbox.disable",
                payload={
                    "director_override": bool(
                        payload.validated_data.get("director_override")
                    ),
                    "override_reason": payload.validated_data.get("note", ""),
                },
                actor_role=getattr(request.user, "role", "") or "",
                by_user=request.user,
            )
            if not evaluation.allowed:
                from rest_framework.exceptions import PermissionDenied as _PD

                raise _PD(detail={
                    "detail": evaluation.reason,
                    "approvalRequestId": evaluation.approval_request_id,
                    "mode": evaluation.mode,
                })
        state = sandbox.set_sandbox_enabled(
            enabled=payload.validated_data["isEnabled"],
            note=payload.validated_data.get("note", ""),
            by_user=request.user,
        )
        return Response(self._serialize(state))

    def post(self, request):
        """Phase 14E — UI-driven sandbox toggle.

        Refuses unless: (a) action is ``enable_sandbox_mode`` or
        ``disable_sandbox_mode``; (b) non-empty ``reason`` (>=10 chars);
        (c) typed confirmation phrase matches the action exactly.
        Preserves the Phase 4C approval matrix gate on disable
        (a non-director admin still gets refused by the matrix even
        though the endpoint permission lets them in).

        Writes a ``sandbox.mode.ui_changed`` audit row carrying actor +
        previous/new state + reason. The legacy
        ``ai.sandbox.{enabled,disabled}`` row that
        ``set_sandbox_enabled`` writes is preserved.
        """
        action = (request.data.get("action") or "").strip()
        reason = (request.data.get("reason") or "").strip()
        confirmation = (request.data.get("confirmationPhrase") or "").strip()

        if action == "enable_sandbox_mode":
            new_enabled = True
            expected_phrase = self._CONFIRMATION_PHRASE_ENABLE
            audit_action_label = "enabled"
        elif action == "disable_sandbox_mode":
            new_enabled = False
            expected_phrase = self._CONFIRMATION_PHRASE_DISABLE
            audit_action_label = "disabled"
        else:
            return Response(
                {
                    "detail": (
                        "action must be 'enable_sandbox_mode' or "
                        "'disable_sandbox_mode'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(reason) < self._MIN_REASON_LENGTH:
            return Response(
                {
                    "detail": (
                        f"A non-empty reason of at least "
                        f"{self._MIN_REASON_LENGTH} characters is required "
                        f"so the audit trail captures why sandbox mode "
                        f"changed."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if confirmation != expected_phrase:
            return Response(
                {
                    "detail": (
                        "Confirmation phrase did not match. Type "
                        f"'{expected_phrase}' exactly to proceed."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        before_state = sandbox.get_state()
        previous_enabled = bool(before_state.is_enabled)

        # Phase 4C preservation — disable still routes through the
        # approval matrix as `ai.sandbox.disable` (director_override).
        # A non-director admin reaching this endpoint will still be
        # refused by the matrix even though _AdminAndUpAlways let them
        # past the permission gate.
        if not new_enabled:
            evaluation = approval_engine.enforce_or_queue(
                action="ai.sandbox.disable",
                payload={
                    "director_override": True,
                    "override_reason": reason,
                },
                actor_role=getattr(request.user, "role", "") or "",
                by_user=request.user,
            )
            if not evaluation.allowed:
                from rest_framework.exceptions import PermissionDenied as _PD

                raise _PD(detail={
                    "detail": evaluation.reason,
                    "approvalRequestId": evaluation.approval_request_id,
                    "mode": evaluation.mode,
                })

        # Re-use the existing service helper — keeps the legacy
        # ``ai.sandbox.{enabled,disabled}`` audit row firing exactly as
        # Phase 3D/4D consumers expect.
        state = sandbox.set_sandbox_enabled(
            enabled=new_enabled,
            note=reason,
            by_user=request.user,
        )

        actor_label = getattr(request.user, "username", "") or getattr(
            request.user, "email", ""
        )
        # Phase 14E — dedicated UI audit kind so operators can separate
        # UI-driven flips from PATCH-driven or matrix-driven flips at
        # audit-review time.
        write_event(
            kind="sandbox.mode.ui_changed",
            text=(
                f"Sandbox Mode {audit_action_label} via UI by "
                f"{actor_label or 'admin'}"
            ),
            tone=(
                AuditEvent.Tone.WARNING
                if new_enabled
                else AuditEvent.Tone.INFO
            ),
            user=request.user,
            payload={
                "phase": "14E",
                "source": "ui",
                "action": action,
                "actor": actor_label,
                "previous_enabled": previous_enabled,
                "new_enabled": bool(state.is_enabled),
                "reason": reason[:280],
            },
        )

        return Response(self._serialize(state))


# ----- Phase 4C — Approval Matrix Middleware endpoints -----


class ApprovalRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Phase 4C — admin/director only. Read-only viewset; transitions go
    through the dedicated approve / reject views.
    """

    queryset = ApprovalRequest.objects.all().prefetch_related("decision_logs")
    serializer_class = ApprovalRequestSerializer
    pagination_class = None
    permission_classes = [_AdminAndUpAlways]

    def list(self, request):
        qs = self.queryset.all()
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        action_param = request.query_params.get("action")
        if action_param:
            qs = qs.filter(action=action_param)
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 200), 1000))
        except (TypeError, ValueError):
            limit = 200
        qs = qs.order_by("-created_at")[:limit]
        return Response(ApprovalRequestSerializer(qs, many=True).data)


class ApprovalApproveView(APIView):
    permission_classes = [_AdminAndUpAlways]

    def post(self, request, pk):
        payload = ApprovalDecisionPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            req = approval_engine.approve_request(
                request_id=pk,
                user=request.user,
                note=payload.validated_data.get("note", ""),
            )
        except ApprovalRequest.DoesNotExist as exc:
            raise NotFound(f"ApprovalRequest {pk} not found") from exc
        except PermissionError as exc:
            from rest_framework.exceptions import PermissionDenied as _PD

            raise _PD(detail=str(exc)) from exc
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError as _VE

            raise _VE({"detail": str(exc)}) from exc
        return Response(ApprovalRequestSerializer(req).data)


class ApprovalRejectView(APIView):
    permission_classes = [_AdminAndUpAlways]

    def post(self, request, pk):
        payload = ApprovalDecisionPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            req = approval_engine.reject_request(
                request_id=pk,
                user=request.user,
                note=payload.validated_data.get("note", ""),
            )
        except ApprovalRequest.DoesNotExist as exc:
            raise NotFound(f"ApprovalRequest {pk} not found") from exc
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError as _VE

            raise _VE({"detail": str(exc)}) from exc
        return Response(ApprovalRequestSerializer(req).data)


class ApprovalEvaluateView(APIView):
    """Preview / persist an evaluation. Admin / director only.

    With ``persist=False`` (default), returns the pure evaluation; with
    ``persist=True``, runs :func:`approval_engine.enforce_or_queue` and
    returns the same shape with the persisted ``approvalRequestId``.
    """

    permission_classes = [_AdminAndUpAlways]

    def post(self, request):
        payload = ApprovalEvaluateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        action = payload.validated_data["action"]
        actor_role = (
            payload.validated_data.get("actorRole")
            or (getattr(request.user, "role", "") or "")
        )
        actor_agent = payload.validated_data.get("actorAgent") or ""
        proposed_payload = dict(payload.validated_data.get("payload") or {})
        target = dict(payload.validated_data.get("target") or {})
        persist = bool(payload.validated_data.get("persist") or False)
        reason = payload.validated_data.get("reason", "")

        if persist:
            result = approval_engine.enforce_or_queue(
                action=action,
                payload=proposed_payload,
                actor_role=actor_role,
                actor_agent=actor_agent,
                target=target,
                reason=reason,
                by_user=request.user,
            )
        else:
            result = approval_engine.evaluate_action(
                action=action,
                actor_role=actor_role,
                actor_agent=actor_agent,
                payload=proposed_payload,
                target=target,
            )
        return Response(
            {
                "action": result.action,
                "mode": result.mode,
                "approver": result.approver,
                "status": result.status,
                "allowed": result.allowed,
                "requiresHuman": result.requires_human,
                "reason": result.reason,
                "policy": dict(result.policy),
                "approvalRequestId": result.approval_request_id,
                "notes": list(result.notes),
            }
        )


class ApprovalExecuteView(APIView):
    """Phase 4D — execute an already-approved ApprovalRequest.

    Permission gating:
    - Anonymous → 401.
    - Viewer / operations → 403.
    - Admin / director → allowed for normal modes.
    - Director-only when ``policy_snapshot.mode == director_override``.
    - CAIO is always blocked (defense-in-depth — also enforced inside
      :func:`approval_execution.execute_approval_request`).
    """

    permission_classes = [_AdminAndUpAlways]

    def post(self, request, pk):
        payload_ser = ApprovalExecutePayloadSerializer(data=request.data)
        payload_ser.is_valid(raise_exception=True)
        try:
            req = ApprovalRequest.objects.get(pk=pk)
        except ApprovalRequest.DoesNotExist as exc:
            raise NotFound(f"ApprovalRequest {pk} not found") from exc

        outcome = approval_execution.execute_approval_request(
            approval_request=req,
            user=request.user,
            payload_override=payload_ser.validated_data.get("payloadOverride") or {},
        )
        return Response(outcome.as_dict(), status=outcome.http_status)


class AgentRunRequestApprovalView(APIView):
    """Promote a successful, non-CAIO AgentRun into an ApprovalRequest."""

    permission_classes = [_AdminAndUpAlways]

    def post(self, request, pk):
        payload = AgentRunApprovalRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            run = AgentRun.objects.get(pk=pk)
        except AgentRun.DoesNotExist as exc:
            raise NotFound(f"AgentRun {pk} not found") from exc
        try:
            req = approval_engine.request_approval_for_agent_run(
                agent_run=run,
                by_user=request.user,
                reason=payload.validated_data.get("reason", ""),
            )
        except PermissionError as exc:
            from rest_framework.exceptions import PermissionDenied as _PD

            raise _PD(detail=str(exc)) from exc
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError as _VE

            raise _VE({"detail": str(exc)}) from exc
        return Response(
            ApprovalRequestSerializer(req).data, status=status.HTTP_201_CREATED
        )
