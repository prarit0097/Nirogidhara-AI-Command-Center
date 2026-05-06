"""``python manage.py prepare_razorpay_payment_dispatch_pilot_plan \\
    --readiness-id <PHASE6R_READINESS_ID> --json``.

Phase 6S — create / re-fetch a pilot plan review row. NEVER starts a
pilot; NEVER sends WhatsApp; NEVER queues an outbound; NEVER calls
Meta Cloud / Delhivery / Razorpay; NEVER creates a shipment / AWB;
NEVER mutates real business tables.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    prepare_phase6s_payment_dispatch_pilot_plan,
)


class Command(BaseCommand):
    help = (
        "Phase 6S — prepare a Limited Internal Dispatch Pilot Plan row "
        "for an approved Phase 6R readiness gate. No pilot execution; "
        "no WhatsApp send; no courier call; no provider call; no real "
        "business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--readiness-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        readiness_id = int(options.get("readiness_id") or 0)
        if readiness_id <= 0:
            raise CommandError("--readiness-id must be a positive integer")
        report = prepare_phase6s_payment_dispatch_pilot_plan(readiness_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared pilot plan id={report['plan']['id']} "
                    f"status={report['plan']['status']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused pilot plan id={report['plan']['id']} "
                    f"status={report['plan']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
