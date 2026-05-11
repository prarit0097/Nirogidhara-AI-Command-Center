"""``python manage.py inspect_phase7i_final_audit_lock --json``.

Phase 7I — read-only readiness report for the Final Phase 7
Payment + WhatsApp + Courier Audit Lock. NEVER calls any provider;
NEVER creates a `Shipment` / AWB row; NEVER sends or queues
WhatsApp; NEVER mutates real business rows; NEVER edits any
`.env*` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase7_final_audit_lock import (
    emit_readiness_inspected_audit,
    inspect_phase7i_final_audit_lock_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7I — read-only readiness for the Final Phase 7 audit "
        "lock. Lock-only meta-audit over Phase 7D + 7E-Live-A + 7G "
        "+ 7H. No provider call, no business mutation, no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7i_final_audit_lock_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7I Final Audit Lock Readiness"
            )
        )
        self.stdout.write(f"  status                : {report['status']}")
        self.stdout.write(
            f"  killSwitchEnabled     : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  eligible 7H locks     : "
            f"{report['eligiblePhase7HEvidenceLockCount']}"
        )
        self.stdout.write(
            f"  eligible 7E-live      : "
            f"{report['eligiblePhase7ELiveAttemptCount']}"
        )
        self.stdout.write(
            f"  eligible 7G attempts  : "
            f"{report['eligiblePhase7GAttemptCount']}"
        )
        for status, count in report["phase7ILockCounts"].items():
            self.stdout.write(f"  locks {status:<32}: {count}")
        self.stdout.write(f"  nextAction            : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
