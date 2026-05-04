"""``python manage.py prepare_razorpay_sandbox_status_review --event-id <ID> --json``.

Phase 6O — create (or re-fetch) a sandbox status review row for one
verified Phase 6M ``RazorpayWebhookEvent``. NEVER mutates business
tables. NEVER calls Razorpay. NEVER sends a customer notification.

Refuses unless ``RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=true`` AND the
source event is synthetic-eligible per Phase 6O policy.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_status_mapping import (
    prepare_phase6o_sandbox_status_review,
)


class Command(BaseCommand):
    help = (
        "Phase 6O — prepare a sandbox-only status review row from a "
        "Phase 6M-verified RazorpayWebhookEvent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--event-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        event_id = options["event_id"]
        if event_id <= 0:
            raise CommandError("--event-id must be a positive integer")

        report = prepare_phase6o_sandbox_status_review(event_id)

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        if report.get("created"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created review id={report['review']['id']} "
                    f"status={report['review']['status']}"
                )
            )
        elif report.get("reused"):
            self.stdout.write(
                self.style.WARNING(
                    f"Reused existing review id="
                    f"{report['review']['id']} status="
                    f"{report['review']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")

        self.stdout.write(f"  nextAction: {report['nextAction']}")
