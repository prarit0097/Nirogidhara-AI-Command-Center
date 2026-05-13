"""``python manage.py reject_phase8f_real_customer_controlled_mutation
--gate-id <ID> --reason "..." [--json]``.

Phase 8F - reject a draft / pending / blocked gate.
require_reason=True. Never mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8f_real_customer_controlled_mutation import (
    reject_phase8f_real_customer_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - reject a draft / pending_manual_review / "
        "blocked gate. require_reason=True. Never mutates business "
        "rows; never calls a provider."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--gate-id",
            type=int,
            required=True,
            help="Phase 8F gate id to reject.",
        )
        parser.add_argument(
            "--reason",
            type=str,
            required=True,
            help="Non-empty Director reject reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options.get("gate_id") or 0)
        if gate_id <= 0:
            raise CommandError("gate_id must be a positive integer.")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason cannot be empty.")
        report = reject_phase8f_real_customer_controlled_mutation(
            gate_id, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 8F reject")
        )
        self.stdout.write(f"  ok        : {report['ok']}")
        self.stdout.write(
            f"  nextAction: {report.get('nextAction')}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
