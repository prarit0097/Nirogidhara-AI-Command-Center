"""``python manage.py rollback_dry_run_delhivery_courier_readiness_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 7F - rollback-dry-run rehearsal. Re-validates invariants
AFTER the dry-run pass to prove no row leaked. NEVER calls
Delhivery; NEVER creates a Shipment / AWB / pickup / label; NEVER
sends WhatsApp; NEVER mutates real business rows. Reason text
required.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_readiness import (
    rollback_dry_run_phase7f_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7F - rollback-dry-run a courier readiness gate (no "
        "provider call; no Delhivery call; no Shipment / AWB / "
        "pickup / label creation; no WhatsApp send; no business "
        "mutation; reason required)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string for Phase 7F rollback dry-run"
            )
        report = rollback_dry_run_phase7f_gate(gate_id, reason=reason)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rollback dry-run passed gate_id={report['gate']['id']}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR("Rollback dry-run blocked.")
            )
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
