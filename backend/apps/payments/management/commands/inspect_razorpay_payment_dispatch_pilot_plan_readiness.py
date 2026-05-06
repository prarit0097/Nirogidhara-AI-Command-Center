"""``python manage.py inspect_razorpay_payment_dispatch_pilot_plan_readiness --json``.

Phase 6S — read-only readiness report. NEVER mutates anything.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    emit_readiness_inspected_audit,
    inspect_phase6s_payment_dispatch_pilot_plan_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 6S — Razorpay Limited Internal Dispatch Pilot Plan "
        "readiness (read-only; planning-only; no pilot execution; no "
        "WhatsApp send; no Meta Cloud call; no Delhivery call; no "
        "shipment creation; no provider call)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase6s_payment_dispatch_pilot_plan_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6S Limited Internal Dispatch Pilot Plan Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  flag                : "
            f"{report['razorpayPaymentDispatchPilotPlanEnabled']}"
        )
        self.stdout.write(
            f"  phase 6R approved   : "
            f"{report['phase6RApprovedReadinessGateCount']}"
        )
        c = report["pilotPlanCounts"]
        self.stdout.write(f"  plans pending       : {c['pendingManualReview']}")
        self.stdout.write(
            f"  plans approved 6T   : {c['approvedForFuturePhase6T']}"
        )
        self.stdout.write(f"  plans rejected      : {c['rejected']}")
        self.stdout.write(f"  plans archived      : {c['archived']}")
        self.stdout.write(
            f"  safeToStartPhase6T  : {report['safeToStartPhase6T']}"
        )
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
