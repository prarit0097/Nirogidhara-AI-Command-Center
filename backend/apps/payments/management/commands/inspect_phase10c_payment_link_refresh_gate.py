"""Phase 10C — CLI: inspect a payment-link refresh gate (read-only)."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.payments.phase10c_payment_link_refresh import inspect_gate


class Command(BaseCommand):
    help = (
        "Phase 10C — Read-only inspector for a payment-link refresh "
        "gate. Shows status, mode, payment summary, previous + new "
        "URL, Razorpay link id, and the runtime env / kill switch "
        "state."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("gate_id", type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        report = inspect_gate(gate_id=int(options["gate_id"]))
        if options.get("json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write(json.dumps(report, default=str, indent=2))
