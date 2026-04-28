from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    WhatsAppConnectionViewSet,
    WhatsAppConsentView,
    WhatsAppConversationMessagesView,
    WhatsAppConversationViewSet,
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
    path(
        "conversations/<str:pk>/messages/",
        WhatsAppConversationMessagesView.as_view(),
        name="whatsapp-conversation-messages",
    ),
] + router.urls
