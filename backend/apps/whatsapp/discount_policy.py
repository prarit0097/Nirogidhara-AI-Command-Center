"""Phase 5C — WhatsApp AI Chat Sales Agent discount discipline.

Wraps the Phase 3E :func:`apps.orders.discounts.validate_discount` policy
with two extra checks the AI agent must respect:

1. **Never offer upfront.** Tracked via
   ``WhatsAppConversation.metadata['ai']['discountAskCount']``. The agent
   may only offer a discount after the customer has asked (and been
   handled with objection-handling) at least ``MIN_OBJECTION_TURNS_BEFORE_OFFER``
   times — OR the customer has explicitly refused the order (rescue
   path).
2. **50% total-discount cap.** Sums prior approved discount on the order
   plus the proposed additional pct. Anything above 50% is refused; the
   agent is expected to escalate via handoff.

Per the Phase 5A-1 addendum (sections AA + BB), this module is the
single source for AI Chat Agent discount decisions. The Phase 3E policy
remains authoritative for human / approval-matrix flows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from apps.orders.discounts import (
    DiscountValidationResult,
    validate_discount,
)


# Locked thresholds. Bumping any of these requires Prarit sign-off.
TOTAL_DISCOUNT_HARD_CAP_PCT: int = 50
MIN_OBJECTION_TURNS_BEFORE_OFFER: int = 2  # 2–3 customer pushes
PROACTIVE_RESCUE_TRIGGERS: frozenset[str] = frozenset(
    {"refused_order", "refused_confirmation", "refused_delivery"}
)


@dataclass(frozen=True)
class WhatsAppDiscountDecision:
    """Outcome of :func:`evaluate_whatsapp_discount`.

    ``allowed`` gates whether the AI may verbalise the discount in the
    next reply. ``handoff_required`` tells the orchestrator to flip the
    conversation into a manual review state instead of auto-sending.
    """

    allowed: bool
    handoff_required: bool
    reason: str
    band: str  # "auto" | "approval" | "director_override" | "blocked" | "rescue"
    proposed_pct: int
    current_total_pct: int
    final_total_pct: int
    cap_passed: bool
    base_validation: DiscountValidationResult
    notes: tuple[str, ...] = field(default_factory=tuple)


def validate_total_discount_cap(
    *,
    current_total_pct: int,
    additional_pct: int,
) -> tuple[bool, int]:
    """Return ``(passed, final_total)`` for the cumulative discount cap."""
    final_total = max(0, int(current_total_pct or 0)) + max(0, int(additional_pct or 0))
    return final_total <= TOTAL_DISCOUNT_HARD_CAP_PCT, final_total


def evaluate_whatsapp_discount(
    *,
    proposed_pct: int,
    current_total_pct: int,
    discount_ask_count: int,
    refusal_trigger: str = "",
    actor_role: str = "operations",
    approval_context: Mapping[str, Any] | None = None,
) -> WhatsAppDiscountDecision:
    """Decide whether the AI Chat Agent may surface ``proposed_pct``.

    Parameters
    ----------
    proposed_pct
        The discount the agent wants to mention (1–100).
    current_total_pct
        Sum of previously-approved discounts on the order (across all
        prior stages).
    discount_ask_count
        Number of times the customer has asked for a discount in this
        conversation. Tracked in ``WhatsAppConversation.metadata.ai``.
    refusal_trigger
        One of :data:`PROACTIVE_RESCUE_TRIGGERS` when the customer is
        refusing — this unlocks proactive offers (rescue path).
    actor_role
        The role attribution for the audit trail. Defaults to
        ``operations`` because the WhatsApp agent runs under the AI
        runtime (admin/director still ride through approval matrix).
    approval_context
        Optional override forwarded to :func:`validate_discount`.
    """
    proposed = int(proposed_pct or 0)
    notes: list[str] = []

    # Early rejection: zero or negative.
    if proposed <= 0:
        base = validate_discount(0, actor_role, approval_context)
        return WhatsAppDiscountDecision(
            allowed=False,
            handoff_required=False,
            reason="No discount proposed (≤0%).",
            band="blocked",
            proposed_pct=0,
            current_total_pct=int(current_total_pct or 0),
            final_total_pct=int(current_total_pct or 0),
            cap_passed=True,
            base_validation=base,
            notes=("no_discount_proposed",),
        )

    base = validate_discount(proposed, actor_role, approval_context)

    # Discount discipline gate: cannot offer without enough customer
    # pushes UNLESS this is a refusal-driven rescue.
    rescue = (refusal_trigger or "").strip() in PROACTIVE_RESCUE_TRIGGERS
    if not rescue and discount_ask_count < MIN_OBJECTION_TURNS_BEFORE_OFFER:
        notes.append("discipline_too_early")
        return WhatsAppDiscountDecision(
            allowed=False,
            handoff_required=False,
            reason=(
                f"Customer has only asked {discount_ask_count} time(s); "
                f"minimum {MIN_OBJECTION_TURNS_BEFORE_OFFER} pushes "
                "required before the AI may surface a discount."
            ),
            band="blocked",
            proposed_pct=proposed,
            current_total_pct=int(current_total_pct or 0),
            final_total_pct=int(current_total_pct or 0) + proposed,
            cap_passed=True,
            base_validation=base,
            notes=tuple(notes),
        )

    # 50% total cap.
    cap_passed, final_total = validate_total_discount_cap(
        current_total_pct=current_total_pct,
        additional_pct=proposed,
    )
    if not cap_passed:
        notes.append("over_total_cap_50")
        return WhatsAppDiscountDecision(
            allowed=False,
            handoff_required=True,
            reason=(
                f"Total discount {final_total}% would exceed the locked "
                f"{TOTAL_DISCOUNT_HARD_CAP_PCT}% cap (current {current_total_pct}% "
                f"+ proposed {proposed}%). Escalate to a human approver."
            ),
            band="blocked",
            proposed_pct=proposed,
            current_total_pct=int(current_total_pct or 0),
            final_total_pct=final_total,
            cap_passed=False,
            base_validation=base,
            notes=tuple(notes),
        )

    # Per-band check via Phase 3E policy.
    if not base.allowed:
        notes.append("blocked_by_phase3e_policy")
        return WhatsAppDiscountDecision(
            allowed=False,
            handoff_required=base.requires_approval
            or base.policy_band in {"director_override", "blocked"},
            reason=base.reason,
            band=base.policy_band,
            proposed_pct=proposed,
            current_total_pct=int(current_total_pct or 0),
            final_total_pct=final_total,
            cap_passed=True,
            base_validation=base,
            notes=tuple(notes + list(base.notes)),
        )

    if rescue:
        notes.append("rescue_unlock")

    return WhatsAppDiscountDecision(
        allowed=True,
        handoff_required=False,
        reason=base.reason,
        band="rescue" if rescue and base.policy_band == "auto" else base.policy_band,
        proposed_pct=proposed,
        current_total_pct=int(current_total_pct or 0),
        final_total_pct=final_total,
        cap_passed=True,
        base_validation=base,
        notes=tuple(notes + list(base.notes)),
    )


__all__ = (
    "MIN_OBJECTION_TURNS_BEFORE_OFFER",
    "PROACTIVE_RESCUE_TRIGGERS",
    "TOTAL_DISCOUNT_HARD_CAP_PCT",
    "WhatsAppDiscountDecision",
    "evaluate_whatsapp_discount",
    "validate_total_discount_cap",
)
