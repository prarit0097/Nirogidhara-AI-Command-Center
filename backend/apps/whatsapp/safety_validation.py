"""Phase 5E-Smoke-Fix-3 — server-side safety flag validation.

The LLM occasionally over-flags inbound messages — for example, marking
"Hi mujhe weight loss product ke baare me batana" (a normal product
inquiry that contains zero side-effect signal) as a
``sideEffectComplaint``. Once that flag is set, ``_safety_block`` in
:mod:`apps.whatsapp.ai_orchestration` short-circuits the run into a
handoff and the smoke harness reports a false positive.

This module adds a deterministic post-LLM corrector. For each safety
flag that triggers a customer-facing block, we check whether the
inbound text actually contains the corresponding signal vocabulary. If
it does not, we downgrade the flag and emit a warning audit row so the
correction is observable, never silent.

Hard rules:

- We **never weaken a flag whose signal vocabulary IS present** in the
  inbound text. Real side-effect / emergency / legal phrases stay
  flagged exactly as the LLM said.
- ``claimVaultUsed`` is **not** in scope here — that is a property of
  the AI's reply, not the customer's inbound.
- ``angryCustomer`` is **not** downgraded — anger is a tone signal
  whose vocabulary is too broad to keyword-match reliably; trust the
  LLM there.
- The corrector is purely additive: it can flip a true→false on the
  three blocker flags below, never false→true.
"""
from __future__ import annotations

from typing import Iterable, Mapping


SIDE_EFFECT_KEYWORDS: tuple[str, ...] = (
    # English
    "side effect",
    "side-effect",
    "side effects",
    "adverse",
    "adverse reaction",
    "allergic",
    "allergy",
    "rash",
    "rashes",
    "swelling",
    "itching",
    "itchy",
    "irritation",
    "vomiting",
    "vomit",
    "nausea",
    "loose motion",
    "loose motions",
    "diarrhea",
    "diarrhoea",
    "discomfort",
    "headache after",
    "pain after",
    "stomach pain after",
    "burning sensation",
    "reaction ho",
    "reaction ho gayi",
    "reaction ho gaya",
    # Hindi / Hinglish
    "ulta asar",
    "ulta-asar",
    "ulta hua",
    "ulti hui",
    "side effect ho",
    "problem ho gayi",
    "problem ho gaya",
    "problem ho rahi",
    "problem ho raha",
    "dikkat ho gayi",
    "dikkat ho gaya",
    "dikkat ho rahi",
    "dikkat aa gayi",
    "dikkat aa rahi",
    "khujli",
    "jalan",
    "khane ke baad problem",
    "lene ke baad problem",
    "khane ke baad dikkat",
    "lene ke baad dikkat",
    "medicine khane ke baad",
    "tablet lene ke baad",
    "tablet khane ke baad",
    "capsule khane ke baad",
    "capsules khane ke baad",
    "capsule lene ke baad",
    "capsules lene ke baad",
    "khane ke baad ulta",
    "lene ke baad ulta",
)


MEDICAL_EMERGENCY_KEYWORDS: tuple[str, ...] = (
    # English
    "emergency",
    "ambulance",
    "hospital",
    "icu",
    "chest pain",
    "heart attack",
    "stroke",
    "unconscious",
    "fainted",
    "fainting",
    "seizure",
    "bleeding",
    "blood pressure very",
    "blood pressure shoot",
    "blood pressure crashing",
    "breathing problem",
    "cant breathe",
    "can't breathe",
    "cannot breathe",
    "shortness of breath",
    "suicid",
    # Hindi / Hinglish
    "saans nahi",
    "saans rok",
    "saans rukh",
    "behosh",
    "behoshi",
    "chakkar aa gaya",
    "chakkar aa rahe",
    "ambulance chahiye",
    "ambulance bula",
    "hospital le ja",
    "seene me dard",
    "chati me dard",
    "dil ka daura",
    "khoon nikal",
    "khoon beh",
)


LEGAL_THREAT_KEYWORDS: tuple[str, ...] = (
    # English
    "lawyer",
    "advocate",
    "legal action",
    "legal notice",
    "court",
    "consumer forum",
    "consumer court",
    "police",
    "fir",
    "fraud",
    "complaint",
    "sue you",
    "sue your",
    "i will sue",
    "media",
    "social media expose",
    "expose you",
    "review bomb",
    "1 star",
    "one star review",
    # Hindi / Hinglish
    "court le ja",
    "case kar",
    "case karunga",
    "case karungi",
    "case karenge",
    "police me jaa",
    "police me ja",
    "police me complaint",
    "fir karwa",
    "fir karwau",
    "consumer forum le",
    "vakil",
    "kanooni",
    "media me jaa",
    "shikayat karunga",
    "shikayat karungi",
)


# Flags this validator can downgrade. Each maps to a vocabulary set.
_DOWNGRADABLE_FLAGS: dict[str, tuple[str, ...]] = {
    "sideEffectComplaint": SIDE_EFFECT_KEYWORDS,
    "medicalEmergency": MEDICAL_EMERGENCY_KEYWORDS,
    "legalThreat": LEGAL_THREAT_KEYWORDS,
}


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _contains_any(needle_text: str, vocabulary: Iterable[str]) -> bool:
    if not needle_text:
        return False
    haystack = needle_text
    for word in vocabulary:
        if word and word in haystack:
            return True
    return False


def validate_safety_flags(
    inbound_text: str,
    safety_flags: Mapping[str, bool] | None,
) -> tuple[dict[str, bool], list[str]]:
    """Downgrade obviously-false safety flags against the inbound text.

    Args:
        inbound_text: The customer's most recent inbound message body.
        safety_flags: The LLM-returned safety dict (5 flags from
            :mod:`apps.whatsapp.ai_schema`).

    Returns:
        A tuple ``(corrected_flags, downgraded_keys)``.

        - ``corrected_flags`` is a fresh dict — never mutates the input.
        - ``downgraded_keys`` is the list of flags that were flipped
          ``true → false`` because no signal vocabulary was present in
          ``inbound_text``. Empty list means the LLM's flags were left
          alone.

    The function is conservative: it only flips flags it knows how to
    keyword-match, only when the LLM said true AND the inbound has zero
    matching vocabulary. ``angryCustomer`` and ``claimVaultUsed`` are
    never touched here.
    """
    base = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": False,
    }
    if isinstance(safety_flags, Mapping):
        for key in base:
            if key in safety_flags:
                base[key] = bool(safety_flags[key])

    haystack = _normalize(inbound_text)
    if not haystack:
        # No inbound text → nothing to validate against. Trust LLM as-is.
        return base, []

    downgraded: list[str] = []
    for flag, vocabulary in _DOWNGRADABLE_FLAGS.items():
        if not base.get(flag):
            continue
        if _contains_any(haystack, vocabulary):
            continue
        base[flag] = False
        downgraded.append(flag)

    return base, downgraded


__all__ = (
    "LEGAL_THREAT_KEYWORDS",
    "MEDICAL_EMERGENCY_KEYWORDS",
    "SIDE_EFFECT_KEYWORDS",
    "validate_safety_flags",
)
