"""Phase 6M-0 — MCP tool executor.

Single entry point: :func:`execute_mcp_tool`. Performs every safety
check before dispatching to a registered handler:

1. Forbidden-tool refusal (hard list).
2. Tool-definition lookup + ``enabled`` check.
3. ``MCP_PROVIDER_TOOLS_ENABLED`` / ``MCP_WRITE_TOOLS_ENABLED`` flags.
4. Scope check (Phase 6M-0 read-only enabled scopes only).
5. Auth check (caller must be authenticated when ``requires_auth``).
6. Input masking + hash.
7. Handler dispatch.
8. Output masking + truncation.
9. Audit log + matching ``AuditEvent``.

Handlers MUST NOT call external providers, MUST NOT mutate business
records, MUST NOT return raw secrets / raw provider responses.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from django.conf import settings

from ..models import (
    McpClientApp,
    McpToolDefinition,
    McpToolInvocationLog,
)
from .audit import (
    new_invocation_id,
    write_invocation_audit,
)
from .auth import (
    grants_for_internal_admin,
    required_scopes_satisfied,
)
from .masking import (
    detect_full_pii,
    detect_raw_secret,
    hash_input,
    mask_payload,
    truncate_output,
)
from .schemas import is_forbidden_tool


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------


_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register_handler(handler_key: str):
    """Decorator used by :mod:`apps.mcp_gateway.services.tool_handlers`."""

    def _wrap(func: Callable[[dict[str, Any]], dict[str, Any]]):
        _HANDLERS[handler_key] = func
        return func

    return _wrap


def get_handler(
    handler_key: str,
) -> Optional[Callable[[dict[str, Any]], dict[str, Any]]]:
    return _HANDLERS.get(handler_key)


def list_registered_handlers() -> tuple[str, ...]:
    return tuple(sorted(_HANDLERS.keys()))


# ---------------------------------------------------------------------------
# Result dataclass-shaped dict
# ---------------------------------------------------------------------------


def _denied_result(
    *,
    tool_name: str,
    blocked_reason: str,
    invocation_id: str,
    next_action: str = "fix_mcp_call_blockers",
) -> dict[str, Any]:
    return {
        "passed": False,
        "status": "blocked",
        "toolName": tool_name,
        "invocationId": invocation_id,
        "blockedReason": blocked_reason,
        "providerCallAttempted": False,
        "businessMutationAttempted": False,
        "rawSecretExposed": False,
        "fullPiiExposed": False,
        "result": None,
        "blockers": [blocked_reason],
        "warnings": [
            "Phase 6M-0 default state: read-only, no provider tools, "
            "no write tools, no public endpoint."
        ],
        "nextAction": next_action,
    }


def _record_blocked(
    *,
    invocation_id: str,
    tool: Optional[McpToolDefinition],
    tool_name: str,
    blocked_reason: str,
    organization=None,
    branch=None,
    actor=None,
    client_app: Optional[McpClientApp] = None,
    safe_input_summary: dict[str, Any] | None = None,
    input_hash: str = "",
) -> McpToolInvocationLog:
    invocation = McpToolInvocationLog.objects.create(
        invocation_id=invocation_id,
        client_app=client_app,
        organization=organization,
        branch=branch,
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        tool_name=tool_name,
        tool_category=(tool.category if tool else ""),
        handler_key=(tool.handler_key if tool else ""),
        status=McpToolInvocationLog.Status.BLOCKED,
        denied_reason=blocked_reason[:200],
        risk_level=(tool.risk_level if tool else "low"),
        read_only=True,
        provider_call_allowed=False,
        business_mutation_allowed=False,
        input_hash=input_hash,
        safe_input_summary=safe_input_summary or {},
        safe_output_summary={},
        provider_call_attempted=False,
        business_mutation_attempted=False,
        request_metadata={"phase": "6M-0"},
    )
    write_invocation_audit(invocation, user=actor)
    return invocation


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------


def execute_mcp_tool(
    tool_name: str,
    input_data: Optional[dict[str, Any]] = None,
    *,
    client_app: Optional[McpClientApp] = None,
    actor=None,
    organization=None,
    branch=None,
    granted_scopes: Optional[list[str]] = None,
    bypass_auth_for_internal: bool = False,
) -> dict[str, Any]:
    """Run one MCP tool through every Phase 6M-0 safety check.

    ``bypass_auth_for_internal=True`` is used by the simulator
    command — it skips the ``MCP_REQUIRE_AUTH`` env gate but does not
    relax any other safety check. The simulator + DRF endpoint are
    permission-protected upstream.
    """
    invocation_id = new_invocation_id()
    raw_input = input_data or {}
    safe_input = mask_payload(raw_input)
    input_hash_value = hash_input(raw_input)

    # ----- 1. Hard forbidden-tool list -----
    if is_forbidden_tool(tool_name):
        _record_blocked(
            invocation_id=invocation_id,
            tool=None,
            tool_name=tool_name,
            blocked_reason="forbidden_tool_phase_6m_0",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="forbidden_tool_phase_6m_0",
            invocation_id=invocation_id,
            next_action="never_register_forbidden_tools",
        )

    # ----- 2. Tool definition + enabled check -----
    tool = McpToolDefinition.objects.filter(name=tool_name).first()
    if tool is None:
        _record_blocked(
            invocation_id=invocation_id,
            tool=None,
            tool_name=tool_name,
            blocked_reason="tool_not_registered",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="tool_not_registered",
            invocation_id=invocation_id,
            next_action="run_ensure_mcp_defaults",
        )
    if not tool.enabled:
        _record_blocked(
            invocation_id=invocation_id,
            tool=tool,
            tool_name=tool_name,
            blocked_reason="tool_disabled",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="tool_disabled",
            invocation_id=invocation_id,
        )

    # ----- 3. Provider-tool / write-tool global flags -----
    provider_tools_enabled = bool(
        getattr(settings, "MCP_PROVIDER_TOOLS_ENABLED", False)
    )
    write_tools_enabled = bool(
        getattr(settings, "MCP_WRITE_TOOLS_ENABLED", False)
    )
    if tool.provider_call_allowed and not provider_tools_enabled:
        _record_blocked(
            invocation_id=invocation_id,
            tool=tool,
            tool_name=tool_name,
            blocked_reason="provider_tools_disabled_in_phase_6m_0",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="provider_tools_disabled_in_phase_6m_0",
            invocation_id=invocation_id,
        )
    if tool.business_mutation_allowed and not write_tools_enabled:
        _record_blocked(
            invocation_id=invocation_id,
            tool=tool,
            tool_name=tool_name,
            blocked_reason="write_tools_disabled_in_phase_6m_0",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="write_tools_disabled_in_phase_6m_0",
            invocation_id=invocation_id,
        )

    # ----- 4. Scope check -----
    grants = (
        list(granted_scopes)
        if granted_scopes is not None
        else list(grants_for_internal_admin())
    )
    if not required_scopes_satisfied(tool.required_scopes or [], grants):
        _record_blocked(
            invocation_id=invocation_id,
            tool=tool,
            tool_name=tool_name,
            blocked_reason="missing_required_scope",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="missing_required_scope",
            invocation_id=invocation_id,
        )

    # ----- 5. Auth check -----
    require_auth_global = bool(getattr(settings, "MCP_REQUIRE_AUTH", True))
    if (
        tool.requires_auth
        and require_auth_global
        and not bypass_auth_for_internal
    ):
        if not (actor and getattr(actor, "is_authenticated", False)):
            _record_blocked(
                invocation_id=invocation_id,
                tool=tool,
                tool_name=tool_name,
                blocked_reason="auth_required",
                organization=organization,
                branch=branch,
                actor=None,
                client_app=client_app,
                safe_input_summary=safe_input,
                input_hash=input_hash_value,
            )
            return _denied_result(
                tool_name=tool_name,
                blocked_reason="auth_required",
                invocation_id=invocation_id,
            )

    # ----- 6. Handler dispatch -----
    handler = get_handler(tool.handler_key)
    if handler is None:
        _record_blocked(
            invocation_id=invocation_id,
            tool=tool,
            tool_name=tool_name,
            blocked_reason="handler_not_implemented",
            organization=organization,
            branch=branch,
            actor=actor,
            client_app=client_app,
            safe_input_summary=safe_input,
            input_hash=input_hash_value,
        )
        return _denied_result(
            tool_name=tool_name,
            blocked_reason="handler_not_implemented",
            invocation_id=invocation_id,
        )

    started = time.monotonic()
    try:
        raw_result = handler(raw_input) or {}
    except Exception as exc:  # noqa: BLE001
        invocation = McpToolInvocationLog.objects.create(
            invocation_id=invocation_id,
            client_app=client_app,
            organization=organization,
            branch=branch,
            actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
            tool_name=tool_name,
            tool_category=tool.category,
            handler_key=tool.handler_key,
            status=McpToolInvocationLog.Status.FAILED,
            denied_reason="",
            risk_level=tool.risk_level,
            read_only=True,
            provider_call_allowed=False,
            business_mutation_allowed=False,
            input_hash=input_hash_value,
            safe_input_summary=safe_input,
            safe_output_summary={"errorClass": exc.__class__.__name__},
            provider_call_attempted=False,
            business_mutation_attempted=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_summary=exc.__class__.__name__,
            request_metadata={"phase": "6M-0"},
        )
        write_invocation_audit(invocation, user=actor)
        return {
            "passed": False,
            "status": "failed",
            "toolName": tool_name,
            "invocationId": invocation_id,
            "providerCallAttempted": False,
            "businessMutationAttempted": False,
            "rawSecretExposed": False,
            "fullPiiExposed": False,
            "result": None,
            "blockers": [exc.__class__.__name__],
            "warnings": ["handler raised; output suppressed for safety."],
            "nextAction": "review_handler_error",
        }

    # ----- 7. Output masking + truncation -----
    masked_output = mask_payload(raw_result)
    raw_secret_exposed = detect_raw_secret(masked_output)
    full_pii_exposed = detect_full_pii(masked_output)
    if raw_secret_exposed or full_pii_exposed:
        masked_output = {"_scrubbed": True}
    safe_output, truncated = truncate_output(masked_output)

    duration_ms = int((time.monotonic() - started) * 1000)

    invocation = McpToolInvocationLog.objects.create(
        invocation_id=invocation_id,
        client_app=client_app,
        organization=organization,
        branch=branch,
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        tool_name=tool_name,
        tool_category=tool.category,
        handler_key=tool.handler_key,
        status=McpToolInvocationLog.Status.SUCCEEDED,
        denied_reason="",
        risk_level=tool.risk_level,
        read_only=True,
        provider_call_allowed=False,
        business_mutation_allowed=False,
        input_hash=input_hash_value,
        safe_input_summary=safe_input,
        safe_output_summary=safe_output,
        output_truncated=truncated,
        raw_secret_exposed=raw_secret_exposed,
        full_pii_exposed=full_pii_exposed,
        provider_call_attempted=False,
        business_mutation_attempted=False,
        duration_ms=duration_ms,
        request_metadata={"phase": "6M-0"},
    )
    write_invocation_audit(invocation, user=actor)

    return {
        "passed": True,
        "status": "succeeded",
        "toolName": tool_name,
        "invocationId": invocation_id,
        "readOnly": True,
        "providerCallAttempted": False,
        "businessMutationAttempted": False,
        "rawSecretExposed": raw_secret_exposed,
        "fullPiiExposed": full_pii_exposed,
        "outputTruncated": truncated,
        "durationMs": duration_ms,
        "result": safe_output,
        "blockers": [],
        "warnings": ["Phase 6M-0 read-only foundation."],
        "nextAction": "ready_for_phase_6m_1_external_client_auth",
    }


__all__ = (
    "register_handler",
    "get_handler",
    "list_registered_handlers",
    "execute_mcp_tool",
)
