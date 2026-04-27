"""Per-agent budget guard — Phase 3D.

Two periods are tracked, daily and monthly. Spend is computed at runtime
by summing ``AgentRun.cost_usd`` for the relevant agent + period. The
runtime calls ``check_budget_before_run`` BEFORE building the prompt and
dispatching to a provider — that way a blocked run never racks up
network cost. Blocking writes a ``failed`` AgentRun + ``ai.budget.blocked``
audit. Crossing the alert threshold writes a ``ai.budget.warning`` audit
but still allows the call.

Compliance: ``check_budget_before_run`` returns BEFORE the dispatcher is
called, so a budget block does NOT trigger the provider fallback chain.
ClaimVaultMissing is checked even earlier — also no fallback. Both refusals
fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone as _tz
from decimal import Decimal
from typing import Any, Literal

from django.db.models import Sum
from django.utils import timezone

from .models import AgentBudget, AgentRun


Period = Literal["daily", "monthly"]


# ----- Result dataclass -----


@dataclass(frozen=True)
class BudgetCheckResult:
    """The full picture the runtime needs to decide what to do."""

    has_budget: bool
    is_enforced: bool
    daily_budget_usd: Decimal
    monthly_budget_usd: Decimal
    daily_spend_usd: Decimal
    monthly_spend_usd: Decimal
    threshold_pct: int
    status: str  # "ok" | "warning" | "blocked"
    reason: str  # human-readable explanation when blocked / warning

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def warning(self) -> bool:
        return self.status == "warning"

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "has_budget": self.has_budget,
            "is_enforced": self.is_enforced,
            "daily_budget_usd": str(self.daily_budget_usd),
            "monthly_budget_usd": str(self.monthly_budget_usd),
            "daily_spend_usd": str(self.daily_spend_usd),
            "monthly_spend_usd": str(self.monthly_spend_usd),
            "threshold_pct": self.threshold_pct,
            "status": self.status,
            "reason": self.reason,
        }


# ----- Helpers -----


def _start_of_day(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(_tz.utc).date(), time.min, tzinfo=_tz.utc)


def _start_of_month(now: datetime) -> datetime:
    aware = now.astimezone(_tz.utc)
    return datetime(aware.year, aware.month, 1, tzinfo=_tz.utc)


def get_agent_budget(agent: str) -> AgentBudget | None:
    """Return the persisted budget row for ``agent`` (or None)."""
    return AgentBudget.objects.filter(agent=agent).first()


def calculate_agent_spend(
    *, agent: str, period: Period = "daily", now: datetime | None = None
) -> Decimal:
    """Sum ``AgentRun.cost_usd`` for ``agent`` over the given period.

    Only ``status=success`` runs count — failed / skipped runs incur no
    actual provider cost. ``cost_usd`` is in USD on the AgentRun row;
    returns Decimal("0") when no successful run exists for the period.
    """
    now = now or timezone.now()
    if period == "daily":
        boundary = _start_of_day(now)
    else:
        boundary = _start_of_month(now)

    total = (
        AgentRun.objects.filter(
            agent=agent,
            status=AgentRun.Status.SUCCESS,
            cost_usd__isnull=False,
            completed_at__gte=boundary,
        ).aggregate(total=Sum("cost_usd"))["total"]
        or Decimal("0")
    )
    return Decimal(total)


def check_budget_before_run(
    *, agent: str, now: datetime | None = None
) -> BudgetCheckResult:
    """Decide whether the runtime should dispatch a call for ``agent``.

    No budget row → ``status=ok`` + ``has_budget=False`` (the runtime
    proceeds without a guard). With a budget row, we sum the period's
    spend, compare against the budget, and pick:
    - ``blocked`` when spend ≥ budget AND the row is enforced
    - ``warning`` when spend ≥ ``alert_threshold_pct`` of the budget
    - ``ok`` otherwise

    Daily budget is checked first — a daily breach alone is enough to
    block. The monthly budget is the secondary guard.
    """
    budget = get_agent_budget(agent)
    if budget is None:
        return BudgetCheckResult(
            has_budget=False,
            is_enforced=False,
            daily_budget_usd=Decimal("0"),
            monthly_budget_usd=Decimal("0"),
            daily_spend_usd=Decimal("0"),
            monthly_spend_usd=Decimal("0"),
            threshold_pct=0,
            status="ok",
            reason="no budget configured",
        )

    daily_spend = calculate_agent_spend(agent=agent, period="daily", now=now)
    monthly_spend = calculate_agent_spend(agent=agent, period="monthly", now=now)
    daily = Decimal(budget.daily_budget_usd)
    monthly = Decimal(budget.monthly_budget_usd)
    threshold = max(0, min(int(budget.alert_threshold_pct or 0), 100))

    daily_ratio = (daily_spend / daily) if daily > 0 else Decimal("0")
    monthly_ratio = (monthly_spend / monthly) if monthly > 0 else Decimal("0")
    over_daily = daily > 0 and daily_spend >= daily
    over_monthly = monthly > 0 and monthly_spend >= monthly

    if budget.is_enforced and (over_daily or over_monthly):
        period_label = "daily" if over_daily else "monthly"
        status = "blocked"
        reason = (
            f"{period_label} budget exceeded: ${period_label_spend(period_label, daily_spend, monthly_spend)} "
            f"vs ${period_label_budget(period_label, daily, monthly)}"
        )
    elif (
        threshold > 0
        and (
            daily_ratio * 100 >= threshold or monthly_ratio * 100 >= threshold
        )
    ):
        status = "warning"
        reason = (
            f"spend at {max(daily_ratio, monthly_ratio) * 100:.0f}% of budget "
            f"(threshold {threshold}%)"
        )
    else:
        status = "ok"
        reason = "within budget"

    return BudgetCheckResult(
        has_budget=True,
        is_enforced=bool(budget.is_enforced),
        daily_budget_usd=daily,
        monthly_budget_usd=monthly,
        daily_spend_usd=daily_spend,
        monthly_spend_usd=monthly_spend,
        threshold_pct=threshold,
        status=status,
        reason=reason,
    )


def period_label_spend(label: str, daily: Decimal, monthly: Decimal) -> Decimal:
    return daily if label == "daily" else monthly


def period_label_budget(label: str, daily: Decimal, monthly: Decimal) -> Decimal:
    return daily if label == "daily" else monthly


__all__ = (
    "BudgetCheckResult",
    "calculate_agent_spend",
    "check_budget_before_run",
    "get_agent_budget",
)
