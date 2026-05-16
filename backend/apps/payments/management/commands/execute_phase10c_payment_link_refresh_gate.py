"""Phase 10C — CLI: execute a Razorpay payment-link refresh gate."""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.payments.phase10c_payment_link_refresh import execute_gate


class Command(BaseCommand):
    help = (
        "Phase 10C — Execute a payment-link refresh gate. Live mode "
        "requires PHASE10C_PAYMENT_LINK_REFRESH_ENABLED=true env, "
        "--confirm-phase10c-payment-link-refresh-live, kill switch on, "
        "RAZORPAY_MODE=live, and a valid in-window Director signoff."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument(
            "--confirm-phase10c-payment-link-refresh-live",
            action="store_true",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        result = execute_gate(
            gate_id=int(options["gate_id"]),
            operator_name=options["operator_name"],
            confirm_live=bool(
                options.get("confirm_phase10c_payment_link_refresh_live")
            ),
        )
        payload = result.to_payload()
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
        else:
            self.stdout.write("OK" if result.ok else "REFUSED")
            self.stdout.write(json.dumps(payload, default=str, indent=2))
        if not result.ok:
            sys.exit(1)
