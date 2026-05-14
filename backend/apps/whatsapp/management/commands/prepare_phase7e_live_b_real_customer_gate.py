from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.whatsapp.phase7e_live_b_real_customer_send import prepare_gate


class Command(BaseCommand):
    help = "Prepare a draft Phase 7E-Live-B real-customer WhatsApp send gate."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--target-phone", required=True)
        parser.add_argument("--target-customer-name", required=True)
        parser.add_argument("--template-name", required=True)
        parser.add_argument("--template-params", default="{}")
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        report = prepare_gate(
            target_phone=options["target_phone"],
            target_customer_name=options["target_customer_name"],
            template_name=options["template_name"],
            template_params=options.get("template_params") or "{}",
            operator_name=options["operator_name"],
        )
        if options.get("json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write(f"ok: {report['ok']}")
        self.stdout.write(f"gateId: {report.get('gateId')}")
        self.stdout.write(f"status: {report.get('status')}")
        self.stdout.write(f"templateName: {report.get('templateName')}")
        self.stdout.write(f"targetMasked: {report.get('targetMasked')}")
        for blocker in report.get("blockers") or []:
            self.stdout.write(f"blocker: {blocker}")
