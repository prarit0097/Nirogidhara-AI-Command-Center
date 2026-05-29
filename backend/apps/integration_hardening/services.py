"""Phase 16E — Payment / Logistics Integration Hardening readiness services.

Pure, read-only functions that compute provider readiness from Django settings
+ the runtime kill switch + sandbox state. **None of these functions calls a
live provider** — they never create a Razorpay/PayU payment link, capture or
refund a payment, book a Delhivery AWB, send WhatsApp/Meta Cloud, place a Vapi
call, or hit any AI/LLM provider. They only read configuration *presence*
(never the secret values) and return a structured readiness snapshot for the
Integration Hardening dashboard.

Live execution remains disabled by default: a provider is only ``live_enabled``
when its mode setting is explicitly ``live`` AND a Director live-gate is
present — and no such HTTP gate exists in Phase 16E, so live stays blocked.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings


# Phase 16E never promotes any provider to live execution. There is no HTTP
# Director live-gate in this phase, so `live_gate_present` is always False and
# live actions stay blocked. (The separate CLI-only Phase 7G-Live / Phase 8F
# gates are unchanged and out of scope here.)
_LIVE_GATE_PRESENT = False


def _mode(setting_name: str) -> str:
    return (getattr(settings, setting_name, "mock") or "mock").lower()


def _present(setting_name: str) -> bool:
    """True if a setting has a non-empty value — never returns the value."""
    return bool((getattr(settings, setting_name, "") or "").strip())


def _normalize_status(
    *, mode: str, configured: bool, live_enabled: bool
) -> str:
    """Map (mode, configured) → a coarse readiness status string."""
    if mode == "mock":
        return "ready"  # mock is always safe + ready (no network)
    if mode in {"test", "sandbox"}:
        return "ready" if configured else "misconfigured"
    if mode == "live":
        # Live is only "ready" when fully configured AND gated; otherwise blocked.
        return "ready" if (configured and live_enabled) else "blocked"
    return "unavailable"


def _display_mode(mode: str) -> str:
    """Surface the mode as the directive's vocabulary (live → live-gated)."""
    if mode == "live":
        return "live-gated"
    if mode in {"mock", "test"}:
        return mode
    return "unavailable"


def razorpay_readiness() -> dict[str, Any]:
    mode = _mode("RAZORPAY_MODE")
    # mock needs no credentials; test/live need key id + secret present.
    configured = (
        True
        if mode == "mock"
        else (_present("RAZORPAY_KEY_ID") and _present("RAZORPAY_KEY_SECRET"))
    )
    live_requested = mode == "live"
    live_enabled = live_requested and configured and _LIVE_GATE_PRESENT
    status = _normalize_status(
        mode=mode, configured=configured, live_enabled=live_enabled
    )

    blocked_reasons: list[str] = []
    if mode == "live" and not _LIVE_GATE_PRESENT:
        blocked_reasons.append(
            "Live Razorpay actions blocked — Director live gate required."
        )
    if mode in {"test", "live"} and not configured:
        blocked_reasons.append(
            "Razorpay key id / secret not configured (presence check only)."
        )

    safe_actions: list[str] = []
    if mode == "mock":
        safe_actions.append("View readiness (mock — no network).")
    elif mode == "test" and configured:
        safe_actions.append(
            "Create a test/sandbox payment link via the existing operations flow."
        )

    return {
        "provider": "razorpay",
        "label": "Razorpay",
        "mode": _display_mode(mode),
        "rawMode": mode,
        "configured": configured,
        "secretRefsPresent": {
            "keyId": _present("RAZORPAY_KEY_ID"),
            "keySecret": _present("RAZORPAY_KEY_SECRET"),
            "webhookSecret": _present("RAZORPAY_WEBHOOK_SECRET"),
        },
        "liveEnabled": live_enabled,
        "liveGateRequired": True,
        "liveGatePresent": _LIVE_GATE_PRESENT,
        "status": status,
        "blockedReasons": blocked_reasons,
        "safeActions": safe_actions,
    }


def payu_readiness() -> dict[str, Any]:
    """PayU is an enum + mock fallback only — no real adapter exists.

    Phase 16E represents PayU as **unavailable** (deferred) and documents the
    missing merchant-key / salt requirement WITHOUT exposing secrets. No live
    PayU API is ever called.
    """
    # PayU has no dedicated mode setting; it is deferred across the runtime.
    merchant_key_present = _present("PAYU_MERCHANT_KEY")
    salt_present = _present("PAYU_SALT")
    configured = merchant_key_present and salt_present
    return {
        "provider": "payu",
        "label": "PayU",
        "mode": "unavailable",
        "rawMode": "unavailable",
        "configured": configured,
        "secretRefsPresent": {
            "merchantKey": merchant_key_present,
            "salt": salt_present,
        },
        "liveEnabled": False,
        "liveGateRequired": True,
        "liveGatePresent": False,
        "status": "unavailable",
        "blockedReasons": [
            "PayU adapter is not implemented (deferred). Only a mock fallback "
            "exists in the payments service.",
            "Missing merchant key / salt configuration (presence check only).",
        ],
        "safeActions": ["View readiness (PayU deferred — no network)."],
    }


def delhivery_readiness() -> dict[str, Any]:
    mode = _mode("DELHIVERY_MODE")
    # mock needs no credentials; test/live need an API token + base URL present.
    configured = (
        True
        if mode == "mock"
        else (
            _present("DELHIVERY_API_TOKEN")
            and _present("DELHIVERY_API_BASE_URL")
        )
    )
    live_requested = mode == "live"
    live_enabled = live_requested and configured and _LIVE_GATE_PRESENT
    status = _normalize_status(
        mode=mode, configured=configured, live_enabled=live_enabled
    )

    blocked_reasons: list[str] = []
    if mode == "live" and not _LIVE_GATE_PRESENT:
        blocked_reasons.append(
            "Live Delhivery booking blocked — Director live gate required."
        )
        # Live booking is refused at the HTTP shipment-create endpoint
        # (HTTP 409); only the controlled CLI Phase 7G-Live gate may book live.
        blocked_reasons.append(
            "HTTP shipment creation is blocked in live mode — use the "
            "controlled CLI courier gate."
        )
    if mode in {"test", "live"} and not configured:
        blocked_reasons.append(
            "Delhivery API token / base URL not configured (presence check only)."
        )

    safe_actions: list[str] = []
    if mode == "mock":
        safe_actions.append(
            "Create a mock shipment via the existing operations flow (no network)."
        )
    elif mode == "test" and configured:
        safe_actions.append(
            "Create a staging/test shipment via the operations flow (Delhivery "
            "staging API — not production)."
        )

    return {
        "provider": "delhivery",
        "label": "Delhivery",
        "mode": _display_mode(mode),
        "rawMode": mode,
        "configured": configured,
        "secretRefsPresent": {
            "apiToken": _present("DELHIVERY_API_TOKEN"),
            "apiBaseUrl": _present("DELHIVERY_API_BASE_URL"),
            "pickupLocation": _present("DELHIVERY_PICKUP_LOCATION"),
            "webhookSecret": _present("DELHIVERY_WEBHOOK_SECRET"),
        },
        "liveEnabled": live_enabled,
        "liveGateRequired": True,
        "liveGatePresent": _LIVE_GATE_PRESENT,
        "status": status,
        "blockedReasons": blocked_reasons,
        "safeActions": safe_actions,
    }


def safety_summary() -> dict[str, Any]:
    """Read-only snapshot of the global safety posture (no mutation)."""
    from apps.ai_governance.sandbox import is_sandbox_enabled

    sandbox_on = bool(is_sandbox_enabled())

    kill_switch_enabled = _kill_switch_enabled()
    # RuntimeKillSwitch.enabled=True → AI Paused (execution blocked).
    return {
        "aiPaused": kill_switch_enabled,
        "sandboxOn": sandbox_on,
        "providerLiveActionsLocked": True,
        "hardeningMode": True,
        "phase": "16E",
    }


def _kill_switch_enabled() -> bool:
    """Best-effort read of the Postgres-safe runtime kill switch (no mutation)."""
    try:
        from apps.saas.models import RuntimeKillSwitch

        row = (
            RuntimeKillSwitch.objects.filter(scope="global")
            .order_by("-pk")
            .first()
        )
        if row is None:
            return True  # default-safe: treat as paused when unknown
        return bool(row.enabled)
    except Exception:
        return True


def payment_logistics_readiness() -> dict[str, Any]:
    """Composite Phase 16E readiness payload for the dashboard."""
    return {
        "safety": safety_summary(),
        "payments": [razorpay_readiness(), payu_readiness()],
        "logistics": [delhivery_readiness()],
        "orderWorkflowGates": {
            "paymentGate": {
                "liveEnabled": False,
                "liveGateRequired": True,
                "liveGatePresent": False,
                "note": (
                    "Live payment link creation / capture / refund is blocked "
                    "without a Director live gate."
                ),
            },
            "shipmentGate": {
                "liveEnabled": False,
                "liveGateRequired": True,
                "liveGatePresent": False,
                "note": (
                    "Live Delhivery AWB booking is blocked without a Director "
                    "live gate; HTTP shipment creation runs mock-only in Phase 16E."
                ),
            },
        },
        "noSideEffect": True,
        "generatedByProvider": False,
    }


def recent_events(limit: int = 25) -> dict[str, Any]:
    """Recent payment + shipment records for the dashboard (safe display only).

    Reads existing rows; never creates anything. Phones / emails / full
    gateway ids are masked. No PII beyond a masked last-4 / truncated id.
    """
    from apps.payments.models import Payment
    from apps.shipments.models import Shipment

    limit = max(1, min(int(limit or 25), 100))

    payments = [
        {
            "id": p.id,
            "orderId": p.order_id,
            "gateway": p.gateway,
            "status": p.status,
            "amount": p.amount,
            "hasPaymentUrl": bool(p.payment_url),
            "gatewayRefLast6": (
                (p.gateway_reference_id or "")[-6:]
                if p.gateway_reference_id
                else ""
            ),
            "createdAt": p.created_at,
        }
        for p in Payment.objects.order_by("-created_at")[:limit]
    ]
    shipments = [
        {
            "awbLast6": (s.awb or "")[-6:],
            "orderId": s.order_id,
            "courier": s.courier,
            "status": s.status,
            "delhiveryStatus": s.delhivery_status,
            "createdAt": s.created_at,
        }
        for s in Shipment.objects.order_by("-created_at")[:limit]
    ]
    return {
        "payments": payments,
        "shipments": shipments,
        "paymentTotal": Payment.objects.count(),
        "shipmentTotal": Shipment.objects.count(),
    }
