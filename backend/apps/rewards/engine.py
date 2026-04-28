"""Phase 4B — Reward / Penalty Engine wiring.

Wires the pure scoring formula in :mod:`apps.rewards.scoring` into:

1. **Per-order, per-AI-agent persistence** as :class:`RewardPenaltyEvent` rows.
2. **Idempotent sweeps** over delivered / RTO / cancelled orders.
3. **Agent-level leaderboard rollups** in :class:`RewardPenalty` so the
   existing ``GET /api/rewards/`` endpoint stays compatible.
4. **Audit ledger** entries for sweep lifecycle + leaderboard rebuilds.

LOCKED Phase 4B decisions (Master Blueprint §10.2 + §26 + Prarit Apr 2026):

- **AI agents only** are scored in this phase — no human staff scoring.
- **CEO AI net accountability** — every delivered order → CEO AI reward
  share, every RTO / cancelled order → CEO AI **always** receives a
  penalty accountability event.
- **CAIO never** receives business reward / penalty (audit-only).
- **Missing data is never invented** — when a signal cannot be derived
  from the order or supplied context, the contribution is 0 and the
  event records an entry in ``missing_data``.
- **Reward cap +100 / penalty cap -100** per order (handled in
  :func:`scoring.calculate_order_reward_penalty`).

The engine is intentionally a *pure* dispatcher: the formula stays in
``scoring.py``; this module decides which AI agents collect points and
how the result rolls up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone as _tz
from typing import Any, Iterable, Mapping

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order
from apps.rewards.scoring import (
    OrderRewardPenaltyResult,
    PENALTY_MAX_TOTAL,
    REWARD_MAX_TOTAL,
    ScoreEntry,
    calculate_order_reward_penalty,
)

from .models import RewardPenalty, RewardPenaltyEvent


# ---------------------------------------------------------------------------
# AI agent registry — Phase 4B scope is AI-only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AiAgentInfo:
    """One AI agent that can collect Phase 4B reward / penalty events."""

    agent_id: str
    name: str
    agent_type: str
    role: str


# Display labels match the seeded ``apps.agents.Agent`` rows so the legacy
# leaderboard rollup can find them by ``name``.
AI_AGENTS: tuple[AiAgentInfo, ...] = (
    AiAgentInfo(
        agent_id="ceo",
        name="CEO AI Agent",
        agent_type="command",
        role="net accountability",
    ),
    AiAgentInfo(
        agent_id="ads",
        name="Ads Agent",
        agent_type="marketing",
        role="lead source quality",
    ),
    AiAgentInfo(
        agent_id="marketing",
        name="Marketing Agent",
        agent_type="marketing",
        role="campaign / creative quality",
    ),
    AiAgentInfo(
        agent_id="sales",
        name="Sales Growth Agent",
        agent_type="sales",
        role="conversion + discount discipline",
    ),
    AiAgentInfo(
        agent_id="calling-tl",
        name="Calling AI",
        agent_type="sales",
        role="closing strength + advance collection",
    ),
    AiAgentInfo(
        agent_id="confirmation",
        name="Confirmation AI",
        agent_type="operations",
        role="address + confirmation strength",
    ),
    AiAgentInfo(
        agent_id="rto",
        name="RTO Prevention Agent",
        agent_type="operations",
        role="rescue + risk handling",
    ),
    AiAgentInfo(
        agent_id="success",
        name="Customer Success / Reorder",
        agent_type="success",
        role="satisfaction + reorder potential",
    ),
    AiAgentInfo(
        agent_id="dq",
        name="Data Quality Agent",
        agent_type="insights",
        role="address / phone / duplicates",
    ),
    AiAgentInfo(
        agent_id="compliance",
        name="Compliance & Medical Safety",
        agent_type="governance",
        role="claim safety",
    ),
)

AI_AGENT_BY_ID: dict[str, AiAgentInfo] = {a.agent_id: a for a in AI_AGENTS}

# Agents to keep out of business scoring per Master Blueprint §26.
EXCLUDED_AGENTS: frozenset[str] = frozenset({"caio"})


# ---------------------------------------------------------------------------
# Eligible order sets.
# ---------------------------------------------------------------------------


# Stages the engine evaluates; everything else is skipped.
ELIGIBLE_DELIVERED_STAGES: frozenset[str] = frozenset({Order.Stage.DELIVERED})
ELIGIBLE_FAILED_STAGES: frozenset[str] = frozenset(
    {Order.Stage.RTO, Order.Stage.CANCELLED}
)
ELIGIBLE_STAGES: frozenset[str] = ELIGIBLE_DELIVERED_STAGES | ELIGIBLE_FAILED_STAGES


# ---------------------------------------------------------------------------
# Sweep summary dataclass.
# ---------------------------------------------------------------------------


@dataclass
class SweepSummary:
    """Aggregate result of a sweep run."""

    evaluated_orders: int = 0
    created_events: int = 0
    updated_events: int = 0
    skipped_orders: int = 0
    total_reward: int = 0
    total_penalty: int = 0
    net_score: int = 0
    dry_run: bool = False
    leaderboard_updated: bool = False
    missing_data_warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluatedOrders": self.evaluated_orders,
            "createdEvents": self.created_events,
            "updatedEvents": self.updated_events,
            "skippedOrders": self.skipped_orders,
            "totalReward": self.total_reward,
            "totalPenalty": self.total_penalty,
            "netScore": self.net_score,
            "dryRun": self.dry_run,
            "leaderboardUpdated": self.leaderboard_updated,
            "missingDataWarnings": list(self.missing_data_warnings),
        }


# ---------------------------------------------------------------------------
# Public engine API.
# ---------------------------------------------------------------------------


def build_reward_context(order: Order) -> dict[str, Any]:
    """Pull every signal the formula understands from the order + related rows.

    The engine NEVER invents signals it cannot prove: anything not derivable
    from the DB is left out of the context dict so the formula records it
    in ``missing_data``.
    """
    ctx: dict[str, Any] = {}

    # Compliance heuristic: derive from any RTO_RISK_HIGH on the order;
    # treat compliance as safe unless an audit row says otherwise.
    if order.advance_paid:
        ctx["clean_data"] = bool(order.state and order.city and order.phone)

    # Discount approval flag — if the order's discount sits in the 11–20
    # band, surface a hint that approval was logged so the formula won't
    # double-penalize. We only mark it ``True`` when there's a positive
    # confirmation in the order's confirmation_outcome.
    if 10 < order.discount_pct <= 20:
        ctx["discount_approved"] = (
            order.confirmation_outcome == Order.ConfirmationOutcome.CONFIRMED
        )
    if order.discount_pct > 20:
        # Director override is never assumed automatically.
        ctx["director_override"] = False

    # Compliance-safe heuristic: order.confirmation_outcome must not be
    # ``rescue_needed`` (that flags weak handling). We don't claim safety
    # unless the order is confirmed.
    if order.confirmation_outcome == Order.ConfirmationOutcome.CONFIRMED:
        ctx["compliance_safe"] = True

    # Net profit signal — we don't have a per-order profit column yet.
    # Leave it out so the formula records the missing data explicitly.

    # RTO warning: if rto_risk was high before terminal stage, mark the
    # warning as raised. The formula only fires the penalty when the
    # warning was raised AND advance was not paid AND the order ended
    # poorly — we let the formula gate it.
    if order.rto_risk in (Order.RtoRisk.HIGH, Order.RtoRisk.MEDIUM):
        ctx["rto_warning_was_raised"] = True

    return ctx


@transaction.atomic
def calculate_for_order(
    order: Order,
    *,
    context: Mapping[str, Any] | None = None,
    triggered_by: str | None = None,
    dry_run: bool = False,
) -> tuple[OrderRewardPenaltyResult, list[RewardPenaltyEvent], SweepSummary]:
    """Score one order and persist :class:`RewardPenaltyEvent` rows.

    Returns ``(result, events, summary)``. When ``dry_run=True`` the
    returned events are unsaved instances built from the same attribution
    logic so the caller can preview the impact.
    """
    if order.stage not in ELIGIBLE_STAGES:
        summary = SweepSummary(
            evaluated_orders=0,
            skipped_orders=1,
            dry_run=dry_run,
        )
        return (
            calculate_order_reward_penalty(order, context=context),
            [],
            summary,
        )

    ctx = dict(build_reward_context(order))
    if context:
        ctx.update(context)

    result = calculate_order_reward_penalty(order, context=ctx)
    is_failed = order.stage in ELIGIBLE_FAILED_STAGES
    triggered_by_str = (triggered_by or "").strip()

    plan = _attribute_event(order, result, is_failed_stage=is_failed)
    persisted: list[RewardPenaltyEvent] = []
    summary = SweepSummary(
        evaluated_orders=1,
        total_reward=result.reward_total,
        total_penalty=result.penalty_total,
        net_score=result.net_score,
        dry_run=dry_run,
    )
    summary.missing_data_warnings.extend(
        f"{order.id}:{m}" for m in result.missing_data
    )

    for entry in plan:
        if dry_run:
            persisted.append(_build_event_instance(order, entry, triggered_by_str))
            summary.created_events += 1
            continue

        unique_key = entry["unique_key"]
        defaults = _event_defaults(order, entry, triggered_by_str)
        obj, created = RewardPenaltyEvent.objects.update_or_create(
            unique_key=unique_key, defaults=defaults
        )
        # Stamp a synthetic id when create_via_update_or_create initialises
        # without one (it always provides an int unless we set max_length).
        if not obj.id:
            obj.id = unique_key[:64]
            obj.save(update_fields=["id"])
        persisted.append(obj)
        if created:
            summary.created_events += 1
        else:
            summary.updated_events += 1

    return result, persisted, summary


def calculate_for_delivered_orders(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    triggered_by: str | None = None,
    dry_run: bool = False,
) -> SweepSummary:
    qs = Order.objects.filter(stage__in=tuple(ELIGIBLE_DELIVERED_STAGES))
    return _sweep_queryset(
        qs,
        start_date=start_date,
        end_date=end_date,
        triggered_by=triggered_by,
        dry_run=dry_run,
        sweep_label="delivered",
    )


def calculate_for_failed_orders(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    triggered_by: str | None = None,
    dry_run: bool = False,
) -> SweepSummary:
    qs = Order.objects.filter(stage__in=tuple(ELIGIBLE_FAILED_STAGES))
    return _sweep_queryset(
        qs,
        start_date=start_date,
        end_date=end_date,
        triggered_by=triggered_by,
        dry_run=dry_run,
        sweep_label="failed",
    )


def calculate_for_all_eligible_orders(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    triggered_by: str | None = None,
    dry_run: bool = False,
) -> SweepSummary:
    qs = Order.objects.filter(stage__in=tuple(ELIGIBLE_STAGES))
    return _sweep_queryset(
        qs,
        start_date=start_date,
        end_date=end_date,
        triggered_by=triggered_by,
        dry_run=dry_run,
        sweep_label="all",
    )


def rebuild_agent_leaderboard(*, triggered_by: str | None = None) -> dict[str, Any]:
    """Aggregate :class:`RewardPenaltyEvent` rows into :class:`RewardPenalty`.

    Existing legacy ``RewardPenalty`` rows for human staff (e.g. seeded
    rows where ``agent_id`` is empty) are left untouched so the legacy
    list endpoint keeps showing the seeded leaderboard. Phase 4B only
    upserts AI-agent rows.
    """
    rebuilt: dict[str, dict[str, Any]] = {}
    for info in AI_AGENTS:
        rewards_qs = RewardPenaltyEvent.objects.filter(
            agent_name=info.name,
        )
        total_reward = 0
        total_penalty = 0
        rewarded_orders = 0
        penalized_orders = 0
        last_at: datetime | None = None
        for event in rewards_qs:
            total_reward += int(event.reward_score or 0)
            total_penalty += int(event.penalty_score or 0)
            if event.reward_score > 0:
                rewarded_orders += 1
            if event.penalty_score > 0:
                penalized_orders += 1
            if last_at is None or (
                event.calculated_at and event.calculated_at > last_at
            ):
                last_at = event.calculated_at
        rebuilt[info.name] = {
            "agent_id": info.agent_id,
            "agent_type": info.agent_type,
            "reward": total_reward,
            "penalty": total_penalty,
            "rewarded_orders": rewarded_orders,
            "penalized_orders": penalized_orders,
            "last_calculated_at": last_at,
        }

    with transaction.atomic():
        for sort_idx, info in enumerate(AI_AGENTS):
            row = rebuilt[info.name]
            RewardPenalty.objects.update_or_create(
                name=info.name,
                defaults={
                    "reward": row["reward"],
                    "penalty": row["penalty"],
                    "agent_id": row["agent_id"],
                    "agent_type": row["agent_type"],
                    "rewarded_orders": row["rewarded_orders"],
                    "penalized_orders": row["penalized_orders"],
                    "last_calculated_at": row["last_calculated_at"],
                    "sort_order": sort_idx,
                },
            )

    write_event(
        kind="ai.reward_penalty.leaderboard_updated",
        text=(
            f"Reward/penalty leaderboard rebuilt · {len(AI_AGENTS)} AI agents"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "agents": len(AI_AGENTS),
            "triggered_by": triggered_by or "",
        },
    )
    return rebuilt


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _sweep_queryset(
    qs,
    *,
    start_date: date | None,
    end_date: date | None,
    triggered_by: str | None,
    dry_run: bool,
    sweep_label: str,
) -> SweepSummary:
    qs = _apply_date_filters(qs, start_date=start_date, end_date=end_date)
    triggered_by_str = (triggered_by or "").strip()

    write_event(
        kind="ai.reward_penalty.sweep_started",
        text=(
            f"Reward/penalty sweep started · {sweep_label} · "
            f"orders={qs.count()} · dry_run={dry_run}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "sweep": sweep_label,
            "dry_run": dry_run,
            "triggered_by": triggered_by_str,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
    )

    aggregate = SweepSummary(dry_run=dry_run)
    try:
        for order in qs.iterator():
            _, _, per_order = calculate_for_order(
                order,
                triggered_by=triggered_by_str,
                dry_run=dry_run,
            )
            aggregate.evaluated_orders += per_order.evaluated_orders
            aggregate.skipped_orders += per_order.skipped_orders
            aggregate.created_events += per_order.created_events
            aggregate.updated_events += per_order.updated_events
            aggregate.total_reward += per_order.total_reward
            aggregate.total_penalty += per_order.total_penalty
            aggregate.missing_data_warnings.extend(per_order.missing_data_warnings)
        aggregate.net_score = aggregate.total_reward - aggregate.total_penalty
    except Exception as exc:  # pragma: no cover - defensive
        write_event(
            kind="ai.reward_penalty.sweep_failed",
            text=(
                f"Reward/penalty sweep failed · {sweep_label} · {exc}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload={"sweep": sweep_label, "error": str(exc)},
        )
        raise

    if not dry_run:
        rebuild_agent_leaderboard(triggered_by=triggered_by_str)
        aggregate.leaderboard_updated = True

    write_event(
        kind="ai.reward_penalty.sweep_completed",
        text=(
            f"Reward/penalty sweep completed · {sweep_label} · "
            f"evaluated={aggregate.evaluated_orders} · "
            f"reward={aggregate.total_reward} · penalty={aggregate.total_penalty} · "
            f"net={aggregate.net_score}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "sweep": sweep_label,
            "dry_run": dry_run,
            **aggregate.as_dict(),
        },
    )
    return aggregate


def _apply_date_filters(
    qs, *, start_date: date | None, end_date: date | None
):
    """Filter a queryset by ``Order.created_at`` if dates are provided."""
    if start_date is not None:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=_tz.utc)
        qs = qs.filter(created_at__gte=start_dt)
    if end_date is not None:
        end_dt = datetime.combine(
            end_date + timedelta(days=1), datetime.min.time(), tzinfo=_tz.utc
        )
        qs = qs.filter(created_at__lt=end_dt)
    return qs


def _attribute_event(
    order: Order,
    result: OrderRewardPenaltyResult,
    *,
    is_failed_stage: bool,
) -> list[dict[str, Any]]:
    """Decide which AI agents collect points for this order's result.

    Returns one ``dict`` per persisted event with ``unique_key`` and the
    ``defaults`` payload :class:`RewardPenaltyEvent` needs.

    Phase 4B locked rule: CEO AI **always** receives net accountability.
    For delivered orders that's a reward; for RTO / cancelled orders
    that's a penalty.
    """
    plan: list[dict[str, Any]] = []
    component_lookup = _index_components(result)

    # ----- CEO AI net accountability (always present) -----
    plan.append(
        _make_attribution(
            order=order,
            agent=AI_AGENT_BY_ID["ceo"],
            event_type=(
                RewardPenaltyEvent.EventType.PENALTY
                if is_failed_stage
                else RewardPenaltyEvent.EventType.REWARD
            ),
            reward_score=0 if is_failed_stage else result.reward_total,
            penalty_score=result.penalty_total if is_failed_stage else 0,
            components=_components_for_ceo(result, is_failed_stage),
            missing_data=list(result.missing_data),
            attribution={
                "rule": "ceo_ai_net_accountability",
                "stage": order.stage,
            },
        )
    )

    # ----- Domain attributions (only when matching components are present) -----
    delivered_attribution: list[tuple[str, str | None, list[str]]] = [
        # (agent_id, primary_event_type override, component codes)
        ("ads", None, ["healthy_net_profit"]),
        ("marketing", None, ["healthy_net_profit"]),
        (
            "sales",
            None,
            ["delivered_order", "advance_paid"],
        ),
        ("calling-tl", None, ["delivered_order", "advance_paid"]),
        (
            "confirmation",
            None,
            ["clean_data"],
        ),
        (
            "rto",
            None,
            # Only awards if RTO risk had been raised but order delivered.
            ["delivered_order"]
            if order.rto_risk in (Order.RtoRisk.HIGH, Order.RtoRisk.MEDIUM)
            else [],
        ),
        ("success", None, ["customer_satisfaction_positive", "reorder_potential_high"]),
        ("dq", None, ["clean_data"]),
        ("compliance", None, ["compliance_safe"]),
    ]
    failed_attribution: list[tuple[str, list[str]]] = [
        ("rto", ["rto_after_dispatch", "ignored_rto_warning"]),
        (
            "sales",
            [
                "no_advance_high_risk_cod",
                "discount_leakage_11_to_20_without_reason",
                "unauthorized_discount_above_20",
            ],
        ),
        (
            "calling-tl",
            ["cancelled_after_punch", "no_advance_high_risk_cod"],
        ),
        (
            "confirmation",
            ["wrong_or_incomplete_address", "cancelled_after_punch"],
        ),
        ("ads", ["bad_fake_lead_quality"]),
        # Marketing only when there's evidence — handled via components.
        ("marketing", []),
        ("compliance", ["risky_claim", "side_effect_legal_refund_mishandled"]),
        ("dq", ["wrong_or_incomplete_address"]),
    ]

    if is_failed_stage:
        for agent_id, codes in failed_attribution:
            agent = AI_AGENT_BY_ID[agent_id]
            matched = _match_components(component_lookup, codes, want_negative=True)
            if not matched:
                continue
            penalty = sum(-entry.points for entry in matched)
            plan.append(
                _make_attribution(
                    order=order,
                    agent=agent,
                    event_type=RewardPenaltyEvent.EventType.PENALTY,
                    reward_score=0,
                    penalty_score=min(penalty, PENALTY_MAX_TOTAL),
                    components=_serialize_entries(matched),
                    missing_data=list(result.missing_data),
                    attribution={
                        "rule": "phase4b_failed_attribution",
                        "agent_id": agent_id,
                        "matched_codes": [e.code for e in matched],
                    },
                )
            )
    else:
        for agent_id, override_type, codes in delivered_attribution:
            agent = AI_AGENT_BY_ID[agent_id]
            matched = _match_components(component_lookup, codes, want_negative=False)
            if not matched:
                continue
            reward = sum(entry.points for entry in matched)
            plan.append(
                _make_attribution(
                    order=order,
                    agent=agent,
                    event_type=override_type
                    or RewardPenaltyEvent.EventType.REWARD,
                    reward_score=min(reward, REWARD_MAX_TOTAL),
                    penalty_score=0,
                    components=_serialize_entries(matched),
                    missing_data=list(result.missing_data),
                    attribution={
                        "rule": "phase4b_delivered_attribution",
                        "agent_id": agent_id,
                        "matched_codes": [e.code for e in matched],
                    },
                )
            )

    return plan


def _index_components(
    result: OrderRewardPenaltyResult,
) -> dict[str, ScoreEntry]:
    out: dict[str, ScoreEntry] = {}
    for entry in result.rewards:
        out[entry.code] = entry
    for entry in result.penalties:
        out[entry.code] = entry
    return out


def _match_components(
    lookup: Mapping[str, ScoreEntry],
    codes: Iterable[str],
    *,
    want_negative: bool,
) -> list[ScoreEntry]:
    matched: list[ScoreEntry] = []
    for code in codes:
        entry = lookup.get(code)
        if entry is None:
            continue
        is_negative = entry.points < 0
        if want_negative and is_negative:
            matched.append(entry)
        elif not want_negative and not is_negative:
            matched.append(entry)
    return matched


def _serialize_entries(entries: Iterable[ScoreEntry]) -> list[dict[str, Any]]:
    return [
        {"code": e.code, "label": e.label, "points": int(e.points)}
        for e in entries
    ]


def _components_for_ceo(
    result: OrderRewardPenaltyResult, is_failed_stage: bool
) -> list[dict[str, Any]]:
    """The CEO AI accountability event mirrors the order's totals."""
    if is_failed_stage:
        return [
            {
                "code": "ceo_net_accountability_penalty",
                "label": "CEO AI net accountability (failed order)",
                "points": -int(result.penalty_total),
            }
        ]
    return [
        {
            "code": "ceo_net_accountability_reward",
            "label": "CEO AI net accountability (delivered order)",
            "points": int(result.reward_total),
        }
    ]


def _make_attribution(
    *,
    order: Order,
    agent: AiAgentInfo,
    event_type: str,
    reward_score: int,
    penalty_score: int,
    components: list[dict[str, Any]],
    missing_data: list[str],
    attribution: dict[str, Any],
) -> dict[str, Any]:
    unique_key = (
        f"{RewardPenaltyEvent.SOURCE_PHASE_4B_ENGINE}:"
        f"{order.id}:{agent.agent_id}:{event_type}"
    )
    return {
        "unique_key": unique_key,
        "order": order,
        "agent_info": agent,
        "event_type": event_type,
        "reward_score": reward_score,
        "penalty_score": penalty_score,
        "components": components,
        "missing_data": missing_data,
        "attribution": attribution,
    }


def _event_defaults(
    order: Order, entry: dict[str, Any], triggered_by: str
) -> dict[str, Any]:
    agent: AiAgentInfo = entry["agent_info"]
    net = int(entry["reward_score"]) - int(entry["penalty_score"])
    return {
        "id": entry["unique_key"][:64],
        "order_id": order.id,
        "order_id_snapshot": order.id,
        "agent_id": _agent_pk_or_none(agent.agent_id),
        "agent_name": agent.name,
        "agent_type": agent.agent_type,
        "event_type": entry["event_type"],
        "reward_score": int(entry["reward_score"]),
        "penalty_score": int(entry["penalty_score"]),
        "net_score": net,
        "components": entry["components"],
        "missing_data": entry["missing_data"],
        "attribution": entry["attribution"],
        "source": RewardPenaltyEvent.SOURCE_PHASE_4B_ENGINE,
        "triggered_by": triggered_by or "",
        "metadata": {
            "stage": order.stage,
            "rto_risk": order.rto_risk,
            "discount_pct": int(order.discount_pct or 0),
        },
    }


def _agent_pk_or_none(agent_id: str) -> str | None:
    """Resolve an Agent FK if the seeded row exists; otherwise return ``None``."""
    if not agent_id:
        return None
    from apps.agents.models import Agent

    if Agent.objects.filter(pk=agent_id).exists():
        return agent_id
    return None


def _build_event_instance(
    order: Order, entry: dict[str, Any], triggered_by: str
) -> RewardPenaltyEvent:
    """Unsaved instance for ``dry_run`` previews."""
    defaults = _event_defaults(order, entry, triggered_by)
    defaults["unique_key"] = entry["unique_key"]
    defaults.pop("order_id", None)
    return RewardPenaltyEvent(order=order, **defaults)


__all__ = (
    "AI_AGENTS",
    "AI_AGENT_BY_ID",
    "EXCLUDED_AGENTS",
    "ELIGIBLE_DELIVERED_STAGES",
    "ELIGIBLE_FAILED_STAGES",
    "ELIGIBLE_STAGES",
    "SweepSummary",
    "build_reward_context",
    "calculate_for_order",
    "calculate_for_delivered_orders",
    "calculate_for_failed_orders",
    "calculate_for_all_eligible_orders",
    "rebuild_agent_leaderboard",
)
