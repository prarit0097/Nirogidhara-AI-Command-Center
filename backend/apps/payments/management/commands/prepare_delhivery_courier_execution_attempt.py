"""``python manage.py prepare_delhivery_courier_execution_attempt --gate-id N --json``.

Phase 7G - prepare a Phase 7G attempt row from an approved Phase 7F
gate. Atomic + idempotent on the source Phase 7F gate. NEVER calls
Delhivery; NEVER creates a Shipment / WorkflowStep / RescueAttempt;
NEVER creates an AWB; NEVER sends WhatsApp; NEVER mutates real
business rows; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution import (
    prepare_phase7g_courier_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - prepare a Phase 7G attempt from an approved "
        "Phase 7F gate. No Delhivery call, no Shipment / AWB row, "
        "no WhatsApp send, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--gate-id",
            required=True,
            type=int,
            help="ID of the source Phase 7F readiness gate.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = prepare_phase7g_courier_execution_attempt(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        attempt = report.get("attempt") or {}
        if report.get("created") or report.get("reused"):
            label = (
                "created" if report.get("created") else "reused"
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7G attempt {label} attempt_id="
                    f"{attempt.get('id')} status={attempt.get('status')}"
                )
            )
            self.stdout.write(
                f"  syntheticOrderId : {attempt.get('syntheticOrderId')}"
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(
            f"  nextAction       : {report['nextAction']}"
        )
