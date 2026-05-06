"""Read-only Phase 6T final audit-lock readiness command."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_phase6_final_audit_lock import (
    emit_readiness_inspected_audit,
    inspect_phase6t_final_audit_lock_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 6T final Phase 6 audit-lock readiness. Read-only; no "
        "pilot execution, provider call, WhatsApp send, courier action, "
        "or real business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--no-audit", action="store_true")

    def handle(self, *args, **options) -> None:
        report = inspect_phase6t_final_audit_lock_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write("Phase 6T Final Audit + Lock Readiness")
        self.stdout.write(f"  status       : {report['status']}")
        self.stdout.write(
            f"  flag         : {report['razorpayPhase6FinalAuditLockEnabled']}"
        )
        self.stdout.write(
            "  locked       : "
            f"{report['finalAuditLockCounts']['lockedForFutureControlledPilotReview']}"
        )
        self.stdout.write(
            "  safe future  : "
            f"{report['safeToStartFutureControlledPilot']}"
        )
        self.stdout.write(f"  nextAction   : {report['nextAction']}")
