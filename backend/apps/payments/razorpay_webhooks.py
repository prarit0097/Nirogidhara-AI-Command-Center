"""Phase 6M — Razorpay test-mode webhook handler service.

Pure service module. Phase 6M never calls Razorpay, never mutates
``Payment`` / ``Order`` / ``Shipment`` / ``DiscountOfferLog``,
never sends a customer notification, never returns the raw webhook
secret / raw signature / raw payload.

Public entry: :func:`process_razorpay_webhook` — verifies signature,
checks idempotency, classifies the event, scrubs the payload, and
persists a :class:`apps.payments.models.RazorpayWebhookEvent`.

Hard rules (asserted by tests):

- Signature verification uses the RAW request body (bytes) with
  HMAC-SHA256 + constant-time compare.
- Idempotency uses ``X-Razorpay-Event-Id``; duplicate returns 200
  with ``processing_status="duplicate"`` and never re-processes.
- Replay window defaults to 300 seconds; older events are blocked
  unless explicitly disabled.
- Allowed-event list is a hard whitelist; anything else is
  ``ignored`` / ``blocked_unknown_event``.
- ``business_mutation_was_made`` / ``customer_notification_sent``
  stay ``False`` everywhere in Phase 6M.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone as django_timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import RazorpayWebhookEvent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PROVIDER = "razorpay"
PROCESSING_MODE = (
    RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
)


AUDIT_KIND_RECEIVED = "razorpay.webhook.received"
AUDIT_KIND_BLOCKED = "razorpay.webhook.blocked"
AUDIT_KIND_SIGNATURE_VERIFIED = "razorpay.webhook.signature_verified"
AUDIT_KIND_SIGNATURE_FAILED = "razorpay.webhook.signature_failed"
AUDIT_KIND_DUPLICATE = "razorpay.webhook.duplicate_ignored"
AUDIT_KIND_STORED = "razorpay.webhook.stored"
AUDIT_KIND_EVENT_DENIED = "razorpay.webhook.event_denied"
AUDIT_KIND_REPLAY_BLOCKED = "razorpay.webhook.replay_blocked"
AUDIT_KIND_BUSINESS_MUTATION_BLOCKED = (
    "razorpay.webhook.business_mutation_blocked"
)


# Sensitive payload key parts we always scrub before persistence.
_SENSITIVE_KEY_PARTS = (
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
    "email",
    "contact",
    "phone",
    "mobile",
    "address",
    "customer_id",
    "customer_phone",
    "customer_email",
    "razorpay_key_id",
    "razorpay_key_secret",
    "razorpay_webhook_secret",
    "secret",
    "token",
    "auth",
    "authorization",
)


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def get_razorpay_webhook_settings() -> dict[str, Any]:
    """Read-only snapshot of all Phase 6M Razorpay-webhook settings."""
    return {
        "testModeEnabled": bool(
            getattr(settings, "RAZORPAY_WEBHOOK_TEST_MODE_ENABLED", False)
        ),
        "businessMutationEnabled": bool(
            getattr(
                settings,
                "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED",
                False,
            )
        ),
        "notifyCustomerEnabled": bool(
            getattr(
                settings, "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED", False
            )
        ),
        "storeRawPayload": bool(
            getattr(settings, "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD", False)
        ),
        "allowTestEventsOnly": bool(
            getattr(
                settings, "RAZORPAY_WEBHOOK_ALLOW_TEST_EVENTS_ONLY", True
            )
        ),
        "replayWindowSeconds": int(
            getattr(settings, "RAZORPAY_WEBHOOK_REPLAY_WINDOW_SECONDS", 300)
        ),
        "allowedEvents": list(
            getattr(settings, "RAZORPAY_WEBHOOK_ALLOWED_EVENTS", []) or []
        ),
        "deniedEvents": list(
            getattr(settings, "RAZORPAY_WEBHOOK_DENIED_EVENTS", []) or []
        ),
        "webhookSecretPresent": bool(
            getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or ""
        ),
    }


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def verify_razorpay_webhook_signature(
    raw_body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Constant-time HMAC-SHA256 check of the raw body against ``secret``.

    Phase 6M MUST receive ``raw_body`` exactly as Razorpay sent it —
    do NOT json.loads + json.dumps before verification, or the byte
    sequence will differ and the signature will not match.
    """
    if not secret or not signature or not isinstance(raw_body, (bytes, bytearray)):
        return False
    try:
        computed = hmac.new(
            key=secret.encode("utf-8"),
            msg=bytes(raw_body),
            digestmod=hashlib.sha256,
        ).hexdigest()
    except Exception:  # noqa: BLE001
        return False
    return hmac.compare_digest(computed, signature)


def compute_razorpay_signature(raw_body: bytes, secret: str) -> str:
    """Helper used by the simulator + tests to compute a valid signature."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=bytes(raw_body),
        digestmod=hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Payload parsing + classification
# ---------------------------------------------------------------------------


def parse_razorpay_webhook_payload(raw_body: bytes) -> dict[str, Any]:
    """Decode the Razorpay JSON body. Raises ``ValueError`` on bad JSON."""
    if not isinstance(raw_body, (bytes, bytearray)):
        raise ValueError("raw_body must be bytes")
    try:
        text = raw_body.decode("utf-8") or "{}"
    except UnicodeDecodeError as exc:
        raise ValueError("raw_body is not utf-8") from exc
    parsed = json.loads(text or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("payload must be a JSON object")
    return parsed


def _payload_contains_keys(payload: dict[str, Any]) -> list[str]:
    contained = (payload.get("contains") or [])
    if isinstance(contained, list):
        return [str(item) for item in contained if isinstance(item, str)]
    return []


def classify_razorpay_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the event name + idempotency-relevant fields without touching
    sensitive sub-objects.
    """
    event_name = str(payload.get("event") or "")
    contains = _payload_contains_keys(payload)
    created_at_raw = payload.get("created_at")
    created_at_dt: Optional[datetime] = None
    if isinstance(created_at_raw, (int, float)):
        try:
            created_at_dt = datetime.fromtimestamp(
                int(created_at_raw), tz=timezone.utc
            )
        except (OverflowError, OSError, ValueError):
            created_at_dt = None
    return {
        "eventName": event_name,
        "entity": str(payload.get("entity") or "event"),
        "contains": contains,
        "createdAt": created_at_dt,
        "createdAtRaw": created_at_raw,
    }


def extract_provider_ids(payload: dict[str, Any]) -> dict[str, Any]:
    """Pluck provider object ids + amount / currency safely."""
    payload_block = payload.get("payload") or {}
    if not isinstance(payload_block, dict):
        payload_block = {}

    payment_entity = (
        ((payload_block.get("payment") or {}).get("entity") or {})
        if isinstance(payload_block.get("payment"), dict)
        else {}
    )
    order_entity = (
        ((payload_block.get("order") or {}).get("entity") or {})
        if isinstance(payload_block.get("order"), dict)
        else {}
    )
    refund_entity = (
        ((payload_block.get("refund") or {}).get("entity") or {})
        if isinstance(payload_block.get("refund"), dict)
        else {}
    )
    payment_link_entity = (
        ((payload_block.get("payment_link") or {}).get("entity") or {})
        if isinstance(payload_block.get("payment_link"), dict)
        else {}
    )

    if not isinstance(payment_entity, dict):
        payment_entity = {}
    if not isinstance(order_entity, dict):
        order_entity = {}
    if not isinstance(refund_entity, dict):
        refund_entity = {}
    if not isinstance(payment_link_entity, dict):
        payment_link_entity = {}

    provider_payment_id = str(payment_entity.get("id") or "")
    provider_order_id = str(
        payment_entity.get("order_id")
        or order_entity.get("id")
        or payment_link_entity.get("order_id")
        or ""
    )
    provider_refund_id = str(refund_entity.get("id") or "")
    amount_raw = (
        payment_entity.get("amount")
        or order_entity.get("amount_paid")
        or order_entity.get("amount")
        or refund_entity.get("amount")
        or payment_link_entity.get("amount_paid")
        or payment_link_entity.get("amount")
    )
    try:
        amount_paise = int(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        amount_paise = None
    currency = str(
        payment_entity.get("currency")
        or order_entity.get("currency")
        or refund_entity.get("currency")
        or payment_link_entity.get("currency")
        or ""
    )
    payment_status = str(payment_entity.get("status") or "")
    order_status = str(order_entity.get("status") or "")
    return {
        "providerPaymentId": provider_payment_id,
        "providerOrderId": provider_order_id,
        "providerRefundId": provider_refund_id,
        "amountPaise": amount_paise,
        "currency": currency,
        "paymentStatus": payment_status,
        "orderStatus": order_status,
    }


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def _is_sensitive_key(key: str) -> bool:
    if not key:
        return False
    lk = str(key).lower()
    return any(part in lk for part in _SENSITIVE_KEY_PARTS)


def _mask_str(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _mask_recursive(
    value: Any,
    key: str = "",
    scrubbed: list[str] | None = None,
) -> Any:
    if scrubbed is None:
        scrubbed = []
    if _is_sensitive_key(key):
        scrubbed.append(key)
        if isinstance(value, str):
            return _mask_str(value)
        if isinstance(value, (int, float)) and value:
            return "***"
        return "***" if value not in (None, "", [], {}) else value
    if isinstance(value, dict):
        return {k: _mask_recursive(v, k, scrubbed) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_recursive(v, key, scrubbed) for v in value]
    return value


def mask_razorpay_webhook_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(masked_payload, scrubbed_keys)``."""
    scrubbed: list[str] = []
    masked = _mask_recursive(payload, "", scrubbed)
    return masked if isinstance(masked, dict) else {}, sorted(set(scrubbed))


def build_safe_razorpay_webhook_summary(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Reduce a Razorpay payload to a non-leaking summary."""
    classify = classify_razorpay_event(payload)
    ids = extract_provider_ids(payload)
    return {
        "event": classify["eventName"],
        "entity": classify["entity"],
        "contains": classify["contains"],
        "createdAtIso": (
            classify["createdAt"].isoformat()
            if classify["createdAt"] is not None
            else None
        ),
        "providerOrderId": ids["providerOrderId"],
        "providerPaymentId": ids["providerPaymentId"],
        "providerRefundId": ids["providerRefundId"],
        "amountPaise": ids["amountPaise"],
        "currency": ids["currency"],
        "paymentStatus": ids["paymentStatus"],
        "orderStatus": ids["orderStatus"],
    }


def _safe_request_headers(headers: Optional[dict[str, str]]) -> dict[str, Any]:
    """Whitelist a small set of safe header names."""
    if not headers:
        return {}
    safe_keys = (
        "content-type",
        "user-agent",
        "x-razorpay-event-id",
        "x-razorpay-signature",
    )
    out: dict[str, Any] = {}
    for raw_key, raw_value in headers.items():
        key = str(raw_key or "").lower()
        if key not in safe_keys:
            continue
        value = str(raw_value or "")
        if key == "x-razorpay-signature":
            # Never echo the raw signature; presence boolean only.
            out[key] = "present" if value else "missing"
        else:
            out[key] = value[:120]
    return out


# ---------------------------------------------------------------------------
# Replay validation
# ---------------------------------------------------------------------------


def validate_replay_window(
    payload_created_at: Optional[datetime],
    received_at: Optional[datetime],
    window_seconds: int,
) -> bool:
    """True when ``payload_created_at`` is within ``window_seconds`` of
    ``received_at``. Missing ``payload_created_at`` returns False.
    """
    if payload_created_at is None or received_at is None or window_seconds <= 0:
        return False
    delta = abs((received_at - payload_created_at).total_seconds())
    return delta <= window_seconds


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _safe_audit_payload(record: RazorpayWebhookEvent) -> dict[str, Any]:
    return {
        "event_id": record.event_id,
        "source_event_id": record.source_event_id,
        "provider": record.provider,
        "environment": record.environment,
        "event_name": record.event_name,
        "signature_present": record.signature_present,
        "signature_valid": record.signature_valid,
        "replay_window_valid": record.replay_window_valid,
        "idempotency_status": record.idempotency_status,
        "processing_status": record.processing_status,
        "processing_mode": record.processing_mode,
        "provider_order_id": record.provider_order_id,
        "provider_payment_id": record.provider_payment_id,
        "provider_refund_id": record.provider_refund_id,
        "amount_paise": record.amount_paise,
        "currency": record.currency,
        "payment_status": record.payment_status,
        "order_status": record.order_status,
        "blockers": record.blockers,
        "warnings": record.warnings,
        "business_mutation_attempted": record.business_mutation_attempted,
        "business_mutation_was_made": record.business_mutation_was_made,
        "customer_notification_attempted": record.customer_notification_attempted,
        "customer_notification_sent": record.customer_notification_sent,
        "raw_secret_exposed": record.raw_secret_exposed,
        "full_pii_exposed": record.full_pii_exposed,
        "duplicate_count": record.duplicate_count,
    }


def _audit_record(
    *,
    kind: str,
    record: RazorpayWebhookEvent,
    text: str,
) -> AuditEvent:
    tone = (
        AuditEvent.Tone.WARNING
        if record.processing_status
        in {
            RazorpayWebhookEvent.ProcessingStatus.BLOCKED,
            RazorpayWebhookEvent.ProcessingStatus.FAILED,
            RazorpayWebhookEvent.ProcessingStatus.IGNORED,
        }
        else AuditEvent.Tone.SUCCESS
        if record.processing_status
        in {
            RazorpayWebhookEvent.ProcessingStatus.STORED,
            RazorpayWebhookEvent.ProcessingStatus.VERIFIED,
        }
        else AuditEvent.Tone.INFO
    )
    return write_event(
        kind=kind,
        text=text,
        tone=tone,
        payload=_safe_audit_payload(record),
    )


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def assert_no_business_mutation(
    record: RazorpayWebhookEvent,
) -> bool:
    return (
        record.business_mutation_was_made is False
        and record.customer_notification_sent is False
        and record.processing_mode
        == RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
    )


# ---------------------------------------------------------------------------
# Main entry: process_razorpay_webhook
# ---------------------------------------------------------------------------


def _hash_body(raw_body: bytes) -> str:
    return hashlib.sha256(bytes(raw_body or b"")).hexdigest()[:32]


def _result(
    *,
    record: Optional[RazorpayWebhookEvent],
    status_code: int,
    next_action: str,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "passed": (
            record is not None
            and record.processing_status
            in {
                RazorpayWebhookEvent.ProcessingStatus.STORED,
                RazorpayWebhookEvent.ProcessingStatus.VERIFIED,
                RazorpayWebhookEvent.ProcessingStatus.DUPLICATE,
            }
        ),
        "statusCode": status_code,
        "eventId": record.event_id if record else "",
        "sourceEventId": record.source_event_id if record else "",
        "eventName": record.event_name if record else "",
        "signatureValid": record.signature_valid if record else False,
        "idempotencyStatus": (
            record.idempotency_status
            if record
            else RazorpayWebhookEvent.IdempotencyStatus.MISSING_EVENT_ID
        ),
        "processingStatus": (
            record.processing_status
            if record
            else RazorpayWebhookEvent.ProcessingStatus.BLOCKED
        ),
        "businessMutationWasMade": False,
        "customerNotificationSent": False,
        "providerCallAttempted": False,
        "blockers": list(record.blockers) if record else [],
        "warnings": list(record.warnings) if record else [],
        "nextAction": next_action,
    }
    if extra:
        payload.update(extra)
    return payload


def _build_blocked_record(
    *,
    event_name: str,
    blockers: list[str],
    warnings: list[str],
    payload_hash: str,
    safe_summary: dict[str, Any],
    scrubbed_keys: list[str],
    headers_summary: dict[str, Any],
    source_event_id: str = "",
    signature_present: bool = False,
    signature_valid: bool = False,
    denied_reason: str = "",
    processing_status: str = (
        RazorpayWebhookEvent.ProcessingStatus.BLOCKED
    ),
) -> RazorpayWebhookEvent:
    return RazorpayWebhookEvent.objects.create(
        provider=PROVIDER,
        environment=RazorpayWebhookEvent.Environment.TEST,
        event_name=event_name or "unknown",
        entity=str(safe_summary.get("entity") or "event"),
        signature_present=signature_present,
        signature_valid=signature_valid,
        replay_window_valid=False,
        idempotency_status=(
            RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN
            if source_event_id
            else RazorpayWebhookEvent.IdempotencyStatus.MISSING_EVENT_ID
        ),
        processing_status=processing_status,
        processing_mode=PROCESSING_MODE,
        source_event_id=source_event_id,
        event_id=source_event_id,
        provider_order_id=safe_summary.get("providerOrderId", "") or "",
        provider_payment_id=safe_summary.get("providerPaymentId", "") or "",
        provider_refund_id=safe_summary.get("providerRefundId", "") or "",
        amount_paise=safe_summary.get("amountPaise"),
        currency=safe_summary.get("currency", "") or "",
        payment_status=safe_summary.get("paymentStatus", "") or "",
        order_status=safe_summary.get("orderStatus", "") or "",
        contains=safe_summary.get("contains", []) or [],
        payload_hash=payload_hash,
        safe_payload_summary=safe_summary,
        scrubbed_keys=list(scrubbed_keys),
        denied_reason=denied_reason[:200],
        blockers=list(blockers),
        warnings=list(warnings),
        request_headers_summary=headers_summary,
        metadata={"phase": "6M"},
    )


def process_razorpay_webhook(
    raw_body: bytes,
    headers: Optional[dict[str, str]] = None,
    request_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Single entry that the DRF view + simulator call.

    Returns a dict carrying ``statusCode`` so the view can choose the
    right HTTP status. NEVER raises — the view always returns the
    structured shape.
    """
    headers = headers or {}
    settings_snapshot = get_razorpay_webhook_settings()
    headers_summary = _safe_request_headers(headers)
    raw_signature = ""
    raw_event_id = ""
    for key, value in headers.items():
        lk = str(key or "").lower()
        if lk == "x-razorpay-signature":
            raw_signature = str(value or "")
        elif lk == "x-razorpay-event-id":
            raw_event_id = str(value or "")
    payload_hash = _hash_body(raw_body)

    # ----- 1. Test mode flag -----
    if not settings_snapshot["testModeEnabled"]:
        record = _build_blocked_record(
            event_name="unknown",
            blockers=["razorpay_webhook_test_mode_disabled"],
            warnings=[],
            payload_hash=payload_hash,
            safe_summary={"event": "", "entity": "event"},
            scrubbed_keys=[],
            headers_summary=headers_summary,
            source_event_id=raw_event_id,
            signature_present=bool(raw_signature),
            denied_reason="razorpay_webhook_test_mode_disabled",
        )
        event = _audit_record(
            kind=AUDIT_KIND_BLOCKED,
            record=record,
            text="Razorpay webhook blocked (test mode disabled).",
        )
        record.audit_event_id = event.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=403,
            next_action="enable_RAZORPAY_WEBHOOK_TEST_MODE_ENABLED_after_review",
        )

    secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or ""
    if not secret:
        record = _build_blocked_record(
            event_name="unknown",
            blockers=["razorpay_webhook_secret_missing"],
            warnings=[],
            payload_hash=payload_hash,
            safe_summary={"event": "", "entity": "event"},
            scrubbed_keys=[],
            headers_summary=headers_summary,
            source_event_id=raw_event_id,
            signature_present=bool(raw_signature),
            denied_reason="razorpay_webhook_secret_missing",
        )
        event = _audit_record(
            kind=AUDIT_KIND_BLOCKED,
            record=record,
            text="Razorpay webhook blocked (secret missing).",
        )
        record.audit_event_id = event.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=400,
            next_action="set_RAZORPAY_WEBHOOK_SECRET_env",
        )

    # ----- 2. Signature verification (raw body) -----
    if not raw_signature:
        record = _build_blocked_record(
            event_name="unknown",
            blockers=["x_razorpay_signature_header_missing"],
            warnings=[],
            payload_hash=payload_hash,
            safe_summary={"event": "", "entity": "event"},
            scrubbed_keys=[],
            headers_summary=headers_summary,
            source_event_id=raw_event_id,
            signature_present=False,
            denied_reason="x_razorpay_signature_header_missing",
        )
        event = _audit_record(
            kind=AUDIT_KIND_SIGNATURE_FAILED,
            record=record,
            text="Razorpay webhook signature missing.",
        )
        record.audit_event_id = event.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=400,
            next_action="ensure_x_razorpay_signature_header_present",
        )
    if not verify_razorpay_webhook_signature(raw_body, raw_signature, secret):
        record = _build_blocked_record(
            event_name="unknown",
            blockers=["razorpay_webhook_signature_invalid"],
            warnings=[],
            payload_hash=payload_hash,
            safe_summary={"event": "", "entity": "event"},
            scrubbed_keys=[],
            headers_summary=headers_summary,
            source_event_id=raw_event_id,
            signature_present=True,
            signature_valid=False,
            denied_reason="razorpay_webhook_signature_invalid",
        )
        event = _audit_record(
            kind=AUDIT_KIND_SIGNATURE_FAILED,
            record=record,
            text="Razorpay webhook signature invalid.",
        )
        record.audit_event_id = event.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=400,
            next_action="reject_invalid_signature",
        )

    # ----- 3. Parse payload (after signature ok) -----
    try:
        payload = parse_razorpay_webhook_payload(raw_body)
    except ValueError:
        record = _build_blocked_record(
            event_name="unknown",
            blockers=["razorpay_webhook_invalid_json"],
            warnings=[],
            payload_hash=payload_hash,
            safe_summary={"event": "", "entity": "event"},
            scrubbed_keys=[],
            headers_summary=headers_summary,
            source_event_id=raw_event_id,
            signature_present=True,
            signature_valid=True,
            denied_reason="razorpay_webhook_invalid_json",
        )
        event = _audit_record(
            kind=AUDIT_KIND_BLOCKED,
            record=record,
            text="Razorpay webhook payload not valid JSON.",
        )
        record.audit_event_id = event.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=400,
            next_action="reject_invalid_json",
        )

    classify = classify_razorpay_event(payload)
    event_name = classify["eventName"] or "unknown"
    safe_summary = build_safe_razorpay_webhook_summary(payload)
    masked_payload, scrubbed_keys = mask_razorpay_webhook_payload(payload)
    safe_summary["maskedPayloadKeys"] = sorted(list(masked_payload.keys()))

    received_at = django_timezone.now()
    replay_ok = validate_replay_window(
        classify["createdAt"],
        received_at,
        settings_snapshot["replayWindowSeconds"],
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if classify["createdAt"] is None:
        warnings.append("payload_created_at_missing")
    if not replay_ok and classify["createdAt"] is not None:
        blockers.append("replay_window_exceeded")

    allowed = set(settings_snapshot["allowedEvents"])
    denied = set(settings_snapshot["deniedEvents"])
    if event_name in denied:
        blockers.append("event_name_denylisted")
    elif event_name not in allowed:
        blockers.append("event_name_not_in_allowlist")

    # ----- 4. Idempotency / dedup on source_event_id -----
    if raw_event_id:
        existing = (
            RazorpayWebhookEvent.objects.filter(
                provider=PROVIDER, source_event_id=raw_event_id
            )
            .order_by("created_at")
            .first()
        )
        if existing is not None:
            existing.duplicate_count = (existing.duplicate_count or 0) + 1
            existing.warnings = list(existing.warnings or []) + [
                "duplicate_seen_at_" + received_at.isoformat()
            ]
            existing.save(
                update_fields=["duplicate_count", "warnings", "updated_at"]
            )
            event = _audit_record(
                kind=AUDIT_KIND_DUPLICATE,
                record=existing,
                text=(
                    f"Razorpay webhook duplicate ignored "
                    f"(source_event_id={raw_event_id})."
                ),
            )
            existing.audit_event_id = event.id
            existing.save(update_fields=["audit_event_id", "updated_at"])
            return _result(
                record=existing,
                status_code=200,
                next_action="duplicate_ignored_no_mutation",
                extra={"duplicate": True},
            )

    # ----- 5. Persist verified record -----
    ids = extract_provider_ids(payload)
    record = RazorpayWebhookEvent(
        provider=PROVIDER,
        environment=RazorpayWebhookEvent.Environment.TEST,
        event_name=event_name,
        entity=str(payload.get("entity") or "event"),
        created_at_from_payload=classify["createdAt"],
        signature_present=True,
        signature_valid=True,
        replay_window_valid=replay_ok,
        idempotency_status=(
            RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN
            if raw_event_id
            else RazorpayWebhookEvent.IdempotencyStatus.MISSING_EVENT_ID
        ),
        processing_mode=PROCESSING_MODE,
        source_event_id=raw_event_id,
        event_id=raw_event_id,
        provider_order_id=ids["providerOrderId"],
        provider_payment_id=ids["providerPaymentId"],
        provider_refund_id=ids["providerRefundId"],
        amount_paise=ids["amountPaise"],
        currency=ids["currency"],
        payment_status=ids["paymentStatus"],
        order_status=ids["orderStatus"],
        contains=classify["contains"],
        payload_hash=payload_hash,
        safe_payload_summary=safe_summary,
        scrubbed_keys=list(scrubbed_keys),
        blockers=list(blockers),
        warnings=list(warnings),
        business_mutation_attempted=False,
        business_mutation_was_made=False,
        customer_notification_attempted=False,
        customer_notification_sent=False,
        raw_secret_exposed=False,
        full_pii_exposed=False,
        request_headers_summary=headers_summary,
        metadata={"phase": "6M", "request_meta": request_meta or {}},
    )

    if blockers:
        # Allowed-event blocker / replay blocker → store as ignored
        # (status 200 so Razorpay does not retry). Audit logs the
        # rejection reason.
        ignore_reason = "blocked_event"
        if "event_name_not_in_allowlist" in blockers:
            ignore_reason = "blocked_unknown_event"
            audit_kind = AUDIT_KIND_EVENT_DENIED
        elif "event_name_denylisted" in blockers:
            ignore_reason = "blocked_event_denylisted"
            audit_kind = AUDIT_KIND_EVENT_DENIED
        elif "replay_window_exceeded" in blockers:
            ignore_reason = "replay_window_exceeded"
            audit_kind = AUDIT_KIND_REPLAY_BLOCKED
        else:
            audit_kind = AUDIT_KIND_BLOCKED
        record.processing_status = (
            RazorpayWebhookEvent.ProcessingStatus.IGNORED
        )
        record.denied_reason = ignore_reason
        try:
            record.save()
        except IntegrityError:
            existing = RazorpayWebhookEvent.objects.filter(
                provider=PROVIDER, source_event_id=raw_event_id
            ).first()
            if existing is None:
                raise
            return _result(
                record=existing,
                status_code=200,
                next_action="duplicate_ignored_no_mutation",
                extra={"duplicate": True},
            )
        event_audit = _audit_record(
            kind=audit_kind,
            record=record,
            text=(
                f"Razorpay webhook {event_name} ignored "
                f"({ignore_reason})."
            ),
        )
        record.audit_event_id = event_audit.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=200,
            next_action="ignored_no_mutation",
        )

    record.processing_status = RazorpayWebhookEvent.ProcessingStatus.STORED
    try:
        record.save()
    except IntegrityError:
        # Concurrent duplicate insert — fall back to the existing row.
        existing = RazorpayWebhookEvent.objects.filter(
            provider=PROVIDER, source_event_id=raw_event_id
        ).first()
        if existing is None:
            raise
        return _result(
            record=existing,
            status_code=200,
            next_action="duplicate_ignored_no_mutation",
            extra={"duplicate": True},
        )

    # Defence-in-depth: business mutation flags must remain False.
    if not assert_no_business_mutation(record):
        record.processing_status = (
            RazorpayWebhookEvent.ProcessingStatus.FAILED
        )
        record.blockers = list(record.blockers or []) + [
            "phase_6m_business_mutation_invariant_violation"
        ]
        record.save()
        event_audit = _audit_record(
            kind=AUDIT_KIND_BUSINESS_MUTATION_BLOCKED,
            record=record,
            text=(
                "Razorpay webhook invariant violation; refusing "
                "business mutation."
            ),
        )
        record.audit_event_id = event_audit.id
        record.save(update_fields=["audit_event_id", "updated_at"])
        return _result(
            record=record,
            status_code=200,
            next_action="invariant_violation_audit_only",
        )

    sig_audit = _audit_record(
        kind=AUDIT_KIND_SIGNATURE_VERIFIED,
        record=record,
        text=(
            f"Razorpay webhook signature verified ({event_name})."
        ),
    )
    record.audit_event_id = sig_audit.id
    record.save(update_fields=["audit_event_id", "updated_at"])
    stored_audit = _audit_record(
        kind=AUDIT_KIND_STORED,
        record=record,
        text=f"Razorpay webhook stored ({event_name}).",
    )
    record.audit_event_id = stored_audit.id
    record.save(update_fields=["audit_event_id", "updated_at"])
    return _result(
        record=record,
        status_code=200,
        next_action="ready_for_phase_6n_business_mutation_sandbox_plan",
    )


__all__ = (
    "PROVIDER",
    "PROCESSING_MODE",
    "AUDIT_KIND_RECEIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_SIGNATURE_VERIFIED",
    "AUDIT_KIND_SIGNATURE_FAILED",
    "AUDIT_KIND_DUPLICATE",
    "AUDIT_KIND_STORED",
    "AUDIT_KIND_EVENT_DENIED",
    "AUDIT_KIND_REPLAY_BLOCKED",
    "AUDIT_KIND_BUSINESS_MUTATION_BLOCKED",
    "get_razorpay_webhook_settings",
    "verify_razorpay_webhook_signature",
    "compute_razorpay_signature",
    "parse_razorpay_webhook_payload",
    "classify_razorpay_event",
    "build_safe_razorpay_webhook_summary",
    "mask_razorpay_webhook_payload",
    "extract_provider_ids",
    "validate_replay_window",
    "process_razorpay_webhook",
    "assert_no_business_mutation",
)
