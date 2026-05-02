"""``python manage.py preview_runtime_operation --operation <type> --json``.

Phase 6G — single-operation dry-run preview command.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.models import Organization
from apps.saas.runtime_dry_run import (
    preview_runtime_routing_for_operation,
    validate_dry_run_has_no_side_effects,
)


class Command(BaseCommand):
    help = (
        "Read-only single-operation dry-run preview. Useful when you "
        "want to inspect one operation without rendering the full "
        "table."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--operation",
            required=True,
            help=(
                "Operation type, e.g. 'whatsapp.send_text' or "
                "'ai.ceo_planning'."
            ),
        )
        parser.add_argument(
            "--organization-code",
            default="",
            help="Default: seeded 'nirogidhara' org.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        code = (options.get("organization_code") or "").strip()
        if code:
            org = Organization.objects.filter(code=code).first()
        else:
            org = get_default_organization()
        operation = options["operation"]
        report = preview_runtime_routing_for_operation(operation, org=org)
        if not validate_dry_run_has_no_side_effects(report):
            report.setdefault("warnings", []).append(
                "Invariant violated — refusing to render as dry-run."
            )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING(operation))
        for key in (
            "providerType",
            "runtimeSource",
            "perOrgRuntimeEnabled",
            "dryRun",
            "liveExecutionAllowed",
            "externalCallWillBeMade",
            "sideEffectRisk",
            "providerSettingExists",
            "settingStatus",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<26} : {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
        if report.get("warnings"):
            self.stdout.write(self.style.WARNING("warnings:"))
            for warning in report["warnings"]:
                self.stdout.write(f"  - {warning}")
