from __future__ import annotations

from django.urls import path

from .monitoring_views import (
    WhatsAppMonitoringOverviewView,
    WhatsAppMonitoringPilotView,
)

urlpatterns = [
    path(
        "monitoring/overview/",
        WhatsAppMonitoringOverviewView.as_view(),
        name="v1-whatsapp-monitoring-overview",
    ),
    path(
        "monitoring/pilot/",
        WhatsAppMonitoringPilotView.as_view(),
        name="v1-whatsapp-monitoring-pilot",
    ),
]
