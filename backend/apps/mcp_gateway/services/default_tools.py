"""Phase 6M-0 — default MCP tool registry seed.

Every tool here is read-only. Provider-call / business-mutation
tools are NOT seeded — they live in the
:data:`apps.mcp_gateway.services.schemas.FORBIDDEN_TOOLS` list and
the executor refuses to dispatch them even if a future row tries.
"""
from __future__ import annotations

from typing import Any


_TOOL_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "name": "system.get_phase_status",
        "title": "Get current phase status",
        "description": (
            "Read-only summary of the current Nirogidhara phase + "
            "production posture. No customer data, no secrets."
        ),
        "category": "system",
        "handler_key": "system.get_phase_status",
        "risk_level": "low",
        "required_scopes": ["mcp:system.read", "mcp:tools.invoke.readonly"],
        "tags": ["status", "phase", "readonly"],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_schema": {
            "type": "object",
            "properties": {
                "currentPhase": {"type": "string"},
                "lastCompletedPhase": {"type": "string"},
                "productionUrl": {"type": "string"},
                "razorpayMode": {"type": "string"},
                "whatsappAutoReplyEnabled": {"type": "boolean"},
                "campaignsLocked": {"type": "boolean"},
            },
        },
    },
    {
        "name": "system.get_health",
        "title": "Get system health summary",
        "description": (
            "Read-only system health summary. Reports component "
            "statuses (no version strings, no env values)."
        ),
        "category": "system",
        "handler_key": "system.get_health",
        "risk_level": "low",
        "required_scopes": ["mcp:system.read", "mcp:tools.invoke.readonly"],
        "tags": ["health", "readonly"],
    },
    {
        "name": "saas.get_current_org",
        "title": "Get masked current organization context",
        "description": (
            "Read-only masked org / branch context. Carries the "
            "active organization code + role, never raw settings."
        ),
        "category": "saas",
        "handler_key": "saas.get_current_org",
        "risk_level": "low",
        "required_scopes": ["mcp:saas.read", "mcp:tools.invoke.readonly"],
        "tags": ["saas", "org", "readonly"],
    },
    {
        "name": "audit.search_events_masked",
        "title": "Search recent audit events (masked)",
        "description": (
            "Returns the latest N audit rows, with payload values "
            "masked. Phone numbers / emails / secrets never echoed."
        ),
        "category": "audit",
        "handler_key": "audit.search_events_masked",
        "risk_level": "medium",
        "pii_exposure_level": "masked",
        "required_scopes": ["mcp:audit.read", "mcp:tools.invoke.readonly"],
        "tags": ["audit", "search", "masked"],
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 25,
                },
                "kind_prefix": {"type": "string"},
            },
        },
    },
    {
        "name": "whatsapp.inspect_auto_reply_gate",
        "title": "Inspect WhatsApp auto-reply gate (read-only)",
        "description": (
            "Returns auto-reply gate status. Calls the existing "
            "WhatsApp dashboard selector — no message is sent, no "
            "WABA call is made."
        ),
        "category": "whatsapp",
        "handler_key": "whatsapp.inspect_auto_reply_gate",
        "risk_level": "medium",
        "pii_exposure_level": "masked",
        "required_scopes": ["mcp:whatsapp.read", "mcp:tools.invoke.readonly"],
        "tags": ["whatsapp", "safety", "readonly"],
    },
    {
        "name": "razorpay.inspect_test_execution_audit",
        "title": "Inspect Razorpay Phase 6K execution audit",
        "description": (
            "Read-only Phase 6K audit review. Returns the same "
            "report as the Phase 6L management command. No Razorpay "
            "API call. No raw provider response."
        ),
        "category": "razorpay",
        "handler_key": "razorpay.inspect_test_execution_audit",
        "risk_level": "medium",
        "required_scopes": ["mcp:razorpay.read", "mcp:tools.invoke.readonly"],
        "tags": ["razorpay", "audit", "readonly"],
        "input_schema": {
            "type": "object",
            "properties": {"execution_id": {"type": "string"}},
            "required": ["execution_id"],
        },
    },
    {
        "name": "razorpay.inspect_webhook_readiness",
        "title": "Inspect Razorpay webhook readiness",
        "description": (
            "Read-only Phase 6L env + Phase 6K artefact sanity check. "
            "Reports presence only; never returns the raw webhook "
            "secret."
        ),
        "category": "razorpay",
        "handler_key": "razorpay.inspect_webhook_readiness",
        "risk_level": "low",
        "required_scopes": ["mcp:razorpay.read", "mcp:tools.invoke.readonly"],
        "tags": ["razorpay", "webhook", "readonly"],
    },
    {
        "name": "razorpay.plan_webhook_readiness",
        "title": "Get Razorpay webhook readiness plan",
        "description": (
            "Returns the canonical Phase 6L Razorpay webhook plan. "
            "Pure policy — never registers a webhook receiver."
        ),
        "category": "razorpay",
        "handler_key": "razorpay.plan_webhook_readiness",
        "risk_level": "low",
        "required_scopes": ["mcp:razorpay.read", "mcp:tools.invoke.readonly"],
        "tags": ["razorpay", "webhook", "plan"],
    },
    {
        "name": "dashboard.get_kpis",
        "title": "Get safe high-level KPIs (aggregated)",
        "description": (
            "Returns aggregated dashboard KPIs only. No row-level "
            "customer data, no PII."
        ),
        "category": "dashboard",
        "handler_key": "dashboard.get_kpis",
        "risk_level": "low",
        "required_scopes": [
            "mcp:dashboard.read",
            "mcp:tools.invoke.readonly",
        ],
        "tags": ["dashboard", "kpis", "readonly"],
    },
    {
        "name": "agents.get_agent_status",
        "title": "Get agent status summary",
        "description": (
            "Returns AI agent status summary (CEO / CAIO / Ads / RTO "
            "etc) — no raw prompts, no raw outputs."
        ),
        "category": "agents",
        "handler_key": "agents.get_agent_status",
        "risk_level": "low",
        "required_scopes": ["mcp:agents.read", "mcp:tools.invoke.readonly"],
        "tags": ["agents", "readonly"],
    },
)


def list_default_tool_seeds() -> tuple[dict[str, Any], ...]:
    return _TOOL_SEEDS


__all__ = ("list_default_tool_seeds",)
