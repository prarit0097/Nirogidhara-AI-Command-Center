from __future__ import annotations

from django.urls import path

from .webhooks import VapiWebhookView

urlpatterns = [
    path("vapi/", VapiWebhookView.as_view(), name="vapi-webhook"),
]
