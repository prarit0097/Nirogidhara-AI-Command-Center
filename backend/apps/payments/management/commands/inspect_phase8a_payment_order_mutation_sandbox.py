"""``python manage.py inspect_phase8a_payment_order_mutation_sandbox --json``.

Phase 8A — read-only readiness for the Payment -> Order Mutation
Sandbox Gate. NEVER calls a provider; NEVER mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8a_payment_order_mutation_sandbox import (
    emit_readiness_inspected_audit,
    inspect_phase8a_payment_order_mutation_sandbox_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 8A — read-only readiness for the Payment -> Order "
        "Mutation Sandbox Gate. Sandbox / dry-run only. No provider "
        "call, no business mutation, no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase8a_payment_order_mutation_sandbox_readiness()
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8A Payment -> Order Mutation Sandbox Readiness"
            )
        )
        self.stdout.write(
            f"  status              : {report['status']}"
        )
        self.stdout.write(
            f"  phase8a flag        : "
            f"{report['phase8APaymentOrderMutationSandboxEnabled']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  eligible 7I locks   : "
            f"{report['eligiblePhase7ILockCount']}"
        )
        for status, count in report["phase8AGateCounts"].items():
            self.stdout.write(f"  gates {status:<40}: {count}")
        self.stdout.write(
            f"  nextAction          : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
