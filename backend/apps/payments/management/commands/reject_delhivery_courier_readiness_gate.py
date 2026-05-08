"""``python manage.py reject_delhivery_courier_readiness_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 7F - reject a courier readiness gate. NEVER calls Delhivery;
NEVER creates a Shipment / AWB / pickup / label; NEVER sends
WhatsApp; NEVER mutates real business rows; NEVER edits any
``.env*`` file. Reason text required. Refuses unless gate is
``draft`` / ``pending_manual_review``.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_readiness import reject_phase7f_gate


class Command(BaseCommand):
    help = (
        "Phase 7F - reject a courier readiness gate. Refuses unless "
        "gate is in draft / pending_manual_review. No provider call; "
        "no Delhivery call; no Shipment / AWB / pickup / label "
        "creation; no WhatsApp send; no business mutation; reason "
        "required."
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
                "--reason must be a non-empty string for Phase 7F reject"
            )
        report = reject_phase7f_gate(
            gate_id, rejected_by=None, reason=reason
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
