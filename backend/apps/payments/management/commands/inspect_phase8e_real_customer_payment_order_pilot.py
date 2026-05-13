"""``python manage.py inspect_phase8e_real_customer_payment_order_pilot --json``.

Phase 8E - read-only readiness for the Real Customer Payment ->
Order Mutation Pilot Gate. NEVER calls a provider; NEVER mutates
business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    emit_readiness_inspected_audit,
    inspect_phase8e_real_customer_payment_order_pilot_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 8E - read-only readiness for the Real Customer "
        "Payment -> Order Mutation Pilot Gate. Review / dry-run "
        "only. No provider call, no business mutation, no .env "
        "edit."
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
            inspect_phase8e_real_customer_payment_order_pilot_readiness()
        )
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8E Real Customer Payment -> Order Pilot Readiness"
            )
        )
        self.stdout.write(f"  status                : {report['status']}")
        self.stdout.write(
            f"  phase8e flag          : "
            f"{report['phase8EPaymentOrderPilotEnabled']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled     : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  eligible 8D locks     : "
            f"{report['eligiblePhase8DLockCount']}"
        )
        for status, count in report["phase8EGateCounts"].items():
            self.stdout.write(f"  gates {status:<60}: {count}")
        self.stdout.write(f"  nextAction            : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
