"""``python manage.py preview_phase7e_live_internal_whatsapp_send --gate-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_send import (
    preview_phase7e_live_internal_send,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - read-only preview of an internal allowed-"
        "list WhatsApp send attempt derived from an approved Phase "
        "7E gate. No DB writes, no Meta Cloud call, no business "
        "mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = preview_phase7e_live_internal_send(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7E-Live-A Internal WhatsApp Send Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(
            f"  recipient  : {report['recipientScope']}"
        )
        self.stdout.write(
            f"  allow-list size : {report['allowedTestNumbersCount']}"
        )
        self.stdout.write(f"  nextAction : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
