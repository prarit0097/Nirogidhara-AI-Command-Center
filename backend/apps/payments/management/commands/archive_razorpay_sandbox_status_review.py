"""``python manage.py archive_razorpay_sandbox_status_review --review-id <ID> --reason "..." --json``.

Phase 6O — archive a sandbox status review. Never mutates business
tables; never calls Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_status_mapping import (
    archive_phase6o_sandbox_status_review,
)


class Command(BaseCommand):
    help = (
        "Phase 6O — archive a sandbox status review. No business "
        "mutation, no provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--review-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        review_id = options["review_id"]
        if review_id <= 0:
            raise CommandError("--review-id must be a positive integer")

        report = archive_phase6o_sandbox_status_review(
            review_id,
            archived_by=None,
            reason=options.get("reason") or "",
        )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        if report.get("ok"):
            self.stdout.write(
                self.style.WARNING(
                    f"Review {report['review']['id']} -> "
                    f"{report['review']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Archive blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
