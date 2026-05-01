"""``python manage.py inspect_default_organization_coverage --json``.

Phase 6B — Default Org Data Backfill Plan.

Read-only coverage inspector. Reports per-model row counts +
``organization`` / ``branch`` coverage percentages so the operator can
confirm the backfill landed before opening Phase 6C (org-scoped API
filtering). Strictly read-only — no DB writes, no audit rows, no
external calls.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.saas.coverage import compute_default_organization_coverage


class Command(BaseCommand):
    help = (
        "Read-only coverage inspector for the Phase 6B default-org "
        "backfill. Reports per-model row counts + org/branch coverage "
        "percentages."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report: dict[str, Any] = compute_default_organization_coverage()

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Default-org coverage inspector"
            )
        )
        self.stdout.write(
            f"  defaultOrganizationExists  : "
            f"{report['defaultOrganizationExists']}"
        )
        self.stdout.write(
            f"  defaultBranchExists        : "
            f"{report['defaultBranchExists']}"
        )
        self.stdout.write(
            f"  globalTenantFilteringEnabled: "
            f"{report['globalTenantFilteringEnabled']}"
        )
        self.stdout.write(
            f"  safeToStartPhase6C         : "
            f"{report['safeToStartPhase6C']}"
        )
        for row in report["models"]:
            self.stdout.write(
                f"  - {row['model']:<40} "
                f"total={row['totalRows']:<6} "
                f"with_org={row['withOrganization']:<6} "
                f"without_org={row['withoutOrganization']:<6} "
                f"org_cov={row['organizationCoveragePercent']:6.2f}% "
                + (
                    f"with_branch={row['withBranch']:<6} "
                    f"without_branch={row['withoutBranch']:<6} "
                    f"branch_cov={row['branchCoveragePercent']:6.2f}%"
                    if row["hasBranchField"]
                    else "branch=n/a"
                )
            )
        if report["blockers"]:
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
