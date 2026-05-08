"""``python manage.py preview_delhivery_courier_execution_attempt --gate-id N --json``.

Phase 7G - read-only preview of a one-shot Delhivery TEST/MOCK
courier execution attempt derived from an approved Phase 7F gate.
NEVER creates rows; NEVER calls Delhivery; NEVER sends WhatsApp;
NEVER mutates real business rows; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution import (
    preview_phase7g_courier_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - read-only preview of a Phase 7G attempt derived "
        "from an approved Phase 7F gate. No DB writes, no Delhivery "
        "calls, no WhatsApp send, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--gate-id",
            required=True,
            type=int,
            help="ID of the source Phase 7F readiness gate.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = preview_phase7g_courier_execution_attempt(gate_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7G Courier Execution Preview"
            )
        )
        self.stdout.write(f"  found             : {report['found']}")
        self.stdout.write(
            f"  source phase7f id : {report['sourcePhase7FGateId']}"
        )
        self.stdout.write(
            f"  source phase7e id : {report['sourcePhase7EGateId']}"
        )
        self.stdout.write(
            f"  source phase7d id : {report['sourcePhase7DAttemptId']}"
        )
        self.stdout.write(
            f"  source phase7b id : {report['sourcePhase7BGateId']}"
        )
        self.stdout.write(
            f"  source phase6t id : {report['sourcePhase6TLockId']}"
        )
        self.stdout.write(
            f"  delhivery mode    : {report['delhiveryModeAtPreview']}"
        )
        self.stdout.write(
            f"  eligible          : {report['eligible']}"
        )
        self.stdout.write(
            f"  nextAction        : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
