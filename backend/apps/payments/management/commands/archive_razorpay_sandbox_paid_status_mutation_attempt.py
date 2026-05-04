"""``python manage.py archive_razorpay_sandbox_paid_status_mutation_attempt \\
    --attempt-id <ID> --reason "..." --json``.

Phase 6P — archive a sandbox mutation attempt. Audit-only.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    archive_phase6p_paid_status_mutation_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — archive a sandbox mutation attempt. No real "
        "business mutation, no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = options["attempt_id"]
        if attempt_id <= 0:
            raise CommandError("--attempt-id must be a positive integer")

        report = archive_phase6p_paid_status_mutation_attempt(
            attempt_id,
            reason=options.get("reason") or "",
            archived_by=None,
        )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("archived"):
            self.stdout.write(
                self.style.WARNING(
                    f"Archived attempt id={report['attempt']['id']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
