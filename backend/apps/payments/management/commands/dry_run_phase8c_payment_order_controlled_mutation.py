"""``python manage.py dry_run_phase8c_payment_order_controlled_mutation \\
    --gate-id N \\
    --target-order-id "phase8c-controlled-order-001" \\
    --target-payment-id "phase8c-controlled-payment-001" \\
    --target-order-reference "phase8c::controlled::order::001" \\
    --target-payment-reference "phase8c::controlled::payment::001" \\
    --json``.

Phase 8C — controlled-mutation dry-run. NEVER mutates real rows.
Requires target Order + Payment IDs that are proven internal /
sandbox / test.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8c_payment_order_controlled_mutation import (
    dry_run_phase8c_payment_order_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8C — controlled-mutation dry-run. Target Order + "
        "Payment IDs required (proven internal/sandbox/test). "
        "Target references must start with `phase8c::controlled::"
        "order::` / `phase8c-controlled-order-` (order) and "
        "`phase8c::controlled::payment::` / `phase8c-controlled-"
        "payment-` (payment). No provider call, no business "
        "mutation, no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--target-order-id", default="", type=str,
            help="Order.id of the sandbox/test Order row.",
        )
        parser.add_argument(
            "--target-payment-id", default="", type=str,
            help="Payment.id of the sandbox/test Payment row.",
        )
        parser.add_argument(
            "--target-order-reference", default="", type=str,
            help=(
                "Controlled-mutation reference. MUST start with one "
                "of the order prefixes."
            ),
        )
        parser.add_argument(
            "--target-payment-reference", default="", type=str,
            help=(
                "Controlled-mutation reference. MUST start with one "
                "of the payment prefixes."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        report = dry_run_phase8c_payment_order_controlled_mutation(
            gate_id,
            target_order_id=(
                options.get("target_order_id") or ""
            ).strip(),
            target_payment_id=(
                options.get("target_payment_id") or ""
            ).strip(),
            target_order_reference=(
                options.get("target_order_reference") or ""
            ).strip(),
            target_payment_reference=(
                options.get("target_payment_reference") or ""
            ).strip(),
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report.get("attempt") or {}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8C dry-run passed attempt_id="
                    f"{attempt.get('id')} gate_id={gate_id}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Dry-run blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
