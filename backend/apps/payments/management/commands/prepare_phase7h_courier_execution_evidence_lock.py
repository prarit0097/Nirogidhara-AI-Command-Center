"""``python manage.py prepare_phase7h_courier_execution_evidence_lock --attempt-id N --json``.

Phase 7H - prepare a Phase 7H evidence-lock row from a completed
Phase 7G TEST/MOCK courier execution attempt. Atomic + idempotent
on the source attempt id. NEVER calls Delhivery; NEVER mutates
business rows; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution_evidence_lock import (
    prepare_phase7h_evidence_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7H - prepare an evidence-lock from a completed Phase "
        "7G TEST/MOCK courier execution attempt."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id",
            required=True,
            type=int,
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        report = prepare_phase7h_evidence_lock(attempt_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created") or report.get("reused"):
            label = (
                "created" if report.get("created") else "reused"
            )
            lock = report.get("lock") or {}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7H evidence lock {label} lock_id="
                    f"{lock.get('id')} status={lock.get('status')}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
