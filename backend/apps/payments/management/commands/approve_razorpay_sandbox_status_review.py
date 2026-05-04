"""``python manage.py approve_razorpay_sandbox_status_review --review-id <ID> --reason "..." --json``.

Phase 6O — mark a sandbox status review approved **for future Phase 6P
only**. This NEVER mutates ``Order`` / ``Payment`` / ``Shipment`` /
``DiscountOfferLog``, NEVER calls Razorpay, NEVER sends a customer
notification. Approval is permission to consider the mapping in Phase
6P, not application of any mutation.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_status_mapping import (
    approve_phase6o_sandbox_status_review,
)


class Command(BaseCommand):
    help = (
        "Phase 6O — approve a sandbox status review for future "
        "Phase 6P. No business mutation, no provider call, no "
        "customer notification."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--review-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        review_id = options["review_id"]
        if review_id <= 0:
            raise CommandError("--review-id must be a positive integer")

        report = approve_phase6o_sandbox_status_review(
            review_id,
            reviewed_by=None,
            reason=options.get("reason") or "",
        )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Review {report['review']['id']} -> "
                    f"{report['review']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approval blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
