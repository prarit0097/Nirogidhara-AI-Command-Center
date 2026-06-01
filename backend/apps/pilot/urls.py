"""Phase 16F + 16G — pilot URLs (mounted at /api/v1/pilot/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    PilotControlSummaryView,
    PilotDryRunDetailView,
    PilotDryRunReviewView,
    PilotDryRunsView,
    PilotPlanDetailView,
    PilotPlanEventsView,
    PilotPlanReviewView,
    PilotPlansView,
    PilotPlanTransitionView,
    PilotReadinessView,
)

app_name = "pilot"

urlpatterns = [
    # Phase 16F — readiness + dry-runs
    path("readiness/", PilotReadinessView.as_view(), name="readiness"),
    path("dry-runs/", PilotDryRunsView.as_view(), name="dry-runs"),
    path("dry-runs/<int:pk>/", PilotDryRunDetailView.as_view(), name="dry-run-detail"),
    path(
        "dry-runs/<int:pk>/review/",
        PilotDryRunReviewView.as_view(),
        name="dry-run-review",
    ),
    # Phase 16G — internal pilot control center
    path("control/summary/", PilotControlSummaryView.as_view(), name="control-summary"),
    path("plans/", PilotPlansView.as_view(), name="plans"),
    path("plans/<int:pk>/", PilotPlanDetailView.as_view(), name="plan-detail"),
    path(
        "plans/<int:pk>/transition/",
        PilotPlanTransitionView.as_view(),
        name="plan-transition",
    ),
    path("plans/<int:pk>/review/", PilotPlanReviewView.as_view(), name="plan-review"),
    path("plans/<int:pk>/events/", PilotPlanEventsView.as_view(), name="plan-events"),
]
