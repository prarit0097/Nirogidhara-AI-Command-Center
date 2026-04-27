"""Phase 3E — Reward / Penalty deterministic scoring formula.

This module captures Master Blueprint §10.2 as code so the eventual
Phase 4B reward / penalty engine has a single source of truth. It is
intentionally pure (no DB writes); callers feed it an ``Order`` (or any
object exposing the same attributes) and a context dict, and get back a
:class:`OrderRewardPenaltyResult` dataclass.

Key locked rules (Master Blueprint §10.2 + §26 #6):
- Reward / penalty is based on **delivered profitable quality orders**,
  never on punching count alone.
- Each event contributes a fixed integer; the sum is capped at +100
  reward / -100 penalty per order.
- Missing data is *never* invented. When a fact cannot be derived, the
  contribution is 0 and the result records an entry in ``missing_data``
  for the auditor / approval-matrix middleware to surface.

The Phase 4B engine will:
1. Iterate over recently changed orders.
2. Call :func:`calculate_order_reward_penalty` for each.
3. Persist the structured result + write an ``ai.reward.calculated``
   audit row.
4. Roll up per-agent leaderboard rows in :class:`apps.rewards.RewardPenalty`.

Phase 3E ships only the pure scoring math — the engine wiring is Phase 4B.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# ---------- Reward components (positive contributions) ----------
REWARD_DELIVERED_ORDER: int = 30
REWARD_HEALTHY_NET_PROFIT: int = 25
REWARD_ADVANCE_PAID: int = 10
REWARD_CUSTOMER_SATISFACTION_POSITIVE: int = 10
REWARD_REORDER_POTENTIAL_HIGH: int = 10
REWARD_CLEAN_DATA: int = 5
REWARD_COMPLIANCE_SAFE: int = 10

REWARD_MAX_TOTAL: int = 100

# ---------- Penalty components (negative contributions) ----------
PENALTY_RTO_AFTER_DISPATCH: int = 30
PENALTY_CANCELLED_AFTER_PUNCH: int = 20
PENALTY_WRONG_OR_INCOMPLETE_ADDRESS: int = 15
PENALTY_NO_ADVANCE_HIGH_RISK_COD: int = 10
PENALTY_DISCOUNT_LEAKAGE_11_TO_20_WITHOUT_REASON: int = 5
PENALTY_UNAUTHORIZED_DISCOUNT_ABOVE_20: int = 25
PENALTY_RISKY_CLAIM: int = 40
PENALTY_SIDE_EFFECT_LEGAL_REFUND_MISHANDLED: int = 30
PENALTY_IGNORED_RTO_WARNING: int = 20
PENALTY_BAD_FAKE_LEAD_QUALITY: int = 15

PENALTY_MAX_TOTAL: int = 100


@dataclass(frozen=True)
class ScoreEntry:
    """One contribution to the final reward or penalty."""

    code: str
    label: str
    points: int  # positive for reward, negative for penalty


@dataclass(frozen=True)
class OrderRewardPenaltyResult:
    """Structured result returned by :func:`calculate_order_reward_penalty`.

    All fields are read-only. The Phase 4B engine persists this verbatim.
    """

    order_id: str
    reward_total: int
    penalty_total: int
    net_score: int
    rewards: tuple[ScoreEntry, ...] = field(default_factory=tuple)
    penalties: tuple[ScoreEntry, ...] = field(default_factory=tuple)
    missing_data: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "high", "positive"}
    return bool(value)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def calculate_order_reward_penalty(
    order: Any,
    context: Mapping[str, Any] | None = None,
) -> OrderRewardPenaltyResult:
    """Compute the reward / penalty score for a single order.

    Parameters
    ----------
    order
        Either an ``apps.orders.Order`` instance or a mapping that exposes the
        same attributes (``id``, ``stage``, ``rto_risk``, ``advance_paid``,
        ``advance_amount``, ``discount_pct``, ``city``, ``state``).
    context
        Optional mapping carrying signals the order row alone cannot answer.
        Recognised keys (all optional):

        - ``net_profit_inr`` (int): post-cost profit on this order.
        - ``customer_satisfaction`` ("positive" | "neutral" | "negative" | None)
        - ``reorder_potential`` ("high" | "medium" | "low" | None)
        - ``clean_data`` (bool): address / phone / consent all present.
        - ``compliance_safe`` (bool): no Claim Vault breach in this order's
          calls / messages.
        - ``rto_warning_was_raised`` (bool): the system flagged the order
          as risky before dispatch.
        - ``discount_approved`` (bool): if the order applied 11–20% discount,
          was a ceo_ai/admin/director approval logged?
        - ``risky_claim_logged`` (bool): a non-Claim-Vault claim was made.
        - ``side_effect_or_legal_mishandled`` (bool): a flagged complaint
          was not escalated to a human.
        - ``fake_lead_quality`` (bool): the upstream lead was flagged as
          junk after delivery.

    Returns
    -------
    :class:`OrderRewardPenaltyResult` — ``reward_total`` capped at
    :data:`REWARD_MAX_TOTAL`, ``penalty_total`` capped at
    :data:`PENALTY_MAX_TOTAL`, ``net_score = reward - penalty``.
    """
    ctx = dict(context or {})
    rewards: list[ScoreEntry] = []
    penalties: list[ScoreEntry] = []
    missing: list[str] = []
    notes: list[str] = []

    order_id = str(_get(order, "id", "") or "")
    stage = str(_get(order, "stage", "") or "")
    rto_risk = str(_get(order, "rto_risk", "") or "")
    advance_paid = bool(_get(order, "advance_paid", False))
    advance_amount = int(_get(order, "advance_amount", 0) or 0)
    discount_pct = int(_get(order, "discount_pct", 0) or 0)
    state = str(_get(order, "state", "") or "")
    city = str(_get(order, "city", "") or "")
    confirmation_outcome = str(_get(order, "confirmation_outcome", "") or "")

    # ----- Rewards -----

    if stage == "Delivered":
        rewards.append(
            ScoreEntry(
                code="delivered_order",
                label="Delivered order",
                points=REWARD_DELIVERED_ORDER,
            )
        )

    if "net_profit_inr" in ctx:
        if int(ctx["net_profit_inr"]) > 0:
            rewards.append(
                ScoreEntry(
                    code="healthy_net_profit",
                    label="Healthy net profit",
                    points=REWARD_HEALTHY_NET_PROFIT,
                )
            )
    else:
        missing.append("net_profit_inr")

    if advance_paid and advance_amount > 0:
        rewards.append(
            ScoreEntry(
                code="advance_paid",
                label="Advance payment collected",
                points=REWARD_ADVANCE_PAID,
            )
        )

    sat = (ctx.get("customer_satisfaction") or "").lower() if isinstance(
        ctx.get("customer_satisfaction"), str
    ) else None
    if sat is None:
        if "customer_satisfaction" not in ctx:
            missing.append("customer_satisfaction")
    elif sat == "positive":
        rewards.append(
            ScoreEntry(
                code="customer_satisfaction_positive",
                label="Customer satisfaction positive",
                points=REWARD_CUSTOMER_SATISFACTION_POSITIVE,
            )
        )

    rp = (ctx.get("reorder_potential") or "").lower() if isinstance(
        ctx.get("reorder_potential"), str
    ) else None
    if rp is None:
        if "reorder_potential" not in ctx:
            missing.append("reorder_potential")
    elif rp == "high":
        rewards.append(
            ScoreEntry(
                code="reorder_potential_high",
                label="High reorder potential",
                points=REWARD_REORDER_POTENTIAL_HIGH,
            )
        )

    if "clean_data" in ctx:
        if _truthy(ctx["clean_data"]):
            rewards.append(
                ScoreEntry(
                    code="clean_data",
                    label="Clean data on file",
                    points=REWARD_CLEAN_DATA,
                )
            )
    elif state and city and order_id:
        # We can derive partial cleanness from the order itself.
        rewards.append(
            ScoreEntry(
                code="clean_data",
                label="Clean data on file (derived from order)",
                points=REWARD_CLEAN_DATA,
            )
        )
    else:
        missing.append("clean_data")

    if "compliance_safe" in ctx:
        if _truthy(ctx["compliance_safe"]):
            rewards.append(
                ScoreEntry(
                    code="compliance_safe",
                    label="Compliance-safe interaction",
                    points=REWARD_COMPLIANCE_SAFE,
                )
            )
    else:
        missing.append("compliance_safe")

    # ----- Penalties -----

    if stage == "RTO":
        penalties.append(
            ScoreEntry(
                code="rto_after_dispatch",
                label="Order RTO after dispatch",
                points=-PENALTY_RTO_AFTER_DISPATCH,
            )
        )

    if stage == "Cancelled" or confirmation_outcome == "cancelled":
        penalties.append(
            ScoreEntry(
                code="cancelled_after_punch",
                label="Order cancelled after punching",
                points=-PENALTY_CANCELLED_AFTER_PUNCH,
            )
        )

    if not (state and city):
        penalties.append(
            ScoreEntry(
                code="wrong_or_incomplete_address",
                label="Wrong / incomplete address",
                points=-PENALTY_WRONG_OR_INCOMPLETE_ADDRESS,
            )
        )

    if (not advance_paid) and rto_risk == "High":
        penalties.append(
            ScoreEntry(
                code="no_advance_high_risk_cod",
                label="High-risk COD without advance",
                points=-PENALTY_NO_ADVANCE_HIGH_RISK_COD,
            )
        )

    if 10 < discount_pct <= 20 and not _truthy(ctx.get("discount_approved")):
        penalties.append(
            ScoreEntry(
                code="discount_leakage_11_to_20_without_reason",
                label="11–20% discount without approval reason",
                points=-PENALTY_DISCOUNT_LEAKAGE_11_TO_20_WITHOUT_REASON,
            )
        )

    if discount_pct > 20 and not _truthy(ctx.get("director_override")):
        penalties.append(
            ScoreEntry(
                code="unauthorized_discount_above_20",
                label="Unauthorized discount above 20%",
                points=-PENALTY_UNAUTHORIZED_DISCOUNT_ABOVE_20,
            )
        )

    if _truthy(ctx.get("risky_claim_logged")):
        penalties.append(
            ScoreEntry(
                code="risky_claim",
                label="Risky / non-Claim-Vault claim emitted",
                points=-PENALTY_RISKY_CLAIM,
            )
        )

    if _truthy(ctx.get("side_effect_or_legal_mishandled")):
        penalties.append(
            ScoreEntry(
                code="side_effect_legal_refund_mishandled",
                label="Side-effect / legal / refund mishandled",
                points=-PENALTY_SIDE_EFFECT_LEGAL_REFUND_MISHANDLED,
            )
        )

    if (
        _truthy(ctx.get("rto_warning_was_raised"))
        and stage in {"RTO", "Out for Delivery", "Dispatched"}
        and not advance_paid
    ):
        penalties.append(
            ScoreEntry(
                code="ignored_rto_warning",
                label="Ignored RTO warning",
                points=-PENALTY_IGNORED_RTO_WARNING,
            )
        )

    if _truthy(ctx.get("fake_lead_quality")):
        penalties.append(
            ScoreEntry(
                code="bad_fake_lead_quality",
                label="Bad / fake lead quality",
                points=-PENALTY_BAD_FAKE_LEAD_QUALITY,
            )
        )

    raw_reward = sum(entry.points for entry in rewards)
    raw_penalty = sum(-entry.points for entry in penalties)  # store as positive
    reward_total = min(raw_reward, REWARD_MAX_TOTAL)
    penalty_total = min(raw_penalty, PENALTY_MAX_TOTAL)
    if raw_reward > REWARD_MAX_TOTAL:
        notes.append(
            f"reward capped at {REWARD_MAX_TOTAL} (raw={raw_reward})"
        )
    if raw_penalty > PENALTY_MAX_TOTAL:
        notes.append(
            f"penalty capped at {PENALTY_MAX_TOTAL} (raw={raw_penalty})"
        )

    net = reward_total - penalty_total

    return OrderRewardPenaltyResult(
        order_id=order_id,
        reward_total=reward_total,
        penalty_total=penalty_total,
        net_score=net,
        rewards=tuple(rewards),
        penalties=tuple(penalties),
        missing_data=tuple(missing),
        notes=tuple(notes),
    )
