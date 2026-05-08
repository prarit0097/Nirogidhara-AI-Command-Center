"""``python manage.py dry_run_delhivery_courier_readiness_gate \\
    --gate-id <ID> --json``.

Phase 7F - dry-run rehearsal. Walks invariants and writes a
``RazorpayCourierReadinessDryRunRecord`` of ``kind=dry_run``. NEVER
calls Delhivery; NEVER creates a Shipment / WorkflowStep /
RescueAttempt / AWB / pickup / label; NEVER sends WhatsApp; NEVER
mutates real business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_readiness import dry_run_phase7f_gate


class Command(BaseCommand):
    help = (
        "Phase 7F - dry-run a courier readiness gate (no provider "
        "call; no Delhivery call; no Shipment / AWB / pickup / "
        "label creation; no WhatsApp send; no business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = dry_run_phase7f_gate(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry-run passed gate_id={report['gate']['id']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Dry-run blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
