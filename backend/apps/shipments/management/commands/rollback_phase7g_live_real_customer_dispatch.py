from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.shipments.phase7g_live_real_customer_dispatch import rollback_gate


class Command(BaseCommand):
    help = (
        "Attempt rollback / cancellation of an executed Phase 7G-Live "
        "real-customer Delhivery dispatch. Delhivery may refuse if the AWB "
        "is already in transit; the result is always recorded honestly."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        if options["gate_id"] <= 0:
            raise CommandError("--gate-id must be positive.")
        report = rollback_gate(
            options["gate_id"],
            reason=options["reason"],
            operator_name=options["operator_name"],
        )
        if options.get("json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write(f"ok: {report['ok']}")
        self.stdout.write(f"gateId: {report.get('gateId')}")
        self.stdout.write(f"status: {report.get('status')}")
        self.stdout.write(f"awbNumber: {report.get('awbNumber')}")
        self.stdout.write(f"nextAction: {report.get('nextAction')}")
        note = report.get("note") or ""
        if note:
            self.stdout.write(f"note: {note}")
        for blocker in report.get("blockers") or []:
            self.stdout.write(f"blocker: {blocker}")
