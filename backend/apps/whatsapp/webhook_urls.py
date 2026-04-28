from __future__ import annotations

from django.urls import path

from .webhooks import WhatsAppMetaWebhookView

urlpatterns = [
    path(
        "whatsapp/meta/",
        WhatsAppMetaWebhookView.as_view(),
        name="whatsapp-meta-webhook",
    ),
]
