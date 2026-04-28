"""Phase 4A — Realtime AuditEvent WebSocket tests.

Covers:
- ``serialize_event`` returns the camelCase shape the frontend expects,
  including the full stored ``payload``.
- ``latest_events`` returns the freshest 25 rows.
- ``publish_audit_event`` schedules a fan-out via
  ``transaction.on_commit`` and never raises when the channel layer
  blows up.
- The ``AuditEventConsumer`` accepts a connection, sends an initial
  ``audit.snapshot`` frame, and forwards new events as ``audit.event``
  frames.
- Existing ``GET /api/dashboard/activity/`` keeps working.
- ``post_save`` publish does not break ``AuditEvent.objects.create`` even
  if the channel layer is broken.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.audit.consumers import AuditEventConsumer
from apps.audit.models import AuditEvent
from apps.audit.realtime import (
    AUDIT_GROUP_NAME,
    latest_events,
    publish_audit_event,
    serialize_event,
)
from apps.audit.routing import websocket_urlpatterns


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_application() -> URLRouter:
    return URLRouter(websocket_urlpatterns)


# ---------------------------------------------------------------------------
# 1. Serializer shape
# ---------------------------------------------------------------------------


def test_serialize_event_includes_full_payload() -> None:
    event = AuditEvent.objects.create(
        kind="test.kind",
        text="hello",
        tone=AuditEvent.Tone.INFO,
        icon="bell",
        payload={"approval_id": "APR-1", "actor_role": "admin", "amount": 499},
    )
    out = serialize_event(event)
    assert out["id"] == event.pk
    assert out["kind"] == "test.kind"
    assert out["text"] == "hello"
    assert out["tone"] == "info"
    assert out["icon"] == "bell"
    assert out["payload"] == {
        "approval_id": "APR-1",
        "actor_role": "admin",
        "amount": 499,
    }
    assert "createdAt" in out
    assert "time" in out


def test_latest_events_returns_recent_rows() -> None:
    for idx in range(30):
        AuditEvent.objects.create(
            kind="test.k", text=f"e{idx}", tone="info", icon="bell"
        )
    rows = latest_events()
    assert len(rows) == 25
    # newest first
    assert rows[0]["text"] == "e29"


# ---------------------------------------------------------------------------
# 2. publish_audit_event resilience
# ---------------------------------------------------------------------------


def test_publish_audit_event_swallows_channel_layer_failure() -> None:
    """An exploding channel layer must not break the underlying DB write."""
    event = AuditEvent.objects.create(
        kind="test.fail", text="boom", tone="info", icon="bell"
    )

    with patch(
        "apps.audit.realtime.get_channel_layer",
        side_effect=RuntimeError("channels broken"),
    ):
        # Should not raise.
        publish_audit_event(event)


def test_post_save_publish_does_not_break_event_creation() -> None:
    """A broken channel layer must not block ``AuditEvent.objects.create``."""

    with patch(
        "apps.audit.realtime.get_channel_layer",
        side_effect=RuntimeError("channels broken"),
    ):
        # If the publisher leaks, this would raise.
        AuditEvent.objects.create(
            kind="test.broken_layer", text="still ok", tone="info", icon="bell"
        )


# ---------------------------------------------------------------------------
# 3. Consumer — connect, snapshot, broadcast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_connect_sends_snapshot(transactional_db) -> None:  # noqa: ARG001
    # Seed two events that should appear in the snapshot.
    from channels.db import database_sync_to_async

    @database_sync_to_async
    def _seed():
        AuditEvent.objects.create(
            kind="seed.a", text="alpha", tone="info", icon="bell"
        )
        AuditEvent.objects.create(
            kind="seed.b", text="beta", tone="info", icon="bell"
        )

    await _seed()

    application = _build_application()
    communicator = WebsocketCommunicator(application, "/ws/audit/events/")
    connected, _ = await communicator.connect()
    assert connected

    snapshot = await communicator.receive_json_from()
    assert snapshot["type"] == "audit.snapshot"
    kinds = {e["kind"] for e in snapshot["events"]}
    assert {"seed.a", "seed.b"} <= kinds
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_consumer_receives_broadcast_audit_event(transactional_db) -> None:  # noqa: ARG001
    application = _build_application()
    communicator = WebsocketCommunicator(application, "/ws/audit/events/")
    connected, _ = await communicator.connect()
    assert connected

    # Drain the snapshot frame.
    await communicator.receive_json_from()

    layer = get_channel_layer()
    fake_payload = {
        "id": 9001,
        "kind": "ai.approval.executed",
        "text": "Approval APR-9001 executed",
        "tone": "success",
        "icon": "play-circle",
        "payload": {"approval_id": "APR-9001"},
        "createdAt": "2026-04-28T12:00:00Z",
        "time": "just now",
    }
    await layer.group_send(
        AUDIT_GROUP_NAME,
        {"type": "audit.event.broadcast", "event": fake_payload},
    )

    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "audit.event"
    assert msg["event"]["kind"] == "ai.approval.executed"
    assert msg["event"]["payload"] == {"approval_id": "APR-9001"}
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_consumer_replies_to_ping(transactional_db) -> None:  # noqa: ARG001
    application = _build_application()
    communicator = WebsocketCommunicator(application, "/ws/audit/events/")
    connected, _ = await communicator.connect()
    assert connected
    # Drain snapshot.
    await communicator.receive_json_from()

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=2)
    assert pong == {"type": "pong"}
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 4. Existing polling endpoint must still work
# ---------------------------------------------------------------------------


def test_dashboard_activity_endpoint_still_works() -> None:
    from rest_framework.test import APIClient

    AuditEvent.objects.create(
        kind="poll.test", text="still polling", tone="info", icon="bell"
    )
    res = APIClient().get("/api/dashboard/activity/")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert any(e.get("text") == "still polling" for e in body)
