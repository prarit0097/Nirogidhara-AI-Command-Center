"""``python manage.py prepare_razorpay_whatsapp_internal_notification_gate \\
    --attempt-id <PHASE_7D_ATTEMPT_ID> --json``.

Phase 7E - create / re-fetch a notification gate row. Idempotent on
the source Phase 7D attempt. NEVER calls a provider; NEVER sends or
queues WhatsApp; NEVER mutates real business rows; NEVER edits any
``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_notification import (
    prepare_phase7e_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - prepare a WhatsApp internal notification gate "
        "row from a Phase 7D attempt. Gate-only; no provider call; "
        "no WhatsApp send; no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        report = prepare_phase7e_gate(attempt_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared gate id={report['gate']['id']} "
                    f"status={report['gate']['status']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused gate id={report['gate']['id']} "
                    f"status={report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
