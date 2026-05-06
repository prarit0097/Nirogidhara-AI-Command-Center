"""``python manage.py preview_razorpay_payment_dispatch_readiness_gate \\
    --gate-id <PHASE6Q_GATE_ID> --json``.

Phase 6R — read-only preview. NEVER creates rows; NEVER sends WhatsApp;
NEVER calls Meta Cloud or Delhivery.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_readiness import (
    preview_phase6r_payment_dispatch_readiness_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6R — preview a payment dispatch readiness gate from an "
        "approved Phase 6Q workflow gate. Read-only. Never mutates "
        "business tables; never sends WhatsApp; never books courier."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options.get("gate_id") or 0)
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = preview_phase6r_payment_dispatch_readiness_gate(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if not report.get("found"):
            self.stdout.write(self.style.ERROR("Source Phase 6Q gate not found."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 6R preview · event={report['eventName']}"
            )
        )
        self.stdout.write(f"  eligible: {report['eligible']}")
        if report.get("proposedContract"):
            c = report["proposedContract"]
            self.stdout.write(
                f"  whatsapp action : {c['futureWhatsAppReadinessAction']}"
            )
            self.stdout.write(
                f"  courier action  : {c['futureCourierReadinessAction']}"
            )
            self.stdout.write(
                f"  dispatch action : {c['futureDispatchReadinessAction']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
