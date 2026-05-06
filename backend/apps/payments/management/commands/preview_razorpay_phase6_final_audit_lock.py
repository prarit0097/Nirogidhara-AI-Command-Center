"""Read-only Phase 6T final audit-lock preview command."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_phase6_final_audit_lock import (
    preview_phase6t_final_audit_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 6T preview for a final audit-lock. Read-only; no row "
        "creation, no provider call, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan-id", type=int, required=False)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        report = preview_phase6t_final_audit_lock(options.get("plan_id"))
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write("Phase 6T Final Audit Preview")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(f"  nextAction : {report['nextAction']}")
