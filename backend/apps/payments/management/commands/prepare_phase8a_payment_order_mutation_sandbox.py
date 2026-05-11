"""``python manage.py prepare_phase8a_payment_order_mutation_sandbox --phase7i-lock-id N --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8a_payment_order_mutation_sandbox import (
    prepare_phase8a_payment_order_mutation_sandbox,
)


class Command(BaseCommand):
    help = (
        "Phase 8A — prepare a sandbox gate from a locked Phase 7I "
        "final audit lock. No provider call, no business mutation, "
        "no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase7i-lock-id", required=True, type=int,
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        lock_id = int(options["phase7i_lock_id"])
        if lock_id <= 0:
            raise CommandError(
                "--phase7i-lock-id must be a positive integer"
            )
        report = prepare_phase8a_payment_order_mutation_sandbox(lock_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("created") or report.get("reused"):
            gate = report.get("gate") or {}
            label = (
                "created" if report.get("created") else "reused"
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8A sandbox gate {label} gate_id="
                    f"{gate.get('id')} status={gate.get('status')}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
