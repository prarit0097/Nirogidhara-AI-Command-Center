"""``python manage.py archive_razorpay_payment_dispatch_pilot_plan \\
    --plan-id <ID> --reason "..." --json``.

Phase 6S — archive a pilot plan. Audit-only.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    archive_phase6s_payment_dispatch_pilot_plan,
)


class Command(BaseCommand):
    help = (
        "Phase 6S — archive a Limited Internal Dispatch Pilot Plan. "
        "No pilot execution; no WhatsApp send; no courier call; no "
        "real business mutation; no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        plan_id = int(options["plan_id"])
        if plan_id <= 0:
            raise CommandError("--plan-id must be a positive integer")
        report = archive_phase6s_payment_dispatch_pilot_plan(
            plan_id,
            archived_by=None,
            reason=options.get("reason") or "",
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.WARNING(
                    f"Pilot plan {report['plan']['id']} -> "
                    f"{report['plan']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
