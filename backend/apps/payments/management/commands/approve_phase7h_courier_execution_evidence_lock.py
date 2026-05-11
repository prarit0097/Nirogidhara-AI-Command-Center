"""``python manage.py approve_phase7h_courier_execution_evidence_lock --lock-id N --reason "..." --json``.

Phase 7H - lock an evidence row. Non-empty reason required. NEVER
calls Delhivery / Meta / Razorpay / Vapi. NEVER mutates business
rows. NEVER enables any live execution path.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution_evidence_lock import (
    approve_phase7h_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7H - lock an evidence row. Lock-only; never calls "
        "Delhivery / Meta / Razorpay / Vapi; never mutates business "
        "rows; never enables live execution."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--lock-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty review reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        lock_id = int(options["lock_id"])
        if lock_id <= 0:
            raise CommandError("--lock-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = approve_phase7h_evidence_lock(
            lock_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            lock = report["lock"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7H evidence locked lock_id={lock['id']} "
                    f"status={lock['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Lock blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
