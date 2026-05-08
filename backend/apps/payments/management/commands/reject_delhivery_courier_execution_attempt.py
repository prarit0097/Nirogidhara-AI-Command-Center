"""``python manage.py reject_delhivery_courier_execution_attempt --attempt-id N --reason "..." --json``.

Phase 7G - mark a Phase 7G attempt rejected. Reject requires a
non-empty ``--reason``. NEVER calls Delhivery; NEVER mutates real
business tables.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution import (
    reject_phase7g_courier_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - mark a Phase 7G attempt rejected. No Delhivery "
        "call, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--reason",
            default="",
            type=str,
            help="Mandatory non-empty rejection reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string."
            )
        report = reject_phase7g_courier_execution_attempt(
            attempt_id, rejected_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 7G attempt rejected attempt_id="
                    f"{attempt['id']} status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Reject blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
