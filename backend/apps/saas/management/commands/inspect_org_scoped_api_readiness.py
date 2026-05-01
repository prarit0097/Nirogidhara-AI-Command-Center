"""``python manage.py inspect_org_scoped_api_readiness --json``.

Phase 6C — Org-Scoped API Filtering Plan.

Read-only diagnostic. Reports every gate the Phase 6C foundation
depends on plus a typed ``nextAction`` so the operator knows what to
run before opening Phase 6D (write-path org assignment).
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.saas.readiness import compute_org_scoped_api_readiness


class Command(BaseCommand):
    help = (
        "Read-only Phase 6C readiness diagnostic — default org / branch "
        "presence, coverage percentages, scoped vs unscoped API map, "
        "audit auto-org context status, and a typed nextAction."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report: dict[str, Any] = compute_org_scoped_api_readiness()

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6C readiness")
        )
        self.stdout.write(
            f"  defaultOrganizationExists  : {report['defaultOrganizationExists']}"
        )
        self.stdout.write(
            f"  defaultBranchExists        : {report['defaultBranchExists']}"
        )
        self.stdout.write(
            f"  organizationCoveragePercent: "
            f"{report['organizationCoveragePercent']}%"
        )
        self.stdout.write(
            f"  branchCoveragePercent      : "
            f"{report['branchCoveragePercent']}%"
        )
        self.stdout.write(
            f"  auditAutoOrgContextEnabled : "
            f"{report['auditAutoOrgContextEnabled']}"
        )
        self.stdout.write(
            f"  globalTenantFilteringEnabled: "
            f"{report['globalTenantFilteringEnabled']}"
        )
        self.stdout.write(
            f"  safeToStartPhase6D         : {report['safeToStartPhase6D']}"
        )
        self.stdout.write(
            f"  scopedModels               : {len(report['scopedModels'])}"
        )
        self.stdout.write(
            f"  unscopedModels             : {len(report['unscopedModels'])}"
        )
        self.stdout.write(
            f"  scopedApis                 : {len(report['scopedApis'])}"
        )
        self.stdout.write(
            f"  unscopedApis               : {len(report['unscopedApis'])}"
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
