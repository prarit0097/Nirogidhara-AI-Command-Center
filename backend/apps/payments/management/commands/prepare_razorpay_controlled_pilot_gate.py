"""``python manage.py prepare_razorpay_controlled_pilot_gate \\
    --phase6t-lock-id <ID> --json``.

Phase 7B - create / re-fetch a Controlled Pilot Execution Gate row.
NEVER calls a provider; NEVER sends WhatsApp; NEVER calls Meta Cloud
/ Delhivery; NEVER creates a shipment / AWB; NEVER mutates real
business tables.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_gate import (
    prepare_phase7b_controlled_pilot_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7B - prepare a Controlled Pilot Execution Gate row "
        "from a locked Phase 6T final audit lock. Gate-only; no "
        "provider call; no business mutation; no customer "
        "notification."
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
        report = prepare_phase7b_controlled_pilot_gate(lock_id)
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
