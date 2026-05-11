"""``python manage.py preview_phase8a_payment_order_mutation_sandbox --phase7i-lock-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8a_payment_order_mutation_sandbox import (
    preview_phase8a_payment_order_mutation_sandbox,
)


class Command(BaseCommand):
    help = (
        "Phase 8A — read-only preview of the Payment -> Order "
        "Mutation Sandbox Gate derived from a locked Phase 7I final "
        "audit lock. No DB writes, no provider call, no business "
        "mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase7i-lock-id", required=True, type=int,
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        lock_id = int(options["phase7i_lock_id"])
        if lock_id <= 0:
            raise CommandError(
                "--phase7i-lock-id must be a positive integer"
            )
        report = preview_phase8a_payment_order_mutation_sandbox(lock_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8A Payment -> Order Mutation Sandbox Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(
            f"  7I lock    : {report['sourcePhase7ILockId']}"
        )
        self.stdout.write(
            f"  7D attempt : {report['sourcePhase7DAttemptId']}"
        )
        self.stdout.write(f"  nextAction : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
