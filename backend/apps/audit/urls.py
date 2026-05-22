"""Phase 15C — audit app URL config.

Only the read-only timeline endpoint is exposed here. The live
WebSocket fan-out is mounted via ``apps.audit.routing`` from the
Channels router (see ``config/routing.py``).
"""
from __future__ import annotations

from django.urls import path

from .views import AuditTimelineView

urlpatterns = [
    path("timeline/", AuditTimelineView.as_view(), name="audit-timeline"),
]
