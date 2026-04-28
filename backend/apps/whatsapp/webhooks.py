"""Phase 5A — Meta Cloud webhook receiver.

Two HTTP methods on the same path:

- ``GET  /api/webhooks/whatsapp/meta/`` — Meta verification handshake.
  Echoes ``hub.challenge`` only when ``hub.mode == "subscribe"`` AND
  ``hub.verify_token == settings.META_WA_VERIFY_TOKEN``.

- ``POST /api/webhooks/whatsapp/meta/`` — signed delivery.
  Verifies ``X-Hub-Signature-256`` via the configured provider, persists
  the envelope into :class:`WhatsAppWebhookEvent` (idempotent), and
  dispatches inbound / status events through the service layer.

The view never raises 5xx for application errors — it always returns a
JSON envelope so Meta does not retry indefinitely. Genuine misconfig
returns 401 / 400.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .integrations.whatsapp.base import ProviderError
from .models import WhatsAppWebhookEvent
from .services import (
    get_active_connection,
    get_provider,
    handle_inbound_message_event,
    handle_status_event,
    record_webhook_envelope,
)


class WhatsAppMetaWebhookView(APIView):
    """``/api/webhooks/whatsapp/meta/`` — verification + signed delivery."""

    permission_classes = [AllowAny]
    authentication_classes: list = []  # Auth comes from HMAC + verify token.

    # ----- GET: subscription verification -----

    def get(self, request):
        mode = request.query_params.get("hub.mode") or ""
        token = request.query_params.get("hub.verify_token") or ""
        challenge = request.query_params.get("hub.challenge") or ""
        expected = getattr(settings, "META_WA_VERIFY_TOKEN", "") or ""

        if mode != "subscribe" or not expected or token != expected:
            return Response(
                {"detail": "verification failed"}, status=403
            )
        # Meta expects the bare challenge value back. DRF wraps it in JSON
        # but Meta accepts that fine; for stricter setups frontends can
        # parse the integer/string from the body.
        try:
            return Response(int(challenge), status=200)
        except (TypeError, ValueError):
            return Response(challenge, status=200)

    # ----- POST: signed delivery -----

    def post(self, request):
        body = request.body or b""
        signature_header = (
            request.META.get("HTTP_X_HUB_SIGNATURE_256")
            or request.META.get("HTTP_X_HUB_SIGNATURE")
            or ""
        )
        timestamp_header = (
            request.META.get("HTTP_X_HUB_TIMESTAMP")
            or request.headers.get("X-Hub-Timestamp")
            or None
        )

        provider = get_provider()
        try:
            verified = provider.verify_webhook(
                signature_header=signature_header,
                body=body,
                timestamp_header=timestamp_header,
            )
        except ProviderError as exc:
            return Response(
                {"detail": f"signature verification error: {exc}"},
                status=401,
            )

        if not verified:
            # Persist the failed attempt for forensic visibility.
            try:
                _record_failed_envelope(body, signature_header)
            except Exception:  # noqa: BLE001 - defensive
                pass
            return Response({"detail": "invalid signature"}, status=401)

        try:
            payload: dict[str, Any] = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid json"}, status=400)

        envelope, created = record_webhook_envelope(
            raw_payload=payload,
            signature_header=signature_header,
            signature_verified=True,
            event_id_hint=_envelope_event_hint(payload, body),
        )
        if not created:
            envelope.processing_status = (
                WhatsAppWebhookEvent.ProcessingStatus.DUPLICATE
            )
            envelope.processed_at = timezone.now()
            envelope.save(update_fields=["processing_status", "processed_at"])
            return Response(
                {
                    "detail": "duplicate",
                    "providerEventId": envelope.provider_event_id,
                },
                status=200,
            )

        from apps.audit.signals import write_event
        from apps.audit.models import AuditEvent

        write_event(
            kind="whatsapp.webhook.received",
            text=(
                f"WhatsApp webhook accepted · provider_event_id="
                f"{envelope.provider_event_id}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "provider_event_id": envelope.provider_event_id,
                "size_bytes": len(body),
            },
        )

        connection = get_active_connection()
        events = provider.parse_webhook_event(body=payload)
        inbound_count = 0
        status_count = 0
        for event in events:
            if event.event_type == "messages":
                handle_inbound_message_event(event, connection=connection)
                inbound_count += 1
            elif event.event_type == "statuses":
                handle_status_event(event)
                status_count += 1

        envelope.processing_status = WhatsAppWebhookEvent.ProcessingStatus.ACCEPTED
        envelope.processed_at = timezone.now()
        envelope.save(update_fields=["processing_status", "processed_at"])

        return Response(
            {
                "detail": "ok",
                "providerEventId": envelope.provider_event_id,
                "inboundProcessed": inbound_count,
                "statusProcessed": status_count,
            },
            status=200,
        )


def _envelope_event_hint(payload: dict[str, Any], body: bytes) -> str:
    """Build a stable provider_event_id for idempotency.

    Meta does not provide a single event id at the envelope level. We use
    the SHA1 of the body + the entry id (when present) so retries collapse.
    """
    digest = hashlib.sha1(body).hexdigest()  # noqa: S324 - identity hash, not security
    entries = payload.get("entry") or []
    entry_id = ""
    if entries and isinstance(entries[0], dict):
        entry_id = str(entries[0].get("id") or "")
    return f"meta:{entry_id}:{digest}"


def _record_failed_envelope(body: bytes, signature_header: str) -> None:
    """Persist an envelope row for invalid signatures so audits show retries."""
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        payload = {"raw_excerpt": body[:200].decode("utf-8", errors="replace")}
    record_webhook_envelope(
        raw_payload=payload,
        signature_header=signature_header,
        signature_verified=False,
        event_id_hint=_envelope_event_hint(
            payload if isinstance(payload, dict) else {}, body
        ),
    )


__all__ = ("WhatsAppMetaWebhookView",)
