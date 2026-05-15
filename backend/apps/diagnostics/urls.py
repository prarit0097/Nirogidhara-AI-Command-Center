"""Phase 10A — Diagnostics URL configuration."""
from __future__ import annotations

from django.urls import path

from .views import PendingPaymentsDrilldownView


app_name = "diagnostics"

urlpatterns = [
    path(
        "pending-payments/",
        PendingPaymentsDrilldownView.as_view(),
        name="pending-payments",
    ),
]
