"""Phase 6M-0 — MCP masking helpers.

Every value flowing into / out of an MCP tool MUST pass through one
of these helpers before it lands in the audit log or the response
payload. Hard rules:

- NEVER return raw secret values.
- NEVER return full phone numbers / emails / addresses.
- NEVER return raw provider responses.
- Truncate output to ``MCP_MAX_OUTPUT_CHARS`` (default 12000).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from django.conf import settings


# Patterns we mask aggressively. The list is intentionally cautious;
# better to over-mask than to leak.
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{8,}\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ENV_LIKE_RE = re.compile(
    r"^(rzp_(test|live)_|sk_(test|live)_|sk-|sk-ant-|sk_proj_)[A-Za-z0-9_\-]+$"
)
# Substring variant used by ``detect_raw_secret`` when scanning a
# JSON blob — the full string variant above is anchored.
_ENV_LIKE_SUBSTRING_RE = re.compile(
    r"(rzp_(test|live)_[A-Za-z0-9_\-]{6,}|"
    r"sk_(test|live)_[A-Za-z0-9_\-]{6,}|"
    r"sk-ant-[A-Za-z0-9_\-]{6,}|"
    r"sk_proj_[A-Za-z0-9_\-]{6,})"
)

_SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "client_secret",
    "webhook_secret",
    "salt",
    "auth",
    "authorization",
    "bearer",
    "razorpay_key_id",
    "razorpay_key_secret",
    "razorpay_webhook_secret",
)

_SENSITIVE_PII_KEYS = (
    "phone",
    "phone_number",
    "mobile",
    "email",
    "address",
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
    "customer_id",
    "customer_phone",
    "customer_email",
    "raw_response",
    "raw_body",
)


def mask_phone(value: str) -> str:
    """Return a +91*****1234-style mask. Empty string stays empty."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "*" * len(digits)
    return f"+{digits[0]}{'*' * max(0, len(digits) - 5)}{digits[-4:]}"


def mask_email(value: str) -> str:
    """Return ``a***@example.com``-style mask."""
    if not value or "@" not in value:
        return ""
    local, _, domain = value.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_secret_value(value: str) -> str:
    """Return ``***`` for any non-empty value. Empty stays empty."""
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-2:]}"


def is_sensitive_key(key: str) -> bool:
    """Lowercase substring check against the secret-key list."""
    if not key:
        return False
    lk = str(key).lower()
    return any(part in lk for part in _SENSITIVE_KEY_PARTS)


def is_pii_key(key: str) -> bool:
    if not key:
        return False
    lk = str(key).lower()
    return any(part in lk for part in _SENSITIVE_PII_KEYS)


def _mask_string(value: str) -> str:
    """Mask phones, emails, and obvious provider keys inside a string."""
    if not isinstance(value, str) or not value:
        return value
    if _ENV_LIKE_RE.match(value):
        return mask_secret_value(value)
    masked = _PHONE_RE.sub(lambda m: mask_phone(m.group(0)), value)
    masked = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), masked)
    return masked


def mask_value(value: Any, key: str = "") -> Any:
    """Recursive masker for any JSON-shaped value.

    - If the *key* looks sensitive (token / secret / etc) → return ``"***"``.
    - If the *key* looks like PII (phone / email / address) and the value is
      a string → mask via the shape-aware helpers.
    - Strings get phone / email / provider-key scrubbing.
    - Dicts / lists recurse.
    - Other primitives pass through unchanged.
    """
    if is_sensitive_key(key):
        return "***" if value not in (None, "", 0, False) else value
    if isinstance(value, dict):
        return {k: mask_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(v, key) for v in value]
    if isinstance(value, str):
        if is_pii_key(key):
            if "@" in value:
                return mask_email(value)
            if any(ch.isdigit() for ch in value):
                return mask_phone(value)
            return mask_secret_value(value)
        return _mask_string(value)
    return value


def mask_payload(payload: Any) -> Any:
    """Top-level helper used by the executor + audit layer."""
    return mask_value(payload)


def hash_input(payload: Any) -> str:
    """Deterministic SHA-256 (truncated) of the canonical JSON form."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def truncate_output(payload: Any) -> tuple[Any, bool]:
    """Truncate a JSON-stringifiable payload to ``MCP_MAX_OUTPUT_CHARS``.

    Returns ``(payload_or_truncation_marker, was_truncated)``.
    """
    cap = getattr(settings, "MCP_MAX_OUTPUT_CHARS", 12000)
    blob = json.dumps(payload, default=str)
    if len(blob) <= cap:
        return payload, False
    return (
        {
            "_truncated": True,
            "_originalSize": len(blob),
            "_maxOutputChars": cap,
            "preview": blob[:512],
        },
        True,
    )


def detect_full_pii(payload: Any) -> bool:
    """Return True if the masked payload still carries an obvious full
    phone (10+ digit run) / full email / full provider-key string.

    This is a defence-in-depth scan; the executor flips
    ``full_pii_exposed=True`` on the audit row when it triggers.
    """
    blob = json.dumps(payload, default=str)
    if _EMAIL_RE.search(blob):
        return True
    # 10+ consecutive digits surrounded by word boundaries — this skips
    # ISO timestamps like ``2026-05-03T10:01:05.123456+00:00`` and
    # most numeric ids that are split by ``-``/``:``/``.``/``T``.
    if re.search(r"\b\d{10,}\b", blob):
        return True
    if _ENV_LIKE_SUBSTRING_RE.search(blob):
        return True
    return False


def detect_raw_secret(payload: Any) -> bool:
    """Return True if the payload contains a string starting with one
    of the known-secret prefixes (rzp_test_ / sk_ / sk-ant- / etc)."""
    blob = json.dumps(payload, default=str)
    return bool(_ENV_LIKE_SUBSTRING_RE.search(blob))


__all__ = (
    "mask_phone",
    "mask_email",
    "mask_secret_value",
    "is_sensitive_key",
    "is_pii_key",
    "mask_value",
    "mask_payload",
    "hash_input",
    "truncate_output",
    "detect_full_pii",
    "detect_raw_secret",
)
