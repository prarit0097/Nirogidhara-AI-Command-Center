from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    WhatsAppAiStatusView,
    WhatsAppConnectionViewSet,
    WhatsAppConsentView,
    WhatsAppConversationAiModeView,
    WhatsAppConversationAiRunsView,
    WhatsAppConversationHandoffToCallView,
    WhatsAppConversationHandoffView,
    WhatsAppConversationHandoffsListView,
    WhatsAppConversationMarkReadView,
    WhatsAppConversationMessagesView,
    WhatsAppConversationNotesView,
    WhatsAppConversationResumeAiView,
    WhatsAppConversationRunAiView,
    WhatsAppConversationSendTemplateView,
    WhatsAppConversationViewSet,
    WhatsAppCustomerTimelineView,
    WhatsAppInboxView,
    WhatsAppLifecycleEventsListView,
    WhatsAppReorderDay20RunView,
    WhatsAppReorderDay20StatusView,
    WhatsAppMessageRetryView,
    WhatsAppMessageViewSet,
    WhatsAppProviderStatusView,
    WhatsAppSendTemplateView,
    WhatsAppTemplateSyncView,
    WhatsAppTemplateViewSet,
)

router = DefaultRouter()
router.register("connections", WhatsAppConnectionViewSet, basename="whatsapp-connection")
router.register("templates", WhatsAppTemplateViewSet, basename="whatsapp-template")
router.register("conversations", WhatsAppConversationViewSet, basename="whatsapp-conversation")
router.register("messages", WhatsAppMessageViewSet, basename="whatsapp-message")

urlpatterns = [
    path("provider/status/", WhatsAppProviderStatusView.as_view(), name="whatsapp-provider-status"),
    path("send-template/", WhatsAppSendTemplateView.as_view(), name="whatsapp-send-template"),
    path("templates/sync/", WhatsAppTemplateSyncView.as_view(), name="whatsapp-templates-sync"),
    path(
        "messages/<str:pk>/retry/",
        WhatsAppMessageRetryView.as_view(),
        name="whatsapp-message-retry",
    ),
    path(
        "consent/<str:customer_id>/",
        WhatsAppConsentView.as_view(),
        name="whatsapp-consent",
    ),
    # Phase 5B — Inbox / Customer 360 endpoints.
    path("inbox/", WhatsAppInboxView.as_view(), name="whatsapp-inbox"),
    path(
        "conversations/<str:pk>/messages/",
        WhatsAppConversationMessagesView.as_view(),
        name="whatsapp-conversation-messages",
    ),
    path(
        "conversations/<str:pk>/notes/",
        WhatsAppConversationNotesView.as_view(),
        name="whatsapp-conversation-notes",
    ),
    path(
        "conversations/<str:pk>/mark-read/",
        WhatsAppConversationMarkReadView.as_view(),
        name="whatsapp-conversation-mark-read",
    ),
    path(
        "conversations/<str:pk>/send-template/",
        WhatsAppConversationSendTemplateView.as_view(),
        name="whatsapp-conversation-send-template",
    ),
    path(
        "customers/<str:customer_id>/timeline/",
        WhatsAppCustomerTimelineView.as_view(),
        name="whatsapp-customer-timeline",
    ),
    # Phase 5C — WhatsApp AI Chat Sales Agent.
    path("ai/status/", WhatsAppAiStatusView.as_view(), name="whatsapp-ai-status"),
    path(
        "conversations/<str:pk>/ai-mode/",
        WhatsAppConversationAiModeView.as_view(),
        name="whatsapp-conversation-ai-mode",
    ),
    path(
        "conversations/<str:pk>/run-ai/",
        WhatsAppConversationRunAiView.as_view(),
        name="whatsapp-conversation-run-ai",
    ),
    path(
        "conversations/<str:pk>/ai-runs/",
        WhatsAppConversationAiRunsView.as_view(),
        name="whatsapp-conversation-ai-runs",
    ),
    path(
        "conversations/<str:pk>/handoff/",
        WhatsAppConversationHandoffView.as_view(),
        name="whatsapp-conversation-handoff",
    ),
    path(
        "conversations/<str:pk>/resume-ai/",
        WhatsAppConversationResumeAiView.as_view(),
        name="whatsapp-conversation-resume-ai",
    ),
    # Phase 5D — Chat-to-call handoff + lifecycle visibility.
    path(
        "conversations/<str:pk>/handoff-to-call/",
        WhatsAppConversationHandoffToCallView.as_view(),
        name="whatsapp-conversation-handoff-to-call",
    ),
    path(
        "conversations/<str:pk>/handoffs/",
        WhatsAppConversationHandoffsListView.as_view(),
        name="whatsapp-conversation-handoffs",
    ),
    path(
        "lifecycle-events/",
        WhatsAppLifecycleEventsListView.as_view(),
        name="whatsapp-lifecycle-events",
    ),
    # Phase 5E — Day-20 reorder admin endpoints.
    path(
        "reorder/day20/status/",
        WhatsAppReorderDay20StatusView.as_view(),
        name="whatsapp-reorder-day20-status",
    ),
    path(
        "reorder/day20/run/",
        WhatsAppReorderDay20RunView.as_view(),
        name="whatsapp-reorder-day20-run",
    ),
] + router.urls
