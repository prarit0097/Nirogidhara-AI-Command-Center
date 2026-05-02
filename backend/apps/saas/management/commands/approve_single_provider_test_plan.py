"""``python manage.py approve_single_provider_test_plan --plan-id <id> ...``.

Phase 6J — approval ONLY enables the future Phase 6K execution gate.
It NEVER unlocks a provider call in Phase 6J.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.models import RuntimeProviderTestPlan
from apps.saas.provider_test_plan import (
    approve_single_provider_test_plan,
    serialize_provider_test_plan,
)


class Command(BaseCommand):
    help = (
        "Approve a validated provider test plan for FUTURE execution. "
        "Phase 6J never executes a provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan-id", required=True, help="Plan ID")
        parser.add_argument("--reason", default="", help="Audit reason")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        plan_id = options["plan_id"]
        if not RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).exists():
            raise CommandError(f"Provider test plan not found: {plan_id}")
        plan = approve_single_provider_test_plan(
            plan_id,
            reason=options.get("reason") or "",
        )
        report = {
            "passed": (
                plan.status
                == RuntimeProviderTestPlan.Status.APPROVED_FOR_FUTURE_EXECUTION
            ),
            **serialize_provider_test_plan(plan),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Provider test plan approval")
        )
        self.stdout.write(f"  plan {report['planId']} → {report['status']}")
        self.stdout.write(f"  next action: {report['nextAction']}")
