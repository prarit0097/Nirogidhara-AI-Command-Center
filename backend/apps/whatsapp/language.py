"""Phase 5C — WhatsApp customer language detection.

Cheap deterministic heuristic + persistence helper. The Chat Agent uses
the result to drive both prompt instructions and template language
selection.

Detection rules (locked):
- Devanagari script ≥ 30% of characters → ``hindi``.
- Latin script with Hindi/Hinglish marker words OR repeated devanagari
  fragments under ASCII fallback → ``hinglish``.
- Otherwise predominantly Latin/ASCII → ``english``.
- Empty / unknown → ``hinglish`` (Indian customer default per Prarit).

The detector is intentionally NOT an LLM call. The LLM later confirms
the language inside the JSON response and the orchestration layer
overrides metadata if confidence is high. Failing closed = stick with
the heuristic.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import WhatsAppConversation, WhatsAppMessage


# Locked vocabulary — keep narrow. Adding more words here should be
# reviewed by Compliance + Sales (Hinglish detection drives reply
# tone).
_HINGLISH_MARKERS: frozenset[str] = frozenset(
    {
        # Common Hinglish question/command words frequently typed in Latin.
        "hai", "haan", "nahi", "kya", "kab", "kaise", "kahan", "kyu",
        "kyun", "main", "mai", "mera", "meri", "tera", "teri", "tum",
        "aap", "aapka", "aapki", "kar", "karo", "karna", "karega",
        "karegi", "ho", "hua", "hui", "rahe", "rahi", "raha",
        "namaste", "namaskar", "dhanyawad", "shukriya", "bhai",
        "bata", "batao", "thik", "theek", "achha", "acha", "bhi",
        "matlab", "samjha", "samjhi", "samajhdar", "chahiye",
        "abhi", "baad", "phir", "fir",
        # Sales-context Hinglish.
        "discount", "kimat", "kimat ", "price", "rupiya", "rupay",
        "rupye", "kal", "aaj", "kab tak", "delivery", "order",
        "payment", "advance", "cod", "ghar", "address", "pincode",
        "shipping",
    }
)

# Crude script ranges. Devanagari covers Hindi, Marathi, Sanskrit; we
# treat the whole block as "hindi script" for first-pass detection.
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[A-Za-zऀ-ॿ]+", flags=re.UNICODE)


LANG_HINDI = "hindi"
LANG_HINGLISH = "hinglish"
LANG_ENGLISH = "english"
LANG_UNKNOWN = "unknown"

LANGUAGE_CHOICES: tuple[str, ...] = (
    LANG_HINDI,
    LANG_HINGLISH,
    LANG_ENGLISH,
    LANG_UNKNOWN,
)


@dataclass(frozen=True)
class LanguageDetection:
    """Result of :func:`detect_language`."""

    language: str
    devanagari_ratio: float
    hinglish_marker_hits: int
    sample_chars: int


def detect_language(text: str) -> LanguageDetection:
    """Classify ``text`` into one of the four language buckets."""
    cleaned = (text or "").strip()
    if not cleaned:
        return LanguageDetection(
            language=LANG_UNKNOWN,
            devanagari_ratio=0.0,
            hinglish_marker_hits=0,
            sample_chars=0,
        )

    devanagari_chars = len(_DEVANAGARI_RE.findall(cleaned))
    latin_chars = len(_LATIN_RE.findall(cleaned))
    sample = max(devanagari_chars + latin_chars, 1)
    devanagari_ratio = devanagari_chars / sample

    if devanagari_ratio >= 0.30:
        return LanguageDetection(
            language=LANG_HINDI,
            devanagari_ratio=devanagari_ratio,
            hinglish_marker_hits=0,
            sample_chars=len(cleaned),
        )

    lowered = cleaned.lower()
    words = _WORD_RE.findall(lowered)
    marker_hits = sum(1 for word in words if word in _HINGLISH_MARKERS)

    # Mixed signal: any devanagari or any Hinglish marker pulls Latin
    # text into the Hinglish bucket.
    if devanagari_chars > 0 or marker_hits > 0:
        return LanguageDetection(
            language=LANG_HINGLISH,
            devanagari_ratio=devanagari_ratio,
            hinglish_marker_hits=marker_hits,
            sample_chars=len(cleaned),
        )

    if latin_chars >= 1:
        return LanguageDetection(
            language=LANG_ENGLISH,
            devanagari_ratio=0.0,
            hinglish_marker_hits=0,
            sample_chars=len(cleaned),
        )

    # Pure emoji / digits / punctuation — fall back to Hinglish (the
    # Indian customer default Prarit selected).
    return LanguageDetection(
        language=LANG_HINGLISH,
        devanagari_ratio=0.0,
        hinglish_marker_hits=0,
        sample_chars=len(cleaned),
    )


def detect_from_history(
    conversation: WhatsAppConversation,
    *,
    inbound_message: WhatsAppMessage | None = None,
    history_limit: int = 6,
) -> LanguageDetection:
    """Run :func:`detect_language` over the latest inbound + recent history.

    The most recent inbound dominates; older inbounds break ties when the
    latest message is too short to classify cleanly (e.g. ``"ok"``).
    """
    pieces: list[str] = []
    if inbound_message is not None and inbound_message.body:
        pieces.append(inbound_message.body)
    qs = (
        WhatsAppMessage.objects.filter(
            conversation=conversation,
            direction=WhatsAppMessage.Direction.INBOUND,
        )
        .order_by("-created_at")
        .values_list("body", flat=True)[: history_limit + 1]
    )
    for body in qs:
        if body:
            pieces.append(body)

    text = "\n".join(pieces[: history_limit + 1])
    detection = detect_language(text)

    # Stamp normalised result on conversation metadata so the
    # orchestration layer + UI can read it without re-running.
    metadata = dict(conversation.metadata or {})
    metadata["detectedLanguage"] = detection.language
    conversation.metadata = metadata
    conversation.save(update_fields=["metadata", "updated_at"])
    return detection


def normalize_language(value: str | None) -> str:
    """Coerce an LLM-reported language string into the locked vocabulary."""
    raw = (value or "").lower().strip()
    if raw in {LANG_HINDI, "hi", "hin"}:
        return LANG_HINDI
    if raw in {LANG_HINGLISH, "hin-eng", "hindlish"}:
        return LANG_HINGLISH
    if raw in {LANG_ENGLISH, "en", "eng"}:
        return LANG_ENGLISH
    return LANG_UNKNOWN


__all__ = (
    "LANG_HINDI",
    "LANG_HINGLISH",
    "LANG_ENGLISH",
    "LANG_UNKNOWN",
    "LANGUAGE_CHOICES",
    "LanguageDetection",
    "detect_language",
    "detect_from_history",
    "normalize_language",
)
