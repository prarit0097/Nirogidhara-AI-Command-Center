"""``python manage.py prepare_razorpay_controlled_pilot_execution_attempt \\
    --gate-id <PHASE_7B_GATE_ID> --json``.

Phase 7D - create / re-fetch a Razorpay controlled pilot execution
attempt row from an approved Phase 7B Controlled Pilot Execution
Gate. NEVER calls a provider; NEVER sends WhatsApp; NEVER calls
Meta Cloud / Delhivery / Vapi; NEVER creates a shipment / AWB;
NEVER mutates Order / Payment / Shipment / DiscountOfferLog /
Customer / Lead; NEVER edits any ``.env*`` file. Idempotent on the
source Phase 7B gate.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_execution import (
    prepare_phase7d_razorpay_test_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - prepare a Razorpay controlled pilot execution "
        "attempt row from an approved Phase 7B gate. No provider "
        "call; no business mutation; no customer notification."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = prepare_phase7d_razorpay_test_execution_attempt(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared attempt id={attempt['id']} "
                    f"status={attempt['status']}"
                )
            )
        elif report.get("reused"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.WARNING(
                    f"Reused attempt id={attempt['id']} "
                    f"status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
