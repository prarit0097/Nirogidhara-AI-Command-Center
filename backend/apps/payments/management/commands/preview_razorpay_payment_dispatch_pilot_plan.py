"""``python manage.py preview_razorpay_payment_dispatch_pilot_plan \\
    --readiness-id <PHASE6R_READINESS_ID> --json``.

Phase 6S — read-only preview. NEVER creates rows; NEVER starts a
pilot; NEVER sends WhatsApp; NEVER calls Meta Cloud / Delhivery /
Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    preview_phase6s_payment_dispatch_pilot_plan,
)


class Command(BaseCommand):
    help = (
        "Phase 6S — preview a pilot plan from an approved Phase 6R "
        "readiness gate. Read-only. Never creates rows; never starts a "
        "pilot; never sends WhatsApp; never calls Meta Cloud / "
        "Delhivery / Razorpay."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--readiness-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        readiness_id = int(options.get("readiness_id") or 0)
        if readiness_id <= 0:
            raise CommandError("--readiness-id must be a positive integer")
        report = preview_phase6s_payment_dispatch_pilot_plan(readiness_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if not report.get("found"):
            self.stdout.write(
                self.style.ERROR("Source Phase 6R readiness gate not found.")
            )
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 6S preview · event={report['eventName']}"
            )
        )
        self.stdout.write(f"  eligible: {report['eligible']}")
        if report.get("proposedContract"):
            c = report["proposedContract"]
            self.stdout.write(
                f"  pilot eligibility : {c['futurePilotEligibility']}"
            )
            self.stdout.write(
                f"  whatsapp action   : {c['futureWhatsAppPilotAction']}"
            )
            self.stdout.write(
                f"  courier action    : {c['futureCourierPilotAction']}"
            )
            self.stdout.write(
                f"  dispatch action   : {c['futureDispatchPilotAction']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
