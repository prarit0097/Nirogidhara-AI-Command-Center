"""Phase 5A — WhatsApp consent helpers.

Locked rules:

- ``crm.Customer.consent_whatsapp`` is the **live gate**. The
  :class:`apps.whatsapp.WhatsAppConsent` row carries lifecycle history.
- Defaults: existing rows default to ``False`` for the live gate; the
  ``WhatsAppConsent`` row defaults to ``unknown`` when first created.
- Opt-out keywords (case-insensitive substring match): ``STOP``,
  ``UNSUBSCRIBE``, ``BAND KARO``, ``BAND``, ``CANCEL``.
- On opt-out: flip ``Customer.consent_whatsapp=False`` AND set
  ``WhatsAppConsent.consent_state=opted_out``. Write a
  ``whatsapp.opt_out.received`` audit. Stop scheduled outbounds for the
  customer.
- Re-opt-in: never automatic. Operator / Admin must explicitly grant via
  the patch endpoint.
"""
from __future__ import annotations

from typing import Iterable

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer

from .models import WhatsAppConsent, WhatsAppMessage


OPT_OUT_KEYWORDS: tuple[str, ...] = (
    "STOP",
    "UNSUBSCRIBE",
    "BAND KARO",
    "BAND",
    "CANCEL",
)


def has_whatsapp_consent(customer: Customer) -> bool:
    """Return True only when both gates agree the customer has consented."""
    if not getattr(customer, "consent_whatsapp", False):
        return False
    consent = WhatsAppConsent.objects.filter(customer=customer).first()
    if consent is None:
        # No row yet but the boolean is True — treat as granted but make sure
        # the history row exists for future writes.
        WhatsAppConsent.objects.update_or_create(
            customer=customer,
            defaults={
                "consent_state": WhatsAppConsent.State.GRANTED,
                "granted_at": timezone.now(),
                "source": "implicit_legacy",
            },
        )
        return True
    return consent.consent_state == WhatsAppConsent.State.GRANTED


def detect_opt_out_keyword(message_body: str) -> str | None:
    """Return the matched keyword (UPPER) or None.

    Substring match is case-insensitive but the returned keyword preserves
    the canonical casing from :data:`OPT_OUT_KEYWORDS` so audit payloads
    are stable.
    """
    if not message_body:
        return None
    needle = message_body.upper()
    for keyword in OPT_OUT_KEYWORDS:
        if keyword in needle:
            return keyword
    return None


@transaction.atomic
def grant_whatsapp_consent(
    customer: Customer,
    *,
    source: str = "operator",
    actor: str = "",
    note: str = "",
) -> WhatsAppConsent:
    """Set the customer's consent to ``granted`` + flip the live gate."""
    customer.consent_whatsapp = True
    customer.save(update_fields=["consent_whatsapp"])
    consent, _created = WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "revoked_at": None,
            "opt_out_keyword": "",
            "source": source,
        },
    )
    write_event(
        kind="whatsapp.consent.updated",
        text=f"WhatsApp consent granted for {customer.id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "customer_id": customer.id,
            "state": "granted",
            "source": source,
            "actor": actor,
            "note": note,
        },
    )
    return consent


@transaction.atomic
def revoke_whatsapp_consent(
    customer: Customer,
    *,
    source: str = "operator",
    actor: str = "",
    note: str = "",
) -> WhatsAppConsent:
    """Mark the customer as ``revoked`` and flip the live gate off."""
    customer.consent_whatsapp = False
    customer.save(update_fields=["consent_whatsapp"])
    consent, _created = WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.REVOKED,
            "revoked_at": timezone.now(),
            "source": source,
        },
    )
    write_event(
        kind="whatsapp.consent.updated",
        text=f"WhatsApp consent revoked for {customer.id}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "customer_id": customer.id,
            "state": "revoked",
            "source": source,
            "actor": actor,
            "note": note,
        },
    )
    return consent


@transaction.atomic
def record_opt_out(
    customer: Customer,
    *,
    keyword: str,
    inbound_message_id: str = "",
) -> WhatsAppConsent:
    """Apply opt-out semantics on inbound STOP-style messages."""
    customer.consent_whatsapp = False
    customer.save(update_fields=["consent_whatsapp"])
    consent, _created = WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.OPTED_OUT,
            "revoked_at": timezone.now(),
            "opt_out_keyword": (keyword or "").upper()[:24],
            "source": "inbound_message",
        },
    )

    # Cancel queued outbounds (no provider call yet — safe to drop).
    cancelled_count = (
        WhatsAppMessage.objects.filter(
            customer=customer,
            direction=WhatsAppMessage.Direction.OUTBOUND,
            status=WhatsAppMessage.Status.QUEUED,
        ).update(
            status=WhatsAppMessage.Status.FAILED,
            error_message=f"opted out via keyword '{keyword}'",
            error_code="opted_out",
            updated_at=timezone.now(),
        )
    )

    write_event(
        kind="whatsapp.opt_out.received",
        text=(
            f"Customer {customer.id} opted out via '{keyword}' — "
            f"{cancelled_count} queued sends cancelled"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "customer_id": customer.id,
            "keyword": (keyword or "").upper(),
            "inbound_message_id": inbound_message_id,
            "queued_cancelled": cancelled_count,
        },
    )
    return consent


def consent_state_for(customer: Customer) -> str:
    """Return the current state string (creates ``unknown`` row if missing)."""
    consent, _created = WhatsAppConsent.objects.get_or_create(
        customer=customer,
        defaults={"consent_state": WhatsAppConsent.State.UNKNOWN},
    )
    return consent.consent_state


def list_opt_out_keywords() -> Iterable[str]:
    return OPT_OUT_KEYWORDS


__all__ = (
    "OPT_OUT_KEYWORDS",
    "consent_state_for",
    "detect_opt_out_keyword",
    "grant_whatsapp_consent",
    "has_whatsapp_consent",
    "list_opt_out_keywords",
    "record_opt_out",
    "revoke_whatsapp_consent",
)
