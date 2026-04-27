"""Vapi webhook receiver.

Vapi POSTs JSON events. When ``VAPI_WEBHOOK_SECRET`` is configured we verify
the request via HMAC-SHA256 of the raw body against ``X-Vapi-Signature``.

Idempotency is per-app: ``calls.WebhookEvent`` (PK = ``event_id``).
Duplicate inserts hit ``IntegrityError`` and the handler short-circuits with
``200 / duplicate``. Every recognised event type writes an explicit
``AuditEvent`` so the Master Event Ledger captures the call lifecycle in
addition to the post-save signals.

Compliance hard stop (Master Blueprint §26 #4): this view never echoes call
content into prompts or audit text beyond what the analyser already gave us.
The Approved Claim Vault is the single source of truth for medical claims.
"""
from __future__ import annotations

import json
from typing import Any

from django.db import IntegrityError, transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .integrations.vapi_client import verify_webhook_signature
from .models import WebhookEvent
from .services import persist_vapi_webhook


class VapiWebhookView(APIView):
    """``POST /api/webhooks/vapi/`` — receives Vapi voice events."""

    permission_classes = [AllowAny]
    authentication_classes: list = []  # public — auth comes from HMAC signature

    def post(self, request):
        body = request.body or b""

        # Signature is enforced only when a secret is configured. Local dev
        # / mock mode default leaves the secret empty so test fixtures don't
        # need to sign every request.
        from django.conf import settings

        secret = getattr(settings, "VAPI_WEBHOOK_SECRET", "") or ""
        if secret:
            signature = request.META.get("HTTP_X_VAPI_SIGNATURE", "") or ""
            if not verify_webhook_signature(body, signature, secret=secret):
                return Response({"detail": "invalid signature"}, status=400)

        try:
            event = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid json"}, status=400)

        event_type = (event.get("type") or event.get("event") or "").lower()
        event_id = event.get("id") or _fallback_event_id(event)

        if event_id:
            try:
                with transaction.atomic():
                    WebhookEvent.objects.create(
                        event_id=event_id, event_type=event_type, provider="vapi"
                    )
            except IntegrityError:
                return Response({"detail": "duplicate", "id": event_id}, status=200)

        call, status = persist_vapi_webhook(event_type=event_type, payload=event)

        if status == "ignored":
            return Response({"detail": "ignored", "event": event_type}, status=200)
        if status == "unknown":
            return Response({"detail": "call not found", "event": event_type}, status=200)
        return Response(
            {
                "detail": "ok",
                "event": event_type,
                "id": event_id,
                "callId": getattr(call, "id", None),
            },
            status=200,
        )


def _fallback_event_id(event: dict[str, Any]) -> str:
    """Derive a deterministic id when the payload omits one (test fixtures)."""
    call = event.get("call") or {}
    parts = (
        event.get("type") or event.get("event") or "?",
        call.get("id") or event.get("callId") or "",
        str(event.get("timestamp") or ""),
    )
    return "auto:" + ":".join(str(p) for p in parts if p)


__all__ = ("VapiWebhookView",)
