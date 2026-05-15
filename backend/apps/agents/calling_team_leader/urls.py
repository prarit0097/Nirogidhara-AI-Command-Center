"""Phase 9E — Calling Team Leader Agent V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
    CallingTeamLeaderSnapshotDetailView,
    CallingTeamLeaderSnapshotLatestView,
    CallingTeamLeaderSnapshotsListView,
)


app_name = "calling_team_leader"

urlpatterns = [
    path(
        "snapshots/",
        CallingTeamLeaderSnapshotsListView.as_view(),
        name="snapshots-list",
    ),
    path(
        "snapshots/latest/",
        CallingTeamLeaderSnapshotLatestView.as_view(),
        name="snapshots-latest",
    ),
    path(
        "snapshots/<int:pk>/",
        CallingTeamLeaderSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
]
