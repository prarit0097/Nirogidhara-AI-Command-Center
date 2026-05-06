"""``python manage.py approve_razorpay_payment_order_workflow_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 6Q — approve a workflow gate **for future Phase 6R only**. NEVER
mutates real ``Order`` / ``Payment`` / ``Shipment`` /
``DiscountOfferLog`` / ``Customer`` / ``Lead``. Reason text required.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_order_workflow_gate import (
    approve_phase6q_payment_order_workflow_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6Q — approve a workflow safety gate for future Phase 6R. "
        "No real business mutation, no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = approve_phase6q_payment_order_workflow_gate(
            gate_id, reviewed_by=None, reason=options.get("reason") or ""
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Gate {report['gate']['id']} -> {report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approval blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
