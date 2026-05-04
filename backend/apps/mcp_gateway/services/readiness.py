"""Phase 6M-0 — MCP gateway readiness + security-posture selectors.

Pure read-only selectors. NEVER call providers. NEVER return raw
secrets. NEVER mutate data.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

from ..models import (
    McpClientApp,
    McpPromptDefinition,
    McpResourceDefinition,
    McpToolDefinition,
    McpToolInvocationLog,
)
from .schemas import (
    ENABLED_SCOPES,
    FORBIDDEN_TOOLS,
    FUTURE_DISABLED_SCOPES,
)


def _settings_bool(key: str, default: bool) -> bool:
    return bool(getattr(settings, key, default))


def get_mcp_gateway_readiness() -> dict[str, Any]:
    enabled_tools = McpToolDefinition.objects.filter(enabled=True)
    write_tool_count = enabled_tools.filter(business_mutation_allowed=True).count()
    provider_tool_count = enabled_tools.filter(provider_call_allowed=True).count()
    forbidden_registered = (
        McpToolDefinition.objects.filter(name__in=FORBIDDEN_TOOLS).count()
    )

    invocations = McpToolInvocationLog.objects.all()
    raw_secret_exposures = invocations.filter(raw_secret_exposed=True).count()
    full_pii_exposures = invocations.filter(full_pii_exposed=True).count()
    provider_call_attempted = invocations.filter(
        provider_call_attempted=True
    ).count()
    business_mutation_attempted = invocations.filter(
        business_mutation_attempted=True
    ).count()

    mcp_enabled = _settings_bool("MCP_ENABLED", False)
    read_only_mode = _settings_bool("MCP_READ_ONLY_MODE", True)
    write_tools_enabled = _settings_bool("MCP_WRITE_TOOLS_ENABLED", False)
    provider_tools_enabled = _settings_bool("MCP_PROVIDER_TOOLS_ENABLED", False)
    audit_enabled = _settings_bool("MCP_AUDIT_ENABLED", True)
    mask_pii = _settings_bool("MCP_MASK_PII", True)
    require_auth = _settings_bool("MCP_REQUIRE_AUTH", True)

    blockers: list[str] = []
    warnings: list[str] = []

    if write_tool_count and not write_tools_enabled:
        warnings.append(
            "Phase 6M-0: write tools registered but MCP_WRITE_TOOLS_ENABLED=false; "
            "executor will refuse them."
        )
    if provider_tool_count and not provider_tools_enabled:
        warnings.append(
            "Phase 6M-0: provider tools registered but "
            "MCP_PROVIDER_TOOLS_ENABLED=false; executor will refuse them."
        )
    if forbidden_registered:
        blockers.append("forbidden_tools_present_in_registry")
    if not require_auth:
        blockers.append("mcp_require_auth_must_remain_true")
    if not mask_pii:
        warnings.append("MCP_MASK_PII=false; defaulting to scrub anyway.")
    if not audit_enabled:
        warnings.append("MCP_AUDIT_ENABLED=false; audit emission still on by default.")
    if mcp_enabled and not getattr(settings, "MCP_PUBLIC_BASE_URL", ""):
        warnings.append(
            "MCP_ENABLED=true but MCP_PUBLIC_BASE_URL not set; external client "
            "discovery cannot work."
        )

    safe_to_enable_read_only_mcp = (
        not blockers
        and require_auth
        and not write_tools_enabled
        and not provider_tools_enabled
        and read_only_mode
    )
    safe_to_start_phase_6m = (
        safe_to_enable_read_only_mcp
        and forbidden_registered == 0
        and provider_call_attempted == 0
        and business_mutation_attempted == 0
    )

    if blockers:
        next_action = "fix_mcp_gateway_blockers"
    elif not McpToolDefinition.objects.exists():
        next_action = "run_ensure_mcp_defaults"
    elif mcp_enabled:
        next_action = "monitor_mcp_external_traffic"
    else:
        next_action = "ready_to_enable_read_only_mcp_when_authorized"

    return {
        "mcpEnabled": mcp_enabled,
        "transport": getattr(settings, "MCP_TRANSPORT", "streamable_http"),
        "publicBaseUrlConfigured": bool(
            getattr(settings, "MCP_PUBLIC_BASE_URL", "")
        ),
        "requireAuth": require_auth,
        "readOnlyMode": read_only_mode,
        "writeToolsEnabled": write_tools_enabled,
        "providerToolsEnabled": provider_tools_enabled,
        "auditEnabled": audit_enabled,
        "maskPii": mask_pii,
        "tokenTtlSeconds": getattr(settings, "MCP_TOKEN_TTL_SECONDS", 3600),
        "maxToolCallsPerMinute": getattr(
            settings, "MCP_MAX_TOOL_CALLS_PER_MINUTE", 30
        ),
        "maxOutputChars": getattr(settings, "MCP_MAX_OUTPUT_CHARS", 12000),
        "exposeResources": _settings_bool("MCP_EXPOSE_RESOURCES", False),
        "exposePrompts": _settings_bool("MCP_EXPOSE_PROMPTS", False),
        "toolCount": McpToolDefinition.objects.count(),
        "enabledToolCount": enabled_tools.count(),
        "writeToolEnabledCount": write_tool_count,
        "providerToolEnabledCount": provider_tool_count,
        "forbiddenToolsRegisteredCount": forbidden_registered,
        "resourceCount": McpResourceDefinition.objects.count(),
        "promptCount": McpPromptDefinition.objects.count(),
        "activeClientCount": McpClientApp.objects.filter(is_active=True).count(),
        "registeredClientCount": McpClientApp.objects.count(),
        "recentInvocationCount": invocations.count(),
        "rawSecretExposureCount": raw_secret_exposures,
        "fullPiiExposureCount": full_pii_exposures,
        "providerCallAttemptedCount": provider_call_attempted,
        "businessMutationAttemptedCount": business_mutation_attempted,
        "enabledScopes": list(ENABLED_SCOPES),
        "futureDisabledScopes": list(FUTURE_DISABLED_SCOPES),
        "forbiddenTools": list(FORBIDDEN_TOOLS),
        "blockers": blockers,
        "warnings": warnings,
        "safeToEnableReadOnlyMcp": safe_to_enable_read_only_mcp,
        "safeToStartPhase6M": safe_to_start_phase_6m,
        "nextAction": next_action,
    }


def get_mcp_security_posture() -> dict[str, Any]:
    readiness = get_mcp_gateway_readiness()
    forbidden_registered = readiness["forbiddenToolsRegisteredCount"] > 0
    write_or_provider_enabled = (
        readiness["writeToolsEnabled"]
        or readiness["providerToolsEnabled"]
        or readiness["writeToolEnabledCount"] > 0
        or readiness["providerToolEnabledCount"] > 0
    )
    blockers: list[str] = list(readiness["blockers"])
    warnings: list[str] = list(readiness["warnings"])
    if write_or_provider_enabled:
        blockers.append("write_or_provider_tools_unexpectedly_enabled")
    if not readiness["requireAuth"]:
        blockers.append("auth_required_must_remain_true")
    return {
        "forbiddenToolsRegistered": forbidden_registered,
        "writeToolsEnabled": readiness["writeToolsEnabled"],
        "providerToolsEnabled": readiness["providerToolsEnabled"],
        "writeToolEnabledCount": readiness["writeToolEnabledCount"],
        "providerToolEnabledCount": readiness["providerToolEnabledCount"],
        "authRequired": readiness["requireAuth"],
        "rawSecretExposureCount": readiness["rawSecretExposureCount"],
        "piiExposureCount": readiness["fullPiiExposureCount"],
        "providerCallAttemptedCount": readiness["providerCallAttemptedCount"],
        "businessMutationAttemptedCount": readiness[
            "businessMutationAttemptedCount"
        ],
        "blockers": blockers,
        "warnings": warnings,
        "safe": not blockers,
        "nextAction": (
            "fix_mcp_security_posture"
            if blockers
            else "phase_6m_0_security_posture_clean"
        ),
    }


__all__ = (
    "get_mcp_gateway_readiness",
    "get_mcp_security_posture",
)
