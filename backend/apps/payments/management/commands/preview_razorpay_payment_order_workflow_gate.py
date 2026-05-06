"""``python manage.py preview_razorpay_payment_order_workflow_gate --attempt-id <ID> --json``.

Phase 6Q — read-only preview. NEVER creates rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_order_workflow_gate import (
    preview_phase6q_payment_order_workflow_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6Q — preview a payment-order workflow gate. Read-only. "
        "Never mutates business tables; never calls Razorpay."
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
        report = preview_phase6q_payment_order_workflow_gate(
            source_attempt_id=attempt_id or None,
            ledger_id=ledger_id or None,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if not report.get("found"):
            self.stdout.write(self.style.ERROR("Source not found."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 6Q preview · event={report['eventName']}"
            )
        )
        self.stdout.write(f"  eligible: {report['eligible']}")
        if report.get("proposedContract"):
            c = report["proposedContract"]
            self.stdout.write(
                f"  proposed payment status : {c['futurePaymentStatus']}"
            )
            self.stdout.write(
                f"  proposed order status   : {c['futureOrderStatusCandidate']}"
            )
            self.stdout.write(
                f"  proposed workflow action: {c['workflowAction']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
