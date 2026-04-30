"""Phase 5F-Gate Claim Vault Grounding Fix — category-slug → Claim.product map.

The WhatsApp AI orchestrator's category detection emits **slug** values
(``weight-management``, ``blood-purification``, …) defined in
:mod:`apps.whatsapp.ai_schema.SUPPORTED_CATEGORIES`. The Approved Claim
Vault stores rows under :class:`apps.compliance.Claim` with a **human
label** in ``Claim.product`` (``Weight Management``,
``Blood Purification``, …).

A previous version of ``_claims_for_category`` ran
``Claim.objects.filter(product__icontains=category)`` directly with the
slug — which never matches the human label because of the ``-`` vs
``" "`` difference, and silently fell through to a fallback that
returned **every claim row** when the customer's ``product_interest``
was blank. Net effect: the LLM received either zero relevant claims
(blocked by the ``claimVaultUsed=false`` safety gate) or a kitchen-sink
prompt (blocked by the ``claim_vault_not_used`` audit reason in the
production logs).

This module ships the deterministic mapping. It is intentionally NOT
fuzzy — it's a routing label table, not a medical-claim source. The
medical content still lives only inside ``Claim.approved``.

Hard rules:

- Mapping is deterministic. Unknown input returns ``""`` (not a
  guess). The orchestrator then fails closed exactly as today.
- The map covers the eight Phase 3E + 5E categories plus the common
  English / Hinglish aliases the LLM emits before the canonical slug
  validator collapses them.
- Adding a new category requires updating this table. Do NOT add new
  fuzzy substring matchers — every entry must be an explicit key.
"""
from __future__ import annotations


# Canonical slug → Claim.product label. The eight live categories.
CATEGORY_SLUG_TO_PRODUCT: dict[str, str] = {
    "weight-management": "Weight Management",
    "blood-purification": "Blood Purification",
    "men-wellness": "Men Wellness",
    "women-wellness": "Women Wellness",
    "immunity": "Immunity",
    "lungs-detox": "Lungs Detox",
    "body-detox": "Body Detox",
    "joint-care": "Joint Care",
}


# Common aliases the LLM (or operators in the inbox) might emit before
# the schema validator collapses them to a canonical slug. The LLM
# should always return a slug from ``SUPPORTED_CATEGORIES``; these
# aliases are defence in depth.
ALIASES: dict[str, str] = {
    # weight management
    "weight loss": "Weight Management",
    "weight-loss": "Weight Management",
    "weight management": "Weight Management",
    "weight_management": "Weight Management",
    "wt management": "Weight Management",
    # blood purification
    "blood purify": "Blood Purification",
    "blood purifier": "Blood Purification",
    "blood purification": "Blood Purification",
    "blood_purification": "Blood Purification",
    # men wellness
    "men wellness": "Men Wellness",
    "male wellness": "Men Wellness",
    "men_wellness": "Men Wellness",
    "mens wellness": "Men Wellness",
    "men's wellness": "Men Wellness",
    # women wellness
    "women wellness": "Women Wellness",
    "female wellness": "Women Wellness",
    "women_wellness": "Women Wellness",
    "womens wellness": "Women Wellness",
    "women's wellness": "Women Wellness",
    # lungs detox
    "lungs detox": "Lungs Detox",
    "lung detox": "Lungs Detox",
    "lungs_detox": "Lungs Detox",
    # body detox
    "body detox": "Body Detox",
    "body_detox": "Body Detox",
    "detox": "Body Detox",
    # joint care
    "joint pain": "Joint Care",
    "joint care": "Joint Care",
    "joints care": "Joint Care",
    "joint_care": "Joint Care",
    # immunity
    "immunity": "Immunity",
    "immune": "Immunity",
    "immunity booster": "Immunity",
}


def _normalize_input(value: str | None) -> str:
    return (value or "").strip().lower()


def category_to_claim_product(category: str | None) -> str:
    """Return the canonical ``Claim.product`` label for a category slug.

    Returns ``""`` for unknown / empty input — the orchestrator must
    fail closed in that case (no Claim Vault grounding → no
    customer-facing send). Never invent a product label.
    """
    norm = _normalize_input(category)
    if not norm or norm == "unknown":
        return ""
    if norm in CATEGORY_SLUG_TO_PRODUCT:
        return CATEGORY_SLUG_TO_PRODUCT[norm]
    if norm in ALIASES:
        return ALIASES[norm]
    return ""


def known_category_slugs() -> tuple[str, ...]:
    """Used by tests + diagnostics; never expand by guessing."""
    return tuple(CATEGORY_SLUG_TO_PRODUCT.keys())


def known_claim_products() -> tuple[str, ...]:
    return tuple(CATEGORY_SLUG_TO_PRODUCT.values())


__all__ = (
    "ALIASES",
    "CATEGORY_SLUG_TO_PRODUCT",
    "category_to_claim_product",
    "known_category_slugs",
    "known_claim_products",
)
