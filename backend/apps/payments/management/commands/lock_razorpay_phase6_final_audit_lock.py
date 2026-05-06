"""CLI-only Phase 6T final audit-lock transition."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_phase6_final_audit_lock import (
    lock_phase6t_final_audit_record,
)


class Command(BaseCommand):
    help = (
        "Phase 6T lock a final audit record for future controlled-pilot "
        "review only. No live execution and no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--audit-lock-id", type=int, required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        audit_lock_id = int(options.get("audit_lock_id") or 0)
        if audit_lock_id <= 0:
            raise CommandError("--audit-lock-id must be a positive integer")
        report = lock_phase6t_final_audit_record(
            audit_lock_id, reason=options.get("reason") or ""
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(f"ok: {report.get('ok')} nextAction: {report['nextAction']}")
