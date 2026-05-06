"""``python manage.py inspect_razorpay_controlled_pilot_gate_readiness --json``.

Phase 7B - read-only readiness report. NEVER mutates anything.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_controlled_pilot_gate import (
    emit_readiness_inspected_audit,
    inspect_phase7b_controlled_pilot_gate_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7B - Razorpay Controlled Pilot Execution Gate readiness "
        "(read-only; gate-only; no provider call; no WhatsApp send; "
        "no Meta Cloud / Delhivery call; no shipment / AWB creation; "
        "no business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7b_controlled_pilot_gate_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7B Controlled Pilot Execution Gate Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  flag                : "
            f"{report['phase7ControlledPilotGateEnabled']}"
        )
        self.stdout.write(
            f"  phase 6T locked     : "
            f"{report['phase6TLockedForFutureControlledPilotReviewCount']}"
        )
        c = report["controlledPilotGateCounts"]
        self.stdout.write(f"  gates pending       : {c['pendingManualReview']}")
        self.stdout.write(
            f"  gates approved 7C   : "
            f"{c['approvedForFuturePhase7CExecutionReview']}"
        )
        self.stdout.write(f"  gates rejected      : {c['rejected']}")
        self.stdout.write(f"  gates archived      : {c['archived']}")
        self.stdout.write(f"  gates blocked       : {c['blocked']}")
        self.stdout.write(
            f"  safeForPhase7CFlow  : "
            f"{report['safeToStartPhase7CExecutionReviewFlow']}"
        )
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
