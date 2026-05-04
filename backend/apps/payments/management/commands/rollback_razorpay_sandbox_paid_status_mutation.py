"""``python manage.py rollback_razorpay_sandbox_paid_status_mutation \\
    --attempt-id <ID> --confirm-sandbox-rollback --reason "..." --json``.

Phase 6P — roll back a sandbox paid-status mutation attempt against
the Phase 6P ledger only. NEVER mutates real ``Order`` / ``Payment``
rows. NEVER calls Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    rollback_phase6p_paid_status_mutation_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — rollback a sandbox paid-status mutation attempt "
        "(ledger-only). No real business mutation, no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--confirm-sandbox-rollback",
            action="store_true",
            help=(
                "Operator confirmation that this rollback only affects "
                "the Phase 6P sandbox ledger row."
            ),
        )
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = options["attempt_id"]
        if attempt_id <= 0:
            raise CommandError("--attempt-id must be a positive integer")

        report = rollback_phase6p_paid_status_mutation_attempt(
            attempt_id,
            confirmed=bool(options.get("confirm_sandbox_rollback")),
            reason=options.get("reason") or "",
            rolled_back_by=None,
        )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        if report.get("rolledBack"):
            self.stdout.write(
                self.style.WARNING(
                    f"Rolled back attempt id={report['attempt']['id']}"
                )
            )
        elif report.get("rolledBackAgain"):
            self.stdout.write(
                self.style.WARNING("Attempt already rolled back.")
            )
        else:
            self.stdout.write(self.style.ERROR("Rollback blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
