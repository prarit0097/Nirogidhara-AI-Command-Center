"""Phase 4B — ``python manage.py calculate_reward_penalties``.

Cron-friendly entry point that re-runs the reward / penalty engine over
delivered / RTO / cancelled orders. No Redis / Celery dependency.

Examples::

    python manage.py calculate_reward_penalties
    python manage.py calculate_reward_penalties --order-id NRG-20410
    python manage.py calculate_reward_penalties --dry-run
    python manage.py calculate_reward_penalties --start-date 2026-04-01 --end-date 2026-04-28
    python manage.py calculate_reward_penalties --rebuild-leaderboard
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError


def _parse_date(value: str | None) -> date | None:
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = (
        "Phase 4B reward / penalty sweep. Scores AI agents only; "
        "CEO AI always receives net accountability."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start-date", default=None)
        parser.add_argument("--end-date", default=None)
        parser.add_argument("--order-id", default=None)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute attribution + summary without persisting events.",
        )
        parser.add_argument(
            "--rebuild-leaderboard",
            action="store_true",
            help="After scoring, rebuild the agent leaderboard rollup.",
        )

    def handle(self, *args, **options) -> None:
        from apps.orders.models import Order
        from apps.rewards import engine

        order_id = options.get("order_id")
        start = _parse_date(options.get("start_date"))
        end = _parse_date(options.get("end_date"))
        dry_run = bool(options.get("dry_run"))
        rebuild_leaderboard = bool(options.get("rebuild_leaderboard"))
        triggered_by = "manage.calculate_reward_penalties"

        if order_id:
            try:
                order = Order.objects.get(pk=order_id)
            except Order.DoesNotExist as exc:
                raise CommandError(f"Order {order_id} not found.") from exc
            result, events, summary = engine.calculate_for_order(
                order, triggered_by=triggered_by, dry_run=dry_run
            )
            self._echo(summary.as_dict())
            if rebuild_leaderboard and not dry_run:
                engine.rebuild_agent_leaderboard(triggered_by=triggered_by)
                self.stdout.write(self.style.SUCCESS("Leaderboard rebuilt."))
            return

        summary = engine.calculate_for_all_eligible_orders(
            start_date=start,
            end_date=end,
            triggered_by=triggered_by,
            dry_run=dry_run,
        )
        self._echo(summary.as_dict())

        if rebuild_leaderboard and not dry_run:
            engine.rebuild_agent_leaderboard(triggered_by=triggered_by)
            self.stdout.write(self.style.SUCCESS("Leaderboard rebuilt."))

    def _echo(self, payload: dict[str, Any]) -> None:
        self.stdout.write(self.style.SUCCESS("Reward / Penalty sweep summary:"))
        for key in (
            "evaluatedOrders",
            "createdEvents",
            "updatedEvents",
            "skippedOrders",
            "totalReward",
            "totalPenalty",
            "netScore",
            "leaderboardUpdated",
            "dryRun",
        ):
            self.stdout.write(f"  {key}: {payload.get(key)}")
        warnings = payload.get("missingDataWarnings") or []
        if warnings:
            self.stdout.write(
                self.style.WARNING(
                    f"  missingDataWarnings: {len(warnings)} signals not derivable"
                )
            )
