"""``python manage.py dry_run_phase8e_real_customer_payment_order_pilot \\
    --gate-id N --candidate-id N --json``.

Phase 8E - review-only dry-run against a validated real-customer
candidate. NEVER mutates real rows. NEVER calls a provider.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    dry_run_phase8e_real_customer_payment_order_pilot,
)


class Command(BaseCommand):
    help = (
        "Phase 8E - review-only dry-run against a validated "
        "real-customer candidate. NEVER mutates real rows. "
        "NEVER calls a provider."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--candidate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        candidate_id = int(options["candidate_id"])
        if candidate_id <= 0:
            raise CommandError(
                "--candidate-id must be a positive integer"
            )
        report = dry_run_phase8e_real_customer_payment_order_pilot(
            gate_id, candidate_id=candidate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            dry = report.get("dryRun") or {}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8E dry-run passed record_id={dry.get('id')} "
                    f"gate_id={gate_id}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Dry-run blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
