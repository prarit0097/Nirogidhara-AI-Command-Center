"""``python manage.py inspect_razorpay_payment_order_workflow_gate_readiness --json``.

Phase 6Q — read-only readiness report. NEVER mutates anything.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_payment_order_workflow_gate import (
    emit_readiness_inspected_audit,
    inspect_phase6q_payment_order_workflow_gate_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 6Q — Razorpay payment-order workflow safety gate "
        "readiness (read-only; no business mutation; no provider call)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase6q_payment_order_workflow_gate_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6Q Payment → Order Workflow Safety Gate Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  flag                : "
            f"{report['razorpayPaymentOrderWorkflowGateEnabled']}"
        )
        self.stdout.write(
            f"  phase 6P executed   : {report['phase6PExecutedCount']}"
        )
        self.stdout.write(
            f"  phase 6P rolledBack : {report['phase6PRolledBackCount']}"
        )
        c = report["gateCounts"]
        self.stdout.write(f"  gates pending       : {c['pendingManualReview']}")
        self.stdout.write(f"  gates approved      : {c['approvedForFuturePhase6R']}")
        self.stdout.write(f"  gates rejected      : {c['rejected']}")
        self.stdout.write(f"  gates archived      : {c['archived']}")
        self.stdout.write(f"  safeToStartPhase6R  : {report['safeToStartPhase6R']}")
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
