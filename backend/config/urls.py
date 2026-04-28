"""Root URL configuration. All API routes live under /api/."""
from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok", "service": "nirogidhara-backend"})


api_patterns = [
    path("healthz/", healthz, name="healthz"),
    path("auth/", include("apps.accounts.urls")),
    path("settings/", include("apps.accounts.settings_urls")),
    path("dashboard/", include("apps.dashboards.urls")),
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
    path("api/", include(api_patterns)),
]
