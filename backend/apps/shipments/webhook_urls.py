from __future__ import annotations

from django.urls import path

from .webhooks import DelhiveryWebhookView

urlpatterns = [
    path("delhivery/", DelhiveryWebhookView.as_view(), name="delhivery-webhook"),
]
