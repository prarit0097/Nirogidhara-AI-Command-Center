"""Phase 10C — CLI: prepare a Razorpay payment-link refresh gate."""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.payments.phase10c_payment_link_refresh import prepare_gate


class Command(BaseCommand):
    help = (
        "Phase 10C — Prepare a Razorpay payment-link refresh gate. "
        "Test mode is the default; live mode is gated separately at "
        "execute time."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("payment_id")
        parser.add_argument(
            "--mode", default="test", choices=("test", "live")
        )
        parser.add_argument("--force-replace", action="store_true")
        parser.add_argument("--operator-name", required=True)
        parser.add_argument("--operator-note", default="")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        result = prepare_gate(
            payment_id=options["payment_id"],
            mode=options["mode"],
            force_replace=bool(options.get("force_replace")),
            operator_name=options["operator_name"],
            operator_note=options.get("operator_note", ""),
        )
        payload = result.to_payload()
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
        else:
            self.stdout.write(
                "OK" if result.ok else "REFUSED"
            )
            self.stdout.write(json.dumps(payload, default=str, indent=2))
        if not result.ok:
            sys.exit(1)
