"""``python manage.py inspect_phase8d_controlled_mutation_evidence_lock --json``.

Phase 8D — read-only readiness for the Controlled Mutation Evidence
Lock. NEVER calls a provider; NEVER mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8d_controlled_mutation_evidence_lock import (
    emit_readiness_inspected_audit,
    inspect_phase8d_controlled_mutation_evidence_lock_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 8D — read-only readiness for the Controlled Mutation "
        "Evidence Lock. Lock-only meta-audit. No provider call, no "
        "business mutation, no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = (
            inspect_phase8d_controlled_mutation_evidence_lock_readiness()
        )
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8D Controlled Mutation Evidence Lock Readiness"
            )
        )
        self.stdout.write(
            f"  status              : {report['status']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  eligible 8C gates   : "
            f"{report['eligiblePhase8CGateCount']}"
        )
        for status, count in report["phase8DLockCounts"].items():
            self.stdout.write(f"  locks {status:<32}: {count}")
        self.stdout.write(
            f"  nextAction          : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
