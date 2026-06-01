"""Phase 16F + 16G — pilot URLs (mounted at /api/v1/pilot/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    PilotControlSummaryView,
    PilotDryRunDetailView,
    PilotDryRunReviewView,
    PilotDryRunsView,
    PilotExecutionSummaryView,
    PilotPlanDetailView,
    PilotPlanEventsView,
    PilotPlanReviewView,
    PilotPlansView,
    PilotPlanTasksView,
    PilotPlanTransitionView,
    PilotReadinessView,
    PilotTaskAssignView,
    PilotTaskDetailView,
    PilotTaskEventsView,
    PilotTasksView,
    PilotTaskTransitionView,
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
    # Phase 16H — internal pilot execution workbench + role-based task queues
    path("execution/summary/", PilotExecutionSummaryView.as_view(), name="execution-summary"),
    path("plans/<int:pk>/tasks/", PilotPlanTasksView.as_view(), name="plan-tasks"),
    path("tasks/", PilotTasksView.as_view(), name="tasks"),
    path("tasks/<int:pk>/", PilotTaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:pk>/transition/", PilotTaskTransitionView.as_view(), name="task-transition"),
    path("tasks/<int:pk>/assign/", PilotTaskAssignView.as_view(), name="task-assign"),
    path("tasks/<int:pk>/events/", PilotTaskEventsView.as_view(), name="task-events"),
]
