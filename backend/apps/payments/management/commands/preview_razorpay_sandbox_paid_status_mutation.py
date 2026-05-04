"""``python manage.py preview_razorpay_sandbox_paid_status_mutation --review-id <ID> --json``.

Phase 6P — read-only preview. NEVER creates rows, NEVER mutates anything.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    preview_phase6p_paid_status_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — preview a sandbox paid-status mutation against an "
        "approved Phase 6O review. Read-only; never mutates business "
        "tables."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--review-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        review_id = options["review_id"]
        if review_id <= 0:
            raise CommandError("--review-id must be a positive integer")
        report = preview_phase6p_paid_status_mutation(review_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if not report.get("found"):
            self.stdout.write(self.style.ERROR("Review not found."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 6P preview · review_id={report['reviewId']}"
            )
        )
        self.stdout.write(f"  eventName               : {report['eventName']}")
        self.stdout.write(
            f"  proposedSandboxPayment : {report['proposedSandboxPaymentStatus']}"
        )
        self.stdout.write(
            f"  proposedSandboxOrder   : {report['proposedSandboxOrderEffect']}"
        )
        self.stdout.write(f"  eligible                : {report['eligible']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction              : {report['nextAction']}")
