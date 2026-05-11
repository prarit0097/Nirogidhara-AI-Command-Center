"""``python manage.py approve_phase7e_live_internal_whatsapp_send \\
    --attempt-id N --reason "..." --director-signoff "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_send import (
    approve_phase7e_live_internal_send,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - approve an internal allowed-list WhatsApp "
        "send attempt for one-shot execution. Approval is a state "
        "transition only; it does NOT call Meta Cloud, does NOT "
        "send a WhatsApp message, does NOT mutate business rows. "
        "The actual send is CLI-only via execute_phase7e_live_*."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty review reason.",
        )
        parser.add_argument(
            "--director-signoff", default="", type=str,
            help=(
                "Mandatory non-empty Director sign-off summary. The "
                "execute command requires the FULL structured "
                "BEGIN_UTC=.../END_UTC=... body."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        director_signoff = (
            options.get("director_signoff") or ""
        ).strip()
        if not director_signoff:
            raise CommandError(
                "--director-signoff must be a non-empty string."
            )
        report = approve_phase7e_live_internal_send(
            attempt_id,
            reviewed_by=None,
            reason=reason,
            director_signoff=director_signoff,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7E-Live-A attempt approved attempt_id="
                    f"{attempt['id']} status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approve blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
