"""``python manage.py rollback_delhivery_courier_execution_attempt --attempt-id N --reason "..." --json``.

Phase 7G - record-only rollback. NEVER calls Delhivery cancel.
Sets ``rollback_status=recorded_only_no_provider_cancel`` on the
attempt and writes a ``RazorpayCourierExecutionRollback`` record.
NEVER mutates real business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution import (
    rollback_phase7g_courier_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - record-only rollback. Never calls Delhivery "
        "cancel; never mutates real business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--reason",
            default="",
            type=str,
            help="Mandatory non-empty rollback reason.",
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
        report = rollback_phase7g_courier_execution_attempt(
            attempt_id, rolled_back_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7G rollback recorded attempt_id="
                    f"{attempt['id']} status={attempt['status']} "
                    f"rollback_status={attempt.get('rollbackStatus')}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Rollback blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
