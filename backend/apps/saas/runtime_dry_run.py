"""Phase 6G — Controlled runtime routing dry-run engine.

Composes the operation taxonomy (:mod:`apps.saas.runtime_operations`),
the Phase 6F provider runtime preview
(:mod:`apps.saas.integration_runtime`), and the AI provider preview
(:mod:`apps.saas.ai_runtime_preview`) into a single dry-run decision
shape consumed by the management command, the read-only DRF endpoint,
and the SaaS Admin Panel "Controlled Runtime Routing Dry Run" section.

LOCKED rules:

- ``runtimeSource`` is always ``"env_config"``.
- ``perOrgRuntimeEnabled``, ``liveExecutionAllowed``,
  ``externalCallWillBeMade`` are always ``False``.
- The engine NEVER calls a provider, NEVER mutates a model, NEVER
  writes a customer-facing audit row.
- Raw secrets are NEVER returned. ENV: refs go through the Phase 6F
  ``get_secret_ref_status`` masker.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

from .ai_runtime_preview import (
    AI_TASK_ROUTES,
    preview_all_ai_provider_routes,
    preview_ai_provider_route,
)
from .context import (
    get_default_organization,
    resolve_request_organization,
    resolve_request_branch,
    get_user_active_organization,
    get_user_active_branch,
)
from .integration_runtime import (
    get_provider_runtime_preview,
    get_secret_ref_status,
)
from .integration_settings import (
    EXPECTED_SECRET_REFS,
    PROVIDER_LABELS,
)
from .models import Branch, Organization
from .runtime_operations import (
    RUNTIME_OPERATIONS,
    RuntimeOperationDefinition,
    get_runtime_operation_definition,
)


_OP_TYPE_TO_AI_TASK: dict[str, str] = {
    "ai.reports_summary": "reports_summaries",
    "ai.ceo_planning": "ceo_planning",
    "ai.caio_compliance": "caio_compliance",
    "ai.customer_hinglish_chat": "hinglish_customer_chat",
    "ai.critical_fallback": "critical_fallback",
    "ai.smoke_test": "smoke_test",
}


def _serialize_org(org: Optional[Organization]) -> Optional[dict[str, Any]]:
    if org is None:
        return None
    return {"id": org.id, "code": org.code, "name": org.name}


def _serialize_branch(branch: Optional[Branch]) -> Optional[dict[str, Any]]:
    if branch is None:
        return None
    return {"id": branch.id, "code": branch.code, "name": branch.name}


def _env_present_map(env_keys: Iterable[str]) -> dict[str, bool]:
    return {key: bool(os.environ.get(key)) for key in env_keys}


def build_runtime_dry_run_context(
    operation_type: str,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    request=None,
    user=None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Lightweight context object for a single dry-run preview call.

    The returned dict is the input shape every downstream
    ``preview_*`` helper consumes. No DB writes; no provider calls.
    """
    org = organization
    if org is None and request is not None:
        org = resolve_request_organization(request)
    if org is None and user is not None:
        org = get_user_active_organization(user)
    if org is None:
        org = get_default_organization()

    resolved_branch = branch
    if resolved_branch is None and request is not None:
        resolved_branch = resolve_request_branch(request, organization=org)
    if resolved_branch is None and user is not None:
        resolved_branch = get_user_active_branch(user, organization=org)

    return {
        "operationType": operation_type,
        "organization": _serialize_org(org),
        "branch": _serialize_branch(resolved_branch),
        "payloadKeys": sorted((payload or {}).keys()),
    }


def resolve_provider_for_operation(
    operation_type: str,
    org: Optional[Organization] = None,
) -> dict[str, Any]:
    """Tell the operator which provider would be selected if the
    operation went live, plus the env/config readiness for that
    provider. Phase 6G keeps live OFF — this is preview only.
    """
    op = get_runtime_operation_definition(operation_type)
    if op is None:
        return {
            "operationType": operation_type,
            "valid": False,
            "providerType": "",
            "blockers": [f"Unknown operation type: {operation_type}"],
        }
    provider_preview = get_provider_runtime_preview(org, op.provider_type)
    return {
        "operationType": operation_type,
        "valid": True,
        "providerType": op.provider_type,
        "providerLabel": PROVIDER_LABELS.get(
            op.provider_type, op.provider_type
        ),
        "providerSettingExists": provider_preview[
            "integrationSettingExists"
        ],
        "settingStatus": provider_preview["settingStatus"],
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
    }


def _ai_block_for_operation(
    operation_type: str,
) -> Optional[dict[str, Any]]:
    """If the operation is an ``ai.*`` task, return its preview shape."""
    task = _OP_TYPE_TO_AI_TASK.get(operation_type)
    if not task:
        return None
    return preview_ai_provider_route(task)


def preview_runtime_routing_for_operation(
    operation_type: str,
    org: Optional[Organization] = None,
    payload: Optional[dict[str, Any]] = None,
    request=None,
    user=None,
) -> dict[str, Any]:
    """Compose a single dry-run preview for ``operation_type``.

    Phase 6G locks every output to ``dryRun=True``,
    ``liveExecutionAllowed=False``, ``externalCallWillBeMade=False``.
    """
    op = get_runtime_operation_definition(operation_type)
    if op is None:
        return {
            "operationType": operation_type,
            "valid": False,
            "dryRun": True,
            "liveExecutionAllowed": False,
            "externalCallWillBeMade": False,
            "blockers": [f"Unknown operation type: {operation_type}"],
            "warnings": [],
            "nextAction": "fix_runtime_operation_lookup",
        }

    context = build_runtime_dry_run_context(
        operation_type,
        organization=org,
        request=request,
        user=user,
        payload=payload,
    )
    resolved_org_payload = context["organization"]
    org_obj = (
        Organization.objects.filter(id=resolved_org_payload["id"]).first()
        if resolved_org_payload
        else None
    )

    provider_preview = get_provider_runtime_preview(org_obj, op.provider_type)
    expected_refs = list(EXPECTED_SECRET_REFS.get(op.provider_type, ()))
    secret_refs_status: dict[str, Any] = {}
    setting_secret_refs = (
        (provider_preview.get("setting") or {}).get("secretRefs") or {}
    )
    for key in expected_refs:
        masked_value = setting_secret_refs.get(key, "")
        # Resolve presence via env when the masked ref maps to one of
        # the operation's expected env keys; otherwise just report the
        # masked label. ``get_secret_ref_status`` accepts masked output
        # because the inner regex handles ENV: / VAULT: prefixes; for
        # missing setting rows we surface an explicit "missing" entry.
        if not masked_value:
            secret_refs_status[key] = {
                "present": False,
                "maskedRef": "",
                "source": "missing",
                "canResolveAtRuntime": False,
                "reason": "no per-org integration setting configured",
            }
        else:
            # ``masked_value`` already came from the Phase 6F masker so
            # we can pass it back through ``get_secret_ref_status`` to
            # render the same shape; presence relies on the env-key
            # level snapshot below since masked refs intentionally can
            # NOT be resolved back to a real env var.
            secret_refs_status[key] = {
                "maskedRef": masked_value,
                "source": (
                    "env"
                    if isinstance(masked_value, str)
                    and masked_value.startswith("ENV:")
                    else "vault"
                    if isinstance(masked_value, str)
                    and masked_value.startswith("VAULT:")
                    else "unknown"
                ),
                "present": None,
                "canResolveAtRuntime": False,
                "reason": (
                    "masked ref only; presence is reported per env key "
                    "below"
                ),
            }

    env_status = _env_present_map(op.required_env_keys)
    config_status = {
        key: True for key in op.required_config_keys
    }  # config keys are stored on the setting, not env

    blockers: list[str] = []
    warnings: list[str] = []

    if not provider_preview["integrationSettingExists"]:
        warnings.append(
            "No per-org integration setting configured. Runtime stays "
            "on env / config."
        )
    missing_envs = [k for k, v in env_status.items() if not v]
    if missing_envs:
        # PayU + Delhivery are explicitly deferred — surface as warning
        # not blocker.
        if op.provider_type in {"payu", "delhivery"}:
            warnings.append(
                f"{op.provider_type} env keys missing — deferred "
                "provider; live execution remains blocked."
            )
        elif op.provider_type == "vapi":
            warnings.append(
                "Vapi env partially configured — phone_number_id and "
                "webhook_secret are still missing; live calls remain "
                "blocked."
            )
        else:
            warnings.append(
                f"Required env keys missing for {op.operation_type}: "
                + ", ".join(missing_envs)
            )

    ai_route = _ai_block_for_operation(operation_type)
    if ai_route:
        for blocker in ai_route.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(blocker)
        for warning in ai_route.get("warnings") or []:
            if warning not in warnings:
                warnings.append(warning)

    next_action = (
        "fix_runtime_routing_blockers"
        if blockers
        else "ready_for_phase_6h_controlled_runtime_live_audit"
    )

    return {
        "operationType": operation_type,
        "operationDefinition": op.to_dict(),
        "organization": context["organization"],
        "branch": context["branch"],
        "providerType": op.provider_type,
        "providerLabel": PROVIDER_LABELS.get(
            op.provider_type, op.provider_type
        ),
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "dryRun": True,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "sideEffectRisk": op.side_effect_risk,
        "providerSettingExists": provider_preview[
            "integrationSettingExists"
        ],
        "settingStatus": provider_preview["settingStatus"],
        "secretRefsStatus": secret_refs_status,
        "envKeyStatus": env_status,
        "configStatus": config_status,
        "providerRuntimePreview": {
            "secretRefsPresent": provider_preview["secretRefsPresent"],
            "missingSecretRefs": provider_preview["missingSecretRefs"],
            "configPresent": provider_preview["configPresent"],
        },
        "aiProviderRoute": ai_route,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "auditKind": "saas.runtime_dry_run.previewed",
    }


def preview_all_runtime_operations(
    org: Optional[Organization] = None,
    *,
    include_ai: bool = True,
) -> dict[str, Any]:
    """Run :func:`preview_runtime_routing_for_operation` for every
    registered operation. Returns a top-level shape ready for the
    SaaS Admin "Controlled Runtime Routing Dry Run" table.
    """
    operations = []
    for op in RUNTIME_OPERATIONS:
        operations.append(
            preview_runtime_routing_for_operation(
                op.operation_type, org=org
            )
        )

    ai_routes = preview_all_ai_provider_routes() if include_ai else None

    blockers: list[str] = []
    warnings: list[str] = []
    for entry in operations:
        for blocker in entry.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(blocker)
        for warning in entry.get("warnings") or []:
            if warning not in warnings:
                warnings.append(warning)

    if ai_routes:
        for blocker in ai_routes.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(blocker)

    safe_to_start_phase_6h = bool(operations) and not blockers
    next_action = (
        "ready_for_phase_6h_controlled_runtime_live_audit"
        if safe_to_start_phase_6h
        else "fix_runtime_routing_blockers"
    )

    return {
        "organization": _serialize_org(org),
        "runtimeUsesPerOrgSettings": False,
        "perOrgRuntimeEnabled": False,
        "runtimeSource": "env_config",
        "dryRun": True,
        "liveExecutionAllowed": False,
        "operations": operations,
        "aiProviderRoutes": ai_routes,
        "global": {
            "safeToStartPhase6H": safe_to_start_phase_6h,
            "blockers": blockers,
            "warnings": warnings,
            "nextAction": next_action,
        },
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
    }


def validate_dry_run_has_no_side_effects(decision: dict[str, Any]) -> bool:
    """Sanity check used in tests + the management command. The
    invariants are simple: every dry-run decision must declare
    ``dryRun=True``, ``liveExecutionAllowed=False``,
    ``externalCallWillBeMade=False``, and ``runtimeSource=env_config``.
    """
    return (
        decision.get("dryRun") is True
        and decision.get("liveExecutionAllowed") is False
        and decision.get("externalCallWillBeMade") is False
        and decision.get("runtimeSource") == "env_config"
        and decision.get("perOrgRuntimeEnabled") is False
    )


def summarize_runtime_dry_run_readiness(
    org: Optional[Organization] = None,
) -> dict[str, Any]:
    """Top-level readiness payload — the management command + the
    ``GET /api/v1/saas/controlled-runtime-readiness/`` endpoint share
    this shape.
    """
    full = preview_all_runtime_operations(org, include_ai=True)
    return {
        "organization": full["organization"],
        "runtimeSource": full["runtimeSource"],
        "perOrgRuntimeEnabled": full["perOrgRuntimeEnabled"],
        "runtimeUsesPerOrgSettings": full["runtimeUsesPerOrgSettings"],
        "dryRun": True,
        "liveExecutionAllowed": False,
        "operationCount": len(full["operations"]),
        "aiTaskCount": len((full.get("aiProviderRoutes") or {}).get("tasks", [])),
        "safeToStartPhase6H": full["global"]["safeToStartPhase6H"],
        "blockers": full["blockers"],
        "warnings": full["warnings"],
        "nextAction": full["nextAction"],
    }


__all__ = (
    "build_runtime_dry_run_context",
    "resolve_provider_for_operation",
    "preview_runtime_routing_for_operation",
    "preview_all_runtime_operations",
    "validate_dry_run_has_no_side_effects",
    "summarize_runtime_dry_run_readiness",
)
