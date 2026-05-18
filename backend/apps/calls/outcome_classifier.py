"""Phase 12B — Call Outcome Classifier V1 (deterministic, recommendations-only).

Reads completed Call + CallTranscriptLine rows produced by the Phase
2D Vapi webhook flow (and the Phase 11A REST pull). Classifies each
call's BUSINESS OUTCOME (converted / callback / not interested /
unclear / not connected / no transcript) using deterministic
Hinglish-aware keyword matching, then SUGGESTS a `Lead.status` update.

**V1 is recommendations-only.** `apply_outcome_updates` is the ONLY
path that mutates `Lead.status`, and it requires:

- a non-blank `--operator-name`
- the `--confirm-outcome-apply` CLI flag (enforced at the command layer)
- each row's `review_status="approved"`
- a non-blank `suggested_lead_status`

Phase 12B never sends WhatsApp, makes a call, dispatches a shipment,
or calls Razorpay / Meta Cloud / Delhivery. Outside of
`apply_outcome_updates` it never mutates `Lead.status` at all.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Lead

from .models import (
    AiCallCampaignGate,
    Call,
    CallOutcomeRecord,
    CallTranscriptLine,
)


logger = logging.getLogger(__name__)


SCORING_VERSION = "deterministic_v1"


# Permissive customer-side classifier — mirrors the Phase 11B who
# classifier conventions (Phase 2D webhook persistence and Phase 11A
# REST normalisation produce different casings).
_CUSTOMER_WHO_VALUES = frozenset({"customer", "user", "human"})


# Hinglish-aware deterministic V1 signal lists. All lowercase. The
# classifier joins customer-side utterances + lowercases them before
# the `in` check, so multi-word phrases like "le lunga" match.
CONVERSION_SIGNALS: tuple[str, ...] = (
    # Note: "ha" (the standalone 2-char form) is intentionally NOT in
    # the list — it triggers false positives against words like
    # "raha"/"raha hoon". "haan" is the canonical Hinglish "yes".
    "haan", "bilkul", "zaroor", "le lunga", "le lungi",
    "order", "khareed", "buy", "payment", "link bhejo",
    "confirm", "lena hai", "chahiye", "mangwa", "mangwana",
    "ok bhai", "theek hai", "kar lete hain",
)

CALLBACK_SIGNALS: tuple[str, ...] = (
    "baad mein", "baad me", "call karo", "call karein",
    "phir baat", "thodi der", "abhi busy", "abhi nahi",
    "kal", "shaam ko", "subah", "raat ko", "ghar aake",
    "callback", "call back", "later",
)

REJECTION_SIGNALS: tuple[str, ...] = (
    "nahi chahiye", "nahi lena", "mujhe nahi", "interested nahi",
    "not interested", "no", "nahi", "band karo",
    "mat karo", "number hatao", "dnd", "remove",
    "koi zaroorat nahi", "paise nahi", "mehnga",
)


# Outcome -> suggested Lead.status mapping. Outcomes that don't have a
# clear status change keep the empty string (apply_outcome_updates
# skips blank suggestions).
OUTCOME_TO_LEAD_STATUS: dict[str, str] = {
    CallOutcomeRecord.DetectedOutcome.CONNECTED_CONVERTED.value: (
        Lead.Status.PAYMENT_LINK_SENT.value
    ),
    CallOutcomeRecord.DetectedOutcome.CONNECTED_CALLBACK.value: (
        Lead.Status.CALLBACK_REQUIRED.value
    ),
    CallOutcomeRecord.DetectedOutcome.CONNECTED_NOT_INTERESTED.value: (
        Lead.Status.NOT_INTERESTED.value
    ),
    CallOutcomeRecord.DetectedOutcome.CONNECTED_UNCLEAR.value: "",
    CallOutcomeRecord.DetectedOutcome.NOT_CONNECTED.value: "",
    CallOutcomeRecord.DetectedOutcome.NO_TRANSCRIPT.value: "",
}


# Call statuses that mean "no conversation happened" (used to gate the
# `not_connected` outcome).
_DISCONNECT_STATUSES = frozenset(
    {
        Call.Status.MISSED.value,
        Call.Status.FAILED.value,
        Call.Status.QUEUED.value,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_customer_who(who: str) -> bool:
    """Permissive case-insensitive customer-side classifier."""
    if not who:
        return False
    lower = who.strip().lower()
    if lower in _CUSTOMER_WHO_VALUES:
        return True
    return any(token in lower for token in _CUSTOMER_WHO_VALUES)


def _parse_duration_seconds(value: str) -> int:
    """Reuse Phase 9E parser conventions for `"m:ss"` strings."""
    if not value:
        return 0
    parts = value.strip().split(":")
    try:
        if len(parts) == 1:
            return max(0, int(parts[0]))
        if len(parts) == 2:
            return max(0, int(parts[0]) * 60 + int(parts[1]))
        if len(parts) == 3:
            return max(
                0, int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            )
    except (TypeError, ValueError):
        return 0
    return 0


def _split_lines(
    lines: Iterable[CallTranscriptLine],
) -> tuple[list[str], list[str], int]:
    """Return (customer_lines, agent_lines, line_count)."""
    customer_lines: list[str] = []
    agent_lines: list[str] = []
    line_count = 0
    for line in lines:
        text = (line.text or "").strip()
        if not text:
            continue
        line_count += 1
        if _is_customer_who(line.who or ""):
            customer_lines.append(text)
        else:
            # Anything non-customer (agent / assistant / system /
            # unknown) is treated as agent-side for utterance counting.
            agent_lines.append(text)
    return customer_lines, agent_lines, line_count


def _find_signals(haystack: str, needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if needle in haystack]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationResult:
    """Lightweight dataclass returned alongside the persisted row."""

    outcome: str
    confidence: str
    suggested_lead_status: str
    evidence: dict[str, Any]


def _classify_text(
    *,
    call_status: str,
    customer_text: str,
    line_count: int,
) -> ClassificationResult:
    """Pure deterministic classification — no DB access.

    Exposed at module level so tests can exercise the rule cascade
    without staging Calls.
    """
    if call_status in _DISCONNECT_STATUSES:
        return ClassificationResult(
            outcome=CallOutcomeRecord.DetectedOutcome.NOT_CONNECTED.value,
            confidence=CallOutcomeRecord.Confidence.HIGH.value,
            suggested_lead_status="",
            evidence={
                "call_status": call_status,
                "transcript_line_count": int(line_count),
                "conversion_signals_found": [],
                "callback_signals_found": [],
                "rejection_signals_found": [],
                "customer_text_excerpt": "",
            },
        )
    if line_count == 0:
        return ClassificationResult(
            outcome=CallOutcomeRecord.DetectedOutcome.NO_TRANSCRIPT.value,
            confidence=CallOutcomeRecord.Confidence.LOW.value,
            suggested_lead_status="",
            evidence={
                "call_status": call_status,
                "transcript_line_count": 0,
                "conversion_signals_found": [],
                "callback_signals_found": [],
                "rejection_signals_found": [],
                "customer_text_excerpt": "",
            },
        )

    haystack = customer_text.lower()
    conv_found = _find_signals(haystack, CONVERSION_SIGNALS)
    cb_found = _find_signals(haystack, CALLBACK_SIGNALS)
    rej_found = _find_signals(haystack, REJECTION_SIGNALS)

    # Priority cascade: rejection > conversion > callback > unclear.
    # Rejection is checked FIRST because Hinglish negations like
    # "nahi chahiye" / "mujhe nahi" / "nahi lena" embed the conversion
    # keyword ("chahiye", "lena") inside an explicit refusal. The
    # conversion list is "yes" keywords; the rejection list is "no"
    # keywords. An explicit "no" must always beat an incidental "yes"
    # keyword match. Rejection also beats callback because "nahi
    # chahiye, kal" is a refusal, not a callback request.
    if rej_found:
        outcome = (
            CallOutcomeRecord.DetectedOutcome.CONNECTED_NOT_INTERESTED.value
        )
        confidence = CallOutcomeRecord.Confidence.HIGH.value
    elif conv_found:
        outcome = (
            CallOutcomeRecord.DetectedOutcome.CONNECTED_CONVERTED.value
        )
        confidence = (
            CallOutcomeRecord.Confidence.HIGH.value
            if len(conv_found) > 1
            else CallOutcomeRecord.Confidence.MEDIUM.value
        )
    elif cb_found:
        outcome = (
            CallOutcomeRecord.DetectedOutcome.CONNECTED_CALLBACK.value
        )
        confidence = CallOutcomeRecord.Confidence.MEDIUM.value
    else:
        outcome = (
            CallOutcomeRecord.DetectedOutcome.CONNECTED_UNCLEAR.value
        )
        confidence = CallOutcomeRecord.Confidence.LOW.value

    return ClassificationResult(
        outcome=outcome,
        confidence=confidence,
        suggested_lead_status=OUTCOME_TO_LEAD_STATUS[outcome],
        evidence={
            "call_status": call_status,
            "transcript_line_count": int(line_count),
            "conversion_signals_found": conv_found,
            "callback_signals_found": cb_found,
            "rejection_signals_found": rej_found,
            "customer_text_excerpt": (customer_text[:240] or ""),
        },
    )


def classify_call(call_id: str) -> CallOutcomeRecord:
    """Classify one Call. Idempotent — returns the existing record if
    one already exists for the given Call (never mutates an existing
    record). Writes a single `call_outcome.classified` audit row on
    creation only.
    """
    call = Call.objects.filter(pk=call_id).first()
    if call is None:
        raise ValueError(f"Call '{call_id}' not found")

    existing = CallOutcomeRecord.objects.filter(call=call).first()
    if existing is not None:
        return existing

    lines = list(
        CallTranscriptLine.objects.filter(call=call).order_by("order")
    )
    customer_lines, agent_lines, line_count = _split_lines(lines)
    customer_text = " ".join(customer_lines)

    classification = _classify_text(
        call_status=(call.status or "").strip(),
        customer_text=customer_text,
        line_count=line_count,
    )
    evidence = dict(classification.evidence)
    evidence.update(
        {
            "agent_utterance_count": len(agent_lines),
            "customer_utterance_count": len(customer_lines),
            "duration_seconds": _parse_duration_seconds(call.duration or ""),
        }
    )

    # Locate the most recent campaign gate this Call participated in
    # (best-effort — Phase 12A stores lead_ids on `leads_attempted`).
    # SQLite doesn't support JSON ``contains``, so scan the latest few
    # gates in Python. Campaigns are bounded at AI_CALLING_MAX_PER_CAMPAIGN
    # (default 20 leads) and there are few gates per day, so this is
    # cheap and engine-agnostic.
    campaign_gate: AiCallCampaignGate | None = None
    if call.lead_id:
        for gate_row in AiCallCampaignGate.objects.order_by("-executed_at")[
            :50
        ]:
            if call.lead_id in (gate_row.leads_attempted or []):
                campaign_gate = gate_row
                break

    current_lead_status = ""
    lead = (
        Lead.objects.filter(pk=call.lead_id).first()
        if call.lead_id
        else None
    )
    if lead is not None:
        current_lead_status = (lead.status or "")[:32]

    record = CallOutcomeRecord.objects.create(
        call=call,
        campaign_gate=campaign_gate,
        lead_id=(call.lead_id or "")[:32],
        current_lead_status=current_lead_status,
        detected_outcome=classification.outcome,
        suggested_lead_status=(
            classification.suggested_lead_status or ""
        )[:32],
        confidence=classification.confidence,
        evidence=evidence,
        review_status=CallOutcomeRecord.ReviewStatus.PENDING.value,
        classified_at=timezone.now(),
        scoring_version=SCORING_VERSION,
    )

    write_event(
        kind="call_outcome.classified",
        text=(
            f"Phase 12B classified call {call.id} as "
            f"{record.detected_outcome} (confidence={record.confidence})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "12B",
            "call_id": call.id,
            "lead_id": record.lead_id,
            "detected_outcome": record.detected_outcome,
            "confidence": record.confidence,
            "suggested_lead_status": record.suggested_lead_status,
            "campaign_gate_id": record.campaign_gate_id,
        },
    )
    return record


def classify_campaign_calls(campaign_gate_id: int) -> dict[str, Any]:
    """Classify every Call linked to a Phase 12A campaign gate.

    Resolves Calls via the gate's `leads_attempted` lead id list. A
    lead with no Call row yet is silently skipped (the Vapi webhook
    hasn't landed); the daily sweep picks it up later.
    """
    gate = AiCallCampaignGate.objects.filter(pk=campaign_gate_id).first()
    if gate is None:
        raise ValueError(
            f"AiCallCampaignGate '{campaign_gate_id}' not found"
        )
    summary = {
        "total": 0,
        "connected_converted": 0,
        "connected_callback": 0,
        "connected_not_interested": 0,
        "connected_unclear": 0,
        "not_connected": 0,
        "no_transcript": 0,
        "skipped_no_call": 0,
    }
    lead_ids: list[str] = list(gate.leads_attempted or [])
    for lead_id in lead_ids:
        call = (
            Call.objects.filter(lead_id=lead_id)
            .order_by("-created_at")
            .first()
        )
        if call is None:
            summary["skipped_no_call"] += 1
            continue
        record = classify_call(call.id)
        summary["total"] += 1
        summary[record.detected_outcome] = (
            summary.get(record.detected_outcome, 0) + 1
        )
    return summary


def classify_recent_calls(hours: int = 24) -> dict[str, Any]:
    """Classify Calls created in the last `hours` window that don't
    yet have a CallOutcomeRecord row.
    """
    cutoff = timezone.now() - timedelta(hours=max(1, int(hours)))
    qs = (
        Call.objects.filter(created_at__gte=cutoff)
        .filter(outcome_record__isnull=True)
        .order_by("created_at")
    )
    summary = {
        "total": 0,
        "connected_converted": 0,
        "connected_callback": 0,
        "connected_not_interested": 0,
        "connected_unclear": 0,
        "not_connected": 0,
        "no_transcript": 0,
        "errors": 0,
    }
    for call in qs:
        try:
            record = classify_call(call.id)
        except Exception as exc:  # noqa: BLE001 - one bad row must not poison the sweep
            logger.warning(
                "phase12b: classify_call failed for %s: %s", call.id, exc
            )
            summary["errors"] += 1
            continue
        summary["total"] += 1
        summary[record.detected_outcome] = (
            summary.get(record.detected_outcome, 0) + 1
        )
    return summary


@transaction.atomic
def apply_outcome_updates(
    *,
    operator_name: str,
    outcome_record_ids: list[int] | None = None,
    sandbox: bool = False,
) -> dict[str, Any]:
    """Apply approved suggestions to `Lead.status`.

    Returns ``{total_applied, skipped_blank, skipped_sandbox, errors,
    applied_record_ids}``. The transaction wrapper ensures partial
    failures don't leave `Lead.status` mutated while the
    `CallOutcomeRecord.review_status` flip rolls back.

    Director must already have run `approve_call_outcome` per record
    — pending records are silently ignored by this function (the CLI
    enforces the `--confirm-outcome-apply` flag separately).
    """
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise ValueError("operator_name is required")

    qs = CallOutcomeRecord.objects.filter(
        review_status=CallOutcomeRecord.ReviewStatus.APPROVED.value,
    )
    if outcome_record_ids is not None:
        qs = qs.filter(pk__in=list(outcome_record_ids))

    total_applied = 0
    skipped_blank = 0
    skipped_sandbox = 0
    errors = 0
    applied_ids: list[int] = []

    for record in qs.select_related("call"):
        suggested = (record.suggested_lead_status or "").strip()
        if not suggested:
            skipped_blank += 1
            continue
        if sandbox:
            skipped_sandbox += 1
            write_event(
                kind="call_outcome.applied",
                text=(
                    f"Phase 12B sandbox skip: would have flipped lead "
                    f"{record.lead_id} to '{suggested}' (record {record.pk})."
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "phase": "12B",
                    "outcome_record_id": record.pk,
                    "lead_id": record.lead_id,
                    "suggested_lead_status": suggested,
                    "sandbox": True,
                    "skipped": True,
                },
            )
            continue
        try:
            lead = Lead.objects.filter(pk=record.lead_id).first()
            if lead is None:
                errors += 1
                logger.warning(
                    "phase12b: apply failed - lead %s missing", record.lead_id
                )
                continue
            previous_status = lead.status
            lead.status = suggested
            lead.save(update_fields=["status"])
            record.review_status = (
                CallOutcomeRecord.ReviewStatus.APPLIED.value
            )
            record.applied_at = timezone.now()
            record.applied_by = operator_name[:120]
            record.save(
                update_fields=[
                    "review_status",
                    "applied_at",
                    "applied_by",
                    "updated_at",
                ]
            )
            total_applied += 1
            applied_ids.append(record.pk)
            write_event(
                kind="call_outcome.applied",
                text=(
                    f"Phase 12B applied lead status update: "
                    f"{record.lead_id} {previous_status!r} -> {suggested!r} "
                    f"(record {record.pk})."
                ),
                tone=AuditEvent.Tone.SUCCESS,
                payload={
                    "phase": "12B",
                    "outcome_record_id": record.pk,
                    "lead_id": record.lead_id,
                    "previous_lead_status": previous_status,
                    "applied_lead_status": suggested,
                    "applied_by": operator_name,
                    "sandbox": False,
                },
            )
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the whole sweep
            errors += 1
            logger.warning(
                "phase12b: apply failed for record %s: %s", record.pk, exc
            )

    return {
        "total_applied": total_applied,
        "skipped_blank": skipped_blank,
        "skipped_sandbox": skipped_sandbox,
        "errors": errors,
        "applied_record_ids": applied_ids,
    }


def get_outcomes_summary() -> dict[str, Any]:
    """Aggregate counts for the read-only summary API."""
    qs = CallOutcomeRecord.objects.all()
    summary = {
        "total": qs.count(),
        "pending_count": qs.filter(
            review_status=CallOutcomeRecord.ReviewStatus.PENDING.value
        ).count(),
        "approved_count": qs.filter(
            review_status=CallOutcomeRecord.ReviewStatus.APPROVED.value
        ).count(),
        "applied_count": qs.filter(
            review_status=CallOutcomeRecord.ReviewStatus.APPLIED.value
        ).count(),
        "skipped_count": qs.filter(
            review_status=CallOutcomeRecord.ReviewStatus.SKIPPED.value
        ).count(),
        "by_outcome": {},
    }
    by_outcome: dict[str, int] = {}
    for row in qs.values_list("detected_outcome", flat=True):
        by_outcome[row] = by_outcome.get(row, 0) + 1
    summary["by_outcome"] = by_outcome
    return summary


def approve_record(*, outcome_record_id: int, operator_name: str) -> CallOutcomeRecord:
    """Director-only helper called by the `approve_call_outcome` CLI.

    Transitions ``pending → approved``. Raises ``ValueError`` on
    missing record or wrong status. NEVER mutates Lead.status.
    """
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise ValueError("operator_name is required")
    record = CallOutcomeRecord.objects.filter(pk=outcome_record_id).first()
    if record is None:
        raise ValueError(
            f"CallOutcomeRecord '{outcome_record_id}' not found"
        )
    if record.review_status != CallOutcomeRecord.ReviewStatus.PENDING.value:
        raise ValueError(
            f"CallOutcomeRecord {record.pk} is in status "
            f"'{record.review_status}', expected 'pending'."
        )
    record.review_status = CallOutcomeRecord.ReviewStatus.APPROVED.value
    record.applied_by = operator_name[:120]  # capture reviewer
    record.save(update_fields=["review_status", "applied_by", "updated_at"])
    write_event(
        kind="call_outcome.classified",
        text=(
            f"Phase 12B outcome record {record.pk} approved by "
            f"{operator_name}."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "12B",
            "outcome_record_id": record.pk,
            "lead_id": record.lead_id,
            "detected_outcome": record.detected_outcome,
            "suggested_lead_status": record.suggested_lead_status,
            "approved_by": operator_name,
            "transition": "pending_to_approved",
        },
    )
    return record


__all__ = (
    "SCORING_VERSION",
    "CONVERSION_SIGNALS",
    "CALLBACK_SIGNALS",
    "REJECTION_SIGNALS",
    "OUTCOME_TO_LEAD_STATUS",
    "ClassificationResult",
    "classify_call",
    "classify_campaign_calls",
    "classify_recent_calls",
    "apply_outcome_updates",
    "approve_record",
    "get_outcomes_summary",
)
