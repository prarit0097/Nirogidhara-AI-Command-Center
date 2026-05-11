"""``python manage.py rollback_phase7e_live_internal_whatsapp_send --attempt-id N --reason "..." --json``.

Phase 7E-Live-A - record-only rollback. NEVER calls Meta Cloud
delete / cancel (Meta Cloud sends are immutable). NEVER mutates
business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_send import (
    rollback_phase7e_live_internal_send,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - record-only rollback. Never calls Meta "
        "Cloud delete; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty rollback reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError("--attempt-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason must be a non-empty string.")
        report = rollback_phase7e_live_internal_send(
            attempt_id, rolled_back_by=None, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7E-Live-A rollback recorded attempt_id="
                    f"{attempt['id']} status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Rollback blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
