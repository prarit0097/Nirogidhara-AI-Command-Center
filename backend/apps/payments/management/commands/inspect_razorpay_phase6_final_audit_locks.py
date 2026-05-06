"""Read-only list/counter command for Phase 6T final audit-lock rows."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_phase6_final_audit_lock import (
    summarize_phase6t_final_audit_locks,
)


class Command(BaseCommand):
    help = "Phase 6T inspect final audit-lock rows. Read-only."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        report = {
            "phase": "6T",
            "status": "final_audit_lock_only",
            **summarize_phase6t_final_audit_locks(
                limit=int(options.get("limit") or 25)
            ),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write("Phase 6T Final Audit Locks")
        self.stdout.write(
            "  locked: "
            f"{report['counts']['lockedForFutureControlledPilotReview']}"
        )
