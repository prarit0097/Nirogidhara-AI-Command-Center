from __future__ import annotations

from django.urls import path

from .webhooks import MetaLeadsWebhookView

urlpatterns = [
    path("meta/leads/", MetaLeadsWebhookView.as_view(), name="meta-leads-webhook"),
]
