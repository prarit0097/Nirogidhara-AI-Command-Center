"""``python manage.py simulate_mcp_tool_call --tool <name> [--input '{...}'] --json``.

Phase 6M-0 — runs ONE registered tool through the executor with
``bypass_auth_for_internal=True`` (the CLI is gated by OS auth, not
by our DRF auth). Never calls external providers, never mutates
business records, always creates an MCP audit row.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

# Importing handlers ensures the in-memory registry is populated
# before the executor dispatches.
from apps.mcp_gateway.services import tool_handlers  # noqa: F401
from apps.mcp_gateway.services.tool_executor import execute_mcp_tool


class Command(BaseCommand):
    help = (
        "Simulate one MCP tool call. Phase 6M-0 read-only foundation; "
        "the call NEVER reaches an external provider and NEVER "
        "mutates business records."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--tool",
            required=True,
            help="Tool name (e.g. system.get_phase_status).",
        )
        parser.add_argument(
            "--input",
            default="",
            help="Optional JSON-encoded input payload.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        tool_name = options["tool"]
        raw = options.get("input") or ""
        input_data: dict = {}
        if raw:
            try:
                parsed = _json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("input must be a JSON object")
                input_data = parsed
            except (ValueError, TypeError) as exc:
                raise CommandError(f"Invalid --input JSON: {exc}") from exc
        result = execute_mcp_tool(
            tool_name,
            input_data=input_data,
            bypass_auth_for_internal=True,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(result, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"MCP simulation: {tool_name}")
        )
        for key in (
            "passed",
            "status",
            "invocationId",
            "providerCallAttempted",
            "businessMutationAttempted",
            "rawSecretExposed",
            "fullPiiExposed",
            "outputTruncated",
            "durationMs",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<26}: {result.get(key)}")
        if result.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in result["blockers"]:
                self.stdout.write(f"  - {b}")
