"""Phase 6M-0 — MCP gateway URL routes."""
from __future__ import annotations

from django.urls import path

from .views import (
    McpInvocationsView,
    McpPromptsView,
    McpReadinessView,
    McpResourcesView,
    McpSecurityPostureView,
    McpSimulateToolCallView,
    McpToolsView,
)


urlpatterns = [
    path("readiness/", McpReadinessView.as_view(), name="mcp-readiness"),
    path(
        "security-posture/",
        McpSecurityPostureView.as_view(),
        name="mcp-security-posture",
    ),
    path("tools/", McpToolsView.as_view(), name="mcp-tools"),
    path(
        "tools/simulate/",
        McpSimulateToolCallView.as_view(),
        name="mcp-tools-simulate",
    ),
    path("resources/", McpResourcesView.as_view(), name="mcp-resources"),
    path("prompts/", McpPromptsView.as_view(), name="mcp-prompts"),
    path("invocations/", McpInvocationsView.as_view(), name="mcp-invocations"),
]
