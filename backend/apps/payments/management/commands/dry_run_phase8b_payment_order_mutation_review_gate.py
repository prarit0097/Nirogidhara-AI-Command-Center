"""``python manage.py dry_run_phase8b_payment_order_mutation_review_gate \\
    --gate-id N --target-order-reference "phase8b::review::order::001" --json``.

Phase 8B — review-only dry-run. NEVER mutates real rows. Requires a
review-only ``target-order-reference`` (one of the known prefixes).
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8b_payment_order_mutation_review import (
    dry_run_phase8b_payment_order_mutation_review_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 8B — review-only dry-run. Target-order reference "
        "required (`phase8b::review::order::...` / "
        "`phase8b-review-...` / `review::phase8b::...`). No provider "
        "call, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--target-order-reference",
            default="",
            type=str,
            help=(
                "Review-only target order reference. MUST start "
                "with one of the review prefixes."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reference = (
            options.get("target_order_reference") or ""
        ).strip()
        report = dry_run_phase8b_payment_order_mutation_review_gate(
            gate_id, target_order_reference=reference
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            dry = report.get("dryRun") or {}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8B dry-run passed record_id={dry.get('id')} "
                    f"gate_id={gate_id}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Dry-run blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
