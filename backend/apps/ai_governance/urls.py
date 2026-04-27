from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AgentRunViewSet, CaioAuditViewSet, CeoBriefingView

router = DefaultRouter()
router.register("agent-runs", AgentRunViewSet, basename="agent-run")

urlpatterns = [
    path("ceo-briefing/", CeoBriefingView.as_view(), name="ceo-briefing"),
    path("caio-audits/", CaioAuditViewSet.as_view({"get": "list"}), name="caio-audits"),
] + router.urls
