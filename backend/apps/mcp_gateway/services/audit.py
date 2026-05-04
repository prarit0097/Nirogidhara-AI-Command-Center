"""Phase 6M-0 — MCP audit helpers.

Writes one ``McpToolInvocationLog`` row per call AND emits a
matching :class:`apps.audit.models.AuditEvent` via the existing
``write_event`` helper so the global ledger captures it. Phase 6M-0
NEVER stores raw input / raw secrets / full PII in either layer.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from ..models import (
    McpClientApp,
    McpToolDefinition,
    McpToolInvocationLog,
)
from .masking import detect_full_pii, detect_raw_secret, mask_payload


AUDIT_KIND_CALL_ATTEMPTED = "mcp.tool.call_attempted"
AUDIT_KIND_CALL_BLOCKED = "mcp.tool.call_blocked"
AUDIT_KIND_CALL_DENIED = "mcp.tool.call_denied"
AUDIT_KIND_CALL_SUCCEEDED = "mcp.tool.call_succeeded"
AUDIT_KIND_CALL_FAILED = "mcp.tool.call_failed"
AUDIT_KIND_FORBIDDEN_TOOL_BLOCKED = "mcp.tool.forbidden_tool_blocked"
AUDIT_KIND_REGISTRY_SEEDED = "mcp.registry.seeded"


_KIND_BY_STATUS = {
    McpToolInvocationLog.Status.ALLOWED: AUDIT_KIND_CALL_ATTEMPTED,
    McpToolInvocationLog.Status.SUCCEEDED: AUDIT_KIND_CALL_SUCCEEDED,
    McpToolInvocationLog.Status.FAILED: AUDIT_KIND_CALL_FAILED,
    McpToolInvocationLog.Status.DENIED: AUDIT_KIND_CALL_DENIED,
    McpToolInvocationLog.Status.BLOCKED: AUDIT_KIND_CALL_BLOCKED,
}


def new_invocation_id() -> str:
    return f"mcp_inv_{uuid4().hex[:24]}"


def _safe_audit_payload(invocation: McpToolInvocationLog) -> dict[str, Any]:
    return {
        "invocation_id": invocation.invocation_id,
        "tool_name": invocation.tool_name,
        "tool_category": invocation.tool_category,
        "handler_key": invocation.handler_key,
        "status": invocation.status,
        "denied_reason": invocation.denied_reason,
        "risk_level": invocation.risk_level,
        "read_only": invocation.read_only,
        "provider_call_allowed": invocation.provider_call_allowed,
        "business_mutation_allowed": invocation.business_mutation_allowed,
        "provider_call_attempted": invocation.provider_call_attempted,
        "business_mutation_attempted": invocation.business_mutation_attempted,
        "raw_secret_exposed": invocation.raw_secret_exposed,
        "full_pii_exposed": invocation.full_pii_exposed,
        "output_truncated": invocation.output_truncated,
        "duration_ms": invocation.duration_ms,
        "error_summary": invocation.error_summary,
        "input_hash": invocation.input_hash,
        # safe summaries already passed through mask_payload before
        # they hit the model row; we still scrub here defensively.
        "safe_input_summary": mask_payload(invocation.safe_input_summary or {}),
        "safe_output_summary": mask_payload(invocation.safe_output_summary or {}),
    }


def write_invocation_audit(
    invocation: McpToolInvocationLog,
    *,
    user=None,
) -> Optional[AuditEvent]:
    """Emit a global AuditEvent corresponding to the invocation row."""
    kind = _KIND_BY_STATUS.get(
        invocation.status, AUDIT_KIND_CALL_ATTEMPTED
    )
    tone = (
        AuditEvent.Tone.WARNING
        if invocation.status
        in {
            McpToolInvocationLog.Status.DENIED,
            McpToolInvocationLog.Status.BLOCKED,
            McpToolInvocationLog.Status.FAILED,
        }
        else AuditEvent.Tone.SUCCESS
        if invocation.status == McpToolInvocationLog.Status.SUCCEEDED
        else AuditEvent.Tone.INFO
    )
    payload = _safe_audit_payload(invocation)
    # Defensive: never let a leaked raw secret / full PII escape into
    # the global audit ledger.
    if detect_raw_secret(payload):
        invocation.raw_secret_exposed = True
        invocation.save(update_fields=["raw_secret_exposed"])
        payload["safe_input_summary"] = {"_scrubbed": True}
        payload["safe_output_summary"] = {"_scrubbed": True}
    if detect_full_pii(payload):
        invocation.full_pii_exposed = True
        invocation.save(update_fields=["full_pii_exposed"])
        payload["safe_input_summary"] = {"_scrubbed": True}
        payload["safe_output_summary"] = {"_scrubbed": True}
    return write_event(
        kind=kind,
        text=(
            f"MCP tool {invocation.tool_name} → {invocation.status} "
            f"(invocation={invocation.invocation_id})"
        ),
        tone=tone,
        payload=payload,
        organization=invocation.organization,
        user=user,
    )


def write_registry_seed_audit(counters: dict[str, Any]) -> AuditEvent:
    """One audit row per ``ensure_mcp_defaults`` apply run."""
    return write_event(
        kind=AUDIT_KIND_REGISTRY_SEEDED,
        text="MCP registry defaults seeded.",
        tone=AuditEvent.Tone.INFO,
        payload=mask_payload(counters),
    )


__all__ = (
    "AUDIT_KIND_CALL_ATTEMPTED",
    "AUDIT_KIND_CALL_BLOCKED",
    "AUDIT_KIND_CALL_DENIED",
    "AUDIT_KIND_CALL_SUCCEEDED",
    "AUDIT_KIND_CALL_FAILED",
    "AUDIT_KIND_FORBIDDEN_TOOL_BLOCKED",
    "AUDIT_KIND_REGISTRY_SEEDED",
    "new_invocation_id",
    "write_invocation_audit",
    "write_registry_seed_audit",
)
