"""``python manage.py prepare_razorpay_payment_dispatch_readiness_gate \\
    --gate-id <PHASE6Q_GATE_ID> --json``.

Phase 6R — create / re-fetch a dispatch readiness gate review row.
NEVER mutates real business tables; NEVER sends WhatsApp; NEVER calls
Meta Cloud / Delhivery.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_readiness import (
    prepare_phase6r_payment_dispatch_readiness_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6R — prepare a Payment → WhatsApp/Courier dispatch "
        "readiness gate row for an approved Phase 6Q workflow gate. No "
        "real business mutation; no WhatsApp send; no courier call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options.get("gate_id") or 0)
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = prepare_phase6r_payment_dispatch_readiness_gate(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared readiness gate id={report['readiness']['id']} "
                    f"status={report['readiness']['status']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused readiness gate id={report['readiness']['id']} "
                    f"status={report['readiness']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
