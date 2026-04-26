from __future__ import annotations

from django.urls import path

from .views import CaioAuditViewSet, CeoBriefingView

urlpatterns = [
    path("ceo-briefing/", CeoBriefingView.as_view(), name="ceo-briefing"),
    path("caio-audits/", CaioAuditViewSet.as_view({"get": "list"}), name="caio-audits"),
]
