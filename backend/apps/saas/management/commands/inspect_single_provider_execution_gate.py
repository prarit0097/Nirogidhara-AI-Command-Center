"""``python manage.py inspect_single_provider_execution_gate --json``.

Phase 6K — read-only readiness inspector for the Razorpay test-mode
execution gate. NEVER calls a provider, NEVER mutates data, NEVER
returns raw secrets.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.models import Organization
from apps.saas.provider_execution import (
    inspect_single_provider_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Read-only Phase 6K diagnostic. Reports approved-plan + env "
        "readiness + execution-attempt counters. No external call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--organization-code", default="", help="Optional org code"
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        code = (options.get("organization_code") or "").strip()
        org = (
            Organization.objects.filter(code=code).first()
            if code
            else get_default_organization()
        )
        report = inspect_single_provider_execution_attempt(organization=org)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6K Razorpay test-mode execution gate"
            )
        )
        for key in (
            "executionAttemptCount",
            "successfulExecutionCount",
            "failedExecutionCount",
            "blockedExecutionCount",
            "providerCallAttemptedCount",
            "externalCallMadeCount",
            "businessMutationCount",
            "killSwitchActive",
            "safeToRunPhase6KExecution",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
