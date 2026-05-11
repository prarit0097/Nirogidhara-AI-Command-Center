"""``python manage.py inspect_phase7e_live_internal_whatsapp_send_attempts --limit N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_whatsapp_internal_send import (
    summarize_phase7e_live_internal_send_attempts,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - read-only listing of internal allowed-"
        "list WhatsApp send attempts. No Meta Cloud call, no "
        "business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit", type=int, default=25,
            help="Cap on the number of returned items (1-200).",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, min(int(options.get("limit") or 25), 200))
        report = summarize_phase7e_live_internal_send_attempts(
            limit=limit
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 7E-Live-A Internal WhatsApp Send Attempts "
                f"(limit={limit})"
            )
        )
        for status, count in report["counts"].items():
            self.stdout.write(f"  {status:<45} : {count}")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Recent ({len(report['items'])}):"
            )
        )
        for row in report["items"]:
            self.stdout.write(
                f"  id={row['id']:<5} status={row['status']:<40} "
                f"template={row['templateName']} "
                f"last4={row['allowedRecipientLast4']}"
            )
