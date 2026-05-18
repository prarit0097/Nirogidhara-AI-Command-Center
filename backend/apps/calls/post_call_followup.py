"""Phase 12C — Post-Call WhatsApp Follow-up Automation V1.

Identifies CallOutcomeRecord rows needing a WhatsApp follow-up and
queues them. The actual WhatsApp send is NEVER triggered here — Phase
12C only creates the Phase 7E-Live-B gate row in `draft` status. The
Director still owns the approve + execute flow via the existing
Phase 7E-Live-B CLI commands.

NEVER sends WhatsApp / makes a call / dispatches a shipment / mutates
Order / Payment / Customer / Lead. The only side effect outside the
PostCallFollowUpQueue table is a Phase 7E-Live-B gate row creation
(itself a draft-status record — no live send).
"""
from __future__ import annotations

import logging
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead

from .models import CallOutcomeRecord, PostCallFollowUpQueue


logger = logging.getLogger(__name__)


# Detected outcome → follow_up_type mapping. Outcomes that are not in
# this dict never queue a follow-up.
TRIGGER_OUTCOMES: dict[str, str] = {
    CallOutcomeRecord.DetectedOutcome.CONNECTED_CONVERTED.value: (
        PostCallFollowUpQueue.FollowUpType.PAYMENT_REMINDER.value
    ),
    CallOutcomeRecord.DetectedOutcome.CONNECTED_CALLBACK.value: (
        PostCallFollowUpQueue.FollowUpType.CALLBACK_CONFIRMATION.value
    ),
}


# Follow-up type → Phase 7E-Live-B template (logical action key) +
# context blurb. The Phase 7E-Live-B gate accepts the logical key
# (e.g. ``"payment_reminder"``) which the Phase 5A template registry
# maps to the Meta-approved ``nrg_*`` template via DEFAULT_TEMPLATE_NAMES.
_FOLLOW_UP_TEMPLATE: dict[str, str] = {
    PostCallFollowUpQueue.FollowUpType.PAYMENT_REMINDER.value: (
        "payment_reminder"
    ),
    PostCallFollowUpQueue.FollowUpType.CALLBACK_CONFIRMATION.value: (
        "confirmation_reminder"
    ),
}

_CONTEXT_TEXT: dict[str, str] = {
    # Note: no payment_url here — Director adds the actual payment link
    # via Phase 10C before sending. This WA is a warm follow-up first.
    PostCallFollowUpQueue.FollowUpType.PAYMENT_REMINDER.value: (
        "ji, aapne humse baat ki. Aapka order confirm karne ke liye "
        "niche link pe tap karein."
    ),
    PostCallFollowUpQueue.FollowUpType.CALLBACK_CONFIRMATION.value: (
        "ji, aapne callback request ki. Hum jaldi hi dobara call "
        "karenge."
    ),
}


AUDIT_QUEUED = "call_followup.queued"
AUDIT_GATE_PREPARED = "call_followup.gate_prepared"
AUDIT_NEEDS_CUSTOMER_SETUP = "call_followup.needs_customer_setup"
AUDIT_GATE_PREP_FAILED = "call_followup.gate_prep_failed"
AUDIT_DISPATCHED = "call_followup.dispatched"
AUDIT_SKIPPED = "call_followup.skipped"
AUDIT_SANDBOX_SKIPPED = "call_followup.sandbox_skipped"


class PostCallFollowUpStateError(Exception):
    """Raised on invalid lifecycle transitions."""


def _mask_last4(phone: str) -> str:
    phone = (phone or "").strip()
    return phone[-4:] if phone else ""


# ---------------------------------------------------------------------------
# Identify + queue
# ---------------------------------------------------------------------------


def identify_follow_up_candidates(
    hours: int = 26,
) -> QuerySet[CallOutcomeRecord]:
    """CallOutcomeRecord rows in the window that need a follow-up but
    don't yet have a PostCallFollowUpQueue row."""
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=max(1, int(hours)))
    return (
        CallOutcomeRecord.objects.filter(
            detected_outcome__in=list(TRIGGER_OUTCOMES.keys()),
            classified_at__gte=cutoff,
        )
        .filter(follow_up__isnull=True)
        .order_by("classified_at")
    )


def create_follow_up_entry(
    *,
    call_outcome: CallOutcomeRecord,
    sandbox: bool = False,
) -> tuple[PostCallFollowUpQueue, bool]:
    """Idempotent — returns ``(existing, False)`` if a row already
    exists for the outcome. Sandbox flag only affects later gate
    preparation; the queue row itself is always written so the
    Director has a clear audit trail.
    """
    existing = (
        PostCallFollowUpQueue.objects.filter(
            call_outcome=call_outcome
        ).first()
    )
    if existing is not None:
        return existing, False

    follow_up_type = TRIGGER_OUTCOMES.get(call_outcome.detected_outcome)
    if follow_up_type is None:
        raise PostCallFollowUpStateError(
            f"outcome '{call_outcome.detected_outcome}' is not a "
            "follow-up trigger"
        )

    phone_last4 = "????"
    if call_outcome.lead_id:
        lead = Lead.objects.filter(pk=call_outcome.lead_id).first()
        if lead is not None:
            phone_last4 = _mask_last4(lead.phone)

    metadata: dict[str, Any] = {}
    # Flag if the outcome record itself hasn't been approved/applied yet —
    # the Director should usually approve the outcome record first so the
    # Lead.status is in sync before sending the WhatsApp follow-up.
    if (
        call_outcome.review_status
        != CallOutcomeRecord.ReviewStatus.APPLIED.value
    ):
        metadata["outcome_not_yet_applied"] = True
        metadata["outcome_review_status"] = call_outcome.review_status

    entry = PostCallFollowUpQueue.objects.create(
        call_outcome=call_outcome,
        lead_id=(call_outcome.lead_id or "")[:32],
        lead_phone_last4=phone_last4[:4],
        follow_up_type=follow_up_type,
        status=PostCallFollowUpQueue.Status.PENDING.value,
        metadata=metadata,
    )
    write_event(
        kind=AUDIT_QUEUED,
        text=(
            f"Phase 12C queued follow-up for outcome "
            f"{call_outcome.pk} (type={follow_up_type})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "12C",
            "follow_up_id": entry.pk,
            "outcome_record_id": call_outcome.pk,
            "follow_up_type": follow_up_type,
            "lead_id": entry.lead_id,
            "phone_last4": entry.lead_phone_last4,
            "outcome_not_yet_applied": bool(
                metadata.get("outcome_not_yet_applied")
            ),
        },
    )
    return entry, True


def bulk_identify_and_queue(
    hours: int = 26, sandbox: bool = False
) -> dict[str, Any]:
    """Drives identify + create across the window."""
    summary = {
        "total_found": 0,
        "queued": 0,
        "already_existed": 0,
        "errors": 0,
        "sandbox": bool(sandbox),
    }
    candidates = list(identify_follow_up_candidates(hours=hours))
    summary["total_found"] = len(candidates)
    for outcome in candidates:
        try:
            entry, created = create_follow_up_entry(
                call_outcome=outcome, sandbox=sandbox
            )
        except Exception as exc:  # noqa: BLE001 - one bad row mustn't kill the sweep
            summary["errors"] += 1
            logger.warning(
                "phase12c: queue create failed for outcome %s: %s",
                outcome.pk,
                exc,
            )
            continue
        if created:
            summary["queued"] += 1
        else:
            summary["already_existed"] += 1
    return summary


# ---------------------------------------------------------------------------
# Phase 7E-Live-B gate preparation bridge
# ---------------------------------------------------------------------------


def _lookup_customer(lead: Lead | None) -> Customer | None:
    if lead is None:
        return None
    phone = (lead.phone or "").strip()
    if not phone:
        return None
    customer = Customer.objects.filter(phone=phone).first()
    if customer is not None:
        return customer
    last4 = phone[-4:]
    if last4:
        return Customer.objects.filter(phone__endswith=last4).first()
    return None


def prepare_gate_for_follow_up(
    *,
    follow_up_id: int,
    operator_name: str,
    sandbox: bool = False,
) -> dict[str, Any]:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise PostCallFollowUpStateError("operator_name is required")
    entry = PostCallFollowUpQueue.objects.filter(pk=follow_up_id).first()
    if entry is None:
        raise PostCallFollowUpStateError(
            f"PostCallFollowUpQueue {follow_up_id} not found"
        )
    if entry.status not in {
        PostCallFollowUpQueue.Status.PENDING.value,
        PostCallFollowUpQueue.Status.NEEDS_CUSTOMER_SETUP.value,
    }:
        raise PostCallFollowUpStateError(
            f"follow-up {entry.pk} is in status '{entry.status}'; "
            "can only prepare from pending or needs_customer_setup"
        )

    lead = (
        Lead.objects.filter(pk=entry.lead_id).first()
        if entry.lead_id
        else None
    )
    customer = _lookup_customer(lead)

    if sandbox:
        entry.status = PostCallFollowUpQueue.Status.SANDBOX_SKIPPED.value
        meta = dict(entry.metadata or {})
        meta["sandbox_attempt_at"] = timezone.now().isoformat()
        entry.metadata = meta
        entry.save(update_fields=["status", "metadata", "updated_at"])
        write_event(
            kind=AUDIT_SANDBOX_SKIPPED,
            text=(
                f"Phase 12C sandbox skip: would have prepared gate for "
                f"follow-up {entry.pk}."
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phase": "12C",
                "follow_up_id": entry.pk,
                "follow_up_type": entry.follow_up_type,
                "reason": "sandbox_mode",
            },
        )
        return {
            "ok": False,
            "follow_up_id": entry.pk,
            "status": entry.status,
            "reason": "sandbox_mode",
            "phone_last4": entry.lead_phone_last4,
        }

    if customer is None:
        entry.status = (
            PostCallFollowUpQueue.Status.NEEDS_CUSTOMER_SETUP.value
        )
        entry.customer_found = False
        meta = dict(entry.metadata or {})
        meta["error"] = "no_customer_for_phone"
        meta["phone_last4"] = entry.lead_phone_last4
        meta["gate_attempt_at"] = timezone.now().isoformat()
        entry.metadata = meta
        entry.save(
            update_fields=[
                "status",
                "customer_found",
                "metadata",
                "updated_at",
            ]
        )
        write_event(
            kind=AUDIT_NEEDS_CUSTOMER_SETUP,
            text=(
                f"Phase 12C follow-up {entry.pk} needs Customer row for "
                f"phone ***{entry.lead_phone_last4}."
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "12C",
                "follow_up_id": entry.pk,
                "lead_id": entry.lead_id,
                "phone_last4": entry.lead_phone_last4,
                "reason": "no_customer_for_phone",
            },
        )
        return {
            "ok": False,
            "follow_up_id": entry.pk,
            "status": entry.status,
            "reason": "needs_customer_setup",
            "phone_last4": entry.lead_phone_last4,
        }

    template_name = _FOLLOW_UP_TEMPLATE[entry.follow_up_type]
    template_params = {
        "customer_name": customer.name,
        "context": _CONTEXT_TEXT[entry.follow_up_type],
    }

    # Lazy import so tests that patch the symbol at this path resolve
    # cleanly. Phase 7E-Live-B `prepare_gate` writes a draft-status row;
    # it NEVER triggers a live send.
    try:
        from apps.whatsapp.phase7e_live_b_real_customer_send import (
            prepare_gate as phase7e_prepare_gate,
        )

        result = phase7e_prepare_gate(
            target_phone=customer.phone,
            target_customer_name=customer.name,
            template_name=template_name,
            template_params=template_params,
            operator_name=operator_name,
        )
    except Exception as exc:  # noqa: BLE001 - non-fatal
        entry.status = (
            PostCallFollowUpQueue.Status.GATE_PREP_FAILED.value
        )
        meta = dict(entry.metadata or {})
        meta["error"] = str(exc)[:240]
        meta["gate_attempt_at"] = timezone.now().isoformat()
        entry.metadata = meta
        entry.save(update_fields=["status", "metadata", "updated_at"])
        write_event(
            kind=AUDIT_GATE_PREP_FAILED,
            text=(
                f"Phase 12C gate prep failed for follow-up {entry.pk}: "
                f"{exc}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "12C",
                "follow_up_id": entry.pk,
                "follow_up_type": entry.follow_up_type,
                "error_excerpt": str(exc)[:240],
            },
        )
        return {
            "ok": False,
            "follow_up_id": entry.pk,
            "status": entry.status,
            "reason": "gate_prep_failed",
            "error_excerpt": str(exc)[:240],
        }

    if not result.get("ok"):
        entry.status = (
            PostCallFollowUpQueue.Status.GATE_PREP_FAILED.value
        )
        meta = dict(entry.metadata or {})
        meta["error"] = "phase7e_live_b_prepare_returned_not_ok"
        meta["blockers"] = list(result.get("blockers") or [])
        meta["gate_attempt_at"] = timezone.now().isoformat()
        entry.metadata = meta
        entry.save(update_fields=["status", "metadata", "updated_at"])
        write_event(
            kind=AUDIT_GATE_PREP_FAILED,
            text=(
                f"Phase 12C gate prep returned not-ok for follow-up "
                f"{entry.pk}: {result.get('blockers')}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "12C",
                "follow_up_id": entry.pk,
                "follow_up_type": entry.follow_up_type,
                "blockers": list(result.get("blockers") or []),
            },
        )
        return {
            "ok": False,
            "follow_up_id": entry.pk,
            "status": entry.status,
            "reason": "gate_prep_blockers",
            "blockers": list(result.get("blockers") or []),
        }

    gate_id = int(result.get("gateId") or 0)
    entry.status = PostCallFollowUpQueue.Status.GATE_PREPARED.value
    entry.phase7e_gate_id = gate_id
    entry.customer_found = True
    meta = dict(entry.metadata or {})
    meta["template_name"] = template_name
    meta["gate_prepared_at"] = timezone.now().isoformat()
    entry.metadata = meta
    entry.save(
        update_fields=[
            "status",
            "phase7e_gate_id",
            "customer_found",
            "metadata",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_GATE_PREPARED,
        text=(
            f"Phase 12C prepared Phase 7E-Live-B gate {gate_id} for "
            f"follow-up {entry.pk} ({entry.follow_up_type})."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "phase": "12C",
            "follow_up_id": entry.pk,
            "follow_up_type": entry.follow_up_type,
            "phase7e_gate_id": gate_id,
            "template_name": template_name,
            "phone_last4": entry.lead_phone_last4,
        },
    )
    return {
        "ok": True,
        "follow_up_id": entry.pk,
        "status": entry.status,
        "phase7e_gate_id": gate_id,
        "customer_found": True,
        "template_name": template_name,
    }


def mark_dispatched(
    *,
    follow_up_id: int,
    operator_name: str,
    note: str = "",
) -> PostCallFollowUpQueue:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise PostCallFollowUpStateError("operator_name is required")
    entry = PostCallFollowUpQueue.objects.filter(pk=follow_up_id).first()
    if entry is None:
        raise PostCallFollowUpStateError(
            f"PostCallFollowUpQueue {follow_up_id} not found"
        )
    if entry.status != PostCallFollowUpQueue.Status.GATE_PREPARED.value:
        raise PostCallFollowUpStateError(
            f"follow-up {entry.pk} is in status '{entry.status}'; "
            "can only mark dispatched from 'gate_prepared'"
        )
    entry.status = PostCallFollowUpQueue.Status.DISPATCHED.value
    entry.dispatched_at = timezone.now()
    entry.dispatched_by = operator_name[:120]
    if note:
        entry.operator_note = note
    entry.save(
        update_fields=[
            "status",
            "dispatched_at",
            "dispatched_by",
            "operator_note",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_DISPATCHED,
        text=(
            f"Phase 12C follow-up {entry.pk} marked dispatched by "
            f"{operator_name}."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "phase": "12C",
            "follow_up_id": entry.pk,
            "follow_up_type": entry.follow_up_type,
            "phase7e_gate_id": entry.phase7e_gate_id,
            "dispatched_by": operator_name,
            "note_excerpt": (note or "")[:240],
        },
    )
    return entry


def skip_follow_up(
    *,
    follow_up_id: int,
    operator_name: str,
    reason: str = "",
) -> PostCallFollowUpQueue:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise PostCallFollowUpStateError("operator_name is required")
    entry = PostCallFollowUpQueue.objects.filter(pk=follow_up_id).first()
    if entry is None:
        raise PostCallFollowUpStateError(
            f"PostCallFollowUpQueue {follow_up_id} not found"
        )
    if entry.status in {
        PostCallFollowUpQueue.Status.DISPATCHED.value,
        PostCallFollowUpQueue.Status.SKIPPED.value,
    }:
        raise PostCallFollowUpStateError(
            f"follow-up {entry.pk} is in status '{entry.status}'; "
            "cannot skip"
        )
    entry.status = PostCallFollowUpQueue.Status.SKIPPED.value
    if reason:
        meta = dict(entry.metadata or {})
        meta["skip_reason"] = reason[:240]
        entry.metadata = meta
    entry.dispatched_by = operator_name[:120]
    entry.save(
        update_fields=[
            "status",
            "metadata",
            "dispatched_by",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_SKIPPED,
        text=(
            f"Phase 12C follow-up {entry.pk} skipped by "
            f"{operator_name} (reason={reason!r})."
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": "12C",
            "follow_up_id": entry.pk,
            "follow_up_type": entry.follow_up_type,
            "skipped_by": operator_name,
            "reason_excerpt": (reason or "")[:240],
        },
    )
    return entry


def get_followups_summary() -> dict[str, Any]:
    qs = PostCallFollowUpQueue.objects.all()
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for row in qs.values_list("status", "follow_up_type"):
        s, t = row
        by_status[s] = by_status.get(s, 0) + 1
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "total": qs.count(),
        "by_status": by_status,
        "by_follow_up_type": by_type,
    }


__all__ = (
    "TRIGGER_OUTCOMES",
    "PostCallFollowUpStateError",
    "identify_follow_up_candidates",
    "create_follow_up_entry",
    "bulk_identify_and_queue",
    "prepare_gate_for_follow_up",
    "mark_dispatched",
    "skip_follow_up",
    "get_followups_summary",
)
