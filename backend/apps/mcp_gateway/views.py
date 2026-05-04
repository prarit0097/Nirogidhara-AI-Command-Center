"""Phase 6M-0 — MCP gateway DRF endpoints.

Six read-only admin views + one POST simulator. Phase 6M-0 ships no
public protocol endpoint; ``MCP_ENABLED`` defaults to ``False`` so
even if a future PR wires a streamable_http handler it stays
disabled until explicitly turned on.
"""
from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpToolDefinition,
    McpToolInvocationLog,
)
from .permissions import McpAdminPermission
from .services import tool_handlers  # noqa: F401  (registers handlers)
from .services.readiness import (
    get_mcp_gateway_readiness,
    get_mcp_security_posture,
)
from .services.tool_executor import execute_mcp_tool


def _serialize_tool(tool: McpToolDefinition) -> dict[str, Any]:
    return {
        "id": tool.id,
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "category": tool.category,
        "handlerKey": tool.handler_key,
        "enabled": tool.enabled,
        "readOnly": tool.read_only,
        "riskLevel": tool.risk_level,
        "requiresAuth": tool.requires_auth,
        "requiresOrgContext": tool.requires_org_context,
        "requiresHumanApproval": tool.requires_human_approval,
        "providerCallAllowed": tool.provider_call_allowed,
        "businessMutationAllowed": tool.business_mutation_allowed,
        "piiExposureLevel": tool.pii_exposure_level,
        "requiredScopes": list(tool.required_scopes or []),
        "tags": list(tool.tags or []),
        "createdAt": tool.created_at.isoformat(),
        "updatedAt": tool.updated_at.isoformat(),
    }


def _serialize_resource(resource: McpResourceDefinition) -> dict[str, Any]:
    return {
        "id": resource.id,
        "uri": resource.uri,
        "name": resource.name,
        "title": resource.title,
        "description": resource.description,
        "mimeType": resource.mime_type,
        "enabled": resource.enabled,
        "readOnly": resource.read_only,
        "requiresAuth": resource.requires_auth,
        "requiredScopes": list(resource.required_scopes or []),
        "piiExposureLevel": resource.pii_exposure_level,
        "handlerKey": resource.handler_key,
    }


def _serialize_prompt(prompt: McpPromptDefinition) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "name": prompt.name,
        "title": prompt.title,
        "description": prompt.description,
        "templatePreview": (prompt.template or "")[:240],
        "variablesSchema": prompt.variables_schema,
        "enabled": prompt.enabled,
        "requiresAuth": prompt.requires_auth,
        "requiredScopes": list(prompt.required_scopes or []),
        "riskLevel": prompt.risk_level,
    }


def _serialize_invocation(row: McpToolInvocationLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "invocationId": row.invocation_id,
        "toolName": row.tool_name,
        "toolCategory": row.tool_category,
        "status": row.status,
        "deniedReason": row.denied_reason,
        "riskLevel": row.risk_level,
        "readOnly": row.read_only,
        "providerCallAllowed": row.provider_call_allowed,
        "businessMutationAllowed": row.business_mutation_allowed,
        "providerCallAttempted": row.provider_call_attempted,
        "businessMutationAttempted": row.business_mutation_attempted,
        "rawSecretExposed": row.raw_secret_exposed,
        "fullPiiExposed": row.full_pii_exposed,
        "outputTruncated": row.output_truncated,
        "durationMs": row.duration_ms,
        "errorSummary": row.error_summary,
        "createdAt": row.created_at.isoformat(),
    }


class McpReadinessView(APIView):
    """``GET /api/v1/mcp/readiness/``."""

    permission_classes = [McpAdminPermission]

    def get(self, _request):
        return Response(get_mcp_gateway_readiness())


class McpSecurityPostureView(APIView):
    """``GET /api/v1/mcp/security-posture/``."""

    permission_classes = [McpAdminPermission]

    def get(self, _request):
        return Response(get_mcp_security_posture())


class McpToolsView(APIView):
    """``GET /api/v1/mcp/tools/``."""

    permission_classes = [McpAdminPermission]

    def get(self, _request):
        rows = [
            _serialize_tool(t)
            for t in McpToolDefinition.objects.all().order_by("category", "name")
        ]
        return Response(
            {
                "count": len(rows),
                "tools": rows,
                "readOnlyMode": True,
                "writeToolsEnabled": False,
                "providerToolsEnabled": False,
            }
        )


class McpResourcesView(APIView):
    """``GET /api/v1/mcp/resources/``."""

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        rows = [
            _serialize_resource(r)
            for r in McpResourceDefinition.objects.all().order_by("uri")
        ]
        return Response({"count": len(rows), "resources": rows})


class McpPromptsView(APIView):
    """``GET /api/v1/mcp/prompts/``."""

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        rows = [
            _serialize_prompt(p)
            for p in McpPromptDefinition.objects.all().order_by("name")
        ]
        return Response({"count": len(rows), "prompts": rows})


class McpInvocationsView(APIView):
    """``GET /api/v1/mcp/invocations/``."""

    permission_classes = [McpAdminPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 100))
        rows = [
            _serialize_invocation(r)
            for r in McpToolInvocationLog.objects.order_by("-created_at")[
                :limit
            ]
        ]
        return Response(
            {
                "count": len(rows),
                "limit": limit,
                "invocations": rows,
                "providerCallAttempted": False,
                "businessMutationAttempted": False,
            }
        )


class McpSimulateToolCallView(APIView):
    """``POST /api/v1/mcp/tools/simulate/``.

    Admin-only simulator. Phase 6M-0: never registers a public MCP
    endpoint; the simulator is the sanctioned read-only path for the
    SaaS Admin UI to render an actual tool result.
    """

    permission_classes = [McpAdminPermission]

    def post(self, request):
        tool_name = (
            request.data.get("toolName")
            or request.data.get("tool_name")
            or ""
        ).strip()
        if not tool_name:
            return Response(
                {"detail": "toolName required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        input_data = request.data.get("input") or {}
        if not isinstance(input_data, dict):
            return Response(
                {"detail": "input must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = execute_mcp_tool(
            tool_name,
            input_data=input_data,
            actor=request.user,
        )
        return Response(result)


__all__ = (
    "McpReadinessView",
    "McpSecurityPostureView",
    "McpToolsView",
    "McpResourcesView",
    "McpPromptsView",
    "McpInvocationsView",
    "McpSimulateToolCallView",
)
