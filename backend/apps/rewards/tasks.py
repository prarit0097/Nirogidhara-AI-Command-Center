"""Phase 4B — Celery task wrapping the reward / penalty sweep.

Local dev runs in eager mode (``CELERY_TASK_ALWAYS_EAGER=true``) so
``.delay()`` runs synchronously and **no Redis is required**. Production
flips eager off and the worker / beat services pick this task up.

The task is read-and-derive only: it never writes to Lead / Order /
Payment / Shipment / Call rows. It only writes to
:class:`apps.rewards.RewardPenaltyEvent` + the legacy
:class:`apps.rewards.RewardPenalty` rollup + :class:`audit.AuditEvent`.
"""
from __future__ import annotations

from typing import Any

from celery import shared_task


@shared_task(name="apps.rewards.tasks.run_reward_penalty_sweep_task")
def run_reward_penalty_sweep_task(triggered_by: str = "") -> dict[str, Any]:
    """Run the all-eligible-orders sweep + rebuild the agent leaderboard."""
    # Import inside the task so the worker bootstrap stays lightweight
    # and Django app loading is finished by the time we touch ORM.
    from apps.rewards.engine import (
        calculate_for_all_eligible_orders,
        rebuild_agent_leaderboard,
    )

    summary = calculate_for_all_eligible_orders(
        triggered_by=triggered_by or "celery",
        dry_run=False,
    )
    rebuild_agent_leaderboard(triggered_by=triggered_by or "celery")
    return summary.as_dict()


__all__ = ("run_reward_penalty_sweep_task",)
