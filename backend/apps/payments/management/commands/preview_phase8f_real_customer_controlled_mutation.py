"""``python manage.py preview_phase8f_real_customer_controlled_mutation
--phase8e-gate-id <ID> [--json]``.

Phase 8F - read-only preview from an approved Phase 8E pilot
gate. NEVER persists a row.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8f_real_customer_controlled_mutation import (
    preview_phase8f_real_customer_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - read-only preview from an approved Phase 8E "
        "pilot gate. Never persists a row, never calls a provider."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase8e-gate-id",
            type=int,
            required=True,
            help="Phase 8E pilot gate id to preview against.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8e_gate_id = int(options.get("phase8e_gate_id") or 0)
        if phase8e_gate_id <= 0:
            raise CommandError(
                "phase8e_gate_id must be a positive integer."
            )
        report = preview_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8F Real Customer Controlled Mutation Preview"
            )
        )
        for key in (
            "phase8EGateId",
            "phase8EGateStatus",
            "candidateOrderId",
            "candidatePaymentId",
            "currentOrderPaymentStatus",
            "currentPaymentStatus",
            "proposedOrderPaymentStatus",
            "proposedPaymentStatus",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
