"""``python manage.py rollback_phase8c_payment_order_controlled_mutation --attempt-id N --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8c_payment_order_controlled_mutation import (
    rollback_phase8c_payment_order_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8C — restore the originally captured old_order_status "
        "/ old_payment_status on the previously mutated rows. Never "
        "calls a provider; never sends WhatsApp; never sends a "
        "customer notification; never creates a Shipment / AWB."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id", required=True, type=int
        )
        parser.add_argument(
            "--reason", default="", type=str,
            help="Mandatory non-empty rollback reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string."
            )
        report = rollback_phase8c_payment_order_controlled_mutation(
            attempt_id, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            rollback = report["rollback"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8C rollback recorded rollback_id="
                    f"{rollback['id']} attempt_id={attempt_id}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Rollback blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
