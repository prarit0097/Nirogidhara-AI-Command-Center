"""``python manage.py preview_razorpay_controlled_pilot_gate \\
    --phase6t-lock-id <ID> --json``.

Phase 7B - read-only preview. NEVER creates rows; NEVER calls a
provider; NEVER sends WhatsApp; NEVER calls Meta Cloud / Delhivery;
NEVER mutates real business tables.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_gate import (
    preview_phase7b_controlled_pilot_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7B - preview a Controlled Pilot Execution Gate from a "
        "locked Phase 6T final audit lock. Read-only. Never creates "
        "rows; never calls a provider."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--phase6t-lock-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        lock_id = int(options.get("phase6t_lock_id") or 0)
        if lock_id <= 0:
            raise CommandError(
                "--phase6t-lock-id must be a positive integer"
            )
        report = preview_phase7b_controlled_pilot_gate(lock_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if not report.get("found"):
            self.stdout.write(
                self.style.ERROR(
                    "Source Phase 6T final audit lock not found."
                )
            )
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 7B preview event={report['eventName']}"
            )
        )
        self.stdout.write(f"  eligible: {report['eligible']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
