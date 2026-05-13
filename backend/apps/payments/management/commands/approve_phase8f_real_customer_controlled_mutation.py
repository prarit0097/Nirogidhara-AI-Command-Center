"""``python manage.py approve_phase8f_real_customer_controlled_mutation
--gate-id <ID> --reason "..." [--json]``.

Phase 8F - approve a prepared gate. Promotes status to
``approved_for_one_shot_real_customer_mutation`` AND mints a
matching attempt row in
``approved_for_one_shot_real_mutation`` status. Approval ALONE
does NOT execute the mutation; the execute CLI command is the
ONLY path that may write Order.payment_status / Payment.status.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8f_real_customer_controlled_mutation import (
    approve_phase8f_real_customer_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - approve a prepared Controlled Real Customer "
        "Payment -> Order Mutation gate. require_reason=True. "
        "Approval ALONE does NOT execute the mutation; the execute "
        "CLI command is the ONLY path that may write Order.payment_status "
        "/ Payment.status."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--gate-id",
            type=int,
            required=True,
            help="Phase 8F gate id to approve.",
        )
        parser.add_argument(
            "--reason",
            type=str,
            required=True,
            help="Non-empty Director approval reason.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options.get("gate_id") or 0)
        if gate_id <= 0:
            raise CommandError("gate_id must be a positive integer.")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError("--reason cannot be empty.")
        report = approve_phase8f_real_customer_controlled_mutation(
            gate_id, reason=reason
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 8F approve")
        )
        self.stdout.write(f"  ok        : {report['ok']}")
        self.stdout.write(
            f"  nextAction: {report.get('nextAction')}"
        )
        if report.get("attempt"):
            self.stdout.write(
                f"  attemptId : {report['attempt']['id']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
