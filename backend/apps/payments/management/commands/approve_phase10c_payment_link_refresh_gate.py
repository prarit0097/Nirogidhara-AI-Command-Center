"""Phase 10C — CLI: approve a Razorpay payment-link refresh gate."""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.payments.phase10c_payment_link_refresh import approve_gate


class Command(BaseCommand):
    help = (
        "Phase 10C — Approve a payment-link refresh gate. Live mode "
        "requires a structured Director signoff with BEGIN_UTC / "
        "END_UTC markers (validate_execution_window applies)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--intent", required=True)
        parser.add_argument("--director-signoff", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        result = approve_gate(
            gate_id=int(options["gate_id"]),
            operator_name=options["operator_name"],
            intent=options["intent"],
            director_signoff=options["director_signoff"],
        )
        payload = result.to_payload()
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
        else:
            self.stdout.write("OK" if result.ok else "REFUSED")
            self.stdout.write(json.dumps(payload, default=str, indent=2))
        if not result.ok:
            sys.exit(1)
