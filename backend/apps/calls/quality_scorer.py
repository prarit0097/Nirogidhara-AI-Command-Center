"""Phase 11B — Call Quality Scorer V1 (deterministic, no LLM).

Scores ingested call transcripts on 5 dimensions using deterministic
keyword/pattern matching. The output (``CallQualityScore`` row +
``raw_signals`` diagnostic dict) feeds the Phase 11C CAIO Audit Agent.
**V1 contains no LLM call** — pure rules-based. Phase 11C will fold
in the Approved Claim Vault.

Compliance hard stop (Master Blueprint §26 #2 + #3):
- Scoring is recommendations-only. CAIO never executes — CAIO only
  reads these rows.
- This module NEVER triggers WhatsApp / makes a call / dispatches a
  shipment, NEVER mutates `Customer` / `Order` / `Payment` / `Lead` /
  `Shipment` / `DiscountOfferLog`.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

# Phase 9E already ships the "m:ss" / "mm:ss" / "h:mm:ss" parser.
# Reuse it to keep the duration semantics consistent.
from apps.agents.calling_team_leader.service import _parse_duration_seconds

from .models import Call, CallQualityScore, CallTranscriptLine


logger = logging.getLogger(__name__)


SCORING_VERSION = "deterministic_v1"

# Composite formula weights — total = 1.0.
WEIGHT_CONNECTION = 0.20
WEIGHT_PRODUCT_KNOWLEDGE = 0.25
WEIGHT_COMPLIANCE = 0.25
WEIGHT_OBJECTION = 0.15
WEIGHT_TONALITY = 0.15


# Agent-side classification — case-insensitive match on the
# ``CallTranscriptLine.who`` field. Phase 2D webhook persistence and
# Phase 11A REST normalization use different conventions; this list
# covers both. The Call.agent value (e.g. "Calling AI · Vapi") is
# matched separately via direct equality.
_AGENT_WHO_VALUES = frozenset({"agent", "assistant", "bot", "system"})
_CUSTOMER_WHO_VALUES = frozenset({"customer", "user", "human"})


# Product / domain keywords — V1 hardcoded list. Phase 11C will fold
# in the full Claim Vault (`apps.compliance.Claim.approved`).
PRODUCT_KEYWORDS: tuple[str, ...] = (
    "weight", "wajan", "metabolism", "metabolizm",
    "capsule", "capsules", "khuraq", "khurak",
    "ayurvedic", "ayurved", "herbal", "jadibooti",
    "natural", "prakritic",
    "ingredient", "tarkib",
    "dose", "din mein", "roz",
    "result", "fayda", "labh", "asar",
)

# Forbidden phrases — Master Blueprint §26 hard stops. Hitting any of
# these inside an agent utterance is a compliance violation; the more
# forbidden phrases land in a single call, the lower compliance_score
# drops.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "guarantee", "guaranteed", "garanti",
    "cure", "theek kar", "thik kar", "ilaaj",
    "medicine", "dawa", "dawai",
    "doctor", "doctor ne kaha", "physician",
    "clinically proven", "clinical trial",
    "100%", "100 percent",
    "no side effect", "koi side effect nahi",
    "fda", "drug",
)

# Customer objection signals — looked up in customer-side utterances.
OBJECTION_KEYWORDS: tuple[str, ...] = (
    "price", "paisa", "mehnga", "mahenga", "costly", "expensive",
    "guarantee", "kya guarantee", "paka",
    "quality", "achha hai", "sahi hai",
    "time", "kitne din", "kab tak",
    "competitor", "dusra", "aur brand",
)

# Agent response signals — must appear in the NEXT agent utterance
# after a customer objection to count as "handled".
RESPONSE_KEYWORDS: tuple[str, ...] = (
    "samjhiye", "dekh", "bilkul", "zaroor", "haan",
    "quality", "result", "asar", "tested",
    "free", "offer", "discount", "cashback",
    "money back", "wapas", "return",
)

GREETING_KEYWORDS: tuple[str, ...] = (
    "namaste", "namaskar", "hello", "hi ", "jai shri"
)

POSITIVE_KEYWORDS: tuple[str, ...] = (
    "bilkul", "zaroor", "acha", "achha", "haan ji",
    "dhanyavad", "shukriya", "samajh gaye", "bahut accha",
)

CLOSING_KEYWORDS: tuple[str, ...] = (
    "dhanyavad", "shukriya", "phir milenge", "jai hind",
    "take care", "goodbye", "namaskar",
)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _is_agent_who(who: str, call_agent_label: str) -> bool:
    """Permissive case-insensitive check for agent-side lines."""
    if not who:
        return False
    raw = who.strip()
    lower = raw.lower()
    if lower in _AGENT_WHO_VALUES:
        return True
    if any(token in lower for token in _AGENT_WHO_VALUES):
        return True
    # Direct match against the Call.agent label (e.g. "Calling AI · Vapi").
    if call_agent_label and raw == call_agent_label:
        return True
    return False


def _is_customer_who(who: str) -> bool:
    if not who:
        return False
    lower = who.strip().lower()
    if lower in _CUSTOMER_WHO_VALUES:
        return True
    return any(token in lower for token in _CUSTOMER_WHO_VALUES)


def _split_lines(
    lines: Iterable[CallTranscriptLine],
    call_agent_label: str,
) -> tuple[list[str], list[str], list[tuple[str, str]], str]:
    """Split transcript lines into (agent, customer, ordered, first_agent_text).

    The fourth return is the first non-empty agent utterance (used by
    the tonality greeting check).
    """
    agent_lines: list[str] = []
    customer_lines: list[str] = []
    ordered: list[tuple[str, str]] = []
    first_agent_text = ""
    for line in lines:
        text = (line.text or "").strip()
        if not text:
            continue
        who = (line.who or "").strip()
        if _is_agent_who(who, call_agent_label):
            agent_lines.append(text)
            ordered.append(("agent", text))
            if not first_agent_text:
                first_agent_text = text
        elif _is_customer_who(who):
            customer_lines.append(text)
            ordered.append(("customer", text))
        else:
            ordered.append(("other", text))
    return agent_lines, customer_lines, ordered, first_agent_text


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(value)))


# ---------------------------------------------------------------------------
# Dimension scoring
# ---------------------------------------------------------------------------


def connection_score(call: Call) -> tuple[int, int]:
    """Return (score, duration_seconds)."""
    status = (call.status or "").strip()
    if status in {Call.Status.MISSED.value, Call.Status.FAILED.value}:
        return 0, 0
    if status in {Call.Status.QUEUED.value, Call.Status.LIVE.value}:
        return 30, 0
    if status != Call.Status.COMPLETED.value:
        return 30, 0
    duration_seconds = _parse_duration_seconds(call.duration or "0:00")
    score = 60
    if duration_seconds >= 30:
        score = 70
    if duration_seconds >= 90:
        score = 80
    if duration_seconds >= 180:
        score = 90
    if duration_seconds >= 300:
        score = 100
    return _clamp(score), duration_seconds


def product_knowledge_score(agent_lines: list[str]) -> tuple[int, list[str]]:
    if not agent_lines:
        return 0, []
    joined = " ".join(agent_lines).lower()
    found = [kw for kw in PRODUCT_KEYWORDS if kw in joined]
    return _clamp(len(found) * 12), found


def compliance_score(agent_lines: list[str]) -> tuple[int, list[str]]:
    if not agent_lines:
        # No agent utterances → no compliance violation possible, but
        # also no proof of compliance. Keep neutral 100 so callers
        # don't double-penalize on zero_agent_utterances.
        return 100, []
    joined = " ".join(agent_lines).lower()
    found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in joined]
    score = max(100 - len(found) * 25, 0)
    return _clamp(score), found


def objection_handling_score(
    ordered: list[tuple[str, str]],
) -> tuple[int, list[str], int, int]:
    """Return (score, found_objection_keywords, objection_total, handled_total).

    The customer side raises an objection when one of
    OBJECTION_KEYWORDS appears in their utterance. An objection is
    "handled" when the immediately following agent utterance contains
    a RESPONSE_KEYWORDS hit.
    """
    found_objections: list[str] = []
    total = 0
    handled = 0
    for index, (who, text) in enumerate(ordered):
        if who != "customer":
            continue
        lower = text.lower()
        hits = [kw for kw in OBJECTION_KEYWORDS if kw in lower]
        if not hits:
            continue
        for hit in hits:
            if hit not in found_objections:
                found_objections.append(hit)
        total += 1
        # Find the next agent utterance after this customer line.
        next_agent_text = ""
        for following_who, following_text in ordered[index + 1:]:
            if following_who == "agent":
                next_agent_text = following_text.lower()
                break
        if not next_agent_text:
            continue
        if any(rk in next_agent_text for rk in RESPONSE_KEYWORDS):
            handled += 1
    if total == 0:
        return 70, [], 0, 0
    score = int(round(handled / total * 100))
    return _clamp(score), found_objections, total, handled


def tonality_score(
    agent_lines: list[str],
    first_agent_text: str,
) -> tuple[int, bool, bool, int]:
    """Return (score, greeting_found, closing_found, positive_hit_count)."""
    base = 50
    first_lower = (first_agent_text or "").lower()
    greeting_found = any(g in first_lower for g in GREETING_KEYWORDS)
    if greeting_found:
        base += 20
    joined = " ".join(agent_lines).lower()
    positive_count = sum(1 for p in POSITIVE_KEYWORDS if p in joined)
    base += min(positive_count * 5, 20)
    closing_found = any(c in joined for c in CLOSING_KEYWORDS)
    if closing_found:
        base += 10
    return _clamp(base), greeting_found, closing_found, positive_count


def _compute_composite(
    conn: int, prod: int, comp: int, obj: int, tone: int
) -> int:
    raw = (
        conn * WEIGHT_CONNECTION
        + prod * WEIGHT_PRODUCT_KNOWLEDGE
        + comp * WEIGHT_COMPLIANCE
        + obj * WEIGHT_OBJECTION
        + tone * WEIGHT_TONALITY
    )
    return _clamp(int(round(raw)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_call(call_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Score one Call. Returns a result dict; never raises on per-call errors."""
    started_ms = time.monotonic()
    call = Call.objects.filter(pk=call_id).first()
    if call is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "call_not_found",
            "call_id": call_id,
        }
    already = CallQualityScore.objects.filter(call=call).first()
    if already is not None and not dry_run:
        return {
            "ok": False,
            "skipped": True,
            "reason": "already_scored",
            "call_id": call.id,
            "composite_score": int(already.composite_score),
            "flags": list(already.flags or []),
        }

    lines = list(
        CallTranscriptLine.objects.filter(call=call).order_by("order")
    )
    agent_lines, customer_lines, ordered, first_agent_text = _split_lines(
        lines, call.agent or ""
    )

    flags: list[str] = []
    conn_score, duration_seconds = connection_score(call)
    if lines:
        prod_score, product_keywords_found = product_knowledge_score(agent_lines)
        comp_score, forbidden_found = compliance_score(agent_lines)
        obj_score, objection_keywords_found, obj_total, obj_handled = (
            objection_handling_score(ordered)
        )
        tone_score, greeting_found, closing_found, positive_count = (
            tonality_score(agent_lines, first_agent_text)
        )
    else:
        # No transcript lines at all — give every dimension a neutral 50
        # except compliance (which is structurally 100 when there are no
        # agent utterances to violate it).
        prod_score = 0
        comp_score = 50
        obj_score = 50
        tone_score = 50
        product_keywords_found = []
        forbidden_found = []
        objection_keywords_found = []
        obj_total = 0
        obj_handled = 0
        greeting_found = False
        closing_found = False
        positive_count = 0
        flags.append(CallQualityScore.Flag.NO_TRANSCRIPT.value)

    composite = _compute_composite(
        conn_score, prod_score, comp_score, obj_score, tone_score
    )

    if forbidden_found and comp_score < 100:
        # The pattern: any forbidden phrase drops compliance below 100;
        # if it drops below the 60 threshold, the flag fires. Spec also
        # requires the flag whenever a forbidden phrase landed (even if
        # the score is still ≥ 60), so two separate cases here:
        if comp_score < 60:
            flags.append(CallQualityScore.Flag.COMPLIANCE_VIOLATION.value)
        else:
            # Soft violation — still record the flag for CAIO visibility.
            flags.append(CallQualityScore.Flag.COMPLIANCE_VIOLATION.value)
    if not agent_lines:
        flags.append(CallQualityScore.Flag.ZERO_AGENT_UTTERANCES.value)
    if (
        agent_lines
        and tone_score < 40
        and not greeting_found
    ):
        flags.append(CallQualityScore.Flag.NO_GREETING.value)
    elif agent_lines and not greeting_found:
        # Greeting missing is itself worth flagging — tonality may still
        # be ≥ 40 because of positive keywords / closing; surface the
        # gap for CAIO.
        flags.append(CallQualityScore.Flag.NO_GREETING.value)
    if agent_lines and prod_score < 40:
        flags.append(CallQualityScore.Flag.WEAK_PRODUCT_KNOWLEDGE.value)
    if obj_total > 0 and obj_score < 40:
        flags.append(CallQualityScore.Flag.NO_OBJECTION_RESPONSE.value)
    if (
        conn_score > 0
        and call.status == Call.Status.COMPLETED.value
        and duration_seconds < 30
    ):
        flags.append(CallQualityScore.Flag.SHORT_CALL.value)

    # Deduplicate while preserving order.
    deduped_flags: list[str] = []
    for f in flags:
        if f not in deduped_flags:
            deduped_flags.append(f)
    flags = deduped_flags

    raw_signals: dict[str, Any] = {
        "agent_utterance_count": len(agent_lines),
        "customer_utterance_count": len(customer_lines),
        "duration_seconds": duration_seconds,
        "product_keywords_found": product_keywords_found,
        "forbidden_phrases_found": forbidden_found,
        "objection_keywords_found": objection_keywords_found,
        "objection_total": obj_total,
        "objection_handled": obj_handled,
        "positive_keyword_count": positive_count,
        "greeting_found": greeting_found,
        "closing_found": closing_found,
        "first_agent_text_excerpt": (first_agent_text or "")[:160],
    }

    result: dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "call_id": call.id,
        "scoring_version": SCORING_VERSION,
        "line_count": len(lines),
        "agent_label": call.agent or "",
        "duration_raw": call.duration or "",
        "connection_score": conn_score,
        "product_knowledge_score": prod_score,
        "compliance_score": comp_score,
        "objection_handling_score": obj_score,
        "tonality_score": tone_score,
        "composite_score": composite,
        "flags": flags,
        "raw_signals": raw_signals,
        "duration_ms": int((time.monotonic() - started_ms) * 1000),
    }

    if dry_run:
        result["dry_run"] = True
        return result

    CallQualityScore.objects.update_or_create(
        call=call,
        defaults={
            "scored_at": timezone.now(),
            "scoring_version": SCORING_VERSION,
            "line_count": len(lines),
            "agent_label": (call.agent or "")[:80],
            "duration_raw": (call.duration or "")[:16],
            "connection_score": conn_score,
            "product_knowledge_score": prod_score,
            "compliance_score": comp_score,
            "objection_handling_score": obj_score,
            "tonality_score": tone_score,
            "composite_score": composite,
            "flags": flags,
            "raw_signals": raw_signals,
        },
    )

    write_event(
        kind="call_quality.scored",
        text=(
            f"Phase 11B scored call {call.id} "
            f"(composite={composite}, flags={','.join(flags) or 'none'})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "11B",
            "call_id": call.id,
            "composite_score": composite,
            "flags": flags,
            # Truncated agent label so PII (e.g. specific Vapi assistant
            # names tagged with phone fragments) never lands in audit.
            "agent_label_suffix": (call.agent or "")[-20:],
        },
    )
    return result


def get_scoring_backlog() -> QuerySet[Call]:
    """Calls ready for quality scoring.

    Eligibility:
    - `transcript_ingested_at` is set (Phase 11A persisted lines).
    - `transcript_line_count > 0` (denormalized count is positive).
    - No `CallQualityScore` row yet.
    """
    return (
        Call.objects.filter(
            transcript_ingested_at__isnull=False,
            transcript_line_count__gt=0,
        )
        .filter(quality_score__isnull=True)
        .order_by("transcript_ingested_at")
    )


def score_backlog(
    *,
    limit: int = 50,
    dry_run: bool = False,
) -> dict[str, Any]:
    started_ms = time.monotonic()
    summary: dict[str, Any] = {
        "total": 0,
        "scored": 0,
        "skipped_already": 0,
        "skipped_no_call": 0,
        "errors": 0,
        "dry_run": bool(dry_run),
        "avg_composite_score": 0.0,
        "duration_ms": 0,
        "results": [],
    }
    composites: list[int] = []
    backlog = list(get_scoring_backlog()[: max(1, int(limit))])
    summary["total"] = len(backlog)
    for call in backlog:
        result = score_call(call.id, dry_run=dry_run)
        summary["results"].append(result)
        if result.get("ok") and not result.get("skipped"):
            summary["scored"] += 1
            composites.append(int(result.get("composite_score") or 0))
        elif result.get("reason") == "already_scored":
            summary["skipped_already"] += 1
        elif result.get("reason") == "call_not_found":
            summary["skipped_no_call"] += 1
        else:
            summary["errors"] += 1
    if composites:
        summary["avg_composite_score"] = round(
            sum(composites) / len(composites), 2
        )
    summary["duration_ms"] = int((time.monotonic() - started_ms) * 1000)
    return summary


def get_scoring_overview(window_days: int = 30) -> dict[str, Any]:
    """Read-only diagnostic snapshot for the inspector CLI + summary API."""
    from datetime import timedelta

    now = timezone.now()
    cutoff = now - timedelta(days=max(1, int(window_days)))
    backlog_qs = get_scoring_backlog()
    scored_qs = CallQualityScore.objects.filter(scored_at__gte=cutoff)
    total_scored = scored_qs.count()
    backlog_count = backlog_qs.count()

    avg_composite = 0.0
    if total_scored:
        avg_composite = round(
            sum(scored_qs.values_list("composite_score", flat=True))
            / max(1, total_scored),
            2,
        )

    # Top 5 flag codes by frequency in the window.
    flag_counts: dict[str, int] = {}
    for row in scored_qs.values_list("flags", flat=True):
        for code in row or []:
            flag_counts[code] = flag_counts.get(code, 0) + 1
    top_flags = sorted(
        flag_counts.items(), key=lambda kv: kv[1], reverse=True
    )[:5]

    low_compliance_count = scored_qs.filter(compliance_score__lt=60).count()

    # Aggregate per agent — denormalized agent_label keeps this cheap.
    by_agent: dict[str, dict[str, Any]] = {}
    for row in scored_qs.values(
        "agent_label", "composite_score", "compliance_score"
    ):
        label = (row["agent_label"] or "unattributed")[:80]
        bucket = by_agent.setdefault(
            label,
            {
                "agent_label": label,
                "call_count": 0,
                "composite_total": 0,
                "compliance_total": 0,
            },
        )
        bucket["call_count"] += 1
        bucket["composite_total"] += int(row["composite_score"] or 0)
        bucket["compliance_total"] += int(row["compliance_score"] or 0)
    avg_by_agent = [
        {
            "agent_label": b["agent_label"],
            "call_count": b["call_count"],
            "avg_composite": round(
                b["composite_total"] / max(1, b["call_count"]), 2
            ),
            "avg_compliance": round(
                b["compliance_total"] / max(1, b["call_count"]), 2
            ),
        }
        for b in sorted(
            by_agent.values(),
            key=lambda x: x["call_count"],
            reverse=True,
        )
    ]

    return {
        "now": now,
        "window_days": int(window_days),
        "total_scored": total_scored,
        "backlog_count": backlog_count,
        "avg_composite": avg_composite,
        "low_compliance_count": low_compliance_count,
        "top_flags": [
            {"flag_code": code, "count": count}
            for code, count in top_flags
        ],
        "avg_by_agent": avg_by_agent,
    }


__all__ = (
    "SCORING_VERSION",
    "PRODUCT_KEYWORDS",
    "FORBIDDEN_PHRASES",
    "OBJECTION_KEYWORDS",
    "RESPONSE_KEYWORDS",
    "GREETING_KEYWORDS",
    "POSITIVE_KEYWORDS",
    "CLOSING_KEYWORDS",
    "connection_score",
    "product_knowledge_score",
    "compliance_score",
    "objection_handling_score",
    "tonality_score",
    "score_call",
    "score_backlog",
    "get_scoring_backlog",
    "get_scoring_overview",
)
