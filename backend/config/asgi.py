"""ASGI entrypoint.

Phase 4A — routes HTTP through Django and WebSocket through the
Channels URLRouter so live AuditEvent streams (`/ws/audit/events/`)
work alongside the existing DRF endpoints.
"""
from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()


from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

from .routing import websocket_urlpatterns  # noqa: E402


http_application = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
