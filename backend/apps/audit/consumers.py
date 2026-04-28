"""Phase 4A — Audit event WebSocket consumer.

Endpoint: ``ws://<host>/ws/audit/events/``.

Initial Phase 4A auth rule (per locked Prarit decision): allow connect
in development. If a JWT is supplied as the ``token`` query string we
validate it and attach the user; otherwise we accept the connection so
the dashboard / governance read-only stream keeps working — the existing
HTTP polling endpoint is also public, so this stays consistent.

Compliance hard stop preserved: the consumer never executes business
actions and never alters AuditEvent rows. It is read-and-fanout only.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .realtime import AUDIT_GROUP_NAME, latest_events


logger = logging.getLogger(__name__)


@database_sync_to_async
def _resolve_user_from_token(raw_token: str):
    """Resolve a JWT token to a Django user. Returns ``None`` on any failure."""
    if not raw_token:
        return None
    try:
        from rest_framework_simplejwt.authentication import JWTAuthentication

        authenticator = JWTAuthentication()
        validated = authenticator.get_validated_token(raw_token)
        return authenticator.get_user(validated)
    except Exception as exc:  # noqa: BLE001 — never block dev usage
        logger.debug("ws audit token validation failed: %s", exc)
        return None


@database_sync_to_async
def _initial_snapshot() -> list[dict[str, Any]]:
    return latest_events()


class AuditEventConsumer(AsyncJsonWebsocketConsumer):
    """Read-only fanout of every newly-committed :class:`AuditEvent`."""

    groups = ()  # set per-connection in connect() so we always join the same group

    async def connect(self) -> None:
        # Optional JWT in the query string — best-effort attach for telemetry.
        query_string = (self.scope.get("query_string") or b"").decode("utf-8")
        params = parse_qs(query_string)
        raw_token = (params.get("token") or [""])[0]
        user = await _resolve_user_from_token(raw_token)
        self.scope["user"] = user  # may be None — that's fine in dev

        await self.channel_layer.group_add(AUDIT_GROUP_NAME, self.channel_name)
        await self.accept()

        try:
            snapshot = await _initial_snapshot()
        except Exception as exc:  # noqa: BLE001 — never crash on snapshot read
            logger.warning("audit snapshot fetch failed: %s", exc)
            snapshot = []

        await self.send_json(
            {"type": "audit.snapshot", "events": snapshot}
        )

    async def disconnect(self, code) -> None:  # noqa: D401, ARG002
        try:
            await self.channel_layer.group_discard(
                AUDIT_GROUP_NAME, self.channel_name
            )
        except Exception:  # noqa: BLE001 — best effort cleanup
            pass

    # Group-message handler — name MUST match the ``type`` field used by
    # ``apps.audit.realtime.publish_audit_event``.
    async def audit_event_broadcast(self, message: dict[str, Any]) -> None:
        try:
            await self.send_json(
                {"type": "audit.event", "event": message.get("event") or {}}
            )
        except Exception as exc:  # noqa: BLE001 — keep socket alive
            logger.debug("audit ws send failed: %s", exc)

    # Permissive receive — consumer is read-only; ignore anything inbound.
    async def receive_json(self, content, **kwargs):  # noqa: ARG002
        # Support a lightweight ping for clients that want to check liveness.
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    @classmethod
    async def encode_json(cls, content) -> str:
        # Lock down JSON encoding — datetimes are pre-formatted in
        # ``serialize_event`` so the default encoder is fine.
        return json.dumps(content, default=str)


__all__ = ("AuditEventConsumer",)
