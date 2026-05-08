"""``python manage.py inspect_razorpay_whatsapp_internal_notification_readiness --json``.

Phase 7E - read-only readiness report. NEVER sends WhatsApp, NEVER
queues, NEVER calls Meta Cloud / Delhivery / Vapi, NEVER mutates
business rows, NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_whatsapp_internal_notification import (
    emit_readiness_inspected_audit,
    inspect_phase7e_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - Razorpay WhatsApp internal notification readiness "
        "(read-only; gate-only; no provider call; no WhatsApp send; "
        "no Meta Cloud / Delhivery call; no shipment / AWB; no "
        "business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7e_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7E WhatsApp Internal Notification Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  gate flag           : "
            f"{report['envFlags']['phase7eGateEnabled']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  phase7DEligible     : "
            f"{report['phase7DEligibleForPhase7ECount']}"
        )
        self.stdout.write(
            f"  phase7DRolledBack   : "
            f"{report['phase7DRolledBackEligibleCount']}"
        )
        for status, count in report["gateCounts"].items():
            self.stdout.write(f"  gates {status:<48}: {count}")
        self.stdout.write(f"  nextAction          : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
