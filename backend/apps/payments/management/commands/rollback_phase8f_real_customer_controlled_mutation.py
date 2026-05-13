"""``python manage.py rollback_phase8f_real_customer_controlled_mutation
--attempt-id <ID> --reason "..." [--json]``.

Phase 8F - rollback an executed Phase 8F attempt. Restores
``Order.payment_status`` + ``Payment.status`` from the attempt's
``old_*`` snapshots. NEVER calls a provider; NEVER sends WhatsApp;
NEVER sends a customer notification.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8f_real_customer_controlled_mutation import (
    rollback_phase8f_real_customer_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - rollback an executed attempt. Restores "
        "Order.payment_status + Payment.status from the attempt's "
        "old_* snapshots. require_reason=True. Never calls a "
        "provider, never sends WhatsApp, never sends a customer "
        "notification."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id",
            type=int,
            required=True,
            help="Phase 8F executed attempt id to roll back.",
        )
        parser.add_argument(
            "--reason",
            type=str,
            required=True,
            help="Non-empty Director rollback reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options.get("attempt_id") or 0)
        if attempt_id <= 0:
            raise CommandError(
                "attempt_id must be a positive integer."
            )
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason cannot be empty.")
        report = rollback_phase8f_real_customer_controlled_mutation(
            attempt_id, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 8F rollback")
        )
        self.stdout.write(f"  ok        : {report['ok']}")
        self.stdout.write(
            f"  nextAction: {report.get('nextAction')}"
        )
        if report.get("rollback"):
            self.stdout.write(
                f"  rollbackId: {report['rollback']['id']}"
            )
            self.stdout.write(
                f"  status    : {report['rollback']['status']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
