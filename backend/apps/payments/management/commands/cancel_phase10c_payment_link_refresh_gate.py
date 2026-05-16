"""Phase 10C — CLI: cancel a draft / approved payment-link refresh gate.

Cancellation is valid only before execute. Executed gates must be
rolled back instead (separate command).
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.payments.phase10c_payment_link_refresh import cancel_gate


class Command(BaseCommand):
    help = (
        "Phase 10C — Cancel a draft / approved payment-link refresh "
        "gate. Use rollback_phase10c_payment_link_refresh_gate for "
        "executed gates."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        result = cancel_gate(
            gate_id=int(options["gate_id"]),
            operator_name=options["operator_name"],
            reason=options.get("reason", ""),
        )
        payload = result.to_payload()
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
        else:
            self.stdout.write("OK" if result.ok else "REFUSED")
            self.stdout.write(json.dumps(payload, default=str, indent=2))
        if not result.ok:
            sys.exit(1)
