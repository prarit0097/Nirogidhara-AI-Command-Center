"""Phase 9F — CEO AI Orchestration V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
    CeoOrchestrationSidebarStatusView,
    CeoOrchestrationSnapshotDetailView,
    CeoOrchestrationSnapshotLatestView,
    CeoOrchestrationSnapshotsListView,
)


app_name = "ceo_orchestration"

urlpatterns = [
    path(
        "snapshots/",
        CeoOrchestrationSnapshotsListView.as_view(),
        name="snapshots-list",
    ),
    path(
        "snapshots/latest/",
        CeoOrchestrationSnapshotLatestView.as_view(),
        name="snapshots-latest",
    ),
    # Phase 15B — slimmer sidebar-badge endpoint. Admin/director only.
    # See views.CeoOrchestrationSidebarStatusView for the safety
    # contract (no briefing body, no provider call, no Celery
    # enqueue, no AuditEvent write).
    path(
        "snapshots/sidebar-status/",
        CeoOrchestrationSidebarStatusView.as_view(),
        name="snapshots-sidebar-status",
    ),
    path(
        "snapshots/<int:pk>/",
        CeoOrchestrationSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
]
