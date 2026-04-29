"""Phase 5E — run the Day-20 reorder reminder sweep.

Idempotent. Safe to re-run on cron (e.g. daily at 10:00 IST). The
lifecycle layer dedupes on the
``lifecycle:whatsapp.reorder_day20_reminder:order:{id}:day20`` key.

Usage::

    python manage.py run_reorder_day20_sweep
    python manage.py run_reorder_day20_sweep --dry-run
    python manage.py run_reorder_day20_sweep --json
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.whatsapp.reorder import run_day20_reorder_sweep


class Command(BaseCommand):
    help = "Run the Day-20 reorder reminder sweep across delivered orders."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report eligible orders without queuing any send.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="emit_json",
            help="Emit the sweep summary as JSON.",
        )

    def handle(self, *args, **options) -> None:
        result = run_day20_reorder_sweep(dry_run=bool(options.get("dry_run")))
        if options.get("emit_json"):
            self.stdout.write(json.dumps(result.to_dict(), indent=2))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Day-20 reorder sweep · "
            f"eligible={result.eligible} queued={result.queued} "
            f"skipped={result.skipped} blocked={result.blocked} "
            f"failed={result.failed} dryRun={result.dry_run}"
        ))
