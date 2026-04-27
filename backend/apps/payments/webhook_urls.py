from __future__ import annotations

from django.urls import path

from .webhooks import RazorpayWebhookView

urlpatterns = [
    path("razorpay/", RazorpayWebhookView.as_view(), name="razorpay-webhook"),
]
