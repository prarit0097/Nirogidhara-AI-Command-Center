"""Phase 11A — v1 read-only endpoints for the transcript ingestion pipeline.

The legacy ``/api/calls/...`` namespace (Phase 1) is unchanged. Phase
11A surfaces transcript-side metadata under ``/api/v1/calls/...`` so
the admin/director dashboard can render the backlog summary + a
per-call transcript detail without touching the Phase 1 viewset.
"""
from __future__ import annotations

from django.urls import path

from .views import (
    AiCallCampaignGateDetailView,
    AiCallCampaignGateLatestView,
    AiCallCampaignGateListView,
    CallOutcomeRecordDetailView,
    CallOutcomeRecordsListView,
    CallOutcomeRecordsSummaryView,
    CallQualityScoreDetailView,
    CallQualityScoresListView,
    CallQualityScoresSummaryView,
    CallTranscriptDetailView,
    PostCallFollowUpDetailView,
    PostCallFollowUpListView,
    PostCallFollowUpSummaryView,
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
    # Phase 12A — AI Calling Campaign Gates (read-only).
    # ``latest/`` is registered BEFORE the dynamic ``<int:pk>`` route
    # so "latest" is never captured as a campaign id.
    path(
        "campaigns/latest/",
        AiCallCampaignGateLatestView.as_view(),
        name="phase12a-campaign-latest",
    ),
    path(
        "campaigns/",
        AiCallCampaignGateListView.as_view(),
        name="phase12a-campaigns-list",
    ),
    path(
        "campaigns/<int:pk>/",
        AiCallCampaignGateDetailView.as_view(),
        name="phase12a-campaign-detail",
    ),
    # Phase 12B — Call Outcome Records (read-only).
    # ``summary/`` is registered BEFORE the dynamic ``<int:pk>`` route
    # so it is never captured as a record id.
    path(
        "outcomes/summary/",
        CallOutcomeRecordsSummaryView.as_view(),
        name="phase12b-outcomes-summary",
    ),
    path(
        "outcomes/",
        CallOutcomeRecordsListView.as_view(),
        name="phase12b-outcomes-list",
    ),
    path(
        "outcomes/<int:pk>/",
        CallOutcomeRecordDetailView.as_view(),
        name="phase12b-outcome-detail",
    ),
    # Phase 12C — Post-Call Follow-up Queue (read-only).
    # ``summary/`` is registered BEFORE the dynamic ``<int:pk>`` route
    # so it is never captured as a follow-up id.
    path(
        "followups/summary/",
        PostCallFollowUpSummaryView.as_view(),
        name="phase12c-followups-summary",
    ),
    path(
        "followups/",
        PostCallFollowUpListView.as_view(),
        name="phase12c-followups-list",
    ),
    path(
        "followups/<int:pk>/",
        PostCallFollowUpDetailView.as_view(),
        name="phase12c-followup-detail",
    ),
]
