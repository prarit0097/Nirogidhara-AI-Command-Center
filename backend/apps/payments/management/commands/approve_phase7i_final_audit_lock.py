"""``python manage.py approve_phase7i_final_audit_lock --lock-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase7_final_audit_lock import (
    approve_phase7i_final_audit_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7I — lock the Final Phase 7 audit-lock row. Lock-only; "
        "never calls Razorpay / Meta Cloud / Delhivery / Vapi; never "
        "mutates business rows; never enables live execution."
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
        report = approve_phase7i_final_audit_lock(
            lock_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            lock = report["lock"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7I final audit locked lock_id={lock['id']} "
                    f"status={lock['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Lock blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
