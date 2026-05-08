"""``python manage.py reject_razorpay_whatsapp_internal_notification_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 7E - reject a notification gate. NEVER sends or queues
WhatsApp; NEVER calls a provider; NEVER mutates real business rows;
NEVER edits any ``.env*`` file. Reason text required.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_notification import (
    reject_phase7e_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - reject a WhatsApp internal notification gate. "
        "Refuses unless gate is in draft / pending_manual_review. "
        "No provider call; no WhatsApp send; no business mutation; "
        "reason required."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string for Phase 7E reject"
            )
        report = reject_phase7e_gate(
            gate_id, reason=reason, rejected_by=None
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.WARNING(
                    f"Gate {report['gate']['id']} -> "
                    f"{report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Reject blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
