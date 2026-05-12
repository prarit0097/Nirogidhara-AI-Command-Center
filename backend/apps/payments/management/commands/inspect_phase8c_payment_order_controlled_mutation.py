"""``python manage.py inspect_phase8c_payment_order_controlled_mutation --json``.

Phase 8C — read-only readiness for the Controlled Real Payment ->
Order Mutation framework. NEVER calls a provider; NEVER mutates
business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8c_payment_order_controlled_mutation import (
    emit_readiness_inspected_audit,
    inspect_phase8c_payment_order_controlled_mutation_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 8C — read-only readiness for the Controlled Real "
        "Payment -> Order Mutation framework. CLI-only one-shot "
        "internal/sandbox mutation. No provider call, no business "
        "mutation, no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the readiness AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = (
            inspect_phase8c_payment_order_controlled_mutation_readiness()
        )
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8C Controlled Payment -> Order Mutation Readiness"
            )
        )
        self.stdout.write(
            f"  status              : {report['status']}"
        )
        self.stdout.write(
            f"  phase8c gate flag   : {report['phase8CGateEnabled']}"
        )
        self.stdout.write(
            f"  director approved   : "
            f"{report['phase8CDirectorApproved']}"
        )
        self.stdout.write(
            f"  allow internal mut. : "
            f"{report['phase8CAllowInternalMutation']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  eligible 8B gates   : "
            f"{report['eligiblePhase8BGateCount']}"
        )
        for status, count in report["phase8CGateCounts"].items():
            self.stdout.write(f"  gates {status:<48}: {count}")
        self.stdout.write(
            f"  nextAction          : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
