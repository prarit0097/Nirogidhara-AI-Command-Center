"""``python manage.py preview_razorpay_whatsapp_internal_notification_gate \\
    --attempt-id <PHASE_7D_ATTEMPT_ID> --json``.

Phase 7E - read-only preview. Never creates rows, never sends, never
queues, never calls a provider, never mutates business rows, never
edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_notification import (
    preview_phase7e_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - preview a WhatsApp internal notification gate from "
        "a Phase 7D attempt (read-only; no provider call; no business "
        "mutation; no WhatsApp send / queue)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        report = preview_phase7e_gate(attempt_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 7E preview for Phase 7D attempt id={attempt_id}"
            )
        )
        self.stdout.write(f"  found       : {report['found']}")
        self.stdout.write(f"  eligible    : {report['eligible']}")
        self.stdout.write(
            f"  phase 7B    : {report.get('sourcePhase7BGateId')}"
        )
        self.stdout.write(
            f"  phase 6T    : {report.get('sourcePhase6TLockId')}"
        )
        self.stdout.write(
            f"  signoff status: "
            f"{report.get('sourcePhase7DSignoffWindowValidationStatus')}"
        )
        self.stdout.write(f"  nextAction  : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
