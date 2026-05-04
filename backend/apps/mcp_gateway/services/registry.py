"""Phase 6M-0 — registry seeders for tools / resources / prompts.

Idempotent. Refuses to seed any forbidden tool. Defaults are LOCKED:
``read_only=True``, ``provider_call_allowed=False``,
``business_mutation_allowed=False``.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from ..models import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpToolDefinition,
)
from .default_prompts import list_default_prompt_seeds
from .default_resources import list_default_resource_seeds
from .default_tools import list_default_tool_seeds
from .schemas import is_forbidden_tool


def _seed_to_tool_kwargs(seed: dict[str, Any]) -> dict[str, Any]:
    """Coerce a default-tool seed to safe model kwargs.

    Phase 6M-0 hard-pins:
      - ``read_only=True``
      - ``provider_call_allowed=False``
      - ``business_mutation_allowed=False``
      - ``enabled=True``
      - ``requires_auth=True``
    """
    return {
        "title": seed["title"],
        "description": seed.get("description", ""),
        "category": seed["category"],
        "handler_key": seed["handler_key"],
        "enabled": True,
        "read_only": True,
        "risk_level": seed.get("risk_level", "low"),
        "requires_auth": True,
        "requires_org_context": seed.get("requires_org_context", True),
        "requires_human_approval": seed.get("requires_human_approval", False),
        "provider_call_allowed": False,
        "business_mutation_allowed": False,
        "pii_exposure_level": seed.get("pii_exposure_level", "none"),
        "input_schema": seed.get("input_schema", {}),
        "output_schema": seed.get("output_schema", {}),
        "required_scopes": list(seed.get("required_scopes", [])),
        "tags": list(seed.get("tags", [])),
        "metadata": dict(seed.get("metadata", {})),
    }


def _seed_to_resource_kwargs(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": seed["name"],
        "title": seed["title"],
        "description": seed.get("description", ""),
        "mime_type": seed.get("mime_type", "application/json"),
        "enabled": True,
        "read_only": True,
        "requires_auth": True,
        "required_scopes": list(seed.get("required_scopes", [])),
        "pii_exposure_level": seed.get("pii_exposure_level", "none"),
        "handler_key": seed["handler_key"],
        "metadata": dict(seed.get("metadata", {})),
    }


def _seed_to_prompt_kwargs(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": seed["title"],
        "description": seed.get("description", ""),
        "template": seed.get("template", ""),
        "variables_schema": seed.get("variables_schema", {}),
        "enabled": True,
        "requires_auth": True,
        "required_scopes": list(seed.get("required_scopes", [])),
        "risk_level": seed.get("risk_level", "low"),
        "metadata": dict(seed.get("metadata", {})),
    }


@transaction.atomic
def register_default_mcp_tools() -> dict[str, Any]:
    """Seed / refresh the default tool / resource / prompt rows.

    Idempotent. Refuses to seed forbidden tools. Returns a counters
    dict so the management command can render the summary.
    """
    tools_created = 0
    tools_updated = 0
    tools_unchanged = 0
    tools_refused = 0
    resources_created = 0
    resources_updated = 0
    prompts_created = 0
    prompts_updated = 0

    for seed in list_default_tool_seeds():
        if is_forbidden_tool(seed["name"]):
            tools_refused += 1
            continue
        kwargs = _seed_to_tool_kwargs(seed)
        existing = McpToolDefinition.objects.filter(name=seed["name"]).first()
        if existing is None:
            McpToolDefinition.objects.create(name=seed["name"], **kwargs)
            tools_created += 1
            continue
        # Force-pin Phase 6M-0 invariants on update.
        kwargs["read_only"] = True
        kwargs["provider_call_allowed"] = False
        kwargs["business_mutation_allowed"] = False
        kwargs["enabled"] = True
        kwargs["requires_auth"] = True
        changed = False
        for field, value in kwargs.items():
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if changed:
            existing.save()
            tools_updated += 1
        else:
            tools_unchanged += 1

    for seed in list_default_resource_seeds():
        kwargs = _seed_to_resource_kwargs(seed)
        existing = McpResourceDefinition.objects.filter(uri=seed["uri"]).first()
        if existing is None:
            McpResourceDefinition.objects.create(uri=seed["uri"], **kwargs)
            resources_created += 1
        else:
            for field, value in kwargs.items():
                setattr(existing, field, value)
            existing.save()
            resources_updated += 1

    for seed in list_default_prompt_seeds():
        kwargs = _seed_to_prompt_kwargs(seed)
        existing = McpPromptDefinition.objects.filter(name=seed["name"]).first()
        if existing is None:
            McpPromptDefinition.objects.create(name=seed["name"], **kwargs)
            prompts_created += 1
        else:
            for field, value in kwargs.items():
                setattr(existing, field, value)
            existing.save()
            prompts_updated += 1

    return {
        "toolsCreated": tools_created,
        "toolsUpdated": tools_updated,
        "toolsUnchanged": tools_unchanged,
        "toolsRefused": tools_refused,
        "resourcesCreated": resources_created,
        "resourcesUpdated": resources_updated,
        "promptsCreated": prompts_created,
        "promptsUpdated": prompts_updated,
    }


__all__ = ("register_default_mcp_tools",)
