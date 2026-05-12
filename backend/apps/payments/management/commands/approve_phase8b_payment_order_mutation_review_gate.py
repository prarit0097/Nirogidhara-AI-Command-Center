"""``python manage.py approve_phase8b_payment_order_mutation_review_gate --gate-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8b_payment_order_mutation_review import (
    approve_phase8b_payment_order_mutation_review_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 8B — approve a review gate (state transition only; "
        "moves status to "
        "approved_for_future_phase8c_controlled_mutation_review). "
        "Requires at least one passed dry-run AND a recorded "
        "rollback dry-run. Never enables any real mutation; never "
        "calls a provider; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty review reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError(
                "--gate-id must be a positive integer"
            )
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string."
            )
        report = approve_phase8b_payment_order_mutation_review_gate(
            gate_id, reviewed_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            gate = report["gate"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8B gate approved gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approve blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
