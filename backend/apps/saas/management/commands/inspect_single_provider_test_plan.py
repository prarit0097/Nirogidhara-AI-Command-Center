"""``python manage.py inspect_single_provider_test_plan --json``.

Phase 6J — read-only inspector for the provider test plan registry.
Reports plan counts by status, latest plan, and a typed nextAction.
NEVER returns raw secrets. NEVER calls a provider.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.models import Organization
from apps.saas.provider_test_plan import (
    inspect_single_provider_test_plan,
)


class Command(BaseCommand):
    help = (
        "Read-only inspector for the Phase 6J provider test plan "
        "registry. No provider call, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--plan-id", default="", help="Optional plan id filter"
        )
        parser.add_argument(
            "--organization-code", default="", help="Optional org code filter"
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        code = (options.get("organization_code") or "").strip()
        org = (
            Organization.objects.filter(code=code).first()
            if code
            else get_default_organization()
        )
        report = inspect_single_provider_test_plan(
            plan_id=options.get("plan_id") or None,
            organization=org,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Provider test plan readiness")
        )
        for key in (
            "planCount",
            "preparedCount",
            "validatedCount",
            "approvedCount",
            "archivedCount",
            "blockedCount",
            "providerCallAttemptedCount",
            "externalCallMadeCount",
            "killSwitchActive",
            "safeToStartPhase6K",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<28}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
