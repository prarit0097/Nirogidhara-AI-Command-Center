"""Phase 3E — Approval Matrix policy (Master Blueprint §12 / §24 #13 / §26 #11).

Static policy table mapping every business action to:
- ``approver``: who can authorize the action.
- ``mode``: how the authorization works at runtime.

This is the source the eventual Phase 4C approval-matrix middleware will
read before it lets an AgentRun suggestion turn into a business write.
Phase 3E ships only the table + a read endpoint; enforcement is Phase 4C.

Modes:
- ``auto``                   — runtime can execute without human approval.
- ``auto_with_consent``      — runtime executes only when the customer
                               consent flag is True for the relevant channel.
- ``approval_required``      — needs an approver in
                               :data:`APPROVER_ROLES` to confirm.
- ``director_override``      — needs an explicit director sign-off.
- ``human_escalation``       — must hand off to a human; no AI execution.

Approver tokens recognised in the table:
- ``auto``        — no approval needed.
- ``ceo_ai``      — CEO AI agent (Phase 4C).
- ``admin``       — admin user role.
- ``director``    — Prarit Sidana (final authority).
- ``compliance``  — compliance reviewer.
- ``human``       — any human; usually means escalation desk.

The table is intentionally a frozen tuple of dicts so it cannot be
mutated at runtime.
"""
from __future__ import annotations

from typing import Any, Mapping


# Role tokens used in the table. Human-only escalations use "human".
APPROVER_ROLES: frozenset[str] = frozenset(
    {"auto", "ceo_ai", "admin", "director", "compliance", "human"}
)


APPROVAL_MATRIX: tuple[Mapping[str, Any], ...] = (
    # Lead lifecycle
    {
        "action": "lead.create",
        "approver": "auto",
        "mode": "auto",
        "description": "Create / import a lead from form, ad, or CSV.",
    },
    {
        "action": "lead.call.trigger",
        "approver": "auto",
        "mode": "auto",
        "description": "Trigger an AI calling session for an existing lead.",
    },
    # Payments
    {
        "action": "payment.link.advance_499",
        "approver": "auto",
        "mode": "auto",
        "description": "Generate the standard ₹499 advance payment link.",
    },
    {
        "action": "payment.link.custom_amount",
        "approver": "admin",
        "mode": "approval_required",
        "description": (
            "Generate a payment link for any amount other than the standard "
            "₹499 advance."
        ),
    },
    {
        "action": "payment.refund",
        "approver": "director",
        "mode": "human_escalation",
        "description": "Issue a refund to a customer.",
    },
    # Orders
    {
        "action": "order.punch",
        "approver": "auto",
        "mode": "auto",
        "description": (
            "Punch an order once customer consent and delivery details are "
            "captured."
        ),
    },
    # Discounts (mirrors apps.orders.discounts).
    {
        "action": "discount.up_to_10",
        "approver": "auto",
        "mode": "auto",
        "description": "Apply a discount of 10% or less.",
    },
    {
        "action": "discount.11_to_20",
        "approver": "ceo_ai",
        "mode": "approval_required",
        "description": "Apply a discount between 11% and 20%.",
    },
    {
        "action": "discount.above_20",
        "approver": "director",
        "mode": "director_override",
        "description": (
            "Apply a discount above 20%. Director override required; no "
            "automated path."
        ),
    },
    # Shipments / RTO
    {
        "action": "shipment.dispatch_after_confirmed",
        "approver": "auto",
        "mode": "auto",
        "description": "Push a confirmed order to Delhivery for dispatch.",
    },
    {
        "action": "rto.rescue.call_or_message",
        "approver": "auto",
        "mode": "auto",
        "description": (
            "Trigger an RTO rescue call / WhatsApp message on a high-risk "
            "shipment."
        ),
    },
    # WhatsApp (Phase 3E design — no live integration yet)
    {
        "action": "whatsapp.payment_reminder",
        "approver": "auto",
        "mode": "auto_with_consent",
        "description": (
            "Send a WhatsApp payment reminder. Requires customer consent."
        ),
    },
    {
        "action": "whatsapp.broadcast_or_campaign",
        "approver": "admin",
        "mode": "approval_required",
        "description": "Send a broadcast / sales campaign over WhatsApp.",
    },
    {
        "action": "whatsapp.support_handover_to_human",
        "approver": "human",
        "mode": "human_escalation",
        "description": (
            "Side-effect / refund / legal threat over WhatsApp → "
            "immediate human escalation."
        ),
    },
    # Catalog / claim governance
    {
        "action": "catalog.product.add_or_update",
        "approver": "admin",
        "mode": "approval_required",
        "description": "Add or update a product / SKU in the catalog.",
    },
    {
        "action": "claim.product_claim_add",
        "approver": "compliance",
        "mode": "approval_required",
        "description": (
            "Add a new product claim to the Claim Vault (compliance review "
            "required; doctor approval optional in Phase 3E but mandatory "
            "before live AI use)."
        ),
    },
    {
        "action": "ad.creative_or_claim_change",
        "approver": "director",
        "mode": "director_override",
        "description": (
            "Change ad creative copy / claims. CEO AI suggests; director "
            "approves."
        ),
    },
    {
        "action": "ad.budget_change",
        "approver": "director",
        "mode": "director_override",
        "description": "Increase / decrease a Meta or Google ad budget.",
    },
    # Governance / safety
    {
        "action": "ai.prompt_version.activate",
        "approver": "admin",
        "mode": "approval_required",
        "description": "Activate or rollback an AI prompt version.",
    },
    {
        "action": "ai.sandbox.disable",
        "approver": "director",
        "mode": "director_override",
        "description": (
            "Disable AI sandbox mode (allow CEO success runs to refresh "
            "live CeoBriefing)."
        ),
    },
    {
        "action": "ai.production.live_mode_switch",
        "approver": "director",
        "mode": "director_override",
        "description": (
            "Flip any AI integration from mock/test to live mode in "
            "production."
        ),
    },
    # Compliance escalations
    {
        "action": "complaint.medical_emergency",
        "approver": "human",
        "mode": "human_escalation",
        "description": "Customer reports a medical emergency.",
    },
    {
        "action": "complaint.side_effect",
        "approver": "human",
        "mode": "human_escalation",
        "description": "Customer reports a side effect.",
    },
    {
        "action": "complaint.legal_threat",
        "approver": "human",
        "mode": "human_escalation",
        "description": "Customer issues a legal threat.",
    },
)


def list_approval_matrix() -> tuple[Mapping[str, Any], ...]:
    """Return the (read-only) approval matrix tuple for serialization."""
    return APPROVAL_MATRIX


def lookup_action(action: str) -> Mapping[str, Any] | None:
    """Find a matrix row by ``action`` key. ``None`` if not found."""
    needle = (action or "").strip()
    for row in APPROVAL_MATRIX:
        if row["action"] == needle:
            return row
    return None
