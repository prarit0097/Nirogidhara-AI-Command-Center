"""``python manage.py preview_phase8c_payment_order_controlled_mutation --phase8b-gate-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8c_payment_order_controlled_mutation import (
    preview_phase8c_payment_order_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8C — preview the Controlled Payment -> Order Mutation "
        "framework against an approved Phase 8B review gate. "
        "Review / dry-run only. No provider call, no business "
        "mutation."
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
        report = preview_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8C Controlled Payment -> Order Mutation Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(
            f"  phase8b    : {report.get('sourcePhase8BGateId')}"
        )
        self.stdout.write(
            f"  phase8a    : {report.get('sourcePhase8AGateId')}"
        )
        self.stdout.write(
            f"  phase7i    : {report.get('sourcePhase7ILockId')}"
        )
        self.stdout.write(
            f"  phase7d    : {report.get('sourcePhase7DAttemptId')}"
        )
        self.stdout.write(f"  nextAction : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
