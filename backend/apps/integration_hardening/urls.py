"""Phase 16E — Integration Hardening URLs.

Mounted at /api/v1/integrations/ in config/urls.py.
"""
from __future__ import annotations

from django.urls import path

from .views import (
    PaymentLogisticsReadinessView,
    PaymentLogisticsRecentEventsView,
)

app_name = "integration_hardening"

urlpatterns = [
    path(
        "payment-logistics/readiness/",
        PaymentLogisticsReadinessView.as_view(),
        name="payment-logistics-readiness",
    ),
    path(
        "payment-logistics/recent-events/",
        PaymentLogisticsRecentEventsView.as_view(),
        name="payment-logistics-recent-events",
    ),
]
