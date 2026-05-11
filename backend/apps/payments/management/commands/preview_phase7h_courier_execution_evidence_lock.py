"""``python manage.py preview_phase7h_courier_execution_evidence_lock --attempt-id N --json``.

Phase 7H - read-only preview of an evidence-lock derived from a
completed Phase 7G TEST/MOCK courier execution attempt. NEVER
creates rows; NEVER calls Delhivery; NEVER mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution_evidence_lock import (
    preview_phase7h_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7H - read-only preview of an evidence-lock derived "
        "from a completed Phase 7G courier execution attempt."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id",
            required=True,
            type=int,
            help="ID of the source Phase 7G courier execution attempt.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        report = preview_phase7h_evidence_lock(attempt_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7H Evidence Lock Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  attemptId  : {report['attemptId']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(f"  nextAction : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
