"""Prepare a Phase 6T final audit-lock row."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_phase6_final_audit_lock import (
    prepare_phase6t_final_audit_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 6T prepare a final audit-lock row. Creates only "
        "RazorpayPhase6FinalAuditLock; no pilot execution, no provider "
        "call, no WhatsApp send, no courier action, no real business "
        "mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan-id", type=int, required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        plan_id = int(options.get("plan_id") or 0)
        if plan_id <= 0:
            raise CommandError("--plan-id must be a positive integer")
        report = prepare_phase6t_final_audit_lock(plan_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared audit lock id={report['auditLock']['id']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused audit lock id={report['auditLock']['id']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for blocker in report.get("blockers") or []:
                self.stdout.write(f"  - {blocker}")
