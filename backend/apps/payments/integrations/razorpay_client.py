"""Razorpay payment-link adapter.

Three modes, selected by ``settings.RAZORPAY_MODE``:

- ``mock`` — deterministic fake link (`https://razorpay.example/pay/<plink_id>`).
  No network. Default for local dev and CI.
- ``test`` — real Razorpay sandbox API (requires ``RAZORPAY_KEY_ID`` /
  ``RAZORPAY_KEY_SECRET`` test credentials).
- ``live`` — real Razorpay production API. Set explicitly via env; never the
  default.

Tests patch ``_create_via_sdk`` (or set ``RAZORPAY_MODE=mock``) so the real
SDK is never called from the test suite.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from django.conf import settings


class RazorpayClientError(Exception):
    """Raised when the underlying SDK call or configuration fails."""


@dataclass(frozen=True)
class PaymentLinkResult:
    plink_id: str
    short_url: str
    status: str = "created"
    raw: dict[str, Any] | None = None


def create_payment_link(
    *,
    order_id: str,
    amount: int,
    customer_name: str,
    customer_phone: str = "",
    customer_email: str = "",
) -> PaymentLinkResult:
    """Dispatch to the configured backend (mock / test / live)."""
    mode = (getattr(settings, "RAZORPAY_MODE", "mock") or "mock").lower()
    if mode == "mock":
        return _create_mock(order_id=order_id, amount=amount)
    if mode in {"test", "live"}:
        return _create_via_sdk(
            order_id=order_id,
            amount=amount,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            mode=mode,
        )
    raise RazorpayClientError(f"Unknown RAZORPAY_MODE: {mode!r}")


def _create_mock(*, order_id: str, amount: int) -> PaymentLinkResult:
    """Deterministic, network-free link. Same inputs produce same outputs."""
    plink_id = f"plink_mock_{order_id.replace('-', '_')}_{amount}"
    short_url = f"https://razorpay.example/pay/{plink_id}"
    return PaymentLinkResult(
        plink_id=plink_id,
        short_url=short_url,
        status="created",
        raw={"id": plink_id, "short_url": short_url, "status": "created", "mode": "mock"},
    )


def _create_via_sdk(
    *,
    order_id: str,
    amount: int,
    customer_name: str,
    customer_phone: str,
    customer_email: str,
    mode: str,
) -> PaymentLinkResult:
    """Call the real Razorpay SDK. Imported lazily so mock mode never needs it."""
    try:
        import razorpay  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only on missing dep
        raise RazorpayClientError(
            "razorpay SDK is not installed; run `pip install razorpay` "
            "or set RAZORPAY_MODE=mock."
        ) from exc

    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
    if not key_id or not key_secret:
        raise RazorpayClientError(
            f"RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not configured (mode={mode})."
        )

    client = razorpay.Client(auth=(key_id, key_secret))
    callback_url = (
        settings.RAZORPAY_CALLBACK_URL
        or f"https://example.invalid/payments/callback/?order={order_id}"
    )

    payload: dict[str, Any] = {
        # Razorpay expects amount in paise (smallest currency unit).
        "amount": int(amount) * 100,
        "currency": "INR",
        "accept_partial": False,
        "description": f"Order {order_id}",
        "customer": {
            "name": customer_name or "Customer",
            "contact": customer_phone or "",
            "email": customer_email or "",
        },
        "notify": {
            "sms": bool(customer_phone),
            "email": bool(customer_email),
        },
        "reminder_enable": True,
        "callback_url": callback_url,
        "callback_method": "get",
        "notes": {"order_id": order_id, "mode": mode},
    }

    try:
        response = client.payment_link.create(payload)
    except Exception as exc:  # pragma: no cover - real-network path
        raise RazorpayClientError(f"Razorpay API error: {exc}") from exc

    plink_id = response.get("id")
    short_url = response.get("short_url")
    if not plink_id or not short_url:
        raise RazorpayClientError(f"Unexpected Razorpay response: {response!r}")

    return PaymentLinkResult(
        plink_id=plink_id,
        short_url=short_url,
        status=response.get("status", "created"),
        raw=response,
    )


def verify_webhook_signature(body: bytes, signature: str, secret: str | None = None) -> bool:
    """HMAC-SHA256 check matching Razorpay's docs.

    Razorpay computes ``HMAC_SHA256(webhook_secret, raw_body)`` and sends the
    hex digest in the ``X-Razorpay-Signature`` header. We replicate it and use
    constant-time comparison.

    A missing secret or signature returns ``False`` (treated as 400 by the
    webhook view).
    """
    if secret is None:
        secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or ""
    if not secret or not signature:
        return False
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


__all__ = (
    "RazorpayClientError",
    "PaymentLinkResult",
    "create_payment_link",
    "verify_webhook_signature",
)
