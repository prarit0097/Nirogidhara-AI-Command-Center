"""``python manage.py inspect_razorpay_sandbox_status_mapping_readiness --json``.

Phase 6O — emit the sandbox status mapping readiness report. Read-only.
NEVER calls Razorpay, NEVER mutates business records.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_sandbox_status_mapping import (
    emit_readiness_inspected_audit,
    inspect_phase6o_sandbox_status_mapping_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 6O — Razorpay sandbox status mapping readiness "
        "(read-only; no business mutation; no provider call)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help=(
                "Skip emitting the readiness AuditEvent (useful for "
                "non-mutating diagnostics in test scripts)."
            ),
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase6o_sandbox_status_mapping_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6O Razorpay Sandbox Status Mapping Readiness"
            )
        )
        self.stdout.write(f"  status                : {report['status']}")
        self.stdout.write(
            f"  latest completed      : {report['latestCompletedPhase']}"
        )
        self.stdout.write(f"  next phase            : {report['nextPhase']}")
        self.stdout.write(
            f"  flag enabled          : "
            f"{report['razorpaySandboxStatusMappingEnabled']}"
        )
        self.stdout.write(
            f"  business mutation     : {report['businessMutationEnabled']}"
        )
        self.stdout.write(
            f"  customer notification : {report['customerNotificationEnabled']}"
        )
        self.stdout.write(
            f"  provider call         : {report['providerCallAttempted']}"
        )
        counts = report["reviewCounts"]
        self.stdout.write(
            f"  reviews proposed      : {counts['proposed']}"
        )
        self.stdout.write(
            f"  reviews pending       : {counts['pendingManualReview']}"
        )
        self.stdout.write(
            f"  reviews approved      : {counts['approvedForFuturePhase6P']}"
        )
        self.stdout.write(f"  reviews rejected      : {counts['rejected']}")
        self.stdout.write(f"  reviews archived      : {counts['archived']}")
        self.stdout.write(
            f"  safeToStartPhase6P    : {report['safeToStartPhase6P']}"
        )
        self.stdout.write(f"  nextAction            : {report['nextAction']}")

        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
