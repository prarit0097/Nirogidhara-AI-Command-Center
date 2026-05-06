"""``python manage.py inspect_razorpay_payment_dispatch_readiness --json``.

Phase 6R — read-only readiness report. NEVER mutates anything.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_payment_dispatch_readiness import (
    emit_readiness_inspected_audit,
    inspect_phase6r_payment_dispatch_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 6R — Razorpay payment → WhatsApp/courier dispatch readiness "
        "(read-only; no business mutation; no WhatsApp send; no courier "
        "call; no provider call)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase6r_payment_dispatch_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6R Payment → WhatsApp / Courier Dispatch Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  flag                : "
            f"{report['razorpayPaymentDispatchReadinessEnabled']}"
        )
        self.stdout.write(
            f"  phase 6Q approved   : {report['phase6QApprovedGateCount']}"
        )
        c = report["readinessCounts"]
        self.stdout.write(f"  gates pending       : {c['pendingManualReview']}")
        self.stdout.write(
            f"  gates approved 6S   : {c['approvedForFuturePhase6S']}"
        )
        self.stdout.write(f"  gates rejected      : {c['rejected']}")
        self.stdout.write(f"  gates archived      : {c['archived']}")
        self.stdout.write(f"  safeToStartPhase6S  : {report['safeToStartPhase6S']}")
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
