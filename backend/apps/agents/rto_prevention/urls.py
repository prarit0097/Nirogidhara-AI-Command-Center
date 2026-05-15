"""Phase 9B — RTO Prevention Agent V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
    RtoPreventionCohortsView,
    RtoPreventionSnapshotDetailView,
    RtoPreventionSnapshotsListView,
)


app_name = "rto_prevention"

urlpatterns = [
    path(
        "snapshots/",
        RtoPreventionSnapshotsListView.as_view(),
        name="snapshots-list",
    ),
    path(
        "snapshots/<int:pk>/",
        RtoPreventionSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
    path(
        "cohorts/",
        RtoPreventionCohortsView.as_view(),
        name="cohorts",
    ),
]
