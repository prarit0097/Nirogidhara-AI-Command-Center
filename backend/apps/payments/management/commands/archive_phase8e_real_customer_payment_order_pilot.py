"""``python manage.py archive_phase8e_real_customer_payment_order_pilot --gate-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    archive_phase8e_real_customer_payment_order_pilot,
)


class Command(BaseCommand):
    help = (
        "Phase 8E - archive a real customer pilot gate. Never "
        "calls a provider; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty archive reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = archive_phase8e_real_customer_payment_order_pilot(
            gate_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            gate = report["gate"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8E gate archived gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
