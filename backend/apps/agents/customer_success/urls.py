"""Phase 9A — Customer Success / Reorder Agent V1 URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import (
    CustomerSuccessCohortsView,
    CustomerSuccessSnapshotDetailView,
    CustomerSuccessSnapshotsListView,
)


app_name = "customer_success"

urlpatterns = [
    path(
        "snapshots/",
        CustomerSuccessSnapshotsListView.as_view(),
        name="snapshots-list",
    ),
    path(
        "snapshots/<int:pk>/",
        CustomerSuccessSnapshotDetailView.as_view(),
        name="snapshots-detail",
    ),
    path(
        "cohorts/",
        CustomerSuccessCohortsView.as_view(),
        name="cohorts",
    ),
]
