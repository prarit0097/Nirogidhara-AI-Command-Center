"""Phase 5C — strict JSON schema for the WhatsApp AI Chat Agent.

The LLM is instructed to return a single JSON object that matches the
shape below. The validator runs server-side BEFORE any send — anything
that fails the schema becomes a ``handoff`` outcome instead of a
customer-facing reply.

Locked decisions (Phase 5A-1 §V + Phase 5C brief):
- ``action`` is one of a small enum. ``send_reply`` is the most common;
  ``book_order`` requires explicit customer confirmation; ``handoff``
  is the safe default for anything risky.
- ``language`` must come from
  :mod:`apps.whatsapp.language` vocabulary.
- ``confidence`` is a float in ``[0.0, 1.0]``. The auto-send rate gate
  uses it.
- ``safety`` flags trigger immediate handoff regardless of ``action``.
- ``orderDraft`` is consumed only when ``action == 'book_order'``.
- ``payment.shouldCreateAdvanceLink`` is honoured only after a
  successful order booking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .language import LANGUAGE_CHOICES, normalize_language


VALID_ACTIONS: tuple[str, ...] = (
    "send_reply",
    "ask_question",
    "book_order",
    "handoff",
    "no_action",
)

# Locked stage vocabulary — the Phase 5C state machine. Stored in
# ``WhatsAppConversation.metadata.ai.stage``.
SALES_STAGES: tuple[str, ...] = (
    "greeting",
    "discovery",
    "category_detection",
    "product_explanation",
    "objection_handling",
    "price_presented",
    "discount_negotiation",
    "address_collection",
    "order_confirmation",
    "order_booked",
    "handoff_required",
)

# Phase 5A-1 / 5C — supported product categories. Mirrors
# ``apps.catalog.ProductCategory`` slugs the Sales team actually uses.
SUPPORTED_CATEGORIES: tuple[str, ...] = (
    "weight-management",
    "blood-purification",
    "men-wellness",
    "women-wellness",
    "immunity",
    "lungs-detox",
    "body-detox",
    "joint-care",
    "unknown",
)

# Phrases the AI must never produce (defence in depth on top of the
# Claim Vault filter in :mod:`apps.ai_governance.prompting`).
BLOCKED_CLAIM_PHRASES: tuple[str, ...] = (
    "guaranteed cure",
    "guaranteed result",
    "permanent solution",
    "permanent cure",
    "no side effects for everyone",
    "no side effects at all",
    "doctor ki zarurat nahi",
    "doctor ki zaroorat nahi",
    "doctor ki jarurat nahi",
    "cures cancer",
    "cures diabetes",
    "cures asthma",
    "cures kidney",
    "cures every",
    "100% cure",
    "100 percent cure",
)


@dataclass(frozen=True)
class ChatAgentDecision:
    """Validated AI response. Use this; never trust raw LLM JSON."""

    action: str
    language: str
    category: str
    confidence: float
    reply_text: str
    needs_template: bool
    handoff_reason: str
    order_draft: dict[str, Any]
    payment: dict[str, Any]
    safety: dict[str, bool]
    raw: dict[str, Any]


class ChatAgentSchemaError(ValueError):
    """Raised when the LLM JSON cannot be coerced to :class:`ChatAgentDecision`."""


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result < 0.0:
        return 0.0
    if result > 1.0:
        return 1.0
    return result


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_action(value: Any) -> str:
    raw = (str(value or "")).strip().lower()
    if raw in VALID_ACTIONS:
        return raw
    return "handoff"


def _normalize_category(value: Any) -> str:
    raw = (str(value or "")).strip().lower()
    if raw in SUPPORTED_CATEGORIES:
        return raw
    return "unknown"


def parse_decision(payload: Mapping[str, Any] | None) -> ChatAgentDecision:
    """Validate the LLM output and return a :class:`ChatAgentDecision`.

    Missing keys are filled with safe defaults — but the safe default is
    ``handoff`` so a malformed response never accidentally auto-sends to
    the customer.
    """
    if not isinstance(payload, Mapping):
        raise ChatAgentSchemaError("AI response is not a JSON object.")

    safety_in = payload.get("safety") or {}
    if not isinstance(safety_in, Mapping):
        safety_in = {}

    safety = {
        "claimVaultUsed": _coerce_bool(safety_in.get("claimVaultUsed"), True),
        "medicalEmergency": _coerce_bool(safety_in.get("medicalEmergency"), False),
        "sideEffectComplaint": _coerce_bool(
            safety_in.get("sideEffectComplaint"), False
        ),
        "legalThreat": _coerce_bool(safety_in.get("legalThreat"), False),
        "angryCustomer": _coerce_bool(safety_in.get("angryCustomer"), False),
    }

    order_in = payload.get("orderDraft") or {}
    if not isinstance(order_in, Mapping):
        order_in = {}
    order_draft = {
        "customerName": str(order_in.get("customerName") or "").strip(),
        "phone": str(order_in.get("phone") or "").strip(),
        "product": str(order_in.get("product") or "").strip(),
        "skuId": str(order_in.get("skuId") or "").strip(),
        "quantity": max(1, _coerce_int(order_in.get("quantity"), 1)),
        "address": str(order_in.get("address") or "").strip(),
        "pincode": str(order_in.get("pincode") or "").strip(),
        "city": str(order_in.get("city") or "").strip(),
        "state": str(order_in.get("state") or "").strip(),
        "landmark": str(order_in.get("landmark") or "").strip(),
        "discountPct": max(0, _coerce_int(order_in.get("discountPct"), 0)),
        "amount": max(0, _coerce_int(order_in.get("amount"), 3000)),
    }

    payment_in = payload.get("payment") or {}
    if not isinstance(payment_in, Mapping):
        payment_in = {}
    payment = {
        "shouldCreateAdvanceLink": _coerce_bool(
            payment_in.get("shouldCreateAdvanceLink"), False
        ),
        "amount": max(0, _coerce_int(payment_in.get("amount"), 499)),
    }

    action = _normalize_action(payload.get("action"))
    language = normalize_language(payload.get("language"))
    if language == "unknown":
        # Unknown language → treat as Hinglish (locked default) so we
        # still pass the validator; orchestration may override.
        language = "hinglish"

    decision = ChatAgentDecision(
        action=action,
        language=language,
        category=_normalize_category(payload.get("category")),
        confidence=_coerce_float(payload.get("confidence"), 0.0),
        reply_text=str(payload.get("replyText") or "").strip(),
        needs_template=_coerce_bool(payload.get("needsTemplate"), False),
        handoff_reason=str(payload.get("handoffReason") or "").strip(),
        order_draft=order_draft,
        payment=payment,
        safety=safety,
        raw=dict(payload),
    )
    return decision


def reply_contains_blocked_phrase(reply_text: str) -> str:
    """Return the first blocked phrase the reply contains, else ``""``."""
    if not reply_text:
        return ""
    haystack = reply_text.lower()
    for phrase in BLOCKED_CLAIM_PHRASES:
        if phrase in haystack:
            return phrase
    return ""


__all__ = (
    "BLOCKED_CLAIM_PHRASES",
    "ChatAgentDecision",
    "ChatAgentSchemaError",
    "SALES_STAGES",
    "SUPPORTED_CATEGORIES",
    "VALID_ACTIONS",
    "parse_decision",
    "reply_contains_blocked_phrase",
)
