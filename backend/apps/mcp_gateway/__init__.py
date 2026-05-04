"""Phase 6M-0 — MCP Gateway Foundation.

Read-only registry + readiness layer that prepares the application
for future MCP-style remote AI clients (Claude / ChatGPT / Codex /
internal). Defaults are LOCKED to safe / disabled — no external
client connection, no write tool, no provider tool, no public
endpoint, no business mutation.
"""

default_app_config = "apps.mcp_gateway.apps.McpGatewayConfig"
