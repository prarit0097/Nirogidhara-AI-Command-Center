"""Calls write services. Phase 2D: Vapi voice trigger + webhook persistence.

The Vapi adapter at ``apps/calls/integrations/vapi_client.py`` is responsible
for the network call; this module owns the database side: creating the
``Call`` row, persisting transcript lines, updating call status, detecting
handoff flags, and writing ``AuditEvent`` rows.

Compliance hard stop (Master Blueprint §26 #4):
- This module never injects medical text into the Vapi prompt. The adapter
  passes only metadata. Any future prompt-builder MUST pull from
  ``apps.compliance.Claim``.
- CAIO never executes business actions; nothing in this module routes through
  CAIO.
"""
from __future__ import annotations

import logging
from datetime import timezone as _tz
from typing import Any, Iterable

from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Lead

from .integrations.vapi_client import (
    CallResult,
    VapiClientError,
    trigger_call as _gateway_trigger_call,
)
from .models import Call, CallTranscriptLine

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


logger = logging.getLogger(__name__)


# ----- Handoff phrases (heuristic fallback) -----
# Vapi's analysis sends explicit ``handoff_flags`` on ``analysis.completed``.
# When that field is missing we fall back to keyword matching on the final
# transcript so the safety net always fires. These phrases are ASCII-only by
# design — Hindi/Hinglish keywords are best detected by the Vapi analyser.

_HANDOFF_KEYWORDS: dict[str, tuple[str, ...]] = {
    "medical_emergency": (
        "emergency",
        "ambulance",
        "hospital admit",
        "chest pain",
        "unconscious",
    ),
    "side_effect_complaint": (
        "side effect",
        "side-effect",
        "rash",
        "vomiting",
        "allergic",
    ),
    "very_angry_customer": (
        "ridiculous",
        "scam",
        "fraud",
        "fake",
        "stop calling",
    ),
    "human_requested": (
        "human agent",
        "real person",
        "talk to a person",
        "manager",
    ),
    "low_confidence": (),  # only set explicitly via analysis payload
    "legal_or_refund_threat": (
        "lawyer",
        "consumer court",
        "legal action",
        "complaint to",
        "refund now",
    ),
}


# ----- Trigger -----


@transaction.atomic
def trigger_call_for_lead(
    *,
    lead: Lead,
    by_user: "User",
    purpose: str = "sales_call",
) -> Call:
    """Create a queued ``Call`` row and route through the Vapi adapter.

    Raises ``VapiClientError`` for adapter / config failures so the view can
    return a 502/400. The Call row is rolled back if the adapter raises.
    """
    if not purpose:
        purpose = "sales_call"

    call_id = next_id("CL", Call, base=8500)

    try:
        result: CallResult = _gateway_trigger_call(
            lead_id=lead.id,
            customer_phone=lead.phone,
            customer_name=lead.name,
            language=lead.language,
            purpose=purpose,
        )
    except VapiClientError:
        # Re-raise — the view returns 502 and the row is never created.
        raise

    call = Call.objects.create(
        id=call_id,
        lead_id=lead.id,
        customer=lead.name,
        phone=lead.phone,
        agent="Calling AI · Vapi",
        language=lead.language,
        status=Call.Status.QUEUED,
        provider=Call.Provider.VAPI,
        provider_call_id=result.provider_call_id,
        raw_response=dict(result.raw or {}),
    )

    write_event(
        kind="call.triggered",
        text=f"Vapi call triggered for {lead.id} · purpose {purpose}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "call_id": call.id,
            "lead_id": lead.id,
            "provider": "vapi",
            "provider_call_id": result.provider_call_id,
            "purpose": purpose,
            "by": getattr(by_user, "username", ""),
        },
    )
    return call


# ----- Webhook persistence -----


def _resolve_call(payload: dict[str, Any]) -> Call | None:
    """Find the local ``Call`` row a webhook references."""
    call_obj = payload.get("call") or {}
    provider_call_id = (
        call_obj.get("id")
        or payload.get("callId")
        or payload.get("call_id")
        or ""
    )
    if not provider_call_id:
        return None
    return Call.objects.filter(provider_call_id=provider_call_id).first()


def _coerce_iso(value: Any) -> Any:
    """Best-effort: parse a timestamp string into an aware datetime, else
    return the timezone-aware now()."""
    if isinstance(value, str) and value:
        try:
            from datetime import datetime

            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(_tz.utc)
        except ValueError:
            pass
    return timezone.now()


def _detect_handoff_flags(payload: dict[str, Any], call: Call) -> list[str]:
    """Combine explicit Vapi flags with keyword fallback on the transcript."""
    explicit = payload.get("handoff_flags") or payload.get("flags") or []
    if isinstance(explicit, str):
        explicit = [f.strip() for f in explicit.split(",") if f.strip()]

    found: set[str] = {f for f in explicit if isinstance(f, str)}

    # Keyword fallback against the latest transcript text.
    transcript_text = " ".join(
        line.text for line in call.transcript_lines.all() if line.text
    )
    if transcript_text:
        haystack = transcript_text.lower()
        for flag, keywords in _HANDOFF_KEYWORDS.items():
            if flag in found or not keywords:
                continue
            if any(kw in haystack for kw in keywords):
                found.add(flag)
    return sorted(found)


def _save_transcript_lines(call: Call, lines: Iterable[dict[str, Any]]) -> int:
    """Replace the call's transcript with the supplied lines.

    Vapi's ``transcript.final`` payload is the single source of truth at end-
    of-call. For ``transcript.updated`` (in-flight updates) we still wipe
    and re-insert because the wire format is the full conversation so far.
    """
    rows: list[CallTranscriptLine] = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        who = str(line.get("who") or line.get("role") or "")[:40]
        text = str(line.get("text") or line.get("content") or "")
        if not text:
            continue
        rows.append(
            CallTranscriptLine(
                call=call,
                order=int(line.get("order") or index),
                who=who or "Unknown",
                text=text,
            )
        )
    if not rows:
        return 0
    # Atomic replace: drop existing then bulk_create.
    call.transcript_lines.all().delete()
    CallTranscriptLine.objects.bulk_create(rows)
    return len(rows)


@transaction.atomic
def persist_vapi_webhook(*, event_type: str, payload: dict[str, Any]) -> tuple[Call | None, str]:
    """Apply a Vapi webhook event to the matching ``Call`` row.

    Returns ``(call, status)`` where ``status`` is one of:

    - ``"ok"``       — event matched a known handler and was applied
    - ``"ignored"``  — event type isn't one we react to (still 200)
    - ``"unknown"``  — the call referenced doesn't exist locally (200)

    The webhook view is responsible for HMAC verification and idempotency
    insertion before calling this function.
    """
    handler = _HANDLERS.get(event_type)
    if handler is None:
        return None, "ignored"

    call = _resolve_call(payload)
    if call is None:
        return None, "unknown"

    handler(payload, call)
    return call, "ok"


def _handle_call_started(payload: dict[str, Any], call: Call) -> None:
    call.status = Call.Status.LIVE
    call.raw_response = {**(call.raw_response or {}), "started": payload}
    call.save(update_fields=["status", "raw_response", "updated_at"])
    write_event(
        kind="call.started",
        text=f"Vapi call {call.provider_call_id} started for {call.lead_id}",
        tone=AuditEvent.Tone.INFO,
        payload={"call_id": call.id, "lead_id": call.lead_id, "via": "webhook"},
    )


def _handle_call_ended(payload: dict[str, Any], call: Call) -> None:
    call.status = Call.Status.COMPLETED
    duration = payload.get("duration") or payload.get("durationSeconds")
    if duration is not None:
        try:
            seconds = int(float(duration))
            mins, secs = divmod(seconds, 60)
            call.duration = f"{mins}:{secs:02d}"
        except (TypeError, ValueError):
            pass
    call.ended_at = _coerce_iso(payload.get("ended_at") or payload.get("endedAt"))
    call.raw_response = {**(call.raw_response or {}), "ended": payload}
    call.save(update_fields=["status", "duration", "ended_at", "raw_response", "updated_at"])
    write_event(
        kind="call.completed",
        text=f"Vapi call {call.provider_call_id} ended ({call.duration}) for {call.lead_id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"call_id": call.id, "lead_id": call.lead_id, "via": "webhook"},
    )


def _handle_transcript_update(payload: dict[str, Any], call: Call) -> None:
    lines = payload.get("transcript") or payload.get("lines") or []
    saved = _save_transcript_lines(call, lines)
    if saved:
        write_event(
            kind="call.transcript",
            text=f"Vapi transcript update · {saved} lines for call {call.id}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "call_id": call.id,
                "lead_id": call.lead_id,
                "lines": saved,
                "final": False,
            },
        )


def _handle_transcript_final(payload: dict[str, Any], call: Call) -> None:
    lines = payload.get("transcript") or payload.get("lines") or []
    saved = _save_transcript_lines(call, lines)
    if saved:
        write_event(
            kind="call.transcript",
            text=f"Vapi final transcript · {saved} lines for call {call.id}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "call_id": call.id,
                "lead_id": call.lead_id,
                "lines": saved,
                "final": True,
            },
        )


def _handle_analysis_completed(payload: dict[str, Any], call: Call) -> None:
    summary = payload.get("summary") or payload.get("analysis", {}).get("summary") or ""
    sentiment = payload.get("sentiment") or ""
    flags = _detect_handoff_flags(payload, call)
    update_fields: list[str] = ["handoff_flags", "raw_response", "updated_at"]
    call.handoff_flags = flags
    call.raw_response = {**(call.raw_response or {}), "analysis": payload}
    if summary:
        call.summary = str(summary)[:5000]
        update_fields.append("summary")
    if sentiment in Call.Sentiment.values:
        call.sentiment = sentiment
        update_fields.append("sentiment")
    call.save(update_fields=update_fields)

    if flags:
        write_event(
            kind="call.handoff_flagged",
            text=f"Vapi call {call.id} flagged handoff: {', '.join(flags)}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "call_id": call.id,
                "lead_id": call.lead_id,
                "flags": flags,
            },
        )
    else:
        write_event(
            kind="call.analysis",
            text=f"Vapi call {call.id} analysis complete",
            tone=AuditEvent.Tone.INFO,
            payload={"call_id": call.id, "lead_id": call.lead_id},
        )


def _handle_call_failed(payload: dict[str, Any], call: Call) -> None:
    call.status = Call.Status.FAILED
    call.error_message = str(
        payload.get("error") or payload.get("reason") or "Vapi call failed"
    )[:5000]
    call.ended_at = _coerce_iso(payload.get("ended_at") or payload.get("endedAt"))
    call.raw_response = {**(call.raw_response or {}), "failed": payload}
    call.save(update_fields=["status", "error_message", "ended_at", "raw_response", "updated_at"])
    write_event(
        kind="call.failed",
        text=f"Vapi call {call.id} failed: {call.error_message}",
        tone=AuditEvent.Tone.DANGER,
        payload={
            "call_id": call.id,
            "lead_id": call.lead_id,
            "error": call.error_message,
        },
    )


_HANDLERS: dict[str, Any] = {
    "call.started": _handle_call_started,
    "call.ended": _handle_call_ended,
    "transcript.updated": _handle_transcript_update,
    "transcript.final": _handle_transcript_final,
    "analysis.completed": _handle_analysis_completed,
    "call.failed": _handle_call_failed,
}


__all__ = (
    "trigger_call_for_lead",
    "persist_vapi_webhook",
)
