"""``python manage.py archive_phase8d_controlled_mutation_evidence_lock --lock-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8d_controlled_mutation_evidence_lock import (
    archive_phase8d_controlled_mutation_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 8D — archive an evidence lock. Never calls a "
        "provider; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--lock-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty archive reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        lock_id = int(options["lock_id"])
        if lock_id <= 0:
            raise CommandError("--lock-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = archive_phase8d_controlled_mutation_evidence_lock(
            lock_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            lock = report["lock"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8D evidence archived lock_id={lock['id']} "
                    f"status={lock['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
