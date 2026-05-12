"""``python manage.py inspect_phase8b_payment_order_mutation_review_gate --json``.

Phase 8B — read-only readiness for the Payment -> Order Mutation
Review Gate. NEVER calls a provider; NEVER mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8b_payment_order_mutation_review import (
    emit_readiness_inspected_audit,
    inspect_phase8b_payment_order_mutation_review_readiness,
)


class Command(BaseCommand):
    help = (
        "Phase 8B — read-only readiness for the Payment -> Order "
        "Mutation Review Gate. Review / dry-run only. No provider "
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
        report = (
            inspect_phase8b_payment_order_mutation_review_readiness()
        )
        if not options.get("no_audit"):
            emit_readiness_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8B Payment -> Order Mutation Review Readiness"
            )
        )
        self.stdout.write(
            f"  status              : {report['status']}"
        )
        self.stdout.write(
            f"  phase8b flag        : "
            f"{report['phase8BPaymentOrderMutationReviewGateEnabled']}"
        )
        self.stdout.write(
            f"  killSwitchEnabled   : "
            f"{report['killSwitch'].get('enabled')}"
        )
        self.stdout.write(
            f"  eligible 8A gates   : "
            f"{report['eligiblePhase8AGateCount']}"
        )
        for status, count in report["phase8BGateCounts"].items():
            self.stdout.write(f"  gates {status:<55}: {count}")
        self.stdout.write(
            f"  nextAction          : {report['nextAction']}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
