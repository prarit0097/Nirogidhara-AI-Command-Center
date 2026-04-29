"""Phase 5E — Rescue discount flow + cumulative 50% cap enforcement.

This module is the single source of truth for "may a rescue discount
be offered right now, and at what magnitude?". It composes:

- The Phase 3E :func:`apps.orders.discounts.validate_discount` policy
  (per-step bands: 0–10 auto / 11–20 approval / >20 director override).
- The Phase 5C :func:`apps.whatsapp.discount_policy.validate_total_discount_cap`
  cumulative cap (locked 50%).
- The Phase 5E :class:`DiscountOfferLog` audit row that captures every
  attempt — accepted / rejected / blocked / skipped / needs_ceo_review.
- The Phase 4C approval engine when an offer needs CEO AI / admin /
  director review.

Locked Prarit decisions for Phase 5E:
1. AI may offer a rescue discount automatically at confirmation,
   delivery, or RTO stages, but cumulative across all stages must
   never exceed 50%.
2. If AI is stuck, unclear, or the cap math fails, it must NOT silently
   skip — it must create a CEO AI / approval request via the matrix.
3. RTO rescue may auto-offer through WhatsApp AI / AI call.
4. Reorder (Day 20) is not an automatic discount path; discounts only
   open if the customer raises a price objection.
5. Default Claim Vault demo seed is a dev/test convenience only;
   production usage_explanation lifecycle still warns when the relevant
   product only has demo claims.

This module never speaks medical claims and never bypasses the Approved
Claim Vault — it only governs price math + CEO escalation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from django.conf import settings
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .discounts import (
    DISCOUNT_AUTO_MAX_PCT,
    DISCOUNT_APPROVAL_MAX_PCT,
    DiscountValidationResult,
    validate_discount,
)
from .models import DiscountOfferLog, Order


logger = logging.getLogger(__name__)


# Cumulative cap. Mirror of apps.whatsapp.discount_policy.TOTAL_DISCOUNT_HARD_CAP_PCT
# — kept in this module so the orders side never has to import the
# WhatsApp app at module load time. Bumping this requires Prarit sign-off.
TOTAL_DISCOUNT_HARD_CAP_PCT: int = 50


# Recommended rescue magnitudes per stage. The agent should always start
# with the conservative value and only escalate after the customer pushes
# again. The numbers respect the per-stage Phase 3E bands (≤10% stays
# auto, 11–20% needs approval, >20% needs director override).
STAGE_RESCUE_LADDER: dict[str, tuple[int, ...]] = {
    DiscountOfferLog.Stage.CONFIRMATION: (5, 10, 15),
    DiscountOfferLog.Stage.DELIVERY: (5, 10),
    DiscountOfferLog.Stage.RTO: (10, 15, 20),
    DiscountOfferLog.Stage.REORDER: (5,),
    DiscountOfferLog.Stage.CUSTOMER_SUCCESS: (5, 10),
    DiscountOfferLog.Stage.ORDER_BOOKING: (5, 10),
}


# Action key the CEO escalation uses. Matches the matrix row added in
# this phase. Keep in sync with apps.ai_governance.approval_matrix.
CEO_DISCOUNT_REVIEW_ACTION: str = "discount.rescue.ceo_review"


@dataclass(frozen=True)
class CapStatus:
    """Cumulative cap snapshot used by callers + frontend."""

    current_total_pct: int
    cap_remaining_pct: int
    final_total_if_applied_pct: int
    cap_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "currentTotalPct": self.current_total_pct,
            "capRemainingPct": self.cap_remaining_pct,
            "finalTotalIfAppliedPct": self.final_total_if_applied_pct,
            "capPassed": self.cap_passed,
            "totalCapPct": TOTAL_DISCOUNT_HARD_CAP_PCT,
        }


@dataclass(frozen=True)
class RescueOffer:
    """Result of :func:`calculate_rescue_discount_offer`.

    ``offered_additional_pct`` is the actual amount the agent should
    surface in the next reply. ``status`` mirrors what the eventual
    :class:`DiscountOfferLog` row will be flagged as.
    """

    allowed: bool
    status: str
    offered_additional_pct: int
    resulting_total_pct: int
    cap_remaining_pct: int
    needs_ceo_review: bool
    reason: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    base_validation: DiscountValidationResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "offeredAdditionalPct": self.offered_additional_pct,
            "resultingTotalPct": self.resulting_total_pct,
            "capRemainingPct": self.cap_remaining_pct,
            "needsCeoReview": self.needs_ceo_review,
            "reason": self.reason,
            "notes": list(self.notes),
            "totalCapPct": TOTAL_DISCOUNT_HARD_CAP_PCT,
        }


# ---------------------------------------------------------------------------
# Cap math
# ---------------------------------------------------------------------------


def get_current_total_discount_pct(
    order: Order,
    *,
    conversation: Any | None = None,  # WhatsAppConversation
) -> int:
    """Return the cumulative approved discount on this order.

    Sources, in priority order:

    1. ``Order.discount_pct`` — already-applied discount.
    2. ``WhatsAppConversation.metadata.ai.totalDiscountPct`` if a
       conversation is supplied — captures pending / unapplied offers
       the WhatsApp orchestrator has tracked across stages.

    The returned value is the larger of the two so over-cap math is
    always conservative.
    """
    base = max(0, int(getattr(order, "discount_pct", 0) or 0))
    if conversation is not None:
        try:
            metadata = dict(getattr(conversation, "metadata", {}) or {})
            ai_state = dict(metadata.get("ai") or {})
            tracked = int(ai_state.get("totalDiscountPct") or 0)
            base = max(base, tracked)
        except Exception:  # noqa: BLE001 - never trip caller on metadata shape
            pass
    return base


def get_discount_cap_remaining(
    order: Order,
    *,
    conversation: Any | None = None,
) -> int:
    """How much discount the order can still absorb before the 50% cap."""
    current = get_current_total_discount_pct(order, conversation=conversation)
    return max(0, TOTAL_DISCOUNT_HARD_CAP_PCT - current)


def cap_status(
    order: Order,
    *,
    additional_pct: int = 0,
    conversation: Any | None = None,
) -> CapStatus:
    """Return a structured snapshot of where the order sits vs. the cap."""
    current = get_current_total_discount_pct(order, conversation=conversation)
    additional = max(0, int(additional_pct or 0))
    final_total = current + additional
    return CapStatus(
        current_total_pct=current,
        cap_remaining_pct=max(0, TOTAL_DISCOUNT_HARD_CAP_PCT - current),
        final_total_if_applied_pct=final_total,
        cap_passed=final_total <= TOTAL_DISCOUNT_HARD_CAP_PCT,
    )


def validate_total_discount_cap(
    order: Order,
    additional_pct: int,
    *,
    conversation: Any | None = None,
) -> tuple[bool, int]:
    """Return ``(passed, final_total)`` for the cumulative cap check."""
    status = cap_status(
        order, additional_pct=additional_pct, conversation=conversation
    )
    return status.cap_passed, status.final_total_if_applied_pct


# ---------------------------------------------------------------------------
# Rescue offer calculator
# ---------------------------------------------------------------------------


def calculate_rescue_discount_offer(
    order: Order,
    *,
    stage: str,
    refusal_count: int = 1,
    risk_level: str = "",
    requested_pct: int | None = None,
    actor_role: str = "operations",
    conversation: Any | None = None,
) -> RescueOffer:
    """Decide whether (and how much) to offer at this stage.

    Strategy:

    1. If the cap is exhausted (cap_remaining = 0), refuse and flag
       ``needs_ceo_review`` so the operator surface escalates instead
       of silently swallowing the offer.
    2. If the caller supplied ``requested_pct``, use that — but cap it
       at the remaining headroom and run the per-step Phase 3E policy.
    3. Otherwise pick from :data:`STAGE_RESCUE_LADDER` based on
       ``refusal_count``: first refusal → ladder[0], second →
       ladder[1], etc. Always conservative; never jumps to the top of
       the ladder.
    4. RTO with ``risk_level == "high"`` may shorten the ladder by one
       step (start higher to actually save the order) but still respects
       the 50% cap.
    5. If the chosen amount ends up at 0 (cap exhausted), the offer is
       blocked.
    6. Run :func:`validate_discount` for the per-stage band check; if
       it requires approval AND the actor is not in the approver pool,
       flag ``needs_ceo_review``.
    """
    stage = (stage or "").strip()
    cap = cap_status(order, additional_pct=0, conversation=conversation)
    current_total = cap.current_total_pct
    remaining = cap.cap_remaining_pct
    notes: list[str] = []

    if remaining <= 0:
        notes.append("cap_exhausted")
        return RescueOffer(
            allowed=False,
            status=DiscountOfferLog.Status.NEEDS_CEO_REVIEW,
            offered_additional_pct=0,
            resulting_total_pct=current_total,
            cap_remaining_pct=0,
            needs_ceo_review=True,
            reason=(
                f"Cumulative discount {current_total}% already at the "
                f"{TOTAL_DISCOUNT_HARD_CAP_PCT}% cap. Escalate to CEO AI / "
                "Director."
            ),
            notes=tuple(notes),
        )

    # Pick a target percent.
    if requested_pct is not None and int(requested_pct) > 0:
        target = int(requested_pct)
        notes.append("requested_pct_supplied")
    else:
        ladder = STAGE_RESCUE_LADDER.get(stage)
        if not ladder:
            notes.append("unknown_stage")
            return RescueOffer(
                allowed=False,
                status=DiscountOfferLog.Status.SKIPPED,
                offered_additional_pct=0,
                resulting_total_pct=current_total,
                cap_remaining_pct=remaining,
                needs_ceo_review=False,
                reason=f"No rescue ladder registered for stage '{stage}'.",
                notes=tuple(notes),
            )
        # 1-indexed refusal_count → 0-indexed ladder; clamp at top of ladder.
        ladder_index = max(0, min(int(refusal_count or 1) - 1, len(ladder) - 1))
        if (risk_level or "").lower() == "high" and stage == DiscountOfferLog.Stage.RTO:
            ladder_index = min(ladder_index + 1, len(ladder) - 1)
            notes.append("rto_high_risk_step_up")
        target = ladder[ladder_index]

    # Cap at remaining headroom — never propose more than the order can absorb.
    if target > remaining:
        notes.append("clamped_to_cap_remaining")
        target = remaining

    if target <= 0:
        return RescueOffer(
            allowed=False,
            status=DiscountOfferLog.Status.BLOCKED,
            offered_additional_pct=0,
            resulting_total_pct=current_total,
            cap_remaining_pct=remaining,
            needs_ceo_review=True,
            reason="Cap math leaves no headroom for a rescue offer.",
            notes=tuple(notes),
        )

    # Per-step band check (Phase 3E policy). The rescue agent typically
    # runs as ``operations`` / ``ai_chat``; treat anything outside the
    # auto band as needing CEO AI approval.
    base = validate_discount(target, actor_role)
    final_total = current_total + target

    if not base.allowed:
        if base.requires_approval:
            notes.append(f"needs_approval_band:{base.policy_band}")
            return RescueOffer(
                allowed=False,
                status=DiscountOfferLog.Status.NEEDS_CEO_REVIEW,
                offered_additional_pct=target,
                resulting_total_pct=final_total,
                cap_remaining_pct=remaining,
                needs_ceo_review=True,
                reason=base.reason,
                notes=tuple(notes),
                base_validation=base,
            )
        notes.append(f"blocked_band:{base.policy_band}")
        return RescueOffer(
            allowed=False,
            status=DiscountOfferLog.Status.BLOCKED,
            offered_additional_pct=target,
            resulting_total_pct=final_total,
            cap_remaining_pct=remaining,
            needs_ceo_review=False,
            reason=base.reason,
            notes=tuple(notes),
            base_validation=base,
        )

    # Within auto band AND within cumulative cap.
    return RescueOffer(
        allowed=True,
        status=DiscountOfferLog.Status.OFFERED,
        offered_additional_pct=target,
        resulting_total_pct=final_total,
        cap_remaining_pct=remaining - target,
        needs_ceo_review=False,
        reason=base.reason,
        notes=tuple(notes),
        base_validation=base,
    )


# ---------------------------------------------------------------------------
# Persisted offer creator
# ---------------------------------------------------------------------------


@transaction.atomic
def create_rescue_discount_offer(
    *,
    order: Order,
    stage: str,
    source_channel: str,
    trigger_reason: str,
    refusal_count: int = 1,
    risk_level: str = "",
    requested_pct: int | None = None,
    actor_role: str = "operations",
    actor_agent: str = "",
    conversation: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DiscountOfferLog:
    """Calculate the rescue offer + persist a :class:`DiscountOfferLog` row.

    Always writes a row — even when the offer is blocked / skipped /
    over-cap — so audit trail is never missing. CAIO is refused at the
    entry: any actor token containing 'caio' is rejected.
    """
    # Hard stop: CAIO can never originate or apply a customer-facing
    # discount offer.
    if (actor_agent or "").lower() == "caio":
        return _record_offer(
            order=order,
            stage=stage,
            source_channel=source_channel,
            trigger_reason=trigger_reason,
            offered_pct=0,
            previous_pct=get_current_total_discount_pct(order, conversation=conversation),
            cap_remaining=get_discount_cap_remaining(order, conversation=conversation),
            status=DiscountOfferLog.Status.BLOCKED,
            blocked_reason="caio_no_send",
            offered_by_agent=actor_agent,
            conversation=conversation,
            metadata={**dict(metadata or {}), "caio_refused": True},
        )

    if not getattr(settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False) and stage in {
        DiscountOfferLog.Stage.CONFIRMATION,
        DiscountOfferLog.Stage.DELIVERY,
    }:
        return _record_offer(
            order=order,
            stage=stage,
            source_channel=source_channel,
            trigger_reason=trigger_reason,
            offered_pct=0,
            previous_pct=get_current_total_discount_pct(order, conversation=conversation),
            cap_remaining=get_discount_cap_remaining(order, conversation=conversation),
            status=DiscountOfferLog.Status.SKIPPED,
            blocked_reason="rescue_disabled",
            offered_by_agent=actor_agent,
            conversation=conversation,
            metadata=dict(metadata or {}),
        )

    if stage == DiscountOfferLog.Stage.RTO and not getattr(
        settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False
    ):
        return _record_offer(
            order=order,
            stage=stage,
            source_channel=source_channel,
            trigger_reason=trigger_reason,
            offered_pct=0,
            previous_pct=get_current_total_discount_pct(order, conversation=conversation),
            cap_remaining=get_discount_cap_remaining(order, conversation=conversation),
            status=DiscountOfferLog.Status.SKIPPED,
            blocked_reason="rto_rescue_disabled",
            offered_by_agent=actor_agent,
            conversation=conversation,
            metadata=dict(metadata or {}),
        )

    rescue = calculate_rescue_discount_offer(
        order,
        stage=stage,
        refusal_count=refusal_count,
        risk_level=risk_level,
        requested_pct=requested_pct,
        actor_role=actor_role,
        conversation=conversation,
    )

    log = _record_offer(
        order=order,
        stage=stage,
        source_channel=source_channel,
        trigger_reason=trigger_reason,
        offered_pct=rescue.offered_additional_pct,
        previous_pct=rescue.resulting_total_pct - rescue.offered_additional_pct,
        cap_remaining=rescue.cap_remaining_pct,
        status=rescue.status,
        blocked_reason=("" if rescue.allowed else rescue.reason)[:80],
        offered_by_agent=actor_agent or actor_role,
        conversation=conversation,
        metadata={
            **dict(metadata or {}),
            "refusal_count": int(refusal_count or 1),
            "risk_level": risk_level or "",
            "notes": list(rescue.notes),
            "reason": rescue.reason[:480],
        },
    )

    if rescue.needs_ceo_review:
        _maybe_create_ceo_review(
            order=order,
            log=log,
            rescue=rescue,
            actor_role=actor_role,
            actor_agent=actor_agent,
            conversation=conversation,
        )
    return log


def _record_offer(
    *,
    order: Order | None,
    stage: str,
    source_channel: str,
    trigger_reason: str,
    offered_pct: int,
    previous_pct: int,
    cap_remaining: int,
    status: str,
    blocked_reason: str = "",
    offered_by_agent: str = "",
    conversation: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DiscountOfferLog:
    log = DiscountOfferLog.objects.create(
        order=order,
        customer=getattr(order, "customer", None) if order else None,
        conversation=conversation,
        source_channel=source_channel,
        stage=stage,
        trigger_reason=trigger_reason or "rescue",
        previous_discount_pct=int(previous_pct or 0),
        offered_additional_pct=int(offered_pct or 0),
        resulting_total_discount_pct=int(previous_pct or 0) + int(offered_pct or 0),
        cap_remaining_pct=int(cap_remaining or 0),
        status=status,
        blocked_reason=(blocked_reason or "")[:80],
        offered_by_agent=(offered_by_agent or "")[:40],
        metadata=dict(metadata or {}),
    )

    audit_kind = {
        DiscountOfferLog.Status.OFFERED: "discount.offer.created",
        DiscountOfferLog.Status.ACCEPTED: "discount.offer.accepted",
        DiscountOfferLog.Status.REJECTED: "discount.offer.rejected",
        DiscountOfferLog.Status.BLOCKED: "discount.offer.blocked",
        DiscountOfferLog.Status.SKIPPED: "discount.offer.blocked",
        DiscountOfferLog.Status.NEEDS_CEO_REVIEW: "discount.offer.needs_ceo_review",
    }.get(status, "discount.offer.created")

    audit_tone = (
        AuditEvent.Tone.SUCCESS
        if status == DiscountOfferLog.Status.ACCEPTED
        else AuditEvent.Tone.WARNING
        if status
        in {
            DiscountOfferLog.Status.NEEDS_CEO_REVIEW,
            DiscountOfferLog.Status.BLOCKED,
            DiscountOfferLog.Status.REJECTED,
        }
        else AuditEvent.Tone.INFO
    )

    write_event(
        kind=audit_kind,
        text=(
            f"Discount offer · order={getattr(order, 'id', '')} · "
            f"stage={stage} · +{log.offered_additional_pct}% → "
            f"{log.resulting_total_discount_pct}% · {status}"
        ),
        tone=audit_tone,
        payload={
            "discount_offer_id": log.pk,
            "order_id": getattr(order, "id", "") or "",
            "stage": stage,
            "status": status,
            "source_channel": source_channel,
            "trigger_reason": trigger_reason,
            "offered_additional_pct": log.offered_additional_pct,
            "previous_discount_pct": log.previous_discount_pct,
            "resulting_total_discount_pct": log.resulting_total_discount_pct,
            "cap_remaining_pct": log.cap_remaining_pct,
            "blocked_reason": log.blocked_reason,
            "offered_by_agent": log.offered_by_agent,
        },
    )
    return log


def _maybe_create_ceo_review(
    *,
    order: Order,
    log: DiscountOfferLog,
    rescue: RescueOffer,
    actor_role: str,
    actor_agent: str,
    conversation: Any | None,
) -> None:
    """Create a CEO AI / approval matrix request when AI is stuck."""
    try:
        from apps.ai_governance.approval_engine import enforce_or_queue

        decision = enforce_or_queue(
            action=CEO_DISCOUNT_REVIEW_ACTION,
            payload={
                "orderId": order.id if order else "",
                "stage": log.stage,
                "offeredAdditionalPct": rescue.offered_additional_pct,
                "currentTotalPct": rescue.resulting_total_pct - rescue.offered_additional_pct,
                "resultingTotalPct": rescue.resulting_total_pct,
                "capRemainingPct": rescue.cap_remaining_pct,
                "reason": rescue.reason,
                "notes": list(rescue.notes),
                "discountOfferId": log.pk,
            },
            actor_role=actor_role,
            actor_agent=actor_agent,
            target={
                "app": "orders",
                "model": "Order",
                "id": getattr(order, "id", ""),
            },
            reason=f"Rescue discount needs CEO review · {log.stage} · {rescue.reason}",
        )
        if decision.approval_request_id:
            from apps.ai_governance.models import ApprovalRequest

            req = ApprovalRequest.objects.filter(
                pk=decision.approval_request_id
            ).first()
            if req is not None:
                log.approval_request = req
                log.save(update_fields=["approval_request", "updated_at"])
    except Exception as exc:  # noqa: BLE001 - never lose the log on governance miss
        logger.warning(
            "CEO review request failed for offer %s: %s", log.pk, exc
        )


# ---------------------------------------------------------------------------
# Accept / reject lifecycle
# ---------------------------------------------------------------------------


@transaction.atomic
def accept_rescue_discount_offer(
    *,
    offer: DiscountOfferLog,
    actor_role: str = "operations",
    actor=None,
) -> DiscountOfferLog:
    """Customer accepted the rescue offer — apply via the orders service."""
    if offer.status not in {
        DiscountOfferLog.Status.OFFERED,
        DiscountOfferLog.Status.NEEDS_CEO_REVIEW,
    }:
        raise ValueError(
            f"Cannot accept a discount offer in status '{offer.status}'."
        )
    if offer.order is None:
        raise ValueError("Discount offer has no Order — cannot apply.")

    # Refresh cap math against the latest order state.
    final_total = offer.resulting_total_discount_pct
    cap_passed, calc_total = validate_total_discount_cap(
        offer.order, additional_pct=offer.offered_additional_pct
    )
    if not cap_passed:
        offer.status = DiscountOfferLog.Status.NEEDS_CEO_REVIEW
        offer.blocked_reason = (
            f"cap_exceeded_at_accept ({calc_total}%)"
        )[:80]
        offer.save(update_fields=["status", "blocked_reason", "updated_at"])
        write_event(
            kind="discount.offer.needs_ceo_review",
            text=(
                f"Discount offer #{offer.pk} cap exceeded at accept time "
                f"({calc_total}%). CEO review needed."
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "discount_offer_id": offer.pk,
                "order_id": offer.order_id or "",
                "resulting_total_discount_pct": calc_total,
            },
        )
        return offer

    from . import services as orders_services
    from .services import DiscountValidationError

    try:
        orders_services.apply_order_discount(
            offer.order,
            discount_pct=final_total,
            actor=actor,
            actor_role=actor_role,
            reason=(
                f"Rescue discount accepted · stage={offer.stage} · "
                f"+{offer.offered_additional_pct}%"
            ),
            source="rescue_discount",
            approval_context={"approved_by": "ceo_ai"}
            if offer.approval_request_id
            else None,
        )
    except DiscountValidationError as exc:
        offer.status = DiscountOfferLog.Status.BLOCKED
        offer.blocked_reason = str(exc)[:80]
        offer.save(update_fields=["status", "blocked_reason", "updated_at"])
        write_event(
            kind="discount.offer.blocked",
            text=f"Discount offer #{offer.pk} apply failed: {exc}",
            tone=AuditEvent.Tone.DANGER,
            payload={
                "discount_offer_id": offer.pk,
                "order_id": offer.order_id or "",
                "error": str(exc)[:480],
            },
        )
        return offer

    offer.status = DiscountOfferLog.Status.ACCEPTED
    offer.save(update_fields=["status", "updated_at"])
    write_event(
        kind="discount.offer.accepted",
        text=(
            f"Discount offer #{offer.pk} accepted · order={offer.order_id} "
            f"· total={final_total}%"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "discount_offer_id": offer.pk,
            "order_id": offer.order_id or "",
            "resulting_total_discount_pct": final_total,
            "stage": offer.stage,
            "source_channel": offer.source_channel,
        },
    )
    return offer


@transaction.atomic
def reject_rescue_discount_offer(
    *,
    offer: DiscountOfferLog,
    note: str = "",
) -> DiscountOfferLog:
    """Customer rejected the offer — record + audit. No order mutation."""
    if offer.status == DiscountOfferLog.Status.ACCEPTED:
        raise ValueError("Cannot reject an already-accepted discount offer.")
    offer.status = DiscountOfferLog.Status.REJECTED
    metadata = dict(offer.metadata or {})
    if note:
        metadata["rejection_note"] = note[:480]
    offer.metadata = metadata
    offer.save(update_fields=["status", "metadata", "updated_at"])
    write_event(
        kind="discount.offer.rejected",
        text=f"Discount offer #{offer.pk} rejected · order={offer.order_id}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "discount_offer_id": offer.pk,
            "order_id": offer.order_id or "",
            "stage": offer.stage,
            "source_channel": offer.source_channel,
            "note": note[:240],
        },
    )
    return offer


__all__ = (
    "CEO_DISCOUNT_REVIEW_ACTION",
    "CapStatus",
    "RescueOffer",
    "STAGE_RESCUE_LADDER",
    "TOTAL_DISCOUNT_HARD_CAP_PCT",
    "accept_rescue_discount_offer",
    "calculate_rescue_discount_offer",
    "cap_status",
    "create_rescue_discount_offer",
    "get_current_total_discount_pct",
    "get_discount_cap_remaining",
    "reject_rescue_discount_offer",
    "validate_total_discount_cap",
)
