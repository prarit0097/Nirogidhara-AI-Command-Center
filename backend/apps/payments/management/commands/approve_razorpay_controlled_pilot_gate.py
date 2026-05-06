"""``python manage.py approve_razorpay_controlled_pilot_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 7B - approve a Controlled Pilot Execution Gate **for future
Phase 7C execution review only**. NEVER executes a pilot; NEVER
calls a provider; NEVER sends WhatsApp; NEVER mutates real business
tables. Reason text required. Requires dry_run_passed=True and
rollback_dry_run_passed=True.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_gate import (
    approve_phase7b_controlled_pilot_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7B - approve a Controlled Pilot Execution Gate for "
        "future Phase 7C execution review. No live execution; no "
        "provider call; no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = approve_phase7b_controlled_pilot_gate(
            gate_id,
            reviewed_by=None,
            reason=options.get("reason") or "",
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Gate {report['gate']['id']} -> "
                    f"{report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approval blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
