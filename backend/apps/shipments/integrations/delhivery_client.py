"""Delhivery courier adapter.

Three modes, selected by ``settings.DELHIVERY_MODE``:

- ``mock`` — deterministic fake AWB matching ``DLH<8 digits>``. No network.
  Default for local dev and CI.
- ``test`` — Delhivery staging API at ``staging-express.delhivery.com``
  (or whatever ``DELHIVERY_API_BASE_URL`` points at). Requires an API token.
- ``live`` — Delhivery production API. Requires a real token + a real
  pickup location registered with Delhivery. Set explicitly via env; never
  the default.

Tests patch ``_create_via_sdk`` (or set ``DELHIVERY_MODE=mock``) so the real
SDK is never called from the test suite.

Status mapping for the tracking webhook lives in
``apps/shipments/webhooks.py`` — this module is gateway-only.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

from django.conf import settings


class DelhiveryClientError(Exception):
    """Raised when the underlying SDK call or configuration fails."""


@dataclass(frozen=True)
class AwbResult:
    awb: str
    status: str = "Pickup Scheduled"
    tracking_url: str = ""
    raw: dict[str, Any] | None = None


def _mint_mock_awb(*, exists: callable | None = None) -> str:
    """Generate a unique mock AWB matching ``DLH<8 digits>``.

    ``exists`` is an optional collision-check callable so callers can dedupe
    against the live ``Shipment`` table without this module importing models.
    """
    for _ in range(10):
        candidate = f"DLH{secrets.randbelow(99_999_999):08d}"
        if exists is None or not exists(candidate):
            return candidate
    raise DelhiveryClientError("Could not mint a unique mock AWB after 10 attempts")


def create_awb(
    *,
    order_id: str,
    customer_name: str,
    customer_phone: str,
    address_line: str,
    city: str,
    state: str,
    pincode: str = "",
    weight_grams: int | None = None,
    payment_mode: str = "Prepaid",
    cod_amount: int = 0,
    exists: callable | None = None,
) -> AwbResult:
    """Dispatch AWB creation to the configured backend (mock / test / live).

    ``exists`` is forwarded to the mock minter so callers can avoid
    collisions with the live ``Shipment`` table without leaking a model
    dependency into this module.
    """
    mode = (getattr(settings, "DELHIVERY_MODE", "mock") or "mock").lower()
    if mode == "mock":
        return _create_mock(order_id=order_id, exists=exists)
    if mode in {"test", "live"}:
        return _create_via_sdk(
            order_id=order_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            address_line=address_line,
            city=city,
            state=state,
            pincode=pincode,
            weight_grams=weight_grams,
            payment_mode=payment_mode,
            cod_amount=cod_amount,
            mode=mode,
        )
    raise DelhiveryClientError(f"Unknown DELHIVERY_MODE: {mode!r}")


def _create_mock(*, order_id: str, exists: callable | None) -> AwbResult:
    """Network-free AWB. Same shape as a real Delhivery ``create.json`` reply."""
    awb = _mint_mock_awb(exists=exists)
    tracking_url = f"https://delhivery.example/track/{awb}"
    return AwbResult(
        awb=awb,
        status="Pickup Scheduled",
        tracking_url=tracking_url,
        raw={
            "mode": "mock",
            "packages": [
                {
                    "waybill": awb,
                    "status": "Pickup Scheduled",
                    "refnum": order_id,
                    "tracking_url": tracking_url,
                }
            ],
        },
    )


def _create_via_sdk(
    *,
    order_id: str,
    customer_name: str,
    customer_phone: str,
    address_line: str,
    city: str,
    state: str,
    pincode: str,
    weight_grams: int | None,
    payment_mode: str,
    cod_amount: int,
    mode: str,
) -> AwbResult:
    """Call the real Delhivery API. ``requests`` is imported lazily so mock
    mode never needs the package installed.
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only on missing dep
        raise DelhiveryClientError(
            "requests is not installed; run `pip install requests` "
            "or set DELHIVERY_MODE=mock."
        ) from exc

    base_url = getattr(settings, "DELHIVERY_API_BASE_URL", "") or ""
    token = getattr(settings, "DELHIVERY_API_TOKEN", "") or ""
    pickup = getattr(settings, "DELHIVERY_PICKUP_LOCATION", "") or ""
    return_addr = getattr(settings, "DELHIVERY_RETURN_ADDRESS", "") or ""
    default_weight = int(
        getattr(settings, "DELHIVERY_DEFAULT_PACKAGE_WEIGHT_GRAMS", 0) or 0
    )

    if not base_url or not token:
        raise DelhiveryClientError(
            f"DELHIVERY_API_BASE_URL / DELHIVERY_API_TOKEN not configured (mode={mode})."
        )
    if not pickup:
        raise DelhiveryClientError(
            f"DELHIVERY_PICKUP_LOCATION not configured (mode={mode})."
        )

    package = {
        "name": customer_name or "Customer",
        "add": address_line or "—",
        "pin": pincode or "",
        "city": city or "",
        "state": state or "",
        "country": "India",
        "phone": customer_phone or "",
        "order": order_id,
        "payment_mode": payment_mode,
        "cod_amount": str(cod_amount),
        "weight": str(weight_grams or default_weight or 500),
        "return_add": return_addr,
    }
    payload = {
        "shipments": [package],
        "pickup_location": {"name": pickup},
    }

    url = f"{base_url.rstrip('/')}/api/cmu/create.json"
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # pragma: no cover - real-network path
        raise DelhiveryClientError(f"Delhivery API error: {exc}") from exc

    packages = body.get("packages") or []
    if not packages:
        raise DelhiveryClientError(f"Unexpected Delhivery response: {body!r}")
    awb = packages[0].get("waybill")
    if not awb:
        raise DelhiveryClientError(f"Delhivery response missing waybill: {body!r}")

    tracking_url = f"https://www.delhivery.com/track/package/{awb}"
    return AwbResult(
        awb=str(awb),
        status=str(packages[0].get("status") or "Pickup Scheduled"),
        tracking_url=tracking_url,
        raw=body,
    )


def verify_webhook_signature(body: bytes, signature: str, secret: str | None = None) -> bool:
    """HMAC-SHA256 check for Delhivery's webhook ``X-Delhivery-Signature``.

    Delhivery's webhook signature scheme is HMAC-SHA256 of the raw body using
    the configured webhook secret. We replicate it and use constant-time
    comparison.

    A missing secret or signature returns ``False`` (treated as 400 by the
    webhook view).
    """
    if secret is None:
        secret = getattr(settings, "DELHIVERY_WEBHOOK_SECRET", "") or ""
    if not secret or not signature:
        return False
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


__all__ = (
    "DelhiveryClientError",
    "AwbResult",
    "create_awb",
    "verify_webhook_signature",
)
