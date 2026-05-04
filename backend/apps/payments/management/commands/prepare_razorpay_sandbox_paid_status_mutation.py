"""``python manage.py prepare_razorpay_sandbox_paid_status_mutation --review-id <ID> --json``.

Phase 6P — create a prepared sandbox mutation attempt row. NEVER
mutates ledger state, NEVER calls Razorpay, NEVER mutates real
business tables.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    prepare_phase6p_paid_status_mutation_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — prepare a sandbox paid-status mutation attempt "
        "for an approved Phase 6O review. No mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--review-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        review_id = options["review_id"]
        if review_id <= 0:
            raise CommandError("--review-id must be a positive integer")
        report = prepare_phase6p_paid_status_mutation_attempt(review_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared attempt id={report['attempt']['id']} "
                    f"status={report['attempt']['status']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused existing attempt id={report['attempt']['id']} "
                    f"status={report['attempt']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
