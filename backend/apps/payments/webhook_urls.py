from __future__ import annotations

from django.urls import path

from .webhooks import RazorpayTestWebhookView, RazorpayWebhookView

urlpatterns = [
    path("razorpay/", RazorpayWebhookView.as_view(), name="razorpay-webhook"),
    # Phase 6M — test-mode handler. Public endpoint; authenticates via
    # HMAC-SHA256 of the raw body using ``RAZORPAY_WEBHOOK_SECRET``.
    path(
        "razorpay/test/",
        RazorpayTestWebhookView.as_view(),
        name="razorpay-webhook-test",
    ),
]
