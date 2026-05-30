"""Root URL configuration. All API routes live under /api/."""
from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


def healthz(_request):
    return JsonResponse({"status": "ok", "service": "nirogidhara-backend"})


api_patterns = [
    path("healthz/", healthz, name="healthz"),
    path("auth/", include("apps.accounts.urls")),
    path("settings/", include("apps.accounts.settings_urls")),
    path("dashboard/", include("apps.dashboards.urls")),
    path("audit/", include("apps.audit.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("", include("apps.crm.urls")),
    path("", include("apps.orders.urls")),
    path("calls/", include("apps.calls.urls")),
    path("payments/", include("apps.payments.urls")),
    path("shipments/", include("apps.shipments.urls")),
    path("rto/", include("apps.shipments.rto_urls")),
    path("agents/", include("apps.agents.urls")),
    path("ai/", include("apps.ai_governance.urls")),
    path("compliance/", include("apps.compliance.urls")),
    path("rewards/", include("apps.rewards.urls")),
    path("learning/", include("apps.learning_engine.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("whatsapp/", include("apps.whatsapp.urls")),
    path("webhooks/", include("apps.payments.webhook_urls")),
    path("webhooks/", include("apps.shipments.webhook_urls")),
    path("webhooks/", include("apps.calls.webhook_urls")),
    path("webhooks/", include("apps.crm.webhook_urls")),
    path("webhooks/", include("apps.whatsapp.webhook_urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    # Phase 13A — Director login flow. Mounts the canonical v1 auth path
    # alongside the legacy /api/auth/token/ endpoint registered via
    # apps.accounts.urls. Frontend (api.login) targets /api/v1/auth/login/.
    path(
        "api/v1/auth/login/",
        TokenObtainPairView.as_view(),
        name="phase13a_token_obtain_pair_v1",
    ),
    path(
        "api/v1/auth/refresh/",
        TokenRefreshView.as_view(),
        name="phase13a_token_refresh_v1",
    ),
    path("api/v1/whatsapp/", include("apps.whatsapp.v1_urls")),
    path("api/v1/saas/", include("apps.saas.urls")),
    path("api/v1/mcp/", include("apps.mcp_gateway.urls")),
    path(
        "api/v1/customer-success/",
        include("apps.agents.customer_success.urls"),
    ),
    path(
        "api/v1/rto-prevention/",
        include("apps.agents.rto_prevention.urls"),
    ),
    path(
        "api/v1/cfo/",
        include("apps.agents.cfo.urls"),
    ),
    path(
        "api/v1/data-analyst/",
        include("apps.agents.data_analyst.urls"),
    ),
    path(
        "api/v1/calling-team-leader/",
        include("apps.agents.calling_team_leader.urls"),
    ),
    path(
        "api/v1/ceo-orchestration/",
        include("apps.agents.ceo_orchestration.urls"),
    ),
    path(
        "api/v1/diagnostics/",
        include("apps.diagnostics.urls"),
    ),
    path(
        "api/v1/caio/",
        include("apps.caio.urls"),
    ),
    path(
        "api/v1/learning/",
        include("apps.learning.urls"),
    ),
    path(
        "api/v1/calls/",
        include("apps.calls.v1_urls"),
    ),
    path(
        "api/v1/director-ops/",
        include("apps.directorops.urls"),
    ),
    path(
        "api/v1/imports/",
        include("apps.data_imports.urls"),
    ),
    path(
        "api/v1/integrations/",
        include("apps.integration_hardening.urls"),
    ),
    path(
        "api/v1/pilot/",
        include("apps.pilot.urls"),
    ),
    path("api/", include(api_patterns)),
]
