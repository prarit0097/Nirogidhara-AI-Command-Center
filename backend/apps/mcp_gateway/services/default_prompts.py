"""Phase 6M-0 — default MCP prompt registry seed.

Prompts are TEMPLATES only. They never embed live customer data, raw
secrets, or executed outputs.
"""
from __future__ import annotations

from typing import Any


_PROMPT_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "name": "ceo_daily_briefing",
        "title": "CEO daily briefing prompt",
        "description": (
            "Asks the connected AI to produce a CEO-grade daily "
            "briefing from masked KPIs + masked audit summary."
        ),
        "template": (
            "You are the Nirogidhara CEO AI briefing assistant.\n"
            "Inputs:\n"
            "- aggregated_kpis: {{kpis}}\n"
            "- masked_audit_summary: {{audit_summary}}\n"
            "Produce a 5-bullet briefing covering: revenue posture, "
            "compliance posture, ops risk, customer-success posture, "
            "and one recommended next action. Never echo raw "
            "customer data."
        ),
        "variables_schema": {
            "type": "object",
            "properties": {
                "kpis": {"type": "object"},
                "audit_summary": {"type": "object"},
            },
            "required": ["kpis", "audit_summary"],
        },
        "risk_level": "low",
        "required_scopes": ["mcp:dashboard.read", "mcp:audit.read"],
    },
    {
        "name": "caio_payment_audit_review",
        "title": "CAIO payment audit review prompt",
        "description": (
            "Asks the connected AI to review the Phase 6K Razorpay "
            "test execution audit + Phase 6L webhook readiness plan "
            "and report safety findings."
        ),
        "template": (
            "You are the Nirogidhara CAIO compliance reviewer.\n"
            "Inputs:\n"
            "- phase_6k_audit: {{phase_6k_audit}}\n"
            "- phase_6l_webhook_readiness: {{webhook_readiness}}\n"
            "- phase_6l_webhook_plan: {{webhook_plan}}\n"
            "Confirm every safety invariant + flag any anomaly. "
            "Never propose enabling write tools. Never propose "
            "calling Razorpay."
        ),
        "variables_schema": {
            "type": "object",
            "properties": {
                "phase_6k_audit": {"type": "object"},
                "webhook_readiness": {"type": "object"},
                "webhook_plan": {"type": "object"},
            },
            "required": [
                "phase_6k_audit",
                "webhook_readiness",
                "webhook_plan",
            ],
        },
        "risk_level": "medium",
        "required_scopes": ["mcp:razorpay.read", "mcp:audit.read"],
    },
    {
        "name": "razorpay_webhook_readiness_review",
        "title": "Razorpay webhook readiness review prompt",
        "description": (
            "Asks the connected AI to summarise the Razorpay "
            "webhook readiness plan + flag missing env."
        ),
        "template": (
            "Inputs: webhook_readiness={{webhook_readiness}}; "
            "webhook_plan={{webhook_plan}}. Summarise readiness "
            "in 4 bullets: secret presence, key mode, latest "
            "Phase 6K artefact, blockers."
        ),
        "variables_schema": {
            "type": "object",
            "properties": {
                "webhook_readiness": {"type": "object"},
                "webhook_plan": {"type": "object"},
            },
            "required": ["webhook_readiness", "webhook_plan"],
        },
        "risk_level": "low",
        "required_scopes": ["mcp:razorpay.read"],
    },
    {
        "name": "whatsapp_safety_review",
        "title": "WhatsApp safety review prompt",
        "description": (
            "Asks the connected AI to review the WhatsApp auto-reply "
            "gate status + summarise blockers."
        ),
        "template": (
            "Inputs: gate={{gate}}. Confirm auto-reply is OFF, "
            "campaigns locked, broad automation flags off; flag any "
            "anomaly."
        ),
        "variables_schema": {
            "type": "object",
            "properties": {"gate": {"type": "object"}},
            "required": ["gate"],
        },
        "risk_level": "medium",
        "required_scopes": ["mcp:whatsapp.read"],
    },
    {
        "name": "phase_deploy_checklist",
        "title": "Phase deploy checklist prompt",
        "description": (
            "Asks the connected AI to produce a deploy checklist for "
            "the current phase from the runbook summary."
        ),
        "template": (
            "Inputs: runbook={{runbook}}. Produce a 7-item deploy "
            "checklist covering migrate / makemigrations check / "
            "tests / lint / build / health-check / rollback plan."
        ),
        "variables_schema": {
            "type": "object",
            "properties": {"runbook": {"type": "object"}},
            "required": ["runbook"],
        },
        "risk_level": "low",
        "required_scopes": ["mcp:system.read"],
    },
    {
        "name": "crm_sales_summary_masked",
        "title": "CRM sales summary (masked) prompt",
        "description": (
            "Asks the connected AI to produce a sales summary from "
            "aggregated KPIs only. No raw customer rows."
        ),
        "template": (
            "Inputs: kpis={{kpis}}. Produce a 5-line sales summary; "
            "no row-level customer data; no phone numbers."
        ),
        "variables_schema": {
            "type": "object",
            "properties": {"kpis": {"type": "object"}},
            "required": ["kpis"],
        },
        "risk_level": "medium",
        "required_scopes": ["mcp:dashboard.read"],
    },
)


def list_default_prompt_seeds() -> tuple[dict[str, Any], ...]:
    return _PROMPT_SEEDS


__all__ = ("list_default_prompt_seeds",)
