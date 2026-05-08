"""``python manage.py inspect_delhivery_courier_execution_readiness --json``.

Phase 7G - read-only readiness report. NEVER calls Delhivery; NEVER
creates a Shipment / WorkflowStep / RescueAttempt; NEVER creates an
AWB; NEVER books a pickup; NEVER generates a courier label; NEVER
sends WhatsApp; NEVER mutates real business rows; NEVER edits any
``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_courier_execution import (
    emit_readiness_inspected_audit,
    inspect_phase7g_courier_execution_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - One-shot Delhivery TEST/MOCK courier execution "
        "readiness (read-only; no provider call; no Shipment / AWB / "
        "pickup / label creation; no WhatsApp send; no business "
        "mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7g_courier_execution_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7G One-shot Delhivery Courier Execution Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  lifecycle flag      : "
            f"{report['phase7GCourierExecutionEnabled']}"
        )
        self.stdout.write(
            f"  director-approved   : "
            f"{report['phase7GDirectorApprovedOneShotCourierExecution']}"
        )
        self.stdout.write(
            f"  allow-test-AWB      : "
            f"{report['phase7GAllowDelhiveryTestAwb']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  delhivery mode      : "
            f"{report['envFlagSnapshot'].get('DELHIVERY_MODE')}"
        )
        self.stdout.write(
            f"  phase7F approved    : "
            f"{report['approvedPhase7FGateCount']}"
        )
        for key, count in report["attemptCounts"].items():
            self.stdout.write(f"  attempts {key:<54}: {count}")
        self.stdout.write(
            f"  safeToRunExecution  : "
            f"{report['safeToRunPhase7GExecution']}"
        )
        self.stdout.write(
            f"  nextAction          : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
