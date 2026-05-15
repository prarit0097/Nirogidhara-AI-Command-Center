"""Phase 9F — CEO AI Orchestration V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
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
    path(
        "snapshots/<int:pk>/",
        CeoOrchestrationSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
]
