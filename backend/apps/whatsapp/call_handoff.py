"""Phase 5D — direct WhatsApp → Vapi call handoff.

Bridges a :class:`WhatsAppConversation` into the existing Vapi call
service path so a customer who explicitly requests a call (or whose
chat hits a low-confidence / safety boundary) lands on the AI calling
agent without an operator click.

Hard rules:

- Always go through :func:`apps.calls.services.trigger_call_for_lead`.
  Never call the Vapi adapter directly.
- Customer must have a phone — fail closed with a ``WhatsAppHandoffToCall``
  row in ``status=skipped`` if missing.
- A :class:`WhatsAppHandoffToCall` row is written for every attempt
  (success, failure, skip). The unique constraint on
  ``(conversation, inbound_message, reason)`` prevents double-trigger.
- :class:`apps.crm.Lead` is required by the Vapi service; we fall back
  to creating a synthetic Lead row tied to the customer's phone when
  the customer has none yet — Phase 5D is allowed to do that because
  the business goal is "call the customer right now".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead

from .models import (
    WhatsAppConversation,
    WhatsAppHandoffToCall,
    WhatsAppMessage,
)


logger = logging.getLogger(__name__)


SAFE_CALL_REASONS: frozenset[str] = frozenset(
    {
        "customer_requested_call",
        "low_confidence_repeated",
        "address_payment_confusion",
        "high_value_sales_intent",
        "operator_handoff",
        "ai_handoff_requested",
    }
)

# Reasons that must NOT auto-dial a generic sales agent. They still
# create a handoff row, but with status="skipped" + a flag so a doctor
# / admin can pick the call up manually.
NON_AUTO_REASONS: frozenset[str] = frozenset(
    {
        "medical_emergency",
        "side_effect_complaint",
        "legal_threat",
        "refund_threat",
    }
)


class CallHandoffError(RuntimeError):
    """Raised when the handoff cannot be processed at all."""

    def __init__(self, message: str, *, code: str = "blocked") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CallHandoffResult:
    """Returned to callers (orchestrator + operator endpoint)."""

    handoff_id: int
    status: str
    call_id: str
    provider_call_id: str
    reason: str
    skipped: bool
    error_message: str = ""


@transaction.atomic
def trigger_vapi_call_from_whatsapp(
    *,
    conversation: WhatsAppConversation,
    reason: str,
    triggered_by=None,
    inbound_message: WhatsAppMessage | None = None,
    trigger_source: str = WhatsAppHandoffToCall.TriggerSource.AI,
    metadata: dict[str, Any] | None = None,
) -> CallHandoffResult:
    """Create a handoff row and (optionally) dial the customer via Vapi.

    Arguments:
        conversation: the WhatsApp thread we are escalating.
        reason: a short reason code (must be in ``SAFE_CALL_REASONS``
            or ``NON_AUTO_REASONS`` — otherwise the call is skipped).
        triggered_by: user / agent token; written to ``requested_by``
            when the value is a real :class:`User`.
        inbound_message: the most recent inbound message that justified
            the handoff. Used for idempotency on the unique constraint.
        trigger_source: ``ai`` / ``operator`` / ``lifecycle`` / ``system``.
        metadata: optional extra metadata stored on the handoff row.
    """
    customer = conversation.customer
    base_metadata = dict(metadata or {})
    base_metadata.setdefault("conversation_id", conversation.id)

    # Idempotency: same (conversation, inbound_message, reason) should
    # never trigger twice. Look the existing row up first.
    existing = WhatsAppHandoffToCall.objects.filter(
        conversation=conversation,
        inbound_message=inbound_message,
        reason=reason,
    ).first()
    if existing is not None:
        write_event(
            kind="whatsapp.handoff.call_skipped_duplicate",
            text=(
                f"Handoff duplicate · conversation={conversation.id} · {reason}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": conversation.id,
                "handoff_id": existing.pk,
                "reason": reason,
                "existing_status": existing.status,
            },
        )
        return CallHandoffResult(
            handoff_id=existing.pk,
            status=existing.status,
            call_id=existing.call_id or "",
            provider_call_id=existing.provider_call_id,
            reason=reason,
            skipped=True,
            error_message="duplicate_handoff",
        )

    handoff = WhatsAppHandoffToCall.objects.create(
        conversation=conversation,
        customer=customer,
        inbound_message=inbound_message,
        reason=reason,
        trigger_source=trigger_source,
        status=WhatsAppHandoffToCall.Status.PENDING,
        requested_by=triggered_by if hasattr(triggered_by, "pk") else None,
        metadata=base_metadata,
    )

    write_event(
        kind="whatsapp.handoff.call_requested",
        text=(
            f"WhatsApp call handoff requested · conversation={conversation.id} · "
            f"reason={reason}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "conversation_id": conversation.id,
            "customer_id": customer.id,
            "reason": reason,
            "trigger_source": trigger_source,
            "handoff_id": handoff.pk,
            "by": getattr(triggered_by, "username", "") or "",
        },
    )

    if not customer.phone:
        return _record_handoff_outcome(
            handoff,
            status=WhatsAppHandoffToCall.Status.SKIPPED,
            error_message="missing_phone",
            tone=AuditEvent.Tone.WARNING,
            audit_kind="whatsapp.handoff.call_failed",
            audit_text=(
                f"Handoff skipped · missing phone · conversation={conversation.id}"
            ),
        )

    if reason in NON_AUTO_REASONS:
        # Safety reasons — never auto-dial a sales agent; flag for human.
        _flag_conversation_metadata(
            conversation,
            handoff_id=handoff.pk,
            reason=reason,
            handoff_type="manual_human",
        )
        return _record_handoff_outcome(
            handoff,
            status=WhatsAppHandoffToCall.Status.SKIPPED,
            error_message="non_auto_reason",
            tone=AuditEvent.Tone.WARNING,
            audit_kind="whatsapp.handoff.call_skipped",
            audit_text=(
                f"Handoff skipped · {reason} requires human/doctor · "
                f"conversation={conversation.id}"
            ),
        )

    if reason not in SAFE_CALL_REASONS:
        # Unknown reason — be conservative: record + skip.
        return _record_handoff_outcome(
            handoff,
            status=WhatsAppHandoffToCall.Status.SKIPPED,
            error_message="unknown_reason",
            tone=AuditEvent.Tone.WARNING,
            audit_kind="whatsapp.handoff.call_skipped",
            audit_text=(
                f"Handoff skipped · unknown reason '{reason}' · "
                f"conversation={conversation.id}"
            ),
        )

    # Resolve / build the Lead row the Vapi service requires.
    lead = _ensure_lead_for_customer(customer)

    try:
        from apps.calls.services import trigger_call_for_lead

        call = trigger_call_for_lead(
            lead=lead,
            by_user=triggered_by,
            purpose="whatsapp_handoff",
        )
    except Exception as exc:  # noqa: BLE001 - any adapter failure
        logger.warning(
            "WhatsApp call handoff trigger failed for conversation %s: %s",
            conversation.id,
            exc,
        )
        return _record_handoff_outcome(
            handoff,
            status=WhatsAppHandoffToCall.Status.FAILED,
            error_message=f"vapi_error: {exc}"[:1000],
            tone=AuditEvent.Tone.DANGER,
            audit_kind="whatsapp.handoff.call_failed",
            audit_text=(
                f"Handoff failed · Vapi error · conversation={conversation.id}"
            ),
        )

    handoff.call = call
    handoff.provider_call_id = call.provider_call_id or ""
    handoff.status = WhatsAppHandoffToCall.Status.TRIGGERED
    handoff.triggered_at = timezone.now()
    handoff.save(
        update_fields=[
            "call",
            "provider_call_id",
            "status",
            "triggered_at",
            "updated_at",
        ]
    )

    _flag_conversation_metadata(
        conversation,
        handoff_id=handoff.pk,
        reason=reason,
        handoff_type="vapi_call",
        call_id=call.id,
        provider_call_id=call.provider_call_id or "",
    )

    write_event(
        kind="whatsapp.handoff.call_triggered",
        text=(
            f"WhatsApp call triggered · conversation={conversation.id} · "
            f"call_id={call.id}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": conversation.id,
            "customer_id": customer.id,
            "reason": reason,
            "call_id": call.id,
            "provider_call_id": call.provider_call_id or "",
            "handoff_id": handoff.pk,
        },
    )
    return CallHandoffResult(
        handoff_id=handoff.pk,
        status=handoff.status,
        call_id=call.id,
        provider_call_id=call.provider_call_id or "",
        reason=reason,
        skipped=False,
    )


def _record_handoff_outcome(
    handoff: WhatsAppHandoffToCall,
    *,
    status: str,
    error_message: str,
    tone: str,
    audit_kind: str,
    audit_text: str,
) -> CallHandoffResult:
    handoff.status = status
    handoff.error_message = (error_message or "")[:1000]
    handoff.save(update_fields=["status", "error_message", "updated_at"])
    write_event(
        kind=audit_kind,
        text=audit_text,
        tone=tone,
        payload={
            "conversation_id": handoff.conversation_id,
            "handoff_id": handoff.pk,
            "reason": handoff.reason,
            "status": status,
            "error": error_message,
        },
    )
    return CallHandoffResult(
        handoff_id=handoff.pk,
        status=status,
        call_id=handoff.call_id or "",
        provider_call_id=handoff.provider_call_id,
        reason=handoff.reason,
        skipped=status != WhatsAppHandoffToCall.Status.TRIGGERED,
        error_message=error_message,
    )


def _flag_conversation_metadata(
    conversation: WhatsAppConversation,
    *,
    handoff_id: int,
    reason: str,
    handoff_type: str,
    call_id: str = "",
    provider_call_id: str = "",
) -> None:
    metadata = dict(conversation.metadata or {})
    ai_state = dict(metadata.get("ai") or {})
    ai_state["handoffRequired"] = True
    ai_state["handoffReason"] = reason
    ai_state["handoffType"] = handoff_type
    ai_state["lastCallHandoffId"] = handoff_id
    if call_id:
        ai_state["lastCallId"] = call_id
    if provider_call_id:
        ai_state["lastProviderCallId"] = provider_call_id
    ai_state["aiStage"] = "handoff_required"
    metadata["ai"] = ai_state
    conversation.metadata = metadata
    if conversation.status not in {
        WhatsAppConversation.Status.RESOLVED,
        WhatsAppConversation.Status.ESCALATED,
    }:
        conversation.status = WhatsAppConversation.Status.ESCALATED
        conversation.save(update_fields=["metadata", "status", "updated_at"])
    else:
        conversation.save(update_fields=["metadata", "updated_at"])


def _ensure_lead_for_customer(customer: Customer) -> Lead:
    """Resolve or create a minimal Lead the Vapi service can call against."""
    lead = (
        Lead.objects.filter(phone=customer.phone)
        .order_by("-created_at")
        .first()
    )
    if lead is not None:
        return lead
    lead_id = next_id("LD", Lead, base=80000)
    return Lead.objects.create(
        id=lead_id,
        name=customer.name or "WhatsApp customer",
        phone=customer.phone,
        state=customer.state or "",
        city=customer.city or "",
        language=customer.language or "Hinglish",
        source="WhatsApp",
        campaign="whatsapp_handoff",
        product_interest=customer.product_interest or "",
        status=Lead.Status.NEW,
        quality=Lead.Quality.WARM,
        quality_score=70,
        assignee="WhatsApp AI",
        duplicate=False,
        created_at_label="just now",
    )


__all__ = (
    "CallHandoffError",
    "CallHandoffResult",
    "NON_AUTO_REASONS",
    "SAFE_CALL_REASONS",
    "trigger_vapi_call_from_whatsapp",
)
