"""``python manage.py inspect_phase8f_real_customer_controlled_mutation [--json]``.

Phase 8F - read-only readiness for the Controlled Real Customer
Payment -> Order Mutation gate. NEVER calls a provider; NEVER
mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8f_real_customer_controlled_mutation import (
    emit_readiness_inspected_audit,
    inspect_phase8f_real_customer_controlled_mutation_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - read-only readiness inspector for the "
        "Controlled Real Customer Payment -> Order Mutation gate. "
        "Never calls a provider; never mutates business rows."
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
            inspect_phase8f_real_customer_controlled_mutation_readiness()
        )
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8F Controlled Real Customer Payment -> "
                "Order Mutation Readiness"
            )
        )
        self.stdout.write(f"  status                : {report['status']}")
        self.stdout.write(
            f"  killSwitchEnabled     : "
            f"{report['killSwitch'].get('enabled')}"
        )
        for key, val in report["phase8FFlags"].items():
            self.stdout.write(f"  {key:<58}: {val}")
        self.stdout.write(
            f"  eligible 8E gates     : "
            f"{report['eligiblePhase8EGateCount']}"
        )
        for status, count in report["phase8FGateCounts"].items():
            self.stdout.write(f"  gates {status:<60}: {count}")
        self.stdout.write(
            f"  nextAction            : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
