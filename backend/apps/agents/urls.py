from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AgentHierarchyView, AgentViewSet

router = DefaultRouter()
router.register("", AgentViewSet, basename="agent")

urlpatterns = [
    path("hierarchy/", AgentHierarchyView.as_view(), name="agent-hierarchy"),
] + router.urls
