"""``python manage.py prepare_phase7e_live_internal_whatsapp_send \\
    --gate-id N --template-name X --template-language Y \\
    --allowed-recipient-last4 NNNN --json``.

Phase 7E-Live-A - prepare an internal allowed-list WhatsApp send
attempt. NEVER calls Meta Cloud; NEVER creates a WhatsApp message
row; NEVER mutates real business tables; NEVER edits any
``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_send import (
    prepare_phase7e_live_internal_send,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - prepare an internal allowed-list WhatsApp "
        "send attempt against an approved Phase 7E gate. No Meta "
        "Cloud call, no WhatsApp message row, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--template-name", required=True, type=str,
            help="Approved Meta template name (lowercase, no spaces).",
        )
        parser.add_argument(
            "--template-language", required=True, type=str,
            help="Approved Meta template language code (e.g. 'en' / 'hi').",
        )
        parser.add_argument(
            "--allowed-recipient-last4", required=True, type=str,
            help=(
                "Last 4 digits of the recipient phone. MUST resolve "
                "to an entry on WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = prepare_phase7e_live_internal_send(
            gate_id,
            template_name=options["template_name"],
            template_language=options["template_language"],
            allowed_recipient_last4=options["allowed_recipient_last4"],
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created") or report.get("reused"):
            attempt = report.get("attempt") or {}
            label = (
                "created" if report.get("created") else "reused"
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7E-Live-A attempt {label} attempt_id="
                    f"{attempt.get('id')} status={attempt.get('status')}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
