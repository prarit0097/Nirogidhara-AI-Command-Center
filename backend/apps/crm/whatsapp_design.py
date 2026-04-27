"""Phase 3E — WhatsApp channel design scaffold.

LOCKED DECISION (Master Blueprint §24 #16, Phase 3E business config):
WhatsApp will serve as **both a sales and a support channel** for
Nirogidhara. The live integration (WhatsApp Business Cloud API) is NOT
implemented in this phase — only the design contract, audit kinds, and
policy reminders. Phase 4+ will wire the actual sender / receiver.

This module is a *scaffold*: when the live adapter lands it should
import the constants below so the messaging boundaries stay aligned with
the policy that was approved here.

Hard rules baked into the scaffold:

1. **Consent required** — every outbound message must hit a customer
   that has consented to WhatsApp contact. The consent flag lives on
   ``apps.crm.Customer.consent.whatsapp`` already.

2. **No medical claims outside the Approved Claim Vault** — Master
   Blueprint §26 #4. Templates that reference medicine benefits must
   pull copy from ``apps.compliance.Claim``; ad-hoc strings are forbidden.

3. **Human escalation for refund / legal / side-effect threats** —
   the message handler must surface the inbound message to a human and
   never auto-reply with a medical statement. See approval matrix
   ``whatsapp.support_handover_to_human``.

4. **Every send writes an AuditEvent** — kinds:
   - ``whatsapp.message_queued``        : outbound queued
   - ``whatsapp.broadcast.requested``   : broadcast / campaign needs admin
   - ``whatsapp.escalation.requested``  : inbound flagged for human

5. **Sender identity** — once the live adapter ships, every outbound
   payload must carry ``sender = "Nirogidhara"`` and the live business
   account id, not a per-agent account.

The frontend never holds business logic for WhatsApp — when the page
arrives in Phase 4+, it will call ``api.sendWhatsAppTemplate(...)``
which will route through the Django service.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class WhatsAppMessageType:
    """One supported WhatsApp message archetype."""

    code: str
    label: str
    requires_consent: bool
    needs_admin_approval: bool
    notes: str = ""


# The full set of message archetypes this channel will support. The live
# adapter (Phase 4+) consumes this list to validate a request before
# accepting it.
SUPPORTED_MESSAGE_TYPES: tuple[WhatsAppMessageType, ...] = (
    WhatsAppMessageType(
        code="follow_up",
        label="Sales follow-up",
        requires_consent=True,
        needs_admin_approval=False,
    ),
    WhatsAppMessageType(
        code="payment_reminder",
        label="Payment reminder",
        requires_consent=True,
        needs_admin_approval=False,
    ),
    WhatsAppMessageType(
        code="confirmation_reminder",
        label="Order confirmation reminder",
        requires_consent=True,
        needs_admin_approval=False,
    ),
    WhatsAppMessageType(
        code="delivery_reminder",
        label="Delivery-day reminder",
        requires_consent=True,
        needs_admin_approval=False,
    ),
    WhatsAppMessageType(
        code="rto_rescue",
        label="RTO rescue message",
        requires_consent=True,
        needs_admin_approval=False,
    ),
    WhatsAppMessageType(
        code="usage_explanation",
        label="Post-delivery usage explanation",
        requires_consent=True,
        needs_admin_approval=False,
        notes=(
            "Copy MUST come from the Approved Claim Vault. "
            "No free-style medical text."
        ),
    ),
    WhatsAppMessageType(
        code="support_complaint",
        label="Support / complaint reply",
        requires_consent=True,
        needs_admin_approval=False,
        notes=(
            "Auto-reply only with non-medical templates. Medical / legal / "
            "refund threats must escalate to human."
        ),
    ),
    WhatsAppMessageType(
        code="reorder_reminder",
        label="Reorder reminder",
        requires_consent=True,
        needs_admin_approval=False,
    ),
    WhatsAppMessageType(
        code="broadcast_campaign",
        label="Broadcast / sales campaign",
        requires_consent=True,
        needs_admin_approval=True,
        notes="Admin/director approval per approval matrix.",
    ),
)


WHATSAPP_AUDIT_KINDS: tuple[str, ...] = (
    "whatsapp.message_queued",
    "whatsapp.broadcast.requested",
    "whatsapp.escalation.requested",
)


def list_supported_types() -> Iterable[WhatsAppMessageType]:
    """Convenience iterator for serialization."""
    return iter(SUPPORTED_MESSAGE_TYPES)
