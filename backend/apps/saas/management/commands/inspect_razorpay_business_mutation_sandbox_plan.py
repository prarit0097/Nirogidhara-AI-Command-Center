"""``python manage.py inspect_razorpay_business_mutation_sandbox_plan --json``.

Phase 6N — emit the Razorpay business-mutation sandbox plan as JSON.
Pure policy / planning. NEVER calls Razorpay, NEVER mutates any DB
row, NEVER returns raw secrets, NEVER returns customer data.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.razorpay_business_mutation_plan import (
    get_razorpay_business_mutation_sandbox_plan,
)


class Command(BaseCommand):
    help = (
        "Emit the Phase 6N Razorpay business-mutation sandbox plan. "
        "Pure planning policy — Phase 6O will own any sandbox "
        "mutation against synthetic test orders."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )

    def handle(self, *args, **options) -> None:
        plan = get_razorpay_business_mutation_sandbox_plan()

        if options.get("json"):
            self.stdout.write(_json.dumps(plan, default=str))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6N Razorpay Business Mutation Sandbox Plan"
            )
        )
        self.stdout.write(f"  policyVersion         : {plan['policyVersion']}")
        self.stdout.write(f"  status                : {plan['status']}")
        self.stdout.write(
            f"  latest completed phase: {plan['latestCompletedPhase']}"
        )
        self.stdout.write(f"  next phase            : {plan['nextPhase']}")
        self.stdout.write(
            f"  businessMutation enabled: {plan['businessMutationEnabled']}"
        )
        self.stdout.write(
            f"  customerNotification    : {plan['customerNotificationEnabled']}"
        )
        self.stdout.write(
            f"  rawPayloadStorage       : {plan['rawPayloadStorageEnabled']}"
        )
        self.stdout.write(f"  safeToStartPhase6O    : {plan['safeToStartPhase6O']}")
        self.stdout.write(
            f"  eventMappings         : {len(plan['eventMappings'])} events"
        )
        self.stdout.write(
            "  manualReviewChecklist : "
            f"{len(plan['manualReviewChecklist'])} items"
        )
        self.stdout.write(
            "  rollbackSteps         : "
            f"{len(plan['rollbackPlan']['rollbackSteps'])} steps"
        )
        self.stdout.write(
            f"  forbiddenActions      : {len(plan['forbiddenActions'])} entries"
        )
        self.stdout.write(f"  nextAction            : {plan['nextAction']}")
        if plan.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in plan["blockers"]:
                self.stdout.write(f"  - {blocker}")
        if plan.get("warnings"):
            self.stdout.write(self.style.WARNING("warnings:"))
            for warning in plan["warnings"]:
                self.stdout.write(f"  - {warning}")
