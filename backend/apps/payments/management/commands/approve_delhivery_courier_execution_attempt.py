"""``python manage.py approve_delhivery_courier_execution_attempt --attempt-id N --reason "..." --json``.

Phase 7G - mark the attempt approved for one-shot courier test/mock
review. Approval requires a non-empty ``--reason``. Approval does
NOT call Delhivery, does NOT mutate real business tables, does NOT
enable any provider call - the actual execute path requires a
SECOND, separately-approved Director window via
``execute_delhivery_courier_one_shot``.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution import (
    approve_phase7g_courier_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - mark a Phase 7G attempt approved for one-shot "
        "courier test/mock review. No Delhivery call, no Shipment / "
        "AWB / pickup / label, no business mutation, no provider "
        "call enabled."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--reason",
            default="",
            type=str,
            help=(
                "Mandatory non-empty manual review reason. The "
                "service NEVER returns the full text - only "
                "``directorSignoffPresent`` is exposed."
            ),
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
        report = approve_phase7g_courier_execution_attempt(
            attempt_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7G attempt approved attempt_id="
                    f"{attempt['id']} status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approve blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
