"""``python manage.py inspect_mcp_security_posture --json``.

Phase 6M-0 — read-only security-posture inspector. Reports any
forbidden tool registered, any unexpected write/provider tool
enabled, raw-secret / PII exposure counters, and a typed
``nextAction``.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.mcp_gateway.services.readiness import get_mcp_security_posture


class Command(BaseCommand):
    help = "Read-only Phase 6M-0 MCP security posture report."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report = get_mcp_security_posture()
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING("MCP security posture"))
        for key in (
            "forbiddenToolsRegistered",
            "writeToolsEnabled",
            "providerToolsEnabled",
            "writeToolEnabledCount",
            "providerToolEnabledCount",
            "authRequired",
            "rawSecretExposureCount",
            "piiExposureCount",
            "providerCallAttemptedCount",
            "businessMutationAttemptedCount",
            "safe",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
