"""``python manage.py dry_run_razorpay_whatsapp_internal_notification_gate \\
    --gate-id <ID> --json``.

Phase 7E - dry-run rehearsal. Walks Claim-Vault grounding + invariants
and writes a ``RazorpayWhatsAppInternalNotificationDryRunRecord`` of
``kind=dry_run``. NEVER opens the Meta Cloud client; NEVER queues a
``WhatsAppMessage`` row; NEVER mutates real business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_notification import (
    dry_run_phase7e_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - dry-run a WhatsApp internal notification gate "
        "(no provider call; no WhatsApp send / queue; no business "
        "mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = dry_run_phase7e_gate(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry-run passed gate_id={report['gate']['id']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Dry-run blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
