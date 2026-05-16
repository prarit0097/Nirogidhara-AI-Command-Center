"""Phase 11C — CAIO read-only URL routes."""
from __future__ import annotations

from django.urls import path

from .views import (
    CaioSnapshotDetailView,
    CaioSnapshotLatestView,
    CaioSnapshotsListView,
)


urlpatterns = [
    # ``latest/`` is registered BEFORE the dynamic ``<int:pk>`` route so
    # "latest" is never interpreted as a snapshot id.
    path(
        "snapshots/latest/",
        CaioSnapshotLatestView.as_view(),
        name="caio-snapshot-latest",
    ),
    path(
        "snapshots/",
        CaioSnapshotsListView.as_view(),
        name="caio-snapshots-list",
    ),
    path(
        "snapshots/<int:pk>/",
        CaioSnapshotDetailView.as_view(),
        name="caio-snapshot-detail",
    ),
]
