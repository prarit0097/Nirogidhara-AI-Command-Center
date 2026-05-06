"""``python manage.py archive_razorpay_payment_dispatch_readiness_gate \\
    --readiness-id <ID> --reason "..." --json``.

Phase 6R — archive a dispatch readiness gate. Audit-only.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_readiness import (
    archive_phase6r_payment_dispatch_readiness_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 6R — archive a payment dispatch readiness gate. No "
        "WhatsApp send, no courier call, no real business mutation, no "
        "provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--readiness-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        readiness_id = int(options["readiness_id"])
        if readiness_id <= 0:
            raise CommandError("--readiness-id must be a positive integer")
        report = archive_phase6r_payment_dispatch_readiness_gate(
            readiness_id,
            archived_by=None,
            reason=options.get("reason") or "",
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.WARNING(
                    f"Readiness {report['readiness']['id']} -> "
                    f"{report['readiness']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
