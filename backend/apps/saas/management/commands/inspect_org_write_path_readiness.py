"""``python manage.py inspect_org_write_path_readiness --json``.

Phase 6D — Org-Aware Write Path Assignment.

Read-only diagnostic. Reports default-org / branch presence, the list
of safe + deferred create paths, the count of rows created in the
trailing 24h that are still missing org / branch, plus a typed
``nextAction``.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.saas.write_readiness import compute_org_write_path_readiness


class Command(BaseCommand):
    help = (
        "Read-only Phase 6D readiness diagnostic — auto-assign signal "
        "coverage, recent missing-org row counts, deferred paths, and "
        "a typed nextAction telling the operator whether Phase 6E is "
        "safe to open."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report: dict[str, Any] = compute_org_write_path_readiness()

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Phase 6D readiness"))
        self.stdout.write(
            f"  defaultOrganizationExists       : "
            f"{report['defaultOrganizationExists']}"
        )
        self.stdout.write(
            f"  defaultBranchExists             : "
            f"{report['defaultBranchExists']}"
        )
        self.stdout.write(
            f"  writeContextHelpersAvailable    : "
            f"{report['writeContextHelpersAvailable']}"
        )
        self.stdout.write(
            f"  auditAutoOrgContextEnabled      : "
            f"{report['auditAutoOrgContextEnabled']}"
        )
        self.stdout.write(
            f"  globalTenantFilteringEnabled    : "
            f"{report['globalTenantFilteringEnabled']}"
        )
        self.stdout.write(
            f"  safeToStartPhase6E              : "
            f"{report['safeToStartPhase6E']}"
        )
        self.stdout.write(
            f"  recentRowsWithoutOrganization   : "
            f"{report['recentRowsWithoutOrganizationLast24h']}"
        )
        self.stdout.write(
            f"  recentRowsWithoutBranch         : "
            f"{report['recentRowsWithoutBranchLast24h']}"
        )
        self.stdout.write(
            f"  safeCreatePathsCovered          : "
            f"{len(report['safeCreatePathsCovered'])}"
        )
        self.stdout.write(
            f"  deferredCreatePaths             : "
            f"{len(report['deferredCreatePaths'])}"
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
