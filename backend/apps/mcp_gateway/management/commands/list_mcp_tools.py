"""``python manage.py list_mcp_tools --json``.

Phase 6M-0 — list registered MCP tools with risk + read-only flags.
Never returns secrets.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.mcp_gateway.models import McpToolDefinition


class Command(BaseCommand):
    help = "List registered MCP tools (Phase 6M-0)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        rows = []
        for tool in McpToolDefinition.objects.all().order_by("category", "name"):
            rows.append(
                {
                    "name": tool.name,
                    "title": tool.title,
                    "category": tool.category,
                    "riskLevel": tool.risk_level,
                    "enabled": tool.enabled,
                    "readOnly": tool.read_only,
                    "providerCallAllowed": tool.provider_call_allowed,
                    "businessMutationAllowed": tool.business_mutation_allowed,
                    "requiresAuth": tool.requires_auth,
                    "piiExposureLevel": tool.pii_exposure_level,
                    "requiredScopes": list(tool.required_scopes or []),
                    "tags": list(tool.tags or []),
                }
            )
        report = {"count": len(rows), "tools": rows}
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"MCP tools ({report['count']})")
        )
        for tool in rows:
            self.stdout.write(
                f"  {tool['name']:<38} {tool['category']:<10} "
                f"risk={tool['riskLevel']:<6} ro={tool['readOnly']} "
                f"provider={tool['providerCallAllowed']} "
                f"mutation={tool['businessMutationAllowed']}"
            )
