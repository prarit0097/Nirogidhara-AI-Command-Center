"""``python manage.py rollback_dry_run_phase8a_payment_order_mutation_sandbox \\
    --dry-run-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8a_payment_order_mutation_sandbox import (
    rollback_dry_run_phase8a_payment_order_mutation_sandbox,
)


class Command(BaseCommand):
    help = (
        "Phase 8A — record-only rollback for a sandbox dry-run. "
        "Never calls a provider; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty rollback reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        dry_run_id = int(options["dry_run_id"])
        if dry_run_id <= 0:
            raise CommandError("--dry-run-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = (
            rollback_dry_run_phase8a_payment_order_mutation_sandbox(
                dry_run_id, reason=reason
            )
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            dry = report["dryRun"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8A dry-run rollback recorded record_id="
                    f"{dry['id']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Rollback blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
