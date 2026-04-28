"""Phase 5A — Meta WhatsApp Business Cloud API provider.

Production target. Calls
``https://graph.facebook.com/{version}/{phone_number_id}/messages`` for sends
and verifies inbound webhooks via HMAC-SHA256 on
``X-Hub-Signature-256``.

LOCKED rules:
- ``META_WA_ACCESS_TOKEN`` is **never** logged. The send log strips
  ``Authorization`` headers before persisting.
- ``requests`` is imported lazily so unit tests using the mock provider
  don't depend on network libraries.
- Missing credentials raise :class:`ProviderError(retryable=False)` so the
  Celery task does not retry forever.
- Webhook signature compare is constant-time. A missing secret returns
  ``False`` — the webhook view rejects unsigned bodies in production.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Mapping

from django.conf import settings

from .base import (
    ProviderError,
    ProviderHealth,
    ProviderSendResult,
    ProviderStatusResult,
    ProviderWebhookEvent,
)
from .mock import _parse_meta_payload  # parser shape is shared


class MetaCloudProvider:
    """Production provider talking to Meta Graph API."""

    name = "meta_cloud"

    def __init__(self) -> None:
        self._access_token = getattr(settings, "META_WA_ACCESS_TOKEN", "") or ""
        self._phone_number_id = (
            getattr(settings, "META_WA_PHONE_NUMBER_ID", "") or ""
        )
        self._waba_id = (
            getattr(settings, "META_WA_BUSINESS_ACCOUNT_ID", "") or ""
        )
        self._app_secret = getattr(settings, "META_WA_APP_SECRET", "") or ""
        self._webhook_secret = (
            getattr(settings, "WHATSAPP_WEBHOOK_SECRET", "") or self._app_secret
        )
        self._api_version = (
            getattr(settings, "META_WA_API_VERSION", "v20.0") or "v20.0"
        )
        self._replay_window_seconds = int(
            getattr(settings, "WHATSAPP_WEBHOOK_REPLAY_WINDOW_SECONDS", 300)
        )
        self._base_url = "https://graph.facebook.com"

    # ----- Sends -----

    def send_template_message(
        self,
        *,
        to_phone: str,
        template_name: str,
        language: str,
        components: list[Mapping[str, Any]],
        idempotency_key: str,
    ) -> ProviderSendResult:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _strip_phone(to_phone),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language or "hi"},
                "components": list(components),
            },
        }
        return self._post_messages(payload, idempotency_key=idempotency_key)

    def send_text_message(
        self,
        *,
        to_phone: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderSendResult:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _strip_phone(to_phone),
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        return self._post_messages(payload, idempotency_key=idempotency_key)

    # ----- Webhook verification + parsing -----

    def verify_webhook(
        self,
        *,
        signature_header: str,
        body: bytes,
        timestamp_header: str | None = None,
    ) -> bool:
        if not self._webhook_secret or not signature_header:
            return False
        # Meta sends ``sha256=<hex>``. Tolerate the bare hex form too.
        expected_hex = hmac.new(
            key=self._webhook_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        candidate = signature_header.strip()
        if candidate.startswith("sha256="):
            candidate = candidate.split("=", 1)[1]
        if not hmac.compare_digest(candidate, expected_hex):
            return False

        # Replay-window check: if a timestamp header is supplied, reject
        # bodies older than ``WHATSAPP_WEBHOOK_REPLAY_WINDOW_SECONDS``.
        if timestamp_header:
            try:
                sent_at = int(timestamp_header)
            except (TypeError, ValueError):
                return False
            now = int(time.time())
            if abs(now - sent_at) > self._replay_window_seconds:
                return False
        return True

    def parse_webhook_event(
        self,
        *,
        body: Mapping[str, Any],
    ) -> list[ProviderWebhookEvent]:
        return _parse_meta_payload(body)

    # ----- Status + health -----

    def get_message_status(
        self,
        *,
        provider_message_id: str,
    ) -> ProviderStatusResult:
        # Meta exposes status only via webhook delivery. The Cloud API does
        # not return per-message status from a polling endpoint, so this is
        # an informational stub.
        return ProviderStatusResult(
            provider=self.name,
            provider_message_id=provider_message_id,
            status="unknown",
            raw={"detail": "Meta Cloud only exposes status via webhook"},
        )

    def health_check(self) -> ProviderHealth:
        if not self._access_token or not self._phone_number_id:
            return ProviderHealth(
                provider=self.name,
                healthy=False,
                detail=(
                    "META_WA_ACCESS_TOKEN / META_WA_PHONE_NUMBER_ID not configured"
                ),
                metadata={"configured": False},
            )
        try:
            requests = _require_requests()
            url = f"{self._base_url}/{self._api_version}/{self._phone_number_id}"
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                params={"fields": "verified_name,quality_rating,display_phone_number"},
                timeout=10,
            )
            ok = bool(response.ok)
            data = {}
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    data = response.json()
                except Exception:  # pragma: no cover - non-JSON path
                    data = {}
            return ProviderHealth(
                provider=self.name,
                healthy=ok,
                detail=f"GET phone-number-id returned HTTP {response.status_code}",
                metadata={"configured": True, "phone_number": data.get("display_phone_number", "")},
            )
        except ProviderError as exc:
            return ProviderHealth(
                provider=self.name,
                healthy=False,
                detail=str(exc),
                metadata={"configured": True},
            )

    # ----- Internals -----

    def _post_messages(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> ProviderSendResult:
        if not self._access_token or not self._phone_number_id:
            raise ProviderError(
                "META_WA_ACCESS_TOKEN / META_WA_PHONE_NUMBER_ID not configured.",
                error_code="config_missing",
                retryable=False,
            )

        requests = _require_requests()
        url = (
            f"{self._base_url}/{self._api_version}/{self._phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        # Meta does not have a native idempotency header; we still pass the
        # key in the payload metadata so the response carries it back to
        # the caller for log correlation.
        request_payload = dict(payload)
        if idempotency_key:
            biz = dict(request_payload.get("biz_opaque_callback_data") or {})
            biz["idempotency_key"] = idempotency_key
            # Meta accepts a string here; encode safely.
            request_payload["biz_opaque_callback_data"] = (
                f"idemp:{idempotency_key}"
            )

        started = time.monotonic()
        try:
            response = requests.post(
                url, json=request_payload, headers=headers, timeout=30
            )
        except Exception as exc:  # pragma: no cover - network path
            latency_ms = int((time.monotonic() - started) * 1000)
            raise ProviderError(
                f"Meta Cloud transport error: {exc}",
                error_code="transport",
                retryable=True,
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        body: Mapping[str, Any]
        try:
            body = response.json()
        except Exception:  # pragma: no cover - non-JSON path
            body = {}

        if not response.ok:
            error_block = (body.get("error") or {}) if isinstance(body, dict) else {}
            error_code = str(error_block.get("code") or response.status_code)
            error_message = str(
                error_block.get("message")
                or f"Meta Cloud HTTP {response.status_code}"
            )
            # 4xx aside from 429 are not retryable; 5xx + 429 are.
            retryable = response.status_code >= 500 or response.status_code == 429
            raise ProviderError(
                error_message,
                error_code=error_code,
                retryable=retryable,
            )

        messages = (body.get("messages") or []) if isinstance(body, dict) else []
        provider_message_id = (
            str((messages[0] or {}).get("id") or "") if messages else ""
        )
        if not provider_message_id:
            raise ProviderError(
                "Meta Cloud response missing message id.",
                error_code="missing_message_id",
                retryable=False,
            )

        # Strip secrets before persisting the request payload via SendLog.
        safe_request = dict(request_payload)
        # The headers carry the access token; never log them.
        return ProviderSendResult(
            provider=self.name,
            provider_message_id=provider_message_id,
            status="sent",
            request_payload=safe_request,
            response_status=response.status_code,
            response_payload=body if isinstance(body, dict) else {"raw": str(body)},
            latency_ms=latency_ms,
        )


def _strip_phone(phone: str) -> str:
    """Meta expects a recipient number with optional ``+``. Trim whitespace."""
    cleaned = (phone or "").strip().replace(" ", "").replace("-", "")
    return cleaned.lstrip("+")


def _require_requests():
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        raise ProviderError(
            "requests is not installed; run `pip install requests` "
            "or set WHATSAPP_PROVIDER=mock.",
            error_code="missing_dependency",
            retryable=False,
        ) from exc
    return requests


__all__ = ("MetaCloudProvider",)
