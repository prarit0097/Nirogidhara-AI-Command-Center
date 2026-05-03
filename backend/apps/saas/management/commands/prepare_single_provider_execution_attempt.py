"""``python manage.py prepare_single_provider_execution_attempt --plan-id <PLAN_ID> --json``.

Phase 6K — creates a :class:`RuntimeProviderExecutionAttempt` row in
``prepared`` (or ``blocked``) status. NEVER calls Razorpay.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.models import RuntimeProviderTestPlan
from apps.saas.provider_execution import (
    prepare_single_provider_execution_attempt,
    serialize_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Prepare a Phase 6K execution attempt. No external provider "
        "call. Use execute_single_razorpay_test_order to run the call "
        "manually after preparing."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--plan-id", required=True, help="Approved Phase 6J plan id"
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        plan_id = options["plan_id"]
        if not RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).exists():
            raise CommandError(
                f"Provider test plan not found: {plan_id}"
            )
        attempt = prepare_single_provider_execution_attempt(plan_id)
        report = {
            "passed": not attempt.blockers,
            **serialize_execution_attempt(attempt),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6K execution attempt prepared")
        )
        for key in (
            "executionId",
            "planId",
            "status",
            "providerCallAllowed",
            "externalCallWillBeMade",
            "providerCallAttempted",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<26}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
