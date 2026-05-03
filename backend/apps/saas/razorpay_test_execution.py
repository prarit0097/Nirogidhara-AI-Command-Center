"""Phase 6K — Razorpay test-mode ``create_order`` adapter.

This adapter is **separate** from the Phase 2B
``apps.payments.integrations.razorpay_client`` (which only owns the
production payment-link path). Phase 6K owns one Razorpay endpoint
only — the Orders API ``create`` method against a test key — and
nothing else.

Hard rules:

- Only callable when ``provider_environment == "test"`` AND the live
  ``RAZORPAY_KEY_ID`` starts with ``rzp_test`` AND
  ``PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=true`` AND ``confirm`` is
  ``True``.
- Never logs or returns the API key.
- Never creates a payment link.
- Never captures a payment.
- Never includes customer name / phone / email / address in the
  payload.
- Returns a SAFE summary only (`{id, status, amount, currency,
  receipt}`); the raw provider response is NOT persisted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from .provider_execution_policy import (
    PHASE_6K_ENV_FLAG,
    RAZORPAY_LIVE_KEY_PREFIX,
    RAZORPAY_TEST_KEY_PREFIX,
)


class RazorpayTestExecutionError(Exception):
    """Raised when a precondition fails or the SDK call fails."""


@dataclass(frozen=True)
class RazorpayTestOrderResult:
    """Safe summary of a Razorpay test order. Never carries raw secrets."""

    provider_object_id: str
    status: str
    amount: int
    currency: str
    receipt: str
    safe_response_summary: dict[str, Any]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def mask_razorpay_key_id(key_id: str) -> str:
    """Mask a Razorpay key id for logs / API output.

    Examples
    --------
    >>> mask_razorpay_key_id("rzp_test_ABCDEF1234567890")
    'rzp_test_***7890'
    >>> mask_razorpay_key_id("")
    ''
    """
    if not key_id:
        return ""
    if len(key_id) <= 12:
        return key_id[:8] + "***"
    return f"{key_id[:9]}***{key_id[-4:]}"


def _classify_key_mode(key_id: str) -> str:
    if not key_id:
        return "missing"
    if key_id.startswith(RAZORPAY_LIVE_KEY_PREFIX):
        return "live"
    if key_id.startswith(RAZORPAY_TEST_KEY_PREFIX):
        return "test"
    return "unknown"


def _env_flag_enabled() -> bool:
    raw = (os.environ.get(PHASE_6K_ENV_FLAG) or "").strip().lower()
    return raw == "true"


def inspect_razorpay_test_env() -> dict[str, Any]:
    """Read-only env diagnostic. Reports presence + key mode only.

    NEVER returns or logs the raw key value.
    """
    key_id = os.environ.get("RAZORPAY_KEY_ID") or ""
    key_secret_present = bool(os.environ.get("RAZORPAY_KEY_SECRET"))
    webhook_present = bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET"))
    mode = _classify_key_mode(key_id)
    return {
        "envFlag": PHASE_6K_ENV_FLAG,
        "envFlagPresent": PHASE_6K_ENV_FLAG in os.environ,
        "envFlagEnabled": _env_flag_enabled(),
        "razorpayKeyIdPresent": bool(key_id),
        "razorpayKeyMode": mode,
        "razorpayKeyIdMasked": mask_razorpay_key_id(key_id),
        "razorpayKeySecretPresent": key_secret_present,
        "razorpayWebhookSecretPresent": webhook_present,
        "isTestKey": mode == "test",
        "isLiveKey": mode == "live",
    }


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def build_razorpay_test_order_payload(
    *,
    execution_id: str,
    amount_paise: int = 100,
    currency: str = "INR",
) -> dict[str, Any]:
    """Construct the synthetic Razorpay test ``create_order`` payload.

    Phase 6K hard rules: amount=100 paise, currency=INR, no customer
    block, no notify, no callbacks, notes flagged as internal-only.
    """
    if amount_paise != 100:
        raise RazorpayTestExecutionError(
            f"Phase 6K amount_paise must be 100; got {amount_paise}"
        )
    if (currency or "INR").upper() != "INR":
        raise RazorpayTestExecutionError(
            f"Phase 6K currency must be INR; got {currency}"
        )
    return {
        "amount": 100,
        "currency": "INR",
        "receipt": f"phase6k_{execution_id}",
        "notes": {
            "purpose": "phase6k_internal_test_mode_only",
            "external_customer": "false",
            "real_money": "false",
            "business_mutation": "false",
            "phase": "6K",
        },
    }


# ---------------------------------------------------------------------------
# Response summary
# ---------------------------------------------------------------------------


def summarize_razorpay_order_response(response: Any) -> dict[str, Any]:
    """Reduce the Razorpay response to a safe summary.

    Strips amount_due / amount_paid blocks beyond the canonical id,
    status, amount, currency, receipt fields. NEVER stores raw
    provider response in DB.
    """
    if not isinstance(response, dict):
        return {
            "id": "",
            "status": "",
            "amount": 0,
            "currency": "INR",
            "receipt": "",
        }
    return {
        "id": str(response.get("id") or ""),
        "status": str(response.get("status") or ""),
        "amount": int(response.get("amount") or 0),
        "currency": str(response.get("currency") or "INR"),
        "receipt": str(response.get("receipt") or ""),
    }


# ---------------------------------------------------------------------------
# Provider call
# ---------------------------------------------------------------------------


def _create_order_via_sdk(payload: dict[str, Any]) -> dict[str, Any]:
    """Call the Razorpay Orders API ``create`` endpoint via the SDK.

    Raises :class:`RazorpayTestExecutionError` when the SDK is not
    installed, when credentials are missing, or when the underlying
    SDK raises. NEVER logs the auth tuple.
    """
    try:
        import razorpay  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RazorpayTestExecutionError(
            "razorpay SDK is not installed; run `pip install razorpay`."
        ) from exc

    key_id = os.environ.get("RAZORPAY_KEY_ID") or ""
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET") or ""
    if not key_id or not key_secret:
        raise RazorpayTestExecutionError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not configured."
        )

    client = razorpay.Client(auth=(key_id, key_secret))
    try:
        return client.order.create(payload)
    except Exception as exc:  # pragma: no cover - real-network path
        # Use class name only; never echo SDK error message verbatim
        # because some SDK errors quote the request body.
        raise RazorpayTestExecutionError(
            f"Razorpay SDK error: {exc.__class__.__name__}"
        ) from exc


def execute_razorpay_test_create_order(
    *,
    execution_id: str,
    amount_paise: int = 100,
    currency: str = "INR",
    confirm: bool = False,
) -> RazorpayTestOrderResult:
    """Issue ONE Razorpay test-mode ``create_order`` call.

    The function refuses to dispatch unless EVERY precondition is
    satisfied. Returns a :class:`RazorpayTestOrderResult` carrying a
    safe summary; raises :class:`RazorpayTestExecutionError` on
    refusal or SDK failure. NEVER returns or logs the API key.
    """
    blockers: list[str] = []
    if not confirm:
        blockers.append("explicit_confirm_flag_required")
    if not _env_flag_enabled():
        blockers.append(
            f"env_flag_{PHASE_6K_ENV_FLAG}_must_be_true"
        )
    env = inspect_razorpay_test_env()
    if not env["razorpayKeyIdPresent"]:
        blockers.append("RAZORPAY_KEY_ID env not set")
    if not env["razorpayKeySecretPresent"]:
        blockers.append("RAZORPAY_KEY_SECRET env not set")
    if env["isLiveKey"]:
        blockers.append("razorpay_key_id_is_live_key_refusing")
    if not env["isTestKey"]:
        blockers.append("razorpay_key_id_must_start_with_rzp_test")

    if blockers:
        raise RazorpayTestExecutionError(
            "Phase 6K execution blocked: " + ", ".join(blockers)
        )

    payload = build_razorpay_test_order_payload(
        execution_id=execution_id,
        amount_paise=amount_paise,
        currency=currency,
    )
    response = _create_order_via_sdk(payload)
    summary = summarize_razorpay_order_response(response)
    if not summary["id"]:
        raise RazorpayTestExecutionError(
            "Razorpay test order succeeded but response carried no id."
        )

    warnings: list[str] = []
    if not env["razorpayWebhookSecretPresent"]:
        warnings.append(
            "RAZORPAY_WEBHOOK_SECRET env not set — required for "
            "Phase 6L webhook readiness."
        )

    return RazorpayTestOrderResult(
        provider_object_id=summary["id"],
        status=summary["status"] or "created",
        amount=summary["amount"],
        currency=summary["currency"],
        receipt=summary["receipt"],
        safe_response_summary=summary,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def assert_no_business_mutation_from_execution(attempt) -> bool:
    """True only when the attempt declares zero business-side mutations.

    Reused by tests + the service layer to guarantee Phase 6K never
    flips an Order/Payment/Shipment row.
    """
    return (
        getattr(attempt, "business_mutation_was_made", False) is False
        and getattr(attempt, "payment_link_created", False) is False
        and getattr(attempt, "payment_captured", False) is False
        and getattr(attempt, "customer_notification_sent", False) is False
    )


__all__ = (
    "RazorpayTestExecutionError",
    "RazorpayTestOrderResult",
    "mask_razorpay_key_id",
    "inspect_razorpay_test_env",
    "build_razorpay_test_order_payload",
    "summarize_razorpay_order_response",
    "execute_razorpay_test_create_order",
    "assert_no_business_mutation_from_execution",
)
