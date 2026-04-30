"""Phase 5F-Gate Deterministic Grounded Reply Builder.

A backend-only fallback for the controlled WhatsApp AI auto-reply test
harness. The previous live ``--send`` runs (`WAM-100007`, `WAM-100008`)
showed the LLM returning ``action=handoff`` + ``claimVaultUsed=false``
even though the backend had:

- mapped category (``weight-management → Weight Management``)
- ``claimRowCount=1``, ``approvedClaimCount=3``
- ``groundingStatus.promptGroundingInjected=true``
- ``businessFactsInjected=true``
- safety flags all false
- normal product-info inquiry

That is a contradiction — the LLM's self-report cannot be trusted
alone. This module produces a deterministic, conservative,
Claim-Vault-grounded reply that the controlled-test command may use as
a **fallback** when the LLM blocks an obviously safe inquiry.

LOCKED rules:

- Reply text is built ONLY from approved phrases on the matching
  ``Claim`` row plus locked business facts (₹3000 / 30 capsules /
  ₹499 advance / conservative usage guidance / doctor-escalation).
- The builder NEVER emits an upfront discount.
- The builder NEVER emits a cure / guarantee / disease-treatment /
  "no side effects" / "doctor not needed" claim.
- The builder fails closed when:
    - any safety flag is true, or
    - the inbound contains a blocked-phrase request
      (cure / guarantee / 100% / permanent solution / etc.), or
    - no approved Claim Vault entry exists for the mapped product.
- The builder is unit-tested.
- The fallback is only used by the controlled-test command path; it
  never replaces the LLM in webhook-driven production runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .ai_schema import BLOCKED_CLAIM_PHRASES, reply_contains_blocked_phrase
from .claim_mapping import category_to_claim_product


# ---------------------------------------------------------------------------
# Locked business facts (NOT medical claims; these are price / quantity /
# operational facts the AI may state freely).
# ---------------------------------------------------------------------------


STANDARD_PRICE_INR: int = 3000
STANDARD_CAPSULE_COUNT: int = 30
ADVANCE_AMOUNT_INR: int = 499


# Conservative safety lines used inside the deterministic reply. These
# are routing labels, not medical claims — they never describe a
# treatment, dosage, cure, or outcome.
USAGE_GUIDANCE_LINE: str = (
    "Iska use label par diye gaye direction ya kisi qualified Ayurvedic "
    "practitioner ki advice ke according karein."
)
DOCTOR_ESCALATION_LINE: str = (
    "Pregnancy, serious illness, allergy, existing medicine ya koi "
    "adverse reaction ho to apne doctor / health advisor se zaroor "
    "consult karein."
)


# ---------------------------------------------------------------------------
# Product-info intent detector
# ---------------------------------------------------------------------------


# Vocabulary that signals "this is a normal product / price / quantity /
# safe-use-guidance question". The detector matches at least one of
# these tokens (case-insensitive) on the inbound text.
PRODUCT_INFO_KEYWORDS: tuple[str, ...] = (
    # Price / quantity
    "price",
    "rate",
    "kitne",
    "kitna",
    "amount",
    "kimat",
    "quantity",
    "qty",
    "capsule",
    "capsules",
    "bottle",
    "pack",
    "30",
    "₹",
    "rs",
    "rs.",
    "rupees",
    "advance",
    "booking",
    "book karna",
    "book kaise",
    # Product info
    "product",
    "details",
    "detail",
    "info",
    "information",
    "jaankari",
    "jankari",
    "bataye",
    "bataiye",
    "batao",
    "bata dijiye",
    "bata sakte",
    "kya hai",
    "kya hota",
    "ke baare",
    "ke bare",
    "about",
    "tell me",
    # Safe-use guidance
    "use guidance",
    "use kaise",
    "kaise use",
    "kaise lena",
    "kaise lete",
    "kaise leni",
    "label",
    "directions",
    "guidance",
    "benefits",
    "fayda",
    "fayde",
    "approved",
    "safe",
    "safe info",
)


# Vocabulary that disqualifies the inbound from being a "normal
# product-info" inquiry. Anything here forces the fallback to skip and
# the existing safety / handoff stack to handle the message. We keep
# the disqualifier list explicit; the safety_validation module already
# handles the safety-flag side, but the detector is independent so
# normal inquiries don't accidentally trigger fallback.
PRODUCT_INFO_DISQUALIFIERS: tuple[str, ...] = (
    # Cure / guarantee / 100% / permanent
    "cure",
    "guarantee",
    "guaranteed",
    "100%",
    "100 percent",
    "permanent",
    "permanent solution",
    "permanent cure",
    "no side effect",
    "doctor ki zarurat nahi",
    "doctor ki zaroorat nahi",
    # Diseases / treatment
    "diabetes",
    "cancer",
    "asthma",
    "kidney",
    "blood pressure",
    "hypertension",
    "tumor",
    "stroke",
    "heart attack",
    "thyroid",
    # Side-effect / adverse reaction vocabulary (handled by
    # safety_validation, but block here as defence in depth)
    "side effect",
    "side-effect",
    "ulta asar",
    "reaction ho gayi",
    "vomiting",
    "rash",
    "swelling",
    "allergy",
    "allergic",
    # Legal / refund threats
    "lawyer",
    "court",
    "consumer forum",
    "police",
    "fir",
    "fraud",
    "refund threat",
    # Discount-only spam
    "discount only",
    "free me",
    "free de do",
)


def _normalize_text(text: str | None) -> str:
    return (text or "").strip().lower()


def is_normal_product_info_inquiry(inbound_text: str | None) -> bool:
    """Deterministic detector for normal product-info / price / safe-use
    inquiries. Returns False on disqualifying vocabulary so the
    existing safety/handoff stack handles those.
    """
    text = _normalize_text(inbound_text)
    if not text:
        return False
    for needle in PRODUCT_INFO_DISQUALIFIERS:
        if needle in text:
            return False
    for needle in PRODUCT_INFO_KEYWORDS:
        if needle in text:
            return True
    return False


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundedReplyEligibility:
    """Result of :func:`can_build_grounded_product_reply`."""

    eligible: bool
    reason: str = ""
    normalized_product: str = ""
    approved_claim_count: int = 0
    disallowed_phrase_count: int = 0


def can_build_grounded_product_reply(
    *,
    category: str | None,
    inbound_text: str | None,
    safety_flags: Mapping[str, bool] | None,
    approved_claims: Iterable[str] | None,
    disallowed_phrases: Iterable[str] | None = None,
) -> GroundedReplyEligibility:
    """Check whether a deterministic grounded reply is safe to build.

    Returns a typed result so callers can audit the precise fail
    reason. ``eligible=True`` means the builder will produce a reply
    that passes the validator.
    """
    safety_flags = dict(safety_flags or {})
    approved_list = [
        str(p).strip()
        for p in (approved_claims or [])
        if str(p).strip()
    ]
    disallowed_list = [
        str(p).strip()
        for p in (disallowed_phrases or [])
        if str(p).strip()
    ]
    normalized_product = category_to_claim_product(category) if category else ""

    if not normalized_product:
        return GroundedReplyEligibility(
            eligible=False,
            reason="category_not_mapped",
            approved_claim_count=len(approved_list),
            disallowed_phrase_count=len(disallowed_list),
        )

    if not approved_list:
        return GroundedReplyEligibility(
            eligible=False,
            reason="no_approved_claims",
            normalized_product=normalized_product,
            disallowed_phrase_count=len(disallowed_list),
        )

    # Any safety flag set to true → fail closed. This lets the existing
    # safety stack handle the inbound exactly as today.
    for flag, value in safety_flags.items():
        if flag == "claimVaultUsed":
            continue  # not a blocker; describes reply, not inbound
        if bool(value):
            return GroundedReplyEligibility(
                eligible=False,
                reason=f"safety_flag_set:{flag}",
                normalized_product=normalized_product,
                approved_claim_count=len(approved_list),
                disallowed_phrase_count=len(disallowed_list),
            )

    if not is_normal_product_info_inquiry(inbound_text):
        return GroundedReplyEligibility(
            eligible=False,
            reason="not_product_info_inquiry",
            normalized_product=normalized_product,
            approved_claim_count=len(approved_list),
            disallowed_phrase_count=len(disallowed_list),
        )

    return GroundedReplyEligibility(
        eligible=True,
        reason="",
        normalized_product=normalized_product,
        approved_claim_count=len(approved_list),
        disallowed_phrase_count=len(disallowed_list),
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class GroundedReplyResult:
    """Output of :func:`build_grounded_product_reply`.

    ``ok`` is true only if the builder produced a non-empty
    ``reply_text`` AND the validator accepts it. Audit / JSON
    consumers must trust ``ok`` rather than ``reply_text`` length.
    """

    ok: bool
    reply_text: str = ""
    used_approved_phrases: tuple[str, ...] = ()
    fallback_reason: str = ""
    validation: dict = field(default_factory=dict)


# Maximum WhatsApp body length we target. Real Meta limit is much
# higher, but a tight bound keeps the deterministic reply readable.
_MAX_REPLY_LEN: int = 1600


def build_grounded_product_reply(
    *,
    normalized_product: str,
    approved_claims: Iterable[str],
    inbound_text: str | None = None,
    customer_name: str | None = None,
) -> GroundedReplyResult:
    """Compose a deterministic Hinglish reply.

    The output literally embeds at least one approved phrase from
    ``approved_claims``. If the customer's inbound mentioned price or
    booking, the reply also includes the locked business facts.
    """
    approved = [
        str(p).strip()
        for p in (approved_claims or [])
        if str(p).strip()
    ]
    if not approved:
        return GroundedReplyResult(
            ok=False, fallback_reason="no_approved_claims"
        )
    if not normalized_product:
        return GroundedReplyResult(
            ok=False, fallback_reason="no_normalized_product"
        )

    inbound_norm = _normalize_text(inbound_text)

    greeting = "Namaste ji"

    # Always state the price + capsule fact when the customer asked
    # about price / quantity / booking. We err on the side of including
    # the facts since the customer in this gate phase is the Director
    # himself testing the controlled flow.
    mention_price = any(
        token in inbound_norm
        for token in (
            "price",
            "kimat",
            "kitne",
            "kitna",
            "amount",
            "rate",
            "₹",
            "rs",
            "rs.",
            "rupees",
            "30",
            "capsule",
            "quantity",
            "qty",
            "bottle",
            "pack",
            "advance",
            "booking",
            "book karna",
            "book kaise",
        )
    )

    # Approved-claim block: surface ALL approved phrases (most rows
    # have 2-3); the first one anchors the lead sentence so the
    # 180-char preview operators see still proves Claim Vault
    # grounding plus the price fact.
    selected_approved = list(approved[:3])
    primary_phrase = selected_approved[0]
    additional_phrases = "; ".join(selected_approved[1:])

    lead_parts: list[str] = [
        f"{greeting} 🙏 {normalized_product}: {primary_phrase}."
    ]
    if mention_price:
        lead_parts.append(
            f"₹{STANDARD_PRICE_INR} / {STANDARD_CAPSULE_COUNT} capsules; "
            f"order par fixed advance ₹{ADVANCE_AMOUNT_INR}."
        )

    parts: list[str] = [" ".join(lead_parts)]
    if additional_phrases:
        parts.append(f"Approved: {additional_phrases}.")
    parts.append(USAGE_GUIDANCE_LINE)
    parts.append(DOCTOR_ESCALATION_LINE)

    reply_text = " ".join(parts).strip()
    if len(reply_text) > _MAX_REPLY_LEN:
        reply_text = reply_text[: _MAX_REPLY_LEN].rstrip()

    validation = validate_reply_uses_claim_vault(
        reply_text=reply_text,
        approved_claims=approved,
    )
    if not validation["passed"]:
        return GroundedReplyResult(
            ok=False,
            reply_text=reply_text,
            used_approved_phrases=tuple(selected_approved),
            fallback_reason="validation_failed",
            validation=validation,
        )

    return GroundedReplyResult(
        ok=True,
        reply_text=reply_text,
        used_approved_phrases=tuple(selected_approved),
        fallback_reason="",
        validation=validation,
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


# Discount / offer vocabulary — the deterministic builder must NEVER
# emit any of these. Validator double-checks.
_DISCOUNT_VOCAB: tuple[str, ...] = (
    "discount",
    "offer",
    "% off",
    "percent off",
    " off",  # leading space avoids matching "office" / "offer" prefix
    "off karunga",
    "free me",
    "free de do",
    "free de denge",
)


def _contains_any(haystack: str, needles: Iterable[str]) -> str:
    """Return the first matching needle, or ``""``."""
    for needle in needles:
        if needle and needle in haystack:
            return needle
    return ""


def validate_reply_uses_claim_vault(
    *,
    reply_text: str | None,
    approved_claims: Iterable[str],
) -> dict:
    """Final validator. Returns a dict that mirrors the
    ``finalReplyValidation`` field surfaced in the controlled-test
    JSON.

    Keys:

    - ``containsApprovedClaim`` — at least one approved phrase is
      literally present in the reply.
    - ``blockedPhraseFree`` — no entry in
      :data:`apps.whatsapp.ai_schema.BLOCKED_CLAIM_PHRASES` is in the
      reply.
    - ``discountOffered`` — true if the reply mentions a discount /
      offer / free-give-away vocabulary.
    - ``safeBusinessFactsOnly`` — true when the reply does NOT
      attempt to state any product benefit beyond the approved
      Claim Vault list.
    - ``passed`` — true only when:
      ``containsApprovedClaim AND blockedPhraseFree AND NOT discountOffered``.
    - ``matchedApprovedPhrase`` — the first approved phrase that hit.
    - ``violation`` — short token describing the failure.

    ``safeBusinessFactsOnly`` is best-effort — we cannot prove the
    reply does not contain other invented benefits, but we can prove
    the absence of blocked vocabulary and the presence of approved
    grounding. Combined with the deterministic builder above, the
    contract is upheld.
    """
    text = (reply_text or "").strip()
    text_lower = text.lower()
    approved = [
        str(p).strip()
        for p in (approved_claims or [])
        if str(p).strip()
    ]
    matched = ""
    for phrase in approved:
        if phrase and phrase.lower() in text_lower:
            matched = phrase
            break

    contains_approved = bool(matched)
    blocked = reply_contains_blocked_phrase(text)
    blocked_free = blocked == ""
    discount_hit = _contains_any(text_lower, _DISCOUNT_VOCAB)
    discount_offered = bool(discount_hit)

    passed = contains_approved and blocked_free and not discount_offered
    violation = ""
    if not contains_approved:
        violation = "missing_approved_phrase"
    elif not blocked_free:
        violation = f"blocked_phrase:{blocked}"
    elif discount_offered:
        violation = f"discount_vocab:{discount_hit.strip()}"

    return {
        "containsApprovedClaim": contains_approved,
        "matchedApprovedPhrase": matched,
        "blockedPhraseFree": blocked_free,
        "blockedPhrase": blocked,
        "discountOffered": discount_offered,
        "discountVocab": discount_hit,
        "safeBusinessFactsOnly": blocked_free and not discount_offered,
        "passed": passed,
        "violation": violation,
    }


__all__ = (
    "ADVANCE_AMOUNT_INR",
    "DOCTOR_ESCALATION_LINE",
    "GroundedReplyEligibility",
    "GroundedReplyResult",
    "PRODUCT_INFO_DISQUALIFIERS",
    "PRODUCT_INFO_KEYWORDS",
    "STANDARD_CAPSULE_COUNT",
    "STANDARD_PRICE_INR",
    "USAGE_GUIDANCE_LINE",
    "build_grounded_product_reply",
    "can_build_grounded_product_reply",
    "is_normal_product_info_inquiry",
    "validate_reply_uses_claim_vault",
)
