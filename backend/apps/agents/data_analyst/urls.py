"""Phase 9D — Data Analyst Agent V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
    DataAnalystSnapshotDetailView,
    DataAnalystSnapshotLatestView,
    DataAnalystSnapshotsListView,
)


app_name = "data_analyst"

urlpatterns = [
    path(
        "snapshots/",
        DataAnalystSnapshotsListView.as_view(),
        name="snapshots-list",
    ),
    path(
        "snapshots/latest/",
        DataAnalystSnapshotLatestView.as_view(),
        name="snapshots-latest",
    ),
    path(
        "snapshots/<int:pk>/",
        DataAnalystSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
]
