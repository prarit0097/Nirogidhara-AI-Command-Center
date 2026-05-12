"""``python manage.py prepare_phase8c_payment_order_controlled_mutation --phase8b-gate-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8c_payment_order_controlled_mutation import (
    prepare_phase8c_payment_order_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8C — prepare the Controlled Payment -> Order Mutation "
        "framework from an approved Phase 8B review gate. CLI-only "
        "review state change. Requires "
        "PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED=true."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase8b-gate-id", required=True, type=int
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8b_gate_id = int(options["phase8b_gate_id"])
        if phase8b_gate_id <= 0:
            raise CommandError(
                "--phase8b-gate-id must be a positive integer"
            )
        report = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            gate = report["gate"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8C gate created gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        elif report.get("reused"):
            gate = report["gate"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 8C gate reused gate_id={gate['id']} "
                    f"status={gate['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
