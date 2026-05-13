"""``python manage.py preview_phase8e_real_customer_payment_order_pilot --phase8d-lock-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    preview_phase8e_real_customer_payment_order_pilot,
)


class Command(BaseCommand):
    help = (
        "Phase 8E - preview the Real Customer Payment -> Order "
        "Pilot Gate against a Phase 8D locked evidence chain. "
        "Review / dry-run only. No provider call, no business "
        "mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--phase8d-lock-id", required=True, type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        phase8d_lock_id = int(options["phase8d_lock_id"])
        if phase8d_lock_id <= 0:
            raise CommandError(
                "--phase8d-lock-id must be a positive integer"
            )
        report = preview_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8E Real Customer Payment -> Order Pilot Preview"
            )
        )
        self.stdout.write(f"  found      : {report['found']}")
        self.stdout.write(f"  eligible   : {report['eligible']}")
        self.stdout.write(
            f"  phase8d    : {report.get('sourcePhase8DLockId')}"
        )
        self.stdout.write(
            f"  phase8c    : {report.get('sourcePhase8CGateId')}"
        )
        self.stdout.write(f"  nextAction : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
