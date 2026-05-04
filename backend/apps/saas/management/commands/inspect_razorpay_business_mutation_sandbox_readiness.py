"""``python manage.py inspect_razorpay_business_mutation_sandbox_readiness --json``.

Phase 6N — emit the Razorpay business-mutation sandbox readiness
report as JSON. Pure read-only. NEVER calls Razorpay, NEVER mutates
any DB row, NEVER returns raw secrets, NEVER returns customer data.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.razorpay_business_mutation_plan import (
    inspect_razorpay_business_mutation_sandbox_readiness,
)


class Command(BaseCommand):
    help = (
        "Emit the Phase 6N Razorpay business-mutation sandbox "
        "readiness report. Read-only; never mutates anything; never "
        "calls Razorpay."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )

    def handle(self, *args, **options) -> None:
        readiness = inspect_razorpay_business_mutation_sandbox_readiness()

        if options.get("json"):
            self.stdout.write(_json.dumps(readiness, default=str))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6N Razorpay Business Mutation Sandbox Readiness"
            )
        )
        self.stdout.write(f"  status              : {readiness['status']}")
        self.stdout.write(
            f"  latest completed    : {readiness['latestCompletedPhase']}"
        )
        self.stdout.write(f"  next phase          : {readiness['nextPhase']}")
        self.stdout.write(
            f"  businessMutationEnabled : {readiness['businessMutationEnabled']}"
        )
        self.stdout.write(
            f"  customerNotificationEnabled: {readiness['customerNotificationEnabled']}"
        )
        self.stdout.write(
            f"  rawPayloadStorageEnabled: {readiness['rawPayloadStorageEnabled']}"
        )
        self.stdout.write(
            f"  phase6M flags locked off: {readiness['phase6MFlagsLockedOff']}"
        )
        self.stdout.write(
            f"  safety counters zero    : {readiness['safetyCountersZero']}"
        )
        self.stdout.write(
            f"  planComplete         : {readiness['planComplete']}"
        )
        self.stdout.write(
            f"  eventMappingCount    : {readiness['eventMappingCount']}"
        )
        self.stdout.write(
            f"  manualReviewSize     : {readiness['manualReviewChecklistSize']}"
        )
        self.stdout.write(
            f"  rollbackStepCount    : {readiness['rollbackStepCount']}"
        )
        self.stdout.write(
            f"  safeToStartPhase6O   : {readiness['safeToStartPhase6O']}"
        )
        self.stdout.write(
            f"  nextAction           : {readiness['nextAction']}"
        )
        if readiness.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in readiness["blockers"]:
                self.stdout.write(f"  - {blocker}")
        if readiness.get("warnings"):
            self.stdout.write(self.style.WARNING("warnings:"))
            for warning in readiness["warnings"]:
                self.stdout.write(f"  - {warning}")
