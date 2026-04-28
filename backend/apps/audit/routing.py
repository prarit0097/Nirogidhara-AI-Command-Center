"""Phase 4A — WebSocket URL routes for the audit app."""
from __future__ import annotations

from django.urls import path

from .consumers import AuditEventConsumer


websocket_urlpatterns = [
    path("ws/audit/events/", AuditEventConsumer.as_asgi()),
]
