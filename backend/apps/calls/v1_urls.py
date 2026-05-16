"""Phase 11A — v1 read-only endpoints for the transcript ingestion pipeline.

The legacy ``/api/calls/...`` namespace (Phase 1) is unchanged. Phase
11A surfaces transcript-side metadata under ``/api/v1/calls/...`` so
the admin/director dashboard can render the backlog summary + a
per-call transcript detail without touching the Phase 1 viewset.
"""
from __future__ import annotations

from django.urls import path

from .views import (
    CallQualityScoreDetailView,
    CallQualityScoresListView,
    CallQualityScoresSummaryView,
    CallTranscriptDetailView,
    TranscriptBacklogView,
)


urlpatterns = [
    path(
        "transcript-backlog/",
        TranscriptBacklogView.as_view(),
        name="phase11a-transcript-backlog",
    ),
    path(
        "transcripts/<str:call_id>/",
        CallTranscriptDetailView.as_view(),
        name="phase11a-transcript-detail",
    ),
    # Phase 11B — Call Quality Scorer V1 (read-only).
    # Place the summary route BEFORE the <call_id> dynamic route so
    # "summary" is not captured as a Call.id.
    path(
        "quality-scores/summary/",
        CallQualityScoresSummaryView.as_view(),
        name="phase11b-quality-scores-summary",
    ),
    path(
        "quality-scores/",
        CallQualityScoresListView.as_view(),
        name="phase11b-quality-scores-list",
    ),
    path(
        "quality-scores/<str:call_id>/",
        CallQualityScoreDetailView.as_view(),
        name="phase11b-quality-score-detail",
    ),
]
