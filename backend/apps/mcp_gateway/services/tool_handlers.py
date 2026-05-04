"""Phase 6M-0 — read-only MCP tool handlers.

Every handler returns a JSON-shaped dict. None of them call external
providers; none of them mutate business records. Imports of existing
selectors are wrapped in try/except so a missing optional dependency
returns a typed "service_unavailable" payload instead of crashing
the gateway.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

from .masking import mask_payload
from .tool_executor import register_handler


# ---------------------------------------------------------------------------
# system.* handlers
# ---------------------------------------------------------------------------


@register_handler("system.get_phase_status")
def _system_get_phase_status(_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "currentPhase": "Phase 6M-0 — MCP Gateway Foundation",
        "lastCompletedPhase": (
            "Phase 6L — Razorpay Audit Review + Webhook Readiness Plan"
        ),
        "productionUrl": "https://ai.nirogidhara.com",
        "razorpayMode": getattr(settings, "RAZORPAY_MODE", "mock"),
        "whatsappAutoReplyEnabled": (
            (
                __import__("os").environ.get(
                    "WHATSAPP_AI_AUTO_REPLY_ENABLED",
                    "false",
                )
                or "false"
            )
            .strip()
            .lower()
            == "true"
        ),
        "campaignsLocked": True,
        "mcpEnabled": bool(getattr(settings, "MCP_ENABLED", False)),
        "readOnlyMode": bool(getattr(settings, "MCP_READ_ONLY_MODE", True)),
        "writeToolsEnabled": bool(
            getattr(settings, "MCP_WRITE_TOOLS_ENABLED", False)
        ),
        "providerToolsEnabled": bool(
            getattr(settings, "MCP_PROVIDER_TOOLS_ENABLED", False)
        ),
        "nextRecommendedPhase": (
            "Phase 6M — Razorpay Webhook Handler Implementation (test-mode)"
        ),
    }


@register_handler("system.get_health")
def _system_get_health(_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "components": {
            "django": "ok",
            "database": "ok",
            "auditLedger": "ok",
            "mcpRegistry": "seeded" if _registry_seeded() else "empty",
        },
        "phaseStatus": "phase_6m_0_foundation_only",
        "providerCallAttempted": False,
        "businessMutationAttempted": False,
    }


def _registry_seeded() -> bool:
    from ..models import McpToolDefinition

    return McpToolDefinition.objects.exists()


# ---------------------------------------------------------------------------
# saas.* handlers
# ---------------------------------------------------------------------------


@register_handler("saas.get_current_org")
def _saas_get_current_org(_input: dict[str, Any]) -> dict[str, Any]:
    try:
        from apps.saas.context import get_default_organization
    except Exception:  # noqa: BLE001
        return {"organization": None, "available": False}
    org = get_default_organization()
    if org is None:
        return {"organization": None, "available": False}
    return {
        "organization": {
            "id": org.id,
            "code": org.code,
            "name": org.name,
            "status": getattr(org, "status", "active"),
        },
        "available": True,
    }


# ---------------------------------------------------------------------------
# audit.* handlers
# ---------------------------------------------------------------------------


@register_handler("audit.search_events_masked")
def _audit_search_events_masked(input_data: dict[str, Any]) -> dict[str, Any]:
    from apps.audit.models import AuditEvent

    raw_limit = input_data.get("limit") if isinstance(input_data, dict) else None
    try:
        limit = int(raw_limit) if raw_limit is not None else 25
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))
    kind_prefix = ""
    if isinstance(input_data, dict):
        prefix_raw = input_data.get("kind_prefix")
        if isinstance(prefix_raw, str):
            kind_prefix = prefix_raw.strip()

    qs = AuditEvent.objects.all().order_by("-occurred_at")
    if kind_prefix:
        qs = qs.filter(kind__startswith=kind_prefix)
    rows = list(qs[:limit])

    events = []
    for event in rows:
        events.append(
            {
                "id": event.id,
                "kind": event.kind,
                "tone": event.tone,
                "occurredAt": event.occurred_at.isoformat(),
                "text": mask_payload(event.text or ""),
                "payloadKeys": sorted(list((event.payload or {}).keys())),
            }
        )
    return {
        "limit": limit,
        "kindPrefix": kind_prefix,
        "count": len(events),
        "events": events,
    }


# ---------------------------------------------------------------------------
# whatsapp.* handlers
# ---------------------------------------------------------------------------


@register_handler("whatsapp.inspect_auto_reply_gate")
def _whatsapp_inspect_auto_reply_gate(_input: dict[str, Any]) -> dict[str, Any]:
    try:
        from apps.whatsapp.dashboard import get_auto_reply_gate_summary
    except Exception:  # noqa: BLE001
        return {
            "available": False,
            "reason": "whatsapp.dashboard service not available.",
            "providerCallAttempted": False,
        }
    try:
        summary = get_auto_reply_gate_summary()
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "reason": f"whatsapp.dashboard error: {exc.__class__.__name__}",
        }
    return {"available": True, "gate": mask_payload(summary)}


# ---------------------------------------------------------------------------
# razorpay.* handlers
# ---------------------------------------------------------------------------


@register_handler("razorpay.inspect_test_execution_audit")
def _razorpay_inspect_audit(input_data: dict[str, Any]) -> dict[str, Any]:
    try:
        from apps.saas.razorpay_audit_review import (
            review_razorpay_test_execution_audit,
        )
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "razorpay audit review unavailable."}
    execution_id = ""
    if isinstance(input_data, dict):
        raw = input_data.get("execution_id") or input_data.get("executionId")
        if isinstance(raw, str):
            execution_id = raw.strip()
    if not execution_id:
        return {
            "available": False,
            "reason": "execution_id required",
            "blockers": ["execution_id_required"],
        }
    review = review_razorpay_test_execution_audit(execution_id)
    return {"available": True, "review": mask_payload(review)}


@register_handler("razorpay.inspect_webhook_readiness")
def _razorpay_inspect_webhook_readiness(_input: dict[str, Any]) -> dict[str, Any]:
    try:
        from apps.saas.razorpay_audit_review import (
            inspect_razorpay_webhook_readiness,
        )
    except Exception:  # noqa: BLE001
        return {"available": False}
    return {"available": True, "readiness": mask_payload(inspect_razorpay_webhook_readiness())}


@register_handler("razorpay.plan_webhook_readiness")
def _razorpay_plan_webhook_readiness(_input: dict[str, Any]) -> dict[str, Any]:
    try:
        from apps.saas.razorpay_audit_review import (
            plan_razorpay_webhook_readiness,
        )
    except Exception:  # noqa: BLE001
        return {"available": False}
    return {"available": True, "plan": mask_payload(plan_razorpay_webhook_readiness())}


# ---------------------------------------------------------------------------
# dashboard.* handlers
# ---------------------------------------------------------------------------


@register_handler("dashboard.get_kpis")
def _dashboard_get_kpis(_input: dict[str, Any]) -> dict[str, Any]:
    """Aggregated, no row-level customer data."""
    try:
        from apps.orders.models import Order
        from apps.payments.models import Payment
    except Exception:  # noqa: BLE001
        return {"available": False}
    return {
        "available": True,
        "totals": {
            "orders": Order.objects.count() if Order is not None else 0,
            "payments": Payment.objects.count() if Payment is not None else 0,
        },
        "providerCallAttempted": False,
        "businessMutationAttempted": False,
    }


# ---------------------------------------------------------------------------
# agents.* handlers
# ---------------------------------------------------------------------------


@register_handler("agents.get_agent_status")
def _agents_get_agent_status(_input: dict[str, Any]) -> dict[str, Any]:
    try:
        from apps.agents.models import Agent
    except Exception:  # noqa: BLE001
        return {"available": False}
    rows = []
    for agent in Agent.objects.all().order_by("name"):
        rows.append(
            {
                "id": agent.id,
                "name": getattr(agent, "name", ""),
                "role": getattr(agent, "role", ""),
                "status": getattr(agent, "status", ""),
            }
        )
    return {"available": True, "agents": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# docs / resource handlers (used by resource fetchers)
# ---------------------------------------------------------------------------


@register_handler("docs.runbook_summary")
def _docs_runbook_summary(_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "6M-0",
        "deployCommands": [
            "git pull origin main",
            "docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --pull never",
            "docker compose -f docker-compose.prod.yml exec backend python manage.py migrate",
            "docker compose -f docker-compose.prod.yml exec backend python manage.py ensure_mcp_defaults --json",
        ],
        "smokeChecks": [
            "GET https://ai.nirogidhara.com/api/healthz/",
            "manage.py inspect_mcp_gateway_readiness --json",
            "manage.py inspect_mcp_security_posture --json",
        ],
        "rollbackPlan": [
            "MCP_ENABLED defaults false; no public traffic served.",
            "Default tools are read-only; no provider call possible.",
            "Disable MCP entirely by leaving MCP_ENABLED=false.",
        ],
    }


__all__ = ()
