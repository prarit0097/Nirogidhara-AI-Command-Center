"""Vapi voice-agent adapter.

Three modes, selected by ``settings.VAPI_MODE``:

- ``mock`` — deterministic fake call id (``call_mock_<lead>_<n>``) with
  status ``queued``. No network. Default for local dev and CI.
- ``test`` — Vapi staging API. Requires ``VAPI_API_KEY`` plus the
  ``VAPI_ASSISTANT_ID`` and ``VAPI_PHONE_NUMBER_ID`` of a sandbox
  assistant + caller-id pair.
- ``live`` — Vapi production. Set explicitly via env; never the default.

Tests patch ``_create_via_sdk`` (or set ``VAPI_MODE=mock``) so the real
SDK is never called from the test suite.

**Compliance hard stop (Master Blueprint §26 #4):** This adapter MUST NOT
inject free-style medical claims into the Vapi prompt. Phase 2D ships with
a deliberately empty prompt — the assistant is configured server-side in
Vapi's dashboard, and any future prompt-builder MUST pull only from
``apps.compliance.Claim``. CAIO never executes.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from django.conf import settings


class VapiClientError(Exception):
    """Raised when the underlying SDK call or configuration fails."""


@dataclass(frozen=True)
class CallResult:
    provider_call_id: str
    status: str = "queued"
    raw: dict[str, Any] | None = None


def trigger_call(
    *,
    lead_id: str,
    customer_phone: str,
    customer_name: str,
    language: str = "",
    purpose: str = "sales_call",
) -> CallResult:
    """Dispatch outbound call creation to the configured backend."""
    mode = (getattr(settings, "VAPI_MODE", "mock") or "mock").lower()
    if mode == "mock":
        return _create_mock(lead_id=lead_id, purpose=purpose)
    if mode in {"test", "live"}:
        return _create_via_sdk(
            lead_id=lead_id,
            customer_phone=customer_phone,
            customer_name=customer_name,
            language=language,
            purpose=purpose,
            mode=mode,
        )
    raise VapiClientError(f"Unknown VAPI_MODE: {mode!r}")


def _create_mock(*, lead_id: str, purpose: str) -> CallResult:
    """Deterministic, network-free call id. Same inputs produce same outputs."""
    # Lead id segments often collide with Python identifier rules; sanitize.
    safe_lead = lead_id.replace("-", "_") or "anon"
    provider_call_id = f"call_mock_{safe_lead}_{purpose}"
    return CallResult(
        provider_call_id=provider_call_id,
        status="queued",
        raw={
            "id": provider_call_id,
            "status": "queued",
            "mode": "mock",
            "lead_id": lead_id,
            "purpose": purpose,
        },
    )


def _create_via_sdk(
    *,
    lead_id: str,
    customer_phone: str,
    customer_name: str,
    language: str,
    purpose: str,
    mode: str,
) -> CallResult:
    """Call the real Vapi REST API. ``requests`` is imported lazily so mock
    mode never needs the package installed.
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        raise VapiClientError(
            "requests is not installed; run `pip install requests` "
            "or set VAPI_MODE=mock."
        ) from exc

    base_url = (getattr(settings, "VAPI_API_BASE_URL", "") or "").rstrip("/")
    api_key = getattr(settings, "VAPI_API_KEY", "") or ""
    assistant_id = getattr(settings, "VAPI_ASSISTANT_ID", "") or ""
    phone_number_id = getattr(settings, "VAPI_PHONE_NUMBER_ID", "") or ""
    callback_url = getattr(settings, "VAPI_CALLBACK_URL", "") or ""
    default_language = (
        language
        or getattr(settings, "VAPI_DEFAULT_LANGUAGE", "hi-IN")
        or "hi-IN"
    )

    if not base_url or not api_key:
        raise VapiClientError(
            f"VAPI_API_BASE_URL / VAPI_API_KEY not configured (mode={mode})."
        )
    if not assistant_id or not phone_number_id:
        raise VapiClientError(
            f"VAPI_ASSISTANT_ID / VAPI_PHONE_NUMBER_ID not configured (mode={mode})."
        )

    # Compliance: payload deliberately stays minimal. The Vapi assistant is
    # configured server-side in Vapi's dashboard with the Approved Claim
    # Vault prompts. We pass only metadata the assistant needs for routing
    # — never free-form medical text.
    payload: dict[str, Any] = {
        "assistantId": assistant_id,
        "phoneNumberId": phone_number_id,
        "customer": {
            "number": customer_phone,
            "name": customer_name or "Customer",
        },
        "metadata": {
            "lead_id": lead_id,
            "purpose": purpose,
            "language": default_language,
            "mode": mode,
        },
    }
    if callback_url:
        payload["serverUrl"] = callback_url

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"{base_url}/call"

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # pragma: no cover - real-network path
        raise VapiClientError(f"Vapi API error: {exc}") from exc

    provider_call_id = body.get("id")
    if not provider_call_id:
        raise VapiClientError(f"Vapi response missing call id: {body!r}")

    return CallResult(
        provider_call_id=str(provider_call_id),
        status=str(body.get("status") or "queued"),
        raw=body,
    )


def verify_webhook_signature(body: bytes, signature: str, secret: str | None = None) -> bool:
    """HMAC-SHA256 check for Vapi webhooks.

    Vapi can be configured to sign webhook bodies with a shared secret using
    HMAC-SHA256; the signature arrives in ``X-Vapi-Signature``. We replicate
    the digest and compare in constant time.

    A missing secret or signature returns ``False`` (treated as 400 by the
    webhook view). When ``VAPI_WEBHOOK_SECRET`` is empty we skip signature
    verification entirely so dev/test fixtures stay simple — that's enforced
    higher up in the webhook view, not here.
    """
    if secret is None:
        secret = getattr(settings, "VAPI_WEBHOOK_SECRET", "") or ""
    if not secret or not signature:
        return False
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


__all__ = (
    "VapiClientError",
    "CallResult",
    "trigger_call",
    "verify_webhook_signature",
)
