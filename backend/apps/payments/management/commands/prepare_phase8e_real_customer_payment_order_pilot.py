"""``python manage.py prepare_phase8e_real_customer_payment_order_pilot --phase8d-lock-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    prepare_phase8e_real_customer_payment_order_pilot,
)


class Command(BaseCommand):
    help = (
        "Phase 8E - prepare the Real Customer Payment -> Order "
        "Pilot Gate from a Phase 8D locked evidence chain. "
        "Review / dry-run only. Requires "
        "PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED=true."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--phase8d-lock-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8d_lock_id = int(options["phase8d_lock_id"])
        if phase8d_lock_id <= 0:
            raise CommandError(
                "--phase8d-lock-id must be a positive integer"
            )
        report = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            gate = report["gate"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8E gate created gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        elif report.get("reused"):
            gate = report["gate"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 8E gate reused gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
