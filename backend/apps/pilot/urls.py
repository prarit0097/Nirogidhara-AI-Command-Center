"""Phase 16F — pilot URLs (mounted at /api/v1/pilot/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    PilotDryRunDetailView,
    PilotDryRunReviewView,
    PilotDryRunsView,
    PilotReadinessView,
)

app_name = "pilot"

urlpatterns = [
    path("readiness/", PilotReadinessView.as_view(), name="readiness"),
    path("dry-runs/", PilotDryRunsView.as_view(), name="dry-runs"),
    path("dry-runs/<int:pk>/", PilotDryRunDetailView.as_view(), name="dry-run-detail"),
    path(
        "dry-runs/<int:pk>/review/",
        PilotDryRunReviewView.as_view(),
        name="dry-run-review",
    ),
]
