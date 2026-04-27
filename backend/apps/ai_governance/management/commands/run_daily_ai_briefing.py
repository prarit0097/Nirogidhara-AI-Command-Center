"""``python manage.py run_daily_ai_briefing`` — Phase 3B scheduler scaffold.

Calls the CEO daily-briefing agent, then the CAIO audit sweep. Both are
read-only / dry-run by construction (the underlying
``run_readonly_agent_analysis`` enforces this regardless of provider).

When ``AI_PROVIDER=disabled`` (the default) every run logs as ``skipped`` —
no network call. The command is safe to wire to cron / Windows Task
Scheduler / Celery beat without further guards.

Phase 3C will replace this with a Celery beat schedule once the rest of
the operations team has Redis available.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai_governance.services.agents import caio, ceo


class Command(BaseCommand):
    help = "Run the CEO daily briefing + CAIO audit sweep (both dry-run)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--triggered-by",
            default="cron",
            help="Tag the AgentRun rows with this triggered_by label.",
        )
        parser.add_argument(
            "--skip-caio",
            action="store_true",
            help="Run only the CEO briefing (skip the CAIO sweep).",
        )
        parser.add_argument(
            "--skip-ceo",
            action="store_true",
            help="Run only the CAIO sweep (skip the CEO briefing).",
        )

    def handle(self, *args, **options) -> None:
        triggered_by = options["triggered_by"]

        if not options["skip_ceo"]:
            self.stdout.write(self.style.NOTICE("CEO daily briefing..."))
            ceo_run = ceo.run(triggered_by=triggered_by)
            self.stdout.write(
                f"  CEO run {ceo_run.id} status={ceo_run.status} provider={ceo_run.provider}"
            )

        if not options["skip_caio"]:
            self.stdout.write(self.style.NOTICE("CAIO audit sweep..."))
            caio_run = caio.run(triggered_by=triggered_by)
            self.stdout.write(
                f"  CAIO run {caio_run.id} status={caio_run.status} provider={caio_run.provider}"
            )

        self.stdout.write(self.style.SUCCESS("Done."))
