"""``python manage.py prepare_delhivery_courier_readiness_gate \\
    --phase7e-gate-id <ID> --json``.

Phase 7F - create / re-fetch a courier readiness gate row.
Idempotent on the source Phase 7E gate. NEVER calls Delhivery;
NEVER creates a Shipment / WorkflowStep / RescueAttempt; NEVER
creates an AWB; NEVER books a pickup; NEVER generates a courier
label; NEVER sends WhatsApp; NEVER mutates real business rows;
NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_readiness import prepare_phase7f_gate


class Command(BaseCommand):
    help = (
        "Phase 7F - prepare a courier readiness gate row from a "
        "Phase 7E approved gate. Gate-only; no provider call; no "
        "Delhivery call; no Shipment / AWB / pickup / label "
        "creation; no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--phase7e-gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["phase7e_gate_id"])
        if gate_id <= 0:
            raise CommandError(
                "--phase7e-gate-id must be a positive integer"
            )
        report = prepare_phase7f_gate(gate_id)
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
