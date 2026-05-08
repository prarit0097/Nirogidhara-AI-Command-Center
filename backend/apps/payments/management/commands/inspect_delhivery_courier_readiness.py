"""``python manage.py inspect_delhivery_courier_readiness --json``.

Phase 7F - read-only readiness report. NEVER calls Delhivery; NEVER
creates a Shipment / WorkflowStep / RescueAttempt; NEVER creates an
AWB; NEVER books a pickup; NEVER generates a courier label; NEVER
sends WhatsApp; NEVER mutates real business rows; NEVER edits any
``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_courier_readiness import (
    emit_readiness_inspected_audit,
    inspect_phase7f_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7F - Delhivery / Courier readiness (read-only; "
        "gate-only; no provider call; no Shipment / AWB / pickup / "
        "label creation; no WhatsApp send; no business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7f_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7F Delhivery / Courier Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  gate flag           : "
            f"{report['envFlags']['phase7fCourierReadinessGateEnabled']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  phase7DHotfix1      : {report['phase7DHotfix1Present']}"
        )
        self.stdout.write(
            f"  delhivery mode      : "
            f"{report['envFlagSnapshot'].get('DELHIVERY_MODE')}"
        )
        self.stdout.write(
            f"  phase7E approved    : {report['phase7EApprovedGateCount']}"
        )
        for status, count in report["phase7FGateCounts"].items():
            self.stdout.write(f"  gates {status:<58}: {count}")
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
