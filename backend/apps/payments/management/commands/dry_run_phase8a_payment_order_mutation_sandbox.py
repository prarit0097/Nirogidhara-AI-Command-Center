"""``python manage.py dry_run_phase8a_payment_order_mutation_sandbox \\
    --gate-id N --synthetic-order-reference "phase8a::sandbox::..." --json``.

Phase 8A — sandbox dry-run. NEVER mutates real rows. Requires a
synthetic-only reference (one of the known sandbox prefixes).
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8a_payment_order_mutation_sandbox import (
    dry_run_phase8a_payment_order_mutation_sandbox,
)


class Command(BaseCommand):
    help = (
        "Phase 8A — sandbox dry-run. Synthetic reference required "
        "(`phase8a::sandbox::...` / `phase8a-sandbox-...` / "
        "`sandbox::...`). No provider call, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument(
            "--synthetic-order-reference",
            default="",
            type=str,
            help=(
                "Synthetic-only reference. MUST start with one of "
                "the sandbox prefixes."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reference = (
            options.get("synthetic_order_reference") or ""
        ).strip()
        report = dry_run_phase8a_payment_order_mutation_sandbox(
            gate_id, synthetic_order_reference=reference
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            dry = report.get("dryRun") or {}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8A dry-run passed record_id={dry.get('id')} "
                    f"gate_id={gate_id}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Dry-run blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
