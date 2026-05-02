"""``python manage.py inspect_runtime_integration_routing --json``.

Phase 6F — Per-Org Runtime Integration Routing Plan diagnostic.

Read-only. Reports per-provider runtime preview for the default
(or a specified) organization. Strict invariants:

- ``runtimeUsesPerOrgSettings`` is always ``False`` in this phase.
- ``runtimeSource`` is always ``env_config`` per provider.
- No external provider calls. No raw secrets returned.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.integration_runtime import get_all_provider_runtime_previews
from apps.saas.models import Organization


class Command(BaseCommand):
    help = (
        "Read-only Phase 6F diagnostic — per-org runtime integration "
        "routing preview. Live runtime still uses env/config; this "
        "command reports the readiness of every per-org provider "
        "setting without contacting any provider or returning secrets."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--organization-code",
            default="",
            help=(
                "Optional org code to inspect. Defaults to the seeded "
                "'nirogidhara' default organization."
            ),
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        code = (options.get("organization_code") or "").strip()
        org: Organization | None
        if code:
            org = Organization.objects.filter(code=code).first()
        else:
            org = get_default_organization()

        report: dict[str, Any] = get_all_provider_runtime_previews(org)

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6F runtime routing preview")
        )
        org_payload = report.get("organization") or {}
        self.stdout.write(
            f"  organization                 : "
            f"{org_payload.get('code', '<missing>')} "
            f"(id={org_payload.get('id', '<missing>')})"
        )
        self.stdout.write(
            f"  runtimeUsesPerOrgSettings    : "
            f"{report['runtimeUsesPerOrgSettings']}"
        )
        self.stdout.write(
            f"  perOrgRuntimeEnabled         : "
            f"{report['perOrgRuntimeEnabled']}"
        )
        for provider in report["providers"]:
            self.stdout.write(
                f"  - {provider['providerLabel']:<16} · "
                f"setting={provider['integrationSettingExists']} · "
                f"status={provider['settingStatus']} · "
                f"runtime={provider['runtimeSource']} · "
                f"refsPresent={provider['secretRefsPresent']} · "
                f"missing={','.join(provider['missingSecretRefs']) or '-'}"
            )
        global_summary = report.get("global", {})
        self.stdout.write(
            f"  safeToStartPhase6G           : "
            f"{global_summary.get('safeToStartPhase6G')}"
        )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
        if report.get("warnings"):
            self.stdout.write(self.style.WARNING("warnings:"))
            for warning in report["warnings"]:
                self.stdout.write(f"  - {warning}")
        self.stdout.write(f"nextAction: {report.get('nextAction', '')}")
