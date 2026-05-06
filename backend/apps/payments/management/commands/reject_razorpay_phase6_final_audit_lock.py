"""CLI-only Phase 6T final audit-lock reject command."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_phase6_final_audit_lock import (
    reject_phase6t_final_audit_lock,
)


class Command(BaseCommand):
    help = "Phase 6T reject a final audit-lock row only."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--audit-lock-id", type=int, required=True)
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        audit_lock_id = int(options.get("audit_lock_id") or 0)
        if audit_lock_id <= 0:
            raise CommandError("--audit-lock-id must be a positive integer")
        report = reject_phase6t_final_audit_lock(
            audit_lock_id, reason=options.get("reason") or ""
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(f"ok: {report.get('ok')} nextAction: {report['nextAction']}")
