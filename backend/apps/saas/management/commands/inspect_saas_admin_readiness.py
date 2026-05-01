"""``python manage.py inspect_saas_admin_readiness --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.admin_readiness import get_saas_admin_overview


class Command(BaseCommand):
    help = "Read-only Phase 6E SaaS admin readiness diagnostic."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        overview = get_saas_admin_overview()
        report = {
            "defaultOrganizationExists": overview[
                "defaultOrganizationExists"
            ],
            "defaultBranchExists": overview["defaultBranchExists"],
            "orgScopeReadiness": overview["orgScopeReadiness"],
            "writePathReadiness": overview["writePathReadiness"],
            "integrationSettingsCount": overview[
                "integrationSettingsCount"
            ],
            "providersConfigured": overview["providersConfigured"],
            "providersMissing": overview["providersMissing"],
            "secretRefsMissing": overview["secretRefsMissing"],
            "runtimeUsesPerOrgSettings": False,
            "safeToStartPhase6F": overview["safeToStartPhase6F"],
            "blockers": overview["blockers"],
            "warnings": overview["warnings"],
            "nextAction": overview["nextAction"],
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING("Phase 6E SaaS admin"))
        for key in (
            "defaultOrganizationExists",
            "defaultBranchExists",
            "integrationSettingsCount",
            "providersConfigured",
            "providersMissing",
            "secretRefsMissing",
            "runtimeUsesPerOrgSettings",
            "safeToStartPhase6F",
        ):
            self.stdout.write(f"  {key}: {report[key]}")
        if report["blockers"]:
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for warning in report["warnings"]:
                self.stdout.write(f"  - {warning}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
