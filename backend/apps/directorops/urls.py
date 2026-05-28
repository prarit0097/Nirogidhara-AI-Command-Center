"""Phase 16C — Director Operations URLs (mounted at /api/v1/director-ops/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    DirectorBriefingOverviewView,
    DirectorBriefingReviewsView,
    TeamRoleAssignView,
    TeamRolesListView,
)

app_name = "directorops"

urlpatterns = [
    path(
        "briefing-overview/",
        DirectorBriefingOverviewView.as_view(),
        name="briefing-overview",
    ),
    path(
        "briefing-reviews/",
        DirectorBriefingReviewsView.as_view(),
        name="briefing-reviews",
    ),
    path(
        "team-roles/",
        TeamRolesListView.as_view(),
        name="team-roles",
    ),
    path(
        "team-roles/assign/",
        TeamRoleAssignView.as_view(),
        name="team-roles-assign",
    ),
]
