"""``python manage.py preview_delhivery_courier_readiness_gate \\
    --phase7e-gate-id <ID> --json``.

Phase 7F - read-only preview from a Phase 7E approved gate. Never
creates rows, never calls Delhivery, never sends WhatsApp, never
mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_readiness import preview_phase7f_gate


class Command(BaseCommand):
    help = (
        "Phase 7F - preview a courier readiness gate from a Phase "
        "7E approved gate (read-only; no provider call; no business "
        "mutation; no Delhivery call)."
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
        report = preview_phase7f_gate(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 7F preview for Phase 7E gate id={gate_id}"
            )
        )
        self.stdout.write(f"  found       : {report['found']}")
        self.stdout.write(f"  eligible    : {report['eligible']}")
        self.stdout.write(
            f"  phase 7D    : {report.get('sourcePhase7DAttemptId')}"
        )
        self.stdout.write(
            f"  phase 7B    : {report.get('sourcePhase7BGateId')}"
        )
        self.stdout.write(
            f"  phase 6T    : {report.get('sourcePhase6TLockId')}"
        )
        self.stdout.write(
            f"  hotfix-1    : {report.get('phase7DHotfix1Present')}"
        )
        self.stdout.write(
            f"  delhivery   : {report.get('delhiveryModeAtPreview')}"
        )
        self.stdout.write(f"  nextAction  : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
