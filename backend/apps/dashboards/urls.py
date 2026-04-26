from __future__ import annotations

from django.urls import path

from .views import ActivityFeedView, DashboardMetricsView

urlpatterns = [
    path("metrics/", DashboardMetricsView.as_view(), name="dashboard-metrics"),
    path("activity/", ActivityFeedView.as_view(), name="dashboard-activity"),
]
