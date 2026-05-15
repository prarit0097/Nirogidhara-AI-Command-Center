from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.shipments.phase7g_live_real_customer_dispatch import prepare_gate


class Command(BaseCommand):
    help = "Prepare a draft Phase 7G-Live real-customer Delhivery dispatch gate."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--order-id", required=True)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        report = prepare_gate(
            order_id=options["order_id"],
            operator_name=options["operator_name"],
        )
        if options.get("json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write(f"ok: {report['ok']}")
        self.stdout.write(f"gateId: {report.get('gateId')}")
        self.stdout.write(f"status: {report.get('status')}")
        self.stdout.write(f"orderId: {report.get('orderId')}")
        self.stdout.write(f"orderState: {report.get('orderState')}")
        for blocker in report.get("blockers") or []:
            self.stdout.write(f"blocker: {blocker}")
