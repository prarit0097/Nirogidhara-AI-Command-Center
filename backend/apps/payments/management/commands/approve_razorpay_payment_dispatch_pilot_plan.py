"""``python manage.py approve_razorpay_payment_dispatch_pilot_plan \\
    --plan-id <ID> --reason "..." --json``.

Phase 6S — approve a pilot plan **for future Phase 6T only**. NEVER
starts a pilot; NEVER sends WhatsApp; NEVER queues an outbound;
NEVER calls Meta Cloud / Delhivery / Razorpay; NEVER creates a
shipment / AWB; NEVER mutates real ``Order`` / ``Payment`` /
``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead``.
Reason text required.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    approve_phase6s_payment_dispatch_pilot_plan,
)


class Command(BaseCommand):
    help = (
        "Phase 6S — approve a Limited Internal Dispatch Pilot Plan for "
        "future Phase 6T. No pilot execution; no WhatsApp send; no "
        "courier call; no real business mutation; no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        plan_id = int(options["plan_id"])
        if plan_id <= 0:
            raise CommandError("--plan-id must be a positive integer")
        report = approve_phase6s_payment_dispatch_pilot_plan(
            plan_id,
            reviewed_by=None,
            reason=options.get("reason") or "",
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Pilot plan {report['plan']['id']} -> "
                    f"{report['plan']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approval blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
