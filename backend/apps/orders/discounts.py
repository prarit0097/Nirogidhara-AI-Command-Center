"""Phase 3E — Discount policy (Master Blueprint §10 / §24 #3 / §26).

Locked decision (Phase 3E business config):
- 0–10%  : auto allowed for any role with order-write authority
- 11–20% : requires CEO AI or admin / director approval
- 21%+   : blocked unless director override (``actor_role='director'`` AND
           ``approval_context['director_override']=True``)

The historical 30% discount referenced in earlier iterations remains a
human-process / legacy reality, not a system permission. The new system
hard-caps automated discounts at 20% unless a Director explicitly
overrides for that specific request.

This module is a *policy*: it inspects the inputs and returns a
``DiscountValidationResult`` describing what the caller is allowed to do.
The order-write service / approval-matrix middleware (Phase 4C) is what
actually enforces the result; the policy itself never mutates state.

The discount policy NEVER speaks medical claims and NEVER bypasses the
Approved Claim Vault — it only governs price math.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


# Locked thresholds. Keep narrow — change only after a director-signed
# blueprint update.
DISCOUNT_AUTO_MAX_PCT: int = 10
DISCOUNT_APPROVAL_MAX_PCT: int = 20
DISCOUNT_HARD_CAP_PCT: int = 20
DISCOUNT_DIRECTOR_OVERRIDE_CEILING_PCT: int = 50


# Roles that can submit a discount request at all. Others are rejected
# outright, regardless of percentage.
_DISCOUNT_REQUESTORS: frozenset[str] = frozenset(
    {"director", "admin", "operations", "compliance", "ceo_ai"}
)
_APPROVER_ROLES: frozenset[str] = frozenset({"director", "admin", "ceo_ai"})


@dataclass(frozen=True)
class DiscountValidationResult:
    """Outcome of :func:`validate_discount`.

    ``allowed`` is the only field the caller needs to gate the action; the
    rest is for telemetry, audit ledgers, and the eventual approval-matrix
    middleware.
    """

    allowed: bool
    requires_approval: bool
    reason: str
    policy_band: str  # "auto" | "approval" | "director_override" | "blocked"
    discount_pct: int
    actor_role: str
    notes: tuple[str, ...] = field(default_factory=tuple)


def validate_discount(
    discount_pct: int,
    actor_role: str,
    approval_context: Optional[Mapping[str, Any]] = None,
) -> DiscountValidationResult:
    """Return whether the caller may apply ``discount_pct`` and on what terms.

    Parameters
    ----------
    discount_pct
        Integer 0–100. Negative values are rejected.
    actor_role
        The user role asking for the discount. Anything outside
        :data:`_DISCOUNT_REQUESTORS` is rejected.
    approval_context
        Optional dict carrying approval state. Recognised keys:
        ``approved_by`` (str), ``director_override`` (bool),
        ``ceo_ai_approval_id`` (str), ``reason`` (str).
    """
    role = (actor_role or "").lower().strip()
    ctx = dict(approval_context or {})
    notes: list[str] = []

    if discount_pct < 0:
        return DiscountValidationResult(
            allowed=False,
            requires_approval=False,
            reason="Discount percentage cannot be negative.",
            policy_band="blocked",
            discount_pct=int(discount_pct),
            actor_role=role,
            notes=("negative_discount",),
        )

    if discount_pct > 100:
        return DiscountValidationResult(
            allowed=False,
            requires_approval=False,
            reason="Discount percentage cannot exceed 100%.",
            policy_band="blocked",
            discount_pct=int(discount_pct),
            actor_role=role,
            notes=("over_100",),
        )

    if role not in _DISCOUNT_REQUESTORS:
        return DiscountValidationResult(
            allowed=False,
            requires_approval=False,
            reason=f"Role '{role or 'unknown'}' may not request discounts.",
            policy_band="blocked",
            discount_pct=int(discount_pct),
            actor_role=role,
            notes=("role_not_authorized",),
        )

    pct = int(discount_pct)

    # Tier 1 — automatic.
    if pct <= DISCOUNT_AUTO_MAX_PCT:
        return DiscountValidationResult(
            allowed=True,
            requires_approval=False,
            reason=(
                f"Discount {pct}% is within the auto-approved band "
                f"(0–{DISCOUNT_AUTO_MAX_PCT}%)."
            ),
            policy_band="auto",
            discount_pct=pct,
            actor_role=role,
        )

    # Tier 2 — approval needed.
    if pct <= DISCOUNT_APPROVAL_MAX_PCT:
        approver = (ctx.get("approved_by") or "").lower().strip()
        ceo_ai_approval = ctx.get("ceo_ai_approval_id")
        # Director / Admin / CEO AI may self-approve via approval_context.
        if role in _APPROVER_ROLES and ctx.get("self_approve"):
            return DiscountValidationResult(
                allowed=True,
                requires_approval=False,
                reason=(
                    f"Discount {pct}% self-approved by {role} "
                    f"(within {DISCOUNT_APPROVAL_MAX_PCT}% authority)."
                ),
                policy_band="approval",
                discount_pct=pct,
                actor_role=role,
                notes=("self_approved",),
            )
        if approver in _APPROVER_ROLES or ceo_ai_approval:
            return DiscountValidationResult(
                allowed=True,
                requires_approval=False,
                reason=(
                    f"Discount {pct}% approved by "
                    f"{approver or 'CEO AI ' + str(ceo_ai_approval)}."
                ),
                policy_band="approval",
                discount_pct=pct,
                actor_role=role,
                notes=("approved",),
            )
        return DiscountValidationResult(
            allowed=False,
            requires_approval=True,
            reason=(
                f"Discount {pct}% requires CEO AI / admin / director approval. "
                f"Caller role '{role}' is below approval authority."
            ),
            policy_band="approval",
            discount_pct=pct,
            actor_role=role,
            notes=("needs_ceo_or_admin_or_director",),
        )

    # Tier 3 — > 20% requires director override.
    if role == "director" and ctx.get("director_override"):
        if pct > DISCOUNT_DIRECTOR_OVERRIDE_CEILING_PCT:
            return DiscountValidationResult(
                allowed=False,
                requires_approval=True,
                reason=(
                    f"Discount {pct}% exceeds director override ceiling "
                    f"({DISCOUNT_DIRECTOR_OVERRIDE_CEILING_PCT}%); blueprint update required."
                ),
                policy_band="blocked",
                discount_pct=pct,
                actor_role=role,
                notes=("over_director_ceiling",),
            )
        return DiscountValidationResult(
            allowed=True,
            requires_approval=False,
            reason=(
                f"Discount {pct}% applied via director override "
                f"(over {DISCOUNT_HARD_CAP_PCT}% cap)."
            ),
            policy_band="director_override",
            discount_pct=pct,
            actor_role=role,
            notes=("director_override",),
        )

    return DiscountValidationResult(
        allowed=False,
        requires_approval=True,
        reason=(
            f"Discount {pct}% exceeds the {DISCOUNT_HARD_CAP_PCT}% cap. "
            f"Director override required (set actor_role='director' and "
            f"approval_context['director_override']=True)."
        ),
        policy_band="blocked",
        discount_pct=pct,
        actor_role=role,
        notes=("over_hard_cap",),
    )
