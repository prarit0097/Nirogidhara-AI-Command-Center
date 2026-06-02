"""Phase 16I — AI Copilot URLs (mounted at /api/v1/ai-copilot/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    AiActionApplyView,
    AiActionCancelView,
    AiActionDetailView,
    AiActionFromSuggestionView,
    AiActionQueueView,
    AiActionRejectView,
    AiActionSummaryView,
    AiCopilotGenerateView,
    AiCopilotReviewView,
    AiCopilotStatusView,
    AiCopilotSuggestionDetailView,
    AiCopilotSuggestionsView,
)

app_name = "ai_copilot"

urlpatterns = [
    path("status/", AiCopilotStatusView.as_view(), name="status"),
    path("suggestions/", AiCopilotSuggestionsView.as_view(), name="suggestions"),
    path(
        "suggestions/generate/",
        AiCopilotGenerateView.as_view(),
        name="suggestions-generate",
    ),
    path(
        "suggestions/<int:pk>/",
        AiCopilotSuggestionDetailView.as_view(),
        name="suggestion-detail",
    ),
    path(
        "suggestions/<int:pk>/review/",
        AiCopilotReviewView.as_view(),
        name="suggestion-review",
    ),
    # Phase 16J — AI-approved internal action queue + work execution bridge
    path("actions/", AiActionQueueView.as_view(), name="actions"),
    path(
        "actions/from-suggestion/",
        AiActionFromSuggestionView.as_view(),
        name="actions-from-suggestion",
    ),
    path("actions/summary/", AiActionSummaryView.as_view(), name="actions-summary"),
    path("actions/<int:pk>/", AiActionDetailView.as_view(), name="action-detail"),
    path("actions/<int:pk>/apply/", AiActionApplyView.as_view(), name="action-apply"),
    path("actions/<int:pk>/reject/", AiActionRejectView.as_view(), name="action-reject"),
    path("actions/<int:pk>/cancel/", AiActionCancelView.as_view(), name="action-cancel"),
]
