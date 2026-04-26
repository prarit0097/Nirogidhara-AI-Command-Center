from __future__ import annotations

from django.urls import path

from .views import (
    AnalyticsCompositeView,
    FunnelView,
    ProductPerformanceView,
    RevenueTrendView,
    StateRtoView,
)

urlpatterns = [
    path("", AnalyticsCompositeView.as_view(), name="analytics-composite"),
    path("funnel/", FunnelView.as_view(), name="analytics-funnel"),
    path("revenue-trend/", RevenueTrendView.as_view(), name="analytics-revenue-trend"),
    path("state-rto/", StateRtoView.as_view(), name="analytics-state-rto"),
    path("product-performance/", ProductPerformanceView.as_view(), name="analytics-product-performance"),
]
