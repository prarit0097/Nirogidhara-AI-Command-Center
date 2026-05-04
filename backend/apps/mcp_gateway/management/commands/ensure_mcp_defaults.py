"""``python manage.py ensure_mcp_defaults --json``.

Phase 6M-0 — idempotent registry seeder. Registers default tools,
resources, and prompts. NEVER enables external MCP traffic; NEVER
toggles ``MCP_ENABLED``.
"""
from __future__ import annotations

import json as _json

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the handlers module registers each handler with the
# executor's in-memory registry — required before any
# simulate_mcp_tool_call run.
from apps.mcp_gateway.services import tool_handlers  # noqa: F401
from apps.mcp_gateway.services.audit import write_registry_seed_audit
from apps.mcp_gateway.services.readiness import get_mcp_gateway_readiness
from apps.mcp_gateway.services.registry import register_default_mcp_tools


class Command(BaseCommand):
    help = (
        "Seed default MCP tools / resources / prompts. Idempotent. "
        "Phase 6M-0: never enables external MCP traffic."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        counters = register_default_mcp_tools()
        write_registry_seed_audit(counters)
        readiness = get_mcp_gateway_readiness()
        report = {
            "passed": True,
            "phase": "6M-0",
            **counters,
            "mcpEnabled": readiness["mcpEnabled"],
            "readOnlyMode": readiness["readOnlyMode"],
            "writeToolsEnabled": readiness["writeToolsEnabled"],
            "providerToolsEnabled": readiness["providerToolsEnabled"],
            "toolCount": readiness["toolCount"],
            "resourceCount": readiness["resourceCount"],
            "promptCount": readiness["promptCount"],
            "nextAction": readiness["nextAction"],
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING("MCP defaults seeded"))
        for key, value in report.items():
            if key == "passed":
                continue
            self.stdout.write(f"  {key:<26}: {value}")
