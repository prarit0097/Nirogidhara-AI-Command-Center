"""``python manage.py validate_single_provider_test_plan --plan-id <id> --json``.

Phase 6J — validates a previously prepared provider test plan. Never
calls the provider. Never mutates business records.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.models import RuntimeProviderTestPlan
from apps.saas.provider_test_plan import (
    assert_provider_test_plan_has_no_side_effects,
    serialize_provider_test_plan,
    validate_single_provider_test_plan,
)


class Command(BaseCommand):
    help = (
        "Validate a previously prepared provider test plan. Reports "
        "env presence + invariants. No external provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--plan-id", required=True, help="Plan ID")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        plan_id = options["plan_id"]
        if not RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).exists():
            raise CommandError(f"Provider test plan not found: {plan_id}")
        plan = validate_single_provider_test_plan(plan_id)
        report = {
            "passed": (
                plan.status == RuntimeProviderTestPlan.Status.VALIDATED
            ),
            "noSideEffects": assert_provider_test_plan_has_no_side_effects(
                plan
            ),
            "payloadHashPresent": bool(plan.payload_hash),
            "idempotencyKeyPresent": bool(plan.idempotency_key),
            **serialize_provider_test_plan(plan),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING("Provider test plan validated"))
        self.stdout.write(f"  plan {report['planId']} → {report['status']}")
        self.stdout.write(f"  next action: {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
