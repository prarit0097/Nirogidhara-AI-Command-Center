"""``python manage.py inspect_razorpay_sandbox_paid_status_mutation_readiness --json``.

Phase 6P — read-only readiness report. NEVER mutates anything,
NEVER calls Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    emit_readiness_inspected_audit,
    inspect_phase6p_paid_status_mutation_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — Razorpay sandbox paid-status mutation readiness "
        "(read-only; no business mutation; no provider call)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase6p_paid_status_mutation_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6P Razorpay Sandbox Paid-Status Mutation Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  flag                : {report['razorpaySandboxPaidStatusMutationEnabled']}"
        )
        self.stdout.write(
            f"  approved reviews    : {report['approvedPhase6OReviewCount']}"
        )
        attempts = report["attemptCounts"]
        self.stdout.write(
            f"  attempts prepared   : {attempts['prepared']}"
        )
        self.stdout.write(
            f"  attempts executed   : {attempts['executed']}"
        )
        self.stdout.write(
            f"  attempts rolledBack : {attempts['rolledBack']}"
        )
        self.stdout.write(
            f"  attempts archived   : {attempts['archived']}"
        )
        self.stdout.write(
            f"  ledger total        : {report['ledgerCounts']['totalLedgers']}"
        )
        self.stdout.write(
            f"  safeToStartPhase6Q  : {report['safeToStartPhase6Q']}"
        )
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
