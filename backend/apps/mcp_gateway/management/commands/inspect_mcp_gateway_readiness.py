"""``python manage.py inspect_mcp_gateway_readiness --json``.

Phase 6M-0 — read-only readiness inspector. Never calls a provider,
never mutates data, never returns raw secrets.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.mcp_gateway.services.readiness import get_mcp_gateway_readiness


class Command(BaseCommand):
    help = (
        "Read-only Phase 6M-0 MCP gateway readiness report. "
        "Reports env/config + registry counters + safety flags."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report = get_mcp_gateway_readiness()
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6M-0 MCP gateway readiness")
        )
        for key in (
            "mcpEnabled",
            "transport",
            "publicBaseUrlConfigured",
            "requireAuth",
            "readOnlyMode",
            "writeToolsEnabled",
            "providerToolsEnabled",
            "auditEnabled",
            "maskPii",
            "toolCount",
            "enabledToolCount",
            "writeToolEnabledCount",
            "providerToolEnabledCount",
            "resourceCount",
            "promptCount",
            "activeClientCount",
            "recentInvocationCount",
            "rawSecretExposureCount",
            "fullPiiExposureCount",
            "providerCallAttemptedCount",
            "businessMutationAttemptedCount",
            "safeToEnableReadOnlyMcp",
            "safeToStartPhase6M",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
