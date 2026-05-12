"""``python manage.py preview_phase8b_payment_order_mutation_review_gate --phase8a-gate-id N --json``.

Phase 8B preview against an approved Phase 8A sandbox gate. NEVER
mutates business rows. NEVER calls a provider.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8b_payment_order_mutation_review import (
    preview_phase8b_payment_order_mutation_review_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 8B — preview the Payment -> Order Mutation Review "
        "Gate against an approved Phase 8A sandbox gate. Review / "
        "dry-run only. No provider call, no business mutation."
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
        report = preview_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8B Payment -> Order Mutation Review Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
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
