from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.shipments.phase7g_live_real_customer_dispatch import approve_gate


class Command(BaseCommand):
    help = "Approve one Phase 7G-Live real-customer Delhivery dispatch gate."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--director-signoff", required=True)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument(
            "--confirm-phase7g-live-real-customer-dispatch",
            action="store_true",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        if options["gate_id"] <= 0:
            raise CommandError("--gate-id must be positive.")
        report = approve_gate(
            options["gate_id"],
            director_signoff=options["director_signoff"],
            operator_name=options["operator_name"],
            confirm=bool(
                options.get("confirm_phase7g_live_real_customer_dispatch")
            ),
        )
        if options.get("json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write(f"ok: {report['ok']}")
        self.stdout.write(f"gateId: {report.get('gateId')}")
        self.stdout.write(f"status: {report.get('status')}")
        self.stdout.write(f"nextAction: {report.get('nextAction')}")
        for blocker in report.get("blockers") or []:
            self.stdout.write(f"blocker: {blocker}")
