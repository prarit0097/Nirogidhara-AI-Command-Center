from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission

from . import services
from .models import AgentRun, CaioAudit, CeoBriefing
from .serializers import (
    AgentRunCreateSerializer,
    AgentRunSerializer,
    CaioAuditSerializer,
    CeoBriefingSerializer,
)


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
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = ADMIN_AND_UP

    def get_permissions(self):
        # Phase 3A: even reads on AgentRun are admin-only because the
        # output_payload may include sensitive operational suggestions.
        # Override the default IsAuthenticatedOrReadOnly behaviour.
        return [_AdminAndUpAlways()]

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


class _AdminAndUpAlways(RoleBasedPermission):
    """Tighten the role check so reads also require admin/director."""

    allowed_roles = ADMIN_AND_UP

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        return getattr(request.user, "role", None) in self.allowed_roles
