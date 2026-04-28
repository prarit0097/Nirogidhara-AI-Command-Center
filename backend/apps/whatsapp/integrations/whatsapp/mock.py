"""Phase 5A — Mock WhatsApp provider.

Deterministic, no network. Default for local dev / CI. Mints
``wamid.MOCK_<idempotency_key>`` for sends. Webhook signature verification
returns True so test fixtures don't need to compute HMAC.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Mapping

from .base import (
    ProviderHealth,
    ProviderSendResult,
    ProviderStatusResult,
    ProviderWebhookEvent,
)


class MockProvider:
    """Deterministic mock provider for tests / dev."""

    name = "mock"

    def send_template_message(
        self,
        *,
        to_phone: str,
        template_name: str,
        language: str,
        components: list[Mapping[str, Any]],
        idempotency_key: str,
    ) -> ProviderSendResult:
        provider_message_id = _mint_mock_wamid(idempotency_key, to_phone)
        return ProviderSendResult(
            provider=self.name,
            provider_message_id=provider_message_id,
            status="sent",
            request_payload={
                "to": to_phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language},
                    "components": list(components),
                },
            },
            response_status=200,
            response_payload={
                "messaging_product": "whatsapp",
                "messages": [{"id": provider_message_id}],
                "mode": "mock",
            },
            latency_ms=1,
        )

    def send_text_message(
        self,
        *,
        to_phone: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderSendResult:
        provider_message_id = _mint_mock_wamid(idempotency_key, to_phone)
        return ProviderSendResult(
            provider=self.name,
            provider_message_id=provider_message_id,
            status="sent",
            request_payload={"to": to_phone, "type": "text", "text": {"body": body}},
            response_status=200,
            response_payload={
                "messaging_product": "whatsapp",
                "messages": [{"id": provider_message_id}],
                "mode": "mock",
            },
            latency_ms=1,
        )

    def verify_webhook(
        self,
        *,
        signature_header: str,
        body: bytes,
        timestamp_header: str | None = None,
    ) -> bool:
        # Mock provider accepts any signature. Tests that want to exercise
        # the failure path pass ``signature_header=""`` (which the webhook
        # view rejects upstream).
        return bool(signature_header) or signature_header == ""  # always True

    def parse_webhook_event(
        self,
        *,
        body: Mapping[str, Any],
    ) -> list[ProviderWebhookEvent]:
        # Mock parser handles the same shape as Meta's so test fixtures stay
        # representative. See :func:`_parse_meta_payload` for the real parse.
        return _parse_meta_payload(body)

    def get_message_status(
        self,
        *,
        provider_message_id: str,
    ) -> ProviderStatusResult:
        return ProviderStatusResult(
            provider=self.name,
            provider_message_id=provider_message_id,
            status="delivered",
            raw={"mode": "mock"},
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            healthy=True,
            detail="mock provider always healthy",
            metadata={"mode": "mock"},
        )


def _mint_mock_wamid(idempotency_key: str, to_phone: str) -> str:
    """Return a deterministic ``wamid.MOCK_*`` id."""
    if idempotency_key:
        digest = hashlib.sha1(  # noqa: S324 - mock id, not security
            idempotency_key.encode("utf-8")
        ).hexdigest()[:16]
        return f"wamid.MOCK_{digest}"
    safe = (to_phone or "anon").replace("+", "").replace(" ", "")
    return f"wamid.MOCK_{safe}"


def _parse_meta_payload(body: Mapping[str, Any]) -> list[ProviderWebhookEvent]:
    """Parse a Meta-shaped webhook body into a list of events.

    Meta envelopes look like::

        {
          "object": "whatsapp_business_account",
          "entry": [{
            "id": "<waba_id>",
            "changes": [{
              "field": "messages",
              "value": {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": "..."},
                "messages": [{"id": "wamid....", "from": "91...", "type": "text",
                              "text": {"body": "hi"}, "timestamp": "..."}],
                "statuses": [{"id": "wamid....", "status": "delivered",
                              "timestamp": "...", "recipient_id": "91..."}],
              }
            }]
          }]
        }
    """
    events: list[ProviderWebhookEvent] = []
    entries = body.get("entry") or []
    for entry in entries:
        entry_id = str(entry.get("id") or "")
        changes = entry.get("changes") or []
        for change in changes:
            field = str(change.get("field") or "")
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")

            for msg in value.get("messages") or []:
                wamid = str(msg.get("id") or "")
                msg_type = str(msg.get("type") or "text")
                ts = _safe_int(msg.get("timestamp"))
                from_phone = str(msg.get("from") or "")
                body_text = ""
                if msg_type == "text":
                    body_text = str((msg.get("text") or {}).get("body") or "")
                elif msg_type == "interactive":
                    interactive = msg.get("interactive") or {}
                    btn = interactive.get("button_reply") or {}
                    body_text = str(btn.get("title") or "")
                events.append(
                    ProviderWebhookEvent(
                        event_id=f"msg:{entry_id}:{wamid}",
                        event_type="messages",
                        direction="inbound",
                        provider_message_id=wamid,
                        from_phone=from_phone,
                        to_phone=phone_number_id,
                        status="delivered",
                        timestamp=ts,
                        body=body_text,
                        raw=msg,
                    )
                )

            for status in value.get("statuses") or []:
                wamid = str(status.get("id") or "")
                ts = _safe_int(status.get("timestamp"))
                status_name = str(status.get("status") or "")
                recipient = str(status.get("recipient_id") or "")
                events.append(
                    ProviderWebhookEvent(
                        event_id=f"sts:{entry_id}:{wamid}:{status_name}:{ts}",
                        event_type="statuses",
                        direction="status",
                        provider_message_id=wamid,
                        from_phone="",
                        to_phone=recipient,
                        status=status_name,
                        timestamp=ts,
                        body="",
                        raw=status,
                    )
                )
    return events


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def hmac_sha256_hex(secret: str, body: bytes) -> str:
    """Helper for tests to build the ``X-Hub-Signature-256`` header."""
    digest = hmac.new(
        key=(secret or "").encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


__all__ = ("MockProvider", "hmac_sha256_hex")
