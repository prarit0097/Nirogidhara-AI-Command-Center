"""``python manage.py prepare_phase8f_real_customer_controlled_mutation
--phase8e-gate-id <ID> [--json]``.

Phase 8F - prepare the Controlled Real Customer Payment -> Order
Mutation gate from a Phase 8E pilot gate that is in
``approved_for_future_phase8f_real_customer_controlled_mutation``
status. Never mutates business rows; never calls a provider.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8f_real_customer_controlled_mutation import (
    prepare_phase8f_real_customer_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - prepare a Controlled Real Customer Payment -> "
        "Order Mutation gate. Never mutates business rows; never "
        "calls a provider; never sends WhatsApp; never sends a "
        "customer notification."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase8e-gate-id",
            type=int,
            required=True,
            help="Phase 8E pilot gate id to prepare from.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8e_gate_id = int(options.get("phase8e_gate_id") or 0)
        if phase8e_gate_id <= 0:
            raise CommandError(
                "phase8e_gate_id must be a positive integer."
            )
        report = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8F prepare"
            )
        )
        self.stdout.write(f"  ok        : {report['ok']}")
        self.stdout.write(
            f"  nextAction: {report.get('nextAction')}"
        )
        if report.get("gate"):
            self.stdout.write(
                f"  gateId    : {report['gate']['id']}"
            )
            self.stdout.write(
                f"  status    : {report['gate']['status']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
