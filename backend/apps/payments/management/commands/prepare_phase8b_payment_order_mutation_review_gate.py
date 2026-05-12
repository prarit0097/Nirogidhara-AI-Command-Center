"""``python manage.py prepare_phase8b_payment_order_mutation_review_gate --phase8a-gate-id N --json``.

Phase 8B prepare against an approved Phase 8A sandbox gate. Atomic
+ idempotent. NEVER mutates business rows. NEVER calls a provider.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8b_payment_order_mutation_review import (
    prepare_phase8b_payment_order_mutation_review_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 8B — prepare the Payment -> Order Mutation Review "
        "Gate from an approved Phase 8A sandbox gate. Review / "
        "dry-run only. Requires "
        "PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=true."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase8a-gate-id", required=True, type=int
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8a_gate_id = int(options["phase8a_gate_id"])
        if phase8a_gate_id <= 0:
            raise CommandError(
                "--phase8a-gate-id must be a positive integer"
            )
        report = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            gate = report["gate"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8B gate created gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        elif report.get("reused"):
            gate = report["gate"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 8B gate reused gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
