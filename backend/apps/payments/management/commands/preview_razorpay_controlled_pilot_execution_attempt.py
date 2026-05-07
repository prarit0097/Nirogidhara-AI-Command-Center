"""``python manage.py preview_razorpay_controlled_pilot_execution_attempt \\
    --gate-id <PHASE_7B_GATE_ID> --json``.

Phase 7D - read-only preview that walks the Phase 7B -> 6T -> 6S ->
6R -> 6Q -> 6P -> 6O -> 6M source chain. NEVER creates rows; NEVER
calls Razorpay; NEVER sends WhatsApp; NEVER mutates business
tables; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_execution import (
    preview_phase7d_razorpay_test_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - preview a Razorpay controlled pilot execution "
        "attempt for a Phase 7B gate (read-only; no provider call; "
        "no business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = preview_phase7d_razorpay_test_execution_attempt(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 7D preview for Phase 7B gate id={gate_id}"
            )
        )
        self.stdout.write(f"  found       : {report['found']}")
        self.stdout.write(f"  eligible    : {report['eligible']}")
        self.stdout.write(
            f"  phase 6T    : {report['sourcePhase6TLockId']}"
        )
        self.stdout.write(f"  nextAction  : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
