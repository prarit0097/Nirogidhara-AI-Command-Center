"""``python manage.py archive_razorpay_controlled_pilot_execution_attempt \\
    --attempt-id <ID> --reason "..." --json``.

Phase 7D - archive a controlled pilot execution attempt. NEVER
calls Razorpay; NEVER sends WhatsApp; NEVER mutates business
tables; NEVER edits any ``.env*`` file. Reason text required.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_execution import (
    archive_phase7d_razorpay_test_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - archive a controlled pilot execution attempt. "
        "No provider call; no business mutation; reason required."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError("--attempt-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string for Phase 7D archive"
            )
        report = archive_phase7d_razorpay_test_execution_attempt(
            attempt_id, archived_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Attempt {attempt['id']} -> {attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
