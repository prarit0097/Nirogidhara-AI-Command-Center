"""Phase 11D — Learning Loop Gate read-only URL routes."""
from __future__ import annotations

from django.urls import path

from .views import (
    LearningProposalDetailView,
    LearningProposalsListView,
    LearningProposalsPendingView,
    LearningProposalsSummaryView,
)


urlpatterns = [
    # ``summary/`` and ``pending/`` are registered BEFORE the dynamic
    # ``<int:pk>`` route so they are never captured as proposal ids.
    path(
        "proposals/summary/",
        LearningProposalsSummaryView.as_view(),
        name="learning-proposals-summary",
    ),
    path(
        "proposals/pending/",
        LearningProposalsPendingView.as_view(),
        name="learning-proposals-pending",
    ),
    path(
        "proposals/",
        LearningProposalsListView.as_view(),
        name="learning-proposals-list",
    ),
    path(
        "proposals/<int:pk>/",
        LearningProposalDetailView.as_view(),
        name="learning-proposal-detail",
    ),
]
