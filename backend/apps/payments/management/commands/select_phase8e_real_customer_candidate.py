"""``python manage.py select_phase8e_real_customer_candidate \\
    --gate-id N --order-id "..." --payment-id "..." --json``.

Phase 8E - select ONE real customer Order + Payment candidate on
the pilot gate. Idempotent on (gate, order_id, payment_id). NEVER
mutates real rows. NEVER persists raw phone / email / address /
provider payload - only the masked phone-last-4 / masked customer
name. NEVER calls a provider.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    select_phase8e_real_customer_candidate,
)


class Command(BaseCommand):
    help = (
        "Phase 8E - select ONE real customer Order + Payment "
        "candidate on the pilot gate. Phase 8C sandbox rows are "
        "rejected. Raw phone / email / address / provider payload "
        "are NEVER persisted; only masked fields surface."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--order-id", required=True, type=str,
            help="Order.id (real customer; must not be a phase8c sandbox row).",
        )
        parser.add_argument(
            "--payment-id", required=True, type=str,
            help="Payment.id (must belong to the same Order).",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        order_id = (options.get("order_id") or "").strip()
        payment_id = (options.get("payment_id") or "").strip()
        if not order_id:
            raise CommandError(
                "--order-id must be a non-empty string."
            )
        if not payment_id:
            raise CommandError(
                "--payment-id must be a non-empty string."
            )
        report = select_phase8e_real_customer_candidate(
            gate_id,
            order_id=order_id,
            payment_id=payment_id,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            cand = report.get("candidate") or {}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8E candidate selected candidate_id="
                    f"{cand.get('id')} gate_id={gate_id} "
                    f"validation_passed=True"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR("Candidate selection blocked.")
            )
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
