from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.whatsapp.phase7e_live_b_real_customer_send import cancel_gate


class Command(BaseCommand):
    help = "Cancel a non-executed Phase 7E-Live-B real-customer send gate."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        if options["gate_id"] <= 0:
            raise CommandError("--gate-id must be positive.")
        report = cancel_gate(
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
        self.stdout.write(f"nextAction: {report.get('nextAction')}")
        for blocker in report.get("blockers") or []:
            self.stdout.write(f"blocker: {blocker}")
