"""``python manage.py prepare_razorpay_payment_order_workflow_gate --attempt-id <ID> --json``.

Phase 6Q — create / re-fetch a workflow gate review row. NEVER
mutates real business tables; NEVER calls Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_order_workflow_gate import (
    prepare_phase6q_payment_order_workflow_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6Q — prepare a Payment → Order workflow safety gate row "
        "for an eligible Phase 6P sandbox attempt. No real business "
        "mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", type=int, default=0)
        parser.add_argument("--ledger-id", type=int, default=0)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options.get("attempt_id") or 0)
        ledger_id = int(options.get("ledger_id") or 0)
        if attempt_id <= 0 and ledger_id <= 0:
            raise CommandError(
                "Provide --attempt-id or --ledger-id (positive integer)."
            )
        report = prepare_phase6q_payment_order_workflow_gate(
            source_attempt_id=attempt_id or None,
            ledger_id=ledger_id or None,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared gate id={report['gate']['id']} status={report['gate']['status']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused gate id={report['gate']['id']} status={report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
