"""``python manage.py preview_phase8d_controlled_mutation_evidence_lock --phase8c-gate-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8d_controlled_mutation_evidence_lock import (
    preview_phase8d_controlled_mutation_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 8D — preview the Controlled Mutation Evidence Lock "
        "against a Phase 8C rolled_back gate. No provider call, no "
        "business mutation."
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
        report = preview_phase8d_controlled_mutation_evidence_lock(
            phase8c_gate_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8D Controlled Mutation Evidence Lock Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(
            f"  phase8c    : {report.get('sourcePhase8CGateId')}"
        )
        self.stdout.write(
            f"  phase8c-attempt: {report.get('sourcePhase8CAttemptId')}"
        )
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
