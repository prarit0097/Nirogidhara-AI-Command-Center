"""Phase 16I — AI Copilot URLs (mounted at /api/v1/ai-copilot/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    AiActionApplyView,
    AiActionAssignView,
    AiActionBlockView,
    AiActionCancelView,
    AiActionClaimView,
    AiActionCompleteInternalView,
    AiActionDetailView,
    AiActionFromSuggestionView,
    AiActionNotesView,
    AiActionQueueView,
    AiActionReassignView,
    AiActionRejectView,
    AiActionStartView,
    AiActionSummaryView,
    AiActionUnblockView,
    AiCopilotGenerateView,
    AiCopilotReviewView,
    AiCopilotStatusView,
    AiCopilotSuggestionDetailView,
    AiCopilotSuggestionsView,
    AiDepartmentMemberActivateView,
    AiDepartmentMemberDeactivateView,
    AiDepartmentMembersView,
    AiMyWorkPermissionsView,
    AiMyWorkSummaryView,
    AiMyWorkView,
    AiDirectorBriefingRecommendationsView,
    AiDirectorBriefingSnapshotAcknowledgeView,
    AiDirectorBriefingSnapshotArchiveView,
    AiDirectorBriefingSnapshotDetailView,
    AiDirectorBriefingSnapshotNeedsFollowUpView,
    AiDirectorBriefingSnapshotNotesView,
    AiDirectorBriefingSnapshotSafeTextView,
    AiDirectorBriefingSnapshotsView,
    AiDirectorBriefingSnapshotSummaryView,
    AiDirectorBriefingSummaryView,
    AiDirectorBriefingView,
    AiWorkboardAnalyticsView,
    AiWorkboardDirectorAttentionView,
    AiWorkboardSummaryView,
    AiWorkboardView,
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
    # Phase 16K — department action workboard + ownership / SLA execution layer
    path("workboard/", AiWorkboardView.as_view(), name="workboard"),
    path("workboard/summary/", AiWorkboardSummaryView.as_view(), name="workboard-summary"),
    path(
        "workboard/director-attention/",
        AiWorkboardDirectorAttentionView.as_view(),
        name="workboard-director-attention",
    ),
    # Phase 16M — workboard analytics + SLA throughput dashboard (read-only)
    path(
        "workboard/analytics/",
        AiWorkboardAnalyticsView.as_view(),
        name="workboard-analytics",
    ),
    # Phase 16N — Director AI daily briefing + safe recommendation pack (read-only)
    path(
        "director-briefing/",
        AiDirectorBriefingView.as_view(),
        name="director-briefing",
    ),
    path(
        "director-briefing/summary/",
        AiDirectorBriefingSummaryView.as_view(),
        name="director-briefing-summary",
    ),
    path(
        "director-briefing/recommendations/",
        AiDirectorBriefingRecommendationsView.as_view(),
        name="director-briefing-recommendations",
    ),
    # Phase 16O — Director briefing snapshot history + acknowledgement trail
    path(
        "director-briefing/snapshots/",
        AiDirectorBriefingSnapshotsView.as_view(),
        name="director-briefing-snapshots",
    ),
    path(
        "director-briefing/snapshots/summary/",
        AiDirectorBriefingSnapshotSummaryView.as_view(),
        name="director-briefing-snapshots-summary",
    ),
    path(
        "director-briefing/snapshots/<int:pk>/",
        AiDirectorBriefingSnapshotDetailView.as_view(),
        name="director-briefing-snapshot-detail",
    ),
    path(
        "director-briefing/snapshots/<int:pk>/acknowledge/",
        AiDirectorBriefingSnapshotAcknowledgeView.as_view(),
        name="director-briefing-snapshot-acknowledge",
    ),
    path(
        "director-briefing/snapshots/<int:pk>/needs-follow-up/",
        AiDirectorBriefingSnapshotNeedsFollowUpView.as_view(),
        name="director-briefing-snapshot-needs-follow-up",
    ),
    path(
        "director-briefing/snapshots/<int:pk>/archive/",
        AiDirectorBriefingSnapshotArchiveView.as_view(),
        name="director-briefing-snapshot-archive",
    ),
    path(
        "director-briefing/snapshots/<int:pk>/notes/",
        AiDirectorBriefingSnapshotNotesView.as_view(),
        name="director-briefing-snapshot-notes",
    ),
    path(
        "director-briefing/snapshots/<int:pk>/safe-text/",
        AiDirectorBriefingSnapshotSafeTextView.as_view(),
        name="director-briefing-snapshot-safe-text",
    ),
    # Phase 16L — scoped team member work permissions + My Work queue
    path("workboard/my/", AiMyWorkView.as_view(), name="workboard-my"),
    path("workboard/my/summary/", AiMyWorkSummaryView.as_view(), name="workboard-my-summary"),
    path(
        "workboard/my-permissions/",
        AiMyWorkPermissionsView.as_view(),
        name="workboard-my-permissions",
    ),
    path(
        "workboard/department-members/",
        AiDepartmentMembersView.as_view(),
        name="workboard-department-members",
    ),
    path(
        "workboard/department-members/<int:pk>/activate/",
        AiDepartmentMemberActivateView.as_view(),
        name="workboard-department-member-activate",
    ),
    path(
        "workboard/department-members/<int:pk>/deactivate/",
        AiDepartmentMemberDeactivateView.as_view(),
        name="workboard-department-member-deactivate",
    ),
    path("actions/<int:pk>/assign/", AiActionAssignView.as_view(), name="action-assign"),
    path("actions/<int:pk>/claim/", AiActionClaimView.as_view(), name="action-claim"),
    path("actions/<int:pk>/start/", AiActionStartView.as_view(), name="action-start"),
    path("actions/<int:pk>/block/", AiActionBlockView.as_view(), name="action-block"),
    path("actions/<int:pk>/unblock/", AiActionUnblockView.as_view(), name="action-unblock"),
    path(
        "actions/<int:pk>/complete-internal/",
        AiActionCompleteInternalView.as_view(),
        name="action-complete-internal",
    ),
    path("actions/<int:pk>/reassign/", AiActionReassignView.as_view(), name="action-reassign"),
    path("actions/<int:pk>/notes/", AiActionNotesView.as_view(), name="action-notes"),
]
