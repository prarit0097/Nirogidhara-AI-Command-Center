from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.whatsapp.phase7e_live_b_real_customer_send import inspect_gate_readiness


class Command(BaseCommand):
    help = "Inspect Phase 7E-Live-B real-customer WhatsApp one-shot gate readiness."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--no-audit", action="store_true")

    def handle(self, *args, **options) -> None:
        report = inspect_gate_readiness(emit_audit=not options.get("no_audit"))
        if options.get("json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write("Phase 7E-Live-B readiness")
        self.stdout.write(f"  status      : {report['status']}")
        self.stdout.write(f"  flagEnabled : {report['flagEnabled']}")
        self.stdout.write(f"  killSwitch  : {report['killSwitch'].get('enabled')}")
        self.stdout.write(f"  nextAction  : {report['nextAction']}")
        for blocker in report.get("blockers") or []:
            self.stdout.write(f"  blocker     : {blocker}")
