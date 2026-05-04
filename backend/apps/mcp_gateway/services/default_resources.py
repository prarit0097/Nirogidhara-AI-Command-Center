"""Phase 6M-0 — default MCP resource registry seed.

Resources are read-only references the future MCP client can ask
the gateway to render. No raw secrets / no raw env / no raw files.
"""
from __future__ import annotations

from typing import Any


_RESOURCE_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "uri": "nirogidhara://phase/current-status",
        "name": "current_phase_status",
        "title": "Current phase status",
        "description": (
            "Read-only summary of the active phase + production "
            "posture. Does not expose env values."
        ),
        "handler_key": "system.get_phase_status",
        "required_scopes": ["mcp:system.read"],
    },
    {
        "uri": "nirogidhara://razorpay/phase-6k-audit",
        "name": "razorpay_phase_6k_audit",
        "title": "Razorpay Phase 6K audit summary",
        "description": (
            "Latest Phase 6K execution audit summary, masked. "
            "Calls the Phase 6L razorpay_audit_review service."
        ),
        "handler_key": "razorpay.inspect_test_execution_audit",
        "required_scopes": ["mcp:razorpay.read"],
    },
    {
        "uri": "nirogidhara://razorpay/webhook-readiness",
        "name": "razorpay_webhook_readiness",
        "title": "Razorpay webhook readiness",
        "description": (
            "Phase 6L env-presence + Phase 6K artefact sanity check."
        ),
        "handler_key": "razorpay.inspect_webhook_readiness",
        "required_scopes": ["mcp:razorpay.read"],
    },
    {
        "uri": "nirogidhara://whatsapp/safety-status",
        "name": "whatsapp_safety_status",
        "title": "WhatsApp auto-reply gate safety status",
        "description": (
            "Read-only summary of the WhatsApp auto-reply gate. "
            "Phones masked to last-4."
        ),
        "handler_key": "whatsapp.inspect_auto_reply_gate",
        "pii_exposure_level": "masked",
        "required_scopes": ["mcp:whatsapp.read"],
    },
    {
        "uri": "nirogidhara://system/health",
        "name": "system_health",
        "title": "System health summary",
        "description": (
            "Read-only system health summary. No version strings, "
            "no env values."
        ),
        "handler_key": "system.get_health",
        "required_scopes": ["mcp:system.read"],
    },
    {
        "uri": "nirogidhara://docs/runbook-summary",
        "name": "runbook_summary",
        "title": "Runbook summary",
        "description": (
            "Static runbook summary: deploy commands, smoke checks, "
            "no secrets, no live URLs with tokens."
        ),
        "handler_key": "docs.runbook_summary",
        "required_scopes": ["mcp:system.read"],
    },
    {
        "uri": "nirogidhara://audit/recent-masked",
        "name": "audit_recent_masked",
        "title": "Recent audit events (masked)",
        "description": (
            "Latest 25 audit rows with masked payload values."
        ),
        "handler_key": "audit.search_events_masked",
        "pii_exposure_level": "masked",
        "required_scopes": ["mcp:audit.read"],
    },
)


def list_default_resource_seeds() -> tuple[dict[str, Any], ...]:
    return _RESOURCE_SEEDS


__all__ = ("list_default_resource_seeds",)
