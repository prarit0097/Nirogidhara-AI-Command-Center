"""``python manage.py prepare_single_provider_test_plan ... --json``.

Phase 6J — read-only-ish: creates a :class:`RuntimeProviderTestPlan`
row but NEVER calls a provider, NEVER mutates business records, and
NEVER returns raw secrets.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.models import Organization
from apps.saas.provider_test_plan import (
    prepare_single_provider_test_plan,
    serialize_provider_test_plan,
)


class Command(BaseCommand):
    help = (
        "Prepare a single internal provider test plan. Phase 6J only "
        "implements razorpay.create_order. No external provider call "
        "is made."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--provider",
            default="razorpay",
            help="Provider type. Default: razorpay.",
        )
        parser.add_argument(
            "--operation",
            default="razorpay.create_order",
            help="Operation type. Default: razorpay.create_order.",
        )
        parser.add_argument(
            "--organization-code",
            default="",
            help="Organization code. Default: seeded 'nirogidhara'.",
        )
        parser.add_argument(
            "--reason",
            default="",
            help="Optional human reason recorded on the plan metadata.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        operation = options.get("operation") or "razorpay.create_order"
        code = (options.get("organization_code") or "").strip()
        org = (
            Organization.objects.filter(code=code).first()
            if code
            else get_default_organization()
        )
        plan = prepare_single_provider_test_plan(
            operation_type=operation,
            organization=org,
            reason=options.get("reason") or "",
        )
        report = {
            "passed": not plan.blockers,
            **serialize_provider_test_plan(plan),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self._render_text(report)

    def _render_text(self, report: dict) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("Provider test plan prepared")
        )
        for key in (
            "planId",
            "providerType",
            "operationType",
            "providerEnvironment",
            "status",
            "amountPaise",
            "currency",
            "dryRun",
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
        if report.get("warnings"):
            self.stdout.write(self.style.WARNING("warnings:"))
            for warning in report["warnings"]:
                self.stdout.write(f"  - {warning}")
