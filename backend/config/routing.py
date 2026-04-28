"""Phase 4A — top-level WebSocket URL router.

Mounts every per-app routing module that defines `websocket_urlpatterns`.
"""
from __future__ import annotations

from apps.audit.routing import websocket_urlpatterns as audit_ws_patterns

websocket_urlpatterns = list(audit_ws_patterns)
