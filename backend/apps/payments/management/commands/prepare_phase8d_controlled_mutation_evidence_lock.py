"""``python manage.py prepare_phase8d_controlled_mutation_evidence_lock --phase8c-gate-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8d_controlled_mutation_evidence_lock import (
    prepare_phase8d_controlled_mutation_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 8D — prepare the Controlled Mutation Evidence Lock "
        "from a Phase 8C rolled_back gate. CLI-only review state "
        "change."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase8c-gate-id", required=True, type=int
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8c_gate_id = int(options["phase8c_gate_id"])
        if phase8c_gate_id <= 0:
            raise CommandError(
                "--phase8c-gate-id must be a positive integer"
            )
        report = prepare_phase8d_controlled_mutation_evidence_lock(
            phase8c_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            lock = report["lock"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8D lock created lock_id={lock['id']} "
                    f"status={lock['status']}"
                )
            )
        elif report.get("reused"):
            lock = report["lock"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 8D lock reused lock_id={lock['id']} "
                    f"status={lock['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
