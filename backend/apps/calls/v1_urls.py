"""Phase 11A — v1 read-only endpoints for the transcript ingestion pipeline.

The legacy ``/api/calls/...`` namespace (Phase 1) is unchanged. Phase
11A surfaces transcript-side metadata under ``/api/v1/calls/...`` so
the admin/director dashboard can render the backlog summary + a
per-call transcript detail without touching the Phase 1 viewset.
"""
from __future__ import annotations

from django.urls import path

from .views import CallTranscriptDetailView, TranscriptBacklogView


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
]
