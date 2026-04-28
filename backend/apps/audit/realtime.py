"""Phase 4A — AuditEvent realtime serialization + WebSocket publisher.

Two responsibilities:

1. ``serialize_event(event)`` — produce a stable, frontend-friendly
   dict for both the WebSocket initial snapshot and the per-event push.
   Returned shape is compatible with the Dashboard ``ActivityEvent``
   type (camelCase, includes ``time`` and ``createdAt``) AND carries the
   full stored ``payload`` so the Governance page can react to specific
   approval / prompt / sandbox / budget events without re-fetching.

2. ``publish_audit_event(event)`` — fan an :class:`AuditEvent` row out to
   the ``audit_events`` Channels group. Wrapped in
   ``transaction.on_commit`` and a broad ``try/except`` so neither
   missing-Redis nor a transient Channels failure can ever break the
   underlying DB write that triggered the audit.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

# Module-level imports so tests can ``mock.patch`` them. The Channels
# call sites still tolerate missing / broken layers — see ``_send`` below.
try:  # pragma: no cover - environments without channels installed
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
except Exception:  # pragma: no cover - defensive
    async_to_sync = None  # type: ignore[assignment]
    get_channel_layer = None  # type: ignore[assignment]

from .models import AuditEvent


logger = logging.getLogger(__name__)


_GROUP_NAME = "audit_events"
_SNAPSHOT_LIMIT = 25


def _relative_time(occurred_at) -> str:
    delta = timezone.now() - occurred_at
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def serialize_event(event: AuditEvent) -> dict[str, Any]:
    """Stable shape used by both the snapshot and per-event WebSocket frames.

    Carries the full stored ``payload`` — the AuditEvent ledger NEVER
    stores secrets (every audit caller across the codebase keeps API
    keys / tokens out of the payload), so streaming it as-is is safe and
    matches the Phase 4A locked rule that the WebSocket message must not
    trim the payload.
    """
    return {
        "id": event.pk,
        "kind": event.kind,
        "text": event.text,
        "tone": event.tone,
        "icon": event.icon,
        "payload": dict(event.payload or {}),
        "createdAt": event.occurred_at.isoformat(),
        "time": _relative_time(event.occurred_at),
    }


def latest_events(limit: int = _SNAPSHOT_LIMIT) -> list[dict[str, Any]]:
    """Initial snapshot the consumer sends on connect."""
    rows = list(AuditEvent.objects.order_by("-occurred_at")[:limit])
    return [serialize_event(row) for row in rows]


def publish_audit_event(event: AuditEvent) -> None:
    """Fan-out one AuditEvent to every connected WebSocket client.

    Wrapped in ``transaction.on_commit`` so subscribers only see rows
    that survived the DB commit. Wrapped in a broad ``try/except`` so
    no Channels failure can cascade into a service-layer write failure.
    """
    payload = serialize_event(event)

    def _send():
        try:
            if get_channel_layer is None or async_to_sync is None:
                return
            layer = get_channel_layer()
            if layer is None:
                return
            async_to_sync(layer.group_send)(
                _GROUP_NAME,
                {"type": "audit.event.broadcast", "event": payload},
            )
        except Exception as exc:  # noqa: BLE001 — never break the DB write
            logger.warning("publish_audit_event failed: %s", exc)

    try:
        transaction.on_commit(_send)
    except Exception as exc:  # noqa: BLE001 — also defensive
        logger.warning("publish_audit_event scheduling failed: %s", exc)


__all__ = (
    "AUDIT_GROUP_NAME",
    "latest_events",
    "publish_audit_event",
    "serialize_event",
)


# Public name for tests / consumer.
AUDIT_GROUP_NAME = _GROUP_NAME
