"""``python manage.py rollback_dry_run_razorpay_controlled_pilot_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 7B - rollback dry-run rehearsal record. Rehearses the synthetic
gate-state revert path. NEVER calls a provider; NEVER flips an env
flag; NEVER mutates real business tables.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_gate import (
    rollback_dry_run_phase7b_controlled_pilot_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7B - rollback dry-run a Controlled Pilot Execution "
        "Gate. Writes a rollback dry-run record only; no provider "
        "call; no env flag flip; no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options.get("gate_id") or 0)
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = rollback_dry_run_phase7b_controlled_pilot_gate(
            gate_id,
            reason=options.get("reason") or "",
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rollback dry-run passed gate_id={report['gate']['id']} "
                    f"record_id={report['record']['id']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Rollback dry-run failed."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
