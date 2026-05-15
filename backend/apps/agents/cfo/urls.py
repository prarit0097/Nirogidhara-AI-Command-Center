"""Phase 9C — CFO Agent V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
    CfoLatestSnapshotView,
    CfoSnapshotDetailView,
    CfoSnapshotsListView,
)


app_name = "cfo"

urlpatterns = [
    path(
        "snapshots/",
        CfoSnapshotsListView.as_view(),
        name="snapshots-list",
    ),
    path(
        "snapshots/<int:pk>/",
        CfoSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
    path(
        "latest/",
        CfoLatestSnapshotView.as_view(),
        name="latest",
    ),
]
