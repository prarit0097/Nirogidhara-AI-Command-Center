"""``python manage.py inspect_razorpay_controlled_pilot_execution_readiness --json``.

Phase 7D - read-only readiness report for the Razorpay Controlled
Pilot Execution Gate (one-shot internal Razorpay TEST execution
capability). NEVER mutates anything; NEVER calls Razorpay; NEVER
sends WhatsApp; NEVER calls Meta Cloud / Delhivery / Vapi; NEVER
mutates Order / Payment / Shipment / DiscountOfferLog / Customer /
Lead; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_controlled_pilot_execution import (
    emit_readiness_inspected_audit,
    inspect_phase7d_razorpay_test_execution_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - Razorpay Controlled Pilot Execution readiness "
        "(read-only; no provider call; no business mutation; no "
        "WhatsApp; no Delhivery; no .env edit)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7d_razorpay_test_execution_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7D Razorpay Controlled Pilot Execution Readiness"
            )
        )
        self.stdout.write(f"  status                : {report['status']}")
        flags = report["envFlags"]
        self.stdout.write(
            f"  lifecycleEnabled      : {flags['lifecycleEnabled']}"
        )
        self.stdout.write(
            f"  directorOneShotApprov : {flags['directorOneShotApproved']}"
        )
        self.stdout.write(
            f"  allowRazorpayTestOrde : {flags['allowRazorpayTestOrder']}"
        )
        c = report["attemptCounts"]
        self.stdout.write(f"  attempts draft        : {c['draft']}")
        self.stdout.write(
            f"  attempts pending sign : {c['pendingDirectorSignoff']}"
        )
        self.stdout.write(
            f"  attempts approved     : {c['approvedForOneShotRun']}"
        )
        self.stdout.write(f"  attempts executed     : {c['executed']}")
        self.stdout.write(f"  attempts failed       : {c['failed']}")
        self.stdout.write(f"  attempts rolled back  : {c['rolledBack']}")
        self.stdout.write(f"  attempts archived     : {c['archived']}")
        self.stdout.write(f"  attempts blocked      : {c['blocked']}")
        ks = report["killSwitch"]
        self.stdout.write(
            f"  killSwitchEnabled     : {ks.get('enabled')}"
        )
        self.stdout.write(f"  nextAction            : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
