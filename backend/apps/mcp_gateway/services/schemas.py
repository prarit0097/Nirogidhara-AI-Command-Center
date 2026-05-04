"""Phase 6M-0 — MCP scope vocabulary + forbidden tool list.

The actual tool registry lives in :mod:`apps.mcp_gateway.services.default_tools`;
this module is the locked vocabulary the rest of the gateway consumes.
"""
from __future__ import annotations


# Read-only scope vocabulary surfaced via the API. WRITE / EXECUTE
# scopes are intentionally omitted from this enabled list — they are
# Phase 6M+ work.
ENABLED_SCOPES: tuple[str, ...] = (
    "mcp:system.read",
    "mcp:saas.read",
    "mcp:audit.read",
    "mcp:whatsapp.read",
    "mcp:razorpay.read",
    "mcp:dashboard.read",
    "mcp:agents.read",
    "mcp:tools.invoke.readonly",
)

# Phase 6M-0 lists these as future / disabled scopes; nothing in the
# code path may grant them yet.
FUTURE_DISABLED_SCOPES: tuple[str, ...] = (
    "mcp:tools.invoke.write",
    "mcp:tools.invoke.provider",
    "mcp:razorpay.write",
    "mcp:whatsapp.write",
    "mcp:payments.write",
    "mcp:shipments.write",
    "mcp:vapi.write",
    "mcp:campaigns.write",
)

# Tools that MUST NEVER be registered nor enabled — even if a future
# config tries to include them. The executor refuses to dispatch
# anything in this list.
FORBIDDEN_TOOLS: tuple[str, ...] = (
    "razorpay.create_order",
    "razorpay.capture_payment",
    "razorpay.create_payment_link",
    "whatsapp.send_message",
    "delhivery.create_shipment",
    "vapi.place_call",
    "campaign.start",
    "payment.execute",
    "order.create_live",
    "crm.bulk_update",
    "system.shell",
    "system.sql",
    "system.http_fetch",
)


def is_forbidden_tool(name: str) -> bool:
    return (name or "") in FORBIDDEN_TOOLS


def is_enabled_scope(scope: str) -> bool:
    return (scope or "") in ENABLED_SCOPES


def is_future_disabled_scope(scope: str) -> bool:
    return (scope or "") in FUTURE_DISABLED_SCOPES


__all__ = (
    "ENABLED_SCOPES",
    "FUTURE_DISABLED_SCOPES",
    "FORBIDDEN_TOOLS",
    "is_forbidden_tool",
    "is_enabled_scope",
    "is_future_disabled_scope",
)
