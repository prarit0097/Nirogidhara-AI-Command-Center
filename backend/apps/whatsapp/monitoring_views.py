"""Phase 5F-Gate Auto-Reply Monitoring Dashboard — DRF views.

All endpoints are strictly read-only. Each view delegates to a
selector in :mod:`apps.whatsapp.dashboard`; no business logic lives
in the view layer.

URL prefix: ``/api/whatsapp/monitoring/``. The deployed app already
exposes ``/api/whatsapp/...`` so we follow that convention rather
than introducing a parallel ``/api/v1/`` namespace; the monitoring
endpoints are scoped under ``monitoring/`` so the soak tooling and
the dashboard share the same shapes.

Permissions: every endpoint requires an authenticated user. The
overview / gate / cohort / audit endpoints additionally require
``admin`` or ``director`` because they expose redacted-but-sensitive
operational metadata (allow-list size, blocker text, audit payload
summaries).
"""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import RoleBasedPermission
from apps.accounts.permissions import ADMIN_AND_UP

from . import dashboard
from .pilot import get_whatsapp_pilot_readiness_summary


class _AdminMonitoringPermission(RoleBasedPermission):
    """Admin / director / superuser only — applies to GET as well.

    The dashboard data is benign on its own (counts + masked phones +
    blocker labels) but operational. We default to admin+ to match
    every other monitoring surface in the app
    (``WhatsAppProviderStatusView`` etc.).
    """

    allowed_roles = ADMIN_AND_UP

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        return getattr(request.user, "role", None) in self.allowed_roles


def _hours_param(request, default: float = 2.0) -> float:
    raw = request.query_params.get("hours") if hasattr(request, "query_params") else None
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _limit_param(request, default: int = 100) -> int:
    raw = request.query_params.get("limit") if hasattr(request, "query_params") else None
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class WhatsAppMonitoringOverviewView(APIView):
    """``GET /api/whatsapp/monitoring/overview/``.

    Combined dashboard payload — gate + activity + cohort + mutation +
    unexpected outbound + a derived top-level ``status`` badge. The
    frontend renders this single response without re-deriving safety
    logic.
    """

    permission_classes = [_AdminMonitoringPermission]

    def get(self, request):
        hours = _hours_param(request, default=2.0)
        return Response(
            dashboard.get_whatsapp_monitoring_dashboard(hours=hours)
        )


class WhatsAppMonitoringGateView(APIView):
    """``GET /api/whatsapp/monitoring/gate/`` — auto-reply gate readiness."""

    permission_classes = [_AdminMonitoringPermission]

    def get(self, _request):
        return Response(dashboard.get_auto_reply_gate_summary())


class WhatsAppMonitoringActivityView(APIView):
    """``GET /api/whatsapp/monitoring/activity/?hours=N`` — soak counts."""

    permission_classes = [_AdminMonitoringPermission]

    def get(self, request):
        hours = _hours_param(request, default=2.0)
        return Response(dashboard.get_recent_auto_reply_activity(hours=hours))


class WhatsAppMonitoringCohortView(APIView):
    """``GET /api/whatsapp/monitoring/cohort/`` — masked cohort readiness."""

    permission_classes = [_AdminMonitoringPermission]

    def get(self, _request):
        return Response(dashboard.get_internal_cohort_summary())


class WhatsAppMonitoringAuditView(APIView):
    """``GET /api/whatsapp/monitoring/audit/?hours=N&limit=K``."""

    permission_classes = [_AdminMonitoringPermission]

    def get(self, request):
        hours = _hours_param(request, default=2.0)
        limit = _limit_param(request, default=100)
        return Response(
            dashboard.get_recent_whatsapp_audit_events(
                hours=hours, limit=limit
            )
        )


class WhatsAppMonitoringMutationSafetyView(APIView):
    """``GET /api/whatsapp/monitoring/mutation-safety/?hours=N``."""

    permission_classes = [_AdminMonitoringPermission]

    def get(self, request):
        hours = _hours_param(request, default=2.0)
        return Response(
            dashboard.get_whatsapp_mutation_safety_summary(hours=hours)
        )


class WhatsAppMonitoringUnexpectedOutboundView(APIView):
    """``GET /api/whatsapp/monitoring/unexpected-outbound/?hours=N``."""

    permission_classes = [_AdminMonitoringPermission]

    def get(self, request):
        hours = _hours_param(request, default=2.0)
        return Response(
            dashboard.get_unexpected_outbound_summary(hours=hours)
        )


class WhatsAppMonitoringPilotView(APIView):
    """``GET /api/v1/whatsapp/monitoring/pilot/``.

    Read-only approved customer pilot readiness. No send / enable / pause
    action lives behind this endpoint.
    """

    permission_classes = [_AdminMonitoringPermission]

    def get(self, request):
        hours = _hours_param(request, default=2.0)
        return Response(get_whatsapp_pilot_readiness_summary(hours=hours))


__all__ = (
    "WhatsAppMonitoringOverviewView",
    "WhatsAppMonitoringGateView",
    "WhatsAppMonitoringActivityView",
    "WhatsAppMonitoringCohortView",
    "WhatsAppMonitoringAuditView",
    "WhatsAppMonitoringMutationSafetyView",
    "WhatsAppMonitoringUnexpectedOutboundView",
    "WhatsAppMonitoringPilotView",
)
