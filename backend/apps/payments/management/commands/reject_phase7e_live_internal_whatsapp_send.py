"""``python manage.py reject_phase7e_live_internal_whatsapp_send --attempt-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_send import (
    reject_phase7e_live_internal_send,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - reject an internal allowed-list WhatsApp "
        "send attempt. Refuses unless attempt is in draft / "
        "pending_director_signoff / approved / blocked."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty rejection reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError("--attempt-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = reject_phase7e_live_internal_send(
            attempt_id, rejected_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 7E-Live-A attempt rejected attempt_id="
                    f"{attempt['id']} status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Reject blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
