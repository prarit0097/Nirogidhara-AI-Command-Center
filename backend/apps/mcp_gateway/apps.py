"""Phase 6M-0 — Django app config for the MCP Gateway."""
from __future__ import annotations

from django.apps import AppConfig


class McpGatewayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mcp_gateway"
    verbose_name = "MCP Gateway (Phase 6M-0 foundation)"
