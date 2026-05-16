"""Phase 10C — CLI: roll back an executed payment-link refresh gate."""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.payments.phase10c_payment_link_refresh import rollback_gate


class Command(BaseCommand):
    help = (
        "Phase 10C — Roll back an executed Razorpay payment-link refresh "
        "gate. Attempts to cancel the Razorpay link AND restores "
        "Payment.payment_url to its previous value. Records the result "
        "honestly even if Razorpay refuses (e.g. already-paid)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        result = rollback_gate(
            gate_id=int(options["gate_id"]),
            operator_name=options["operator_name"],
        )
        payload = result.to_payload()
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
        else:
            self.stdout.write("OK" if result.ok else "REFUSED")
            self.stdout.write(json.dumps(payload, default=str, indent=2))
        if not result.ok:
            sys.exit(1)
