"""Phase 16I — AI Copilot URLs (mounted at /api/v1/ai-copilot/)."""
from __future__ import annotations

from django.urls import path

from .views import (
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
]
