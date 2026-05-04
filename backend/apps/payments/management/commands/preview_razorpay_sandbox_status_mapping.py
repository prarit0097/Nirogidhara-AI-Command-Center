"""``python manage.py preview_razorpay_sandbox_status_mapping --event-id <ID> --json``.

Phase 6O — read-only preview of how a Phase 6M ``RazorpayWebhookEvent``
would map onto a sandbox review row. NEVER creates a review row,
NEVER mutates business tables, NEVER calls Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_status_mapping import (
    preview_phase6o_status_mapping_for_event,
)


class Command(BaseCommand):
    help = (
        "Phase 6O — preview the sandbox-only status mapping for one "
        "RazorpayWebhookEvent. No review is created, no provider call, "
        "no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--event-id",
            required=True,
            type=int,
            help="Primary key of the source RazorpayWebhookEvent row.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        event_id = options["event_id"]
        if event_id <= 0:
            raise CommandError("--event-id must be a positive integer")

        report = preview_phase6o_status_mapping_for_event(event_id)

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        if not report.get("found"):
            self.stdout.write(self.style.WARNING("Event not found."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
            return

        ev = report["event"]
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 6O preview · {ev['eventName']} ({ev['sourceEventId']})"
            )
        )
        self.stdout.write(f"  eligible: {report['eligible']}")
        if report.get("proposedMapping"):
            mapping = report["proposedMapping"]
            self.stdout.write(
                f"  proposed payment status : "
                f"{mapping['futureSandboxPaymentStatus']}"
            )
            self.stdout.write(
                f"  proposed order effect   : "
                f"{mapping['futureSandboxOrderEffect']}"
            )
            self.stdout.write(
                f"  proposed review action  : "
                f"{mapping['proposedReviewAction']}"
            )
            self.stdout.write(
                f"  mutation in 6O          : "
                f"{mapping['mutationAllowedInPhase6O']}"
            )

        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
