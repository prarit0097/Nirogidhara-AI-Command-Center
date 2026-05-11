"""``python manage.py reject_phase7h_courier_execution_evidence_lock --lock-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution_evidence_lock import (
    reject_phase7h_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7H - reject an evidence lock (only valid from draft / "
        "pending_manual_review / blocked). Lock-only; never calls "
        "Delhivery / Meta; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--lock-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty rejection reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        lock_id = int(options["lock_id"])
        if lock_id <= 0:
            raise CommandError("--lock-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = reject_phase7h_evidence_lock(
            lock_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            lock = report["lock"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 7H evidence lock rejected lock_id="
                    f"{lock['id']} status={lock['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Reject blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
