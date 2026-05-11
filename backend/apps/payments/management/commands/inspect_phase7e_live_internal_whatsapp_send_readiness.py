"""``python manage.py inspect_phase7e_live_internal_whatsapp_send_readiness --json``.

Phase 7E-Live-A - read-only readiness report. NEVER calls Meta
Cloud; NEVER creates a WhatsApp message row; NEVER mutates real
business rows; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_whatsapp_internal_send import (
    emit_readiness_inspected_audit,
    inspect_phase7e_live_internal_send_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - Internal allowed-list WhatsApp one-shot "
        "send readiness (read-only; no provider call; no business "
        "mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase7e_live_internal_send_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7E-Live-A Internal WhatsApp Send Readiness"
            )
        )
        self.stdout.write(f"  status              : {report['status']}")
        self.stdout.write(
            f"  send flag           : "
            f"{report['phase7ELiveInternalWhatsAppSendEnabled']}"
        )
        self.stdout.write(
            f"  limited test mode   : "
            f"{report['whatsAppLiveMetaLimitedTestMode']}"
        )
        self.stdout.write(
            f"  allow-list size     : "
            f"{report['allowedTestNumbersCount']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        for key, count in report["attemptCounts"].items():
            self.stdout.write(f"  attempts {key:<48}: {count}")
        self.stdout.write(
            f"  safeToRunSend       : "
            f"{report['safeToRunPhase7ELiveSend']}"
        )
        self.stdout.write(
            f"  nextAction          : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
