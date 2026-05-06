"""``python manage.py archive_razorpay_payment_order_workflow_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 6Q — archive a workflow safety gate. Audit-only.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_order_workflow_gate import (
    archive_phase6q_payment_order_workflow_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6Q — archive a workflow safety gate. No real business "
        "mutation, no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = archive_phase6q_payment_order_workflow_gate(
            gate_id, archived_by=None, reason=options.get("reason") or ""
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.WARNING(
                    f"Gate {report['gate']['id']} -> {report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
