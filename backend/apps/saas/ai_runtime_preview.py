"""Phase 6G — AI provider routing preview.

Read-only resolver layer for the AI provider router. Phase 6G never
calls NVIDIA / OpenAI / Anthropic from a normal preview path; the
optional ``smoke_test_ai_provider_routes`` management command is the
only place a tiny non-customer prompt may go out, and only when the
operator explicitly invokes it.

LOCKED rules:

- ``runtimeMode`` reflects ``AI_PROVIDER_RUNTIME_MODE`` env (defaults
  to ``preview`` in this phase).
- ``liveCallWillBeMade`` is always ``False`` in the preview helpers.
- API keys are NEVER returned. The resolver reports presence (boolean)
  only.
- Customer-facing AI drafts still need the existing Claim Vault +
  safety stack + approval matrix before any future live send.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional


_AI_RUNTIME_MODE_ENV = "AI_PROVIDER_RUNTIME_MODE"
_AI_PRIMARY_PROVIDER_ENV = "AI_PRIMARY_PROVIDER"
_AI_FALLBACK_PROVIDER_ENV = "AI_FALLBACK_PROVIDER"


@dataclass(frozen=True)
class AiTaskRoute:
    """Static route definition for a logical AI task."""

    task_type: str
    primary_provider: str
    primary_model_env: str
    primary_model_default: str
    fallback_provider: str
    fallback_model_env: str
    fallback_model_default: str
    max_tokens_env: str
    max_tokens_default: int
    notes: str = ""


# Canonical task → provider routing table. Values mirror the manual
# NVIDIA smoke test the operator already ran on the VPS.
AI_TASK_ROUTES: tuple[AiTaskRoute, ...] = (
    AiTaskRoute(
        task_type="reports_summaries",
        primary_provider="nvidia",
        primary_model_env="NVIDIA_MODEL_REPORTS_SUMMARIES",
        primary_model_default="minimaxai/minimax-m2.7",
        fallback_provider="openai",
        fallback_model_env="OPENAI_MODEL_REPORTS_SUMMARIES",
        fallback_model_default="gpt-4o-mini",
        max_tokens_env="AI_MAX_TOKENS_REPORTS",
        max_tokens_default=3000,
        notes=(
            "Internal reporting only — no customer messaging side "
            "effect. Output is consumed by the dashboards."
        ),
    ),
    AiTaskRoute(
        task_type="ceo_planning",
        primary_provider="nvidia",
        primary_model_env="NVIDIA_MODEL_CEO_PLANNING",
        primary_model_default="moonshotai/kimi-k2.6",
        fallback_provider="openai",
        fallback_model_env="OPENAI_MODEL_CEO_PLANNING",
        fallback_model_default="gpt-4o",
        max_tokens_env="AI_MAX_TOKENS_CEO",
        max_tokens_default=2048,
        notes="Drives the CEO AI Briefing surface; internal only.",
    ),
    AiTaskRoute(
        task_type="caio_compliance",
        primary_provider="nvidia",
        primary_model_env="NVIDIA_MODEL_CAIO_COMPLIANCE",
        primary_model_default="mistralai/mistral-medium-3.5-128b",
        fallback_provider="openai",
        fallback_model_env="OPENAI_MODEL_CAIO_COMPLIANCE",
        fallback_model_default="gpt-4o",
        max_tokens_env="AI_MAX_TOKENS_COMPLIANCE",
        max_tokens_default=1024,
        notes=(
            "Compliance reasoning. Low-confidence findings escalate "
            "to the existing human-review CAIO workflow."
        ),
    ),
    AiTaskRoute(
        task_type="hinglish_customer_chat",
        primary_provider="nvidia",
        primary_model_env="NVIDIA_MODEL_HINGLISH_CHAT",
        primary_model_default="google/gemma-4-31b-it",
        fallback_provider="openai",
        fallback_model_env="OPENAI_MODEL_HINGLISH_CHAT",
        fallback_model_default="gpt-4o-mini",
        max_tokens_env="AI_MAX_TOKENS_CUSTOMER_CHAT",
        max_tokens_default=512,
        notes=(
            "Customer-facing drafts. Must pass Claim Vault + safety "
            "stack + approval matrix before any future live send."
        ),
    ),
    AiTaskRoute(
        task_type="critical_fallback",
        primary_provider="nvidia",
        primary_model_env="NVIDIA_MODEL_CAIO_COMPLIANCE",
        primary_model_default="mistralai/mistral-medium-3.5-128b",
        fallback_provider="openai",
        fallback_model_env="OPENAI_MODEL_CRITICAL_FALLBACK",
        fallback_model_default="gpt-4o",
        max_tokens_env="AI_MAX_TOKENS_COMPLIANCE",
        max_tokens_default=1024,
        notes=(
            "Critical-path fallback. OpenAI primary fallback; "
            "Anthropic Claude is the secondary fallback when "
            "configured."
        ),
    ),
    AiTaskRoute(
        task_type="smoke_test",
        primary_provider="nvidia",
        primary_model_env="NVIDIA_MODEL_HINGLISH_CHAT",
        primary_model_default="google/gemma-4-31b-it",
        fallback_provider="openai",
        fallback_model_env="OPENAI_MODEL_HINGLISH_CHAT",
        fallback_model_default="gpt-4o-mini",
        max_tokens_env="AI_MAX_TOKENS_SMOKE",
        max_tokens_default=32,
        notes=(
            "Tiny non-customer prompt used for provider reachability "
            "checks. Smoke test command is the only path that may "
            "issue a live call to NVIDIA."
        ),
    ),
)


_TASK_REGISTRY: dict[str, AiTaskRoute] = {
    route.task_type: route for route in AI_TASK_ROUTES
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_present(env_key: str) -> bool:
    return bool(os.environ.get(env_key))


def get_ai_runtime_mode() -> str:
    """Return ``preview`` / ``shadow`` / ``live`` based on env. Defaults
    to ``preview`` so Phase 6G is the safe path."""
    return (os.environ.get(_AI_RUNTIME_MODE_ENV) or "preview").lower()


def get_ai_task_route(task_type: str) -> Optional[AiTaskRoute]:
    return _TASK_REGISTRY.get(task_type or "")


def get_ai_task_max_tokens(task_type: str) -> dict[str, Any]:
    """Resolve task-wise ``max_tokens`` from env with a typed default.

    Returns ``{"value": int, "source": "env" | "default", "envKey": str}``
    so the SaaS Admin UI can show where the value came from. Invalid
    integers fall back to the default.
    """
    route = get_ai_task_route(task_type)
    if route is None:
        return {"value": 0, "source": "unknown", "envKey": ""}
    raw = os.environ.get(route.max_tokens_env)
    if raw:
        try:
            return {
                "value": int(raw),
                "source": "env",
                "envKey": route.max_tokens_env,
            }
        except ValueError:
            pass
    return {
        "value": route.max_tokens_default,
        "source": "default",
        "envKey": route.max_tokens_env,
    }


def validate_ai_model_envs() -> dict[str, Any]:
    """Return per-env-var presence map (booleans only).

    Never logs or returns the raw value. Useful for the Admin Panel
    "AI Provider Routing" section.
    """
    keys = (
        "NVIDIA_API_KEY",
        "NVIDIA_API_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE_URL",
        "ANTHROPIC_API_KEY",
        _AI_RUNTIME_MODE_ENV,
        _AI_PRIMARY_PROVIDER_ENV,
        _AI_FALLBACK_PROVIDER_ENV,
    )
    return {key: _env_present(key) for key in keys}


def mask_ai_provider_env_status() -> dict[str, Any]:
    """Public-API-safe summary of provider env state. Booleans only,
    no values, no keys."""
    base = validate_ai_model_envs()
    return {
        "runtimeMode": get_ai_runtime_mode(),
        "primaryProvider": (
            os.environ.get(_AI_PRIMARY_PROVIDER_ENV) or "nvidia"
        ).lower(),
        "fallbackProvider": (
            os.environ.get(_AI_FALLBACK_PROVIDER_ENV) or "openai"
        ).lower(),
        "envKeyPresence": base,
    }


def _resolve_model(env_key: str, default_value: str) -> dict[str, str]:
    raw = os.environ.get(env_key)
    if raw:
        return {"value": raw, "source": "env"}
    return {"value": default_value, "source": "default"}


# ---------------------------------------------------------------------------
# Preview composition
# ---------------------------------------------------------------------------


def preview_ai_provider_route(
    task_type: str,
    prompt_preview: Optional[str] = None,
) -> dict[str, Any]:
    """Return the dry-run preview for a single AI task.

    Phase 6G invariants:

    - ``liveCallWillBeMade`` is ``False``.
    - ``dryRun`` is ``True``.
    - Raw API keys never appear; only presence booleans.
    """
    route = get_ai_task_route(task_type)
    if route is None:
        return {
            "taskType": task_type,
            "valid": False,
            "blockers": [f"Unknown task type: {task_type}"],
            "warnings": [],
            "nextAction": "fix_ai_task_route_lookup",
        }

    primary_model = _resolve_model(
        route.primary_model_env, route.primary_model_default
    )
    fallback_model = _resolve_model(
        route.fallback_model_env, route.fallback_model_default
    )
    max_tokens = get_ai_task_max_tokens(task_type)
    runtime_mode = get_ai_runtime_mode()
    nvidia_key_present = _env_present("NVIDIA_API_KEY")
    nvidia_base_present = _env_present("NVIDIA_API_BASE_URL")
    openai_key_present = _env_present("OPENAI_API_KEY")
    anthropic_key_present = _env_present("ANTHROPIC_API_KEY")

    blockers: list[str] = []
    warnings: list[str] = []

    if route.primary_provider == "nvidia":
        if not nvidia_key_present:
            blockers.append("NVIDIA_API_KEY is not set")
        if not nvidia_base_present:
            warnings.append(
                "NVIDIA_API_BASE_URL is not set; the adapter will use "
                "its built-in default."
            )
    if route.fallback_provider == "openai" and not openai_key_present:
        warnings.append(
            "OPENAI_API_KEY is not set; the OpenAI fallback path will "
            "be unavailable."
        )

    safety_warnings: list[str] = []
    if task_type == "hinglish_customer_chat":
        safety_warnings.append(
            "Customer-facing drafts must still pass through Claim "
            "Vault, blocked phrase filter, safety stack, and approval "
            "matrix before any live send."
        )
    if task_type == "caio_compliance":
        safety_warnings.append(
            "Low-confidence compliance findings must escalate to the "
            "existing human-review CAIO workflow."
        )

    next_action = "ready_for_ai_provider_dry_run_preview"
    if blockers:
        next_action = "fix_ai_provider_env_before_dry_run"

    payload: dict[str, Any] = {
        "taskType": route.task_type,
        "primaryProvider": route.primary_provider,
        "primaryModel": primary_model["value"],
        "primaryModelSource": primary_model["source"],
        "expectedPrimaryModel": route.primary_model_default,
        "fallbackProvider": route.fallback_provider,
        "fallbackModel": fallback_model["value"],
        "fallbackModelSource": fallback_model["source"],
        "fallbackConfigured": openai_key_present,
        "anthropicFallbackConfigured": anthropic_key_present,
        "runtimeMode": runtime_mode,
        "maxTokens": max_tokens["value"],
        "maxTokensSource": max_tokens["envKey"],
        "maxTokensFromEnv": max_tokens["source"] == "env",
        "apiBaseUrlPresent": nvidia_base_present,
        "apiKeyPresent": nvidia_key_present,
        "openaiKeyPresent": openai_key_present,
        "liveCallWillBeMade": False,
        "dryRun": True,
        "safetyWrappersRequired": bool(safety_warnings),
        "safetyNotes": safety_warnings,
        "blockers": blockers,
        "warnings": warnings + safety_warnings,
        "nextAction": next_action,
        "valid": True,
    }
    # Optional truncated prompt preview — never echo customer payloads
    # in the dashboard fixture path.
    if prompt_preview is not None:
        payload["promptPreview"] = (prompt_preview or "")[:120]
    return payload


def preview_all_ai_provider_routes() -> dict[str, Any]:
    routes = [
        preview_ai_provider_route(route.task_type)
        for route in AI_TASK_ROUTES
    ]
    blockers: list[str] = []
    for route in routes:
        for blocker in route.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(blocker)
    safe_to_start = bool(routes) and not blockers
    next_action = (
        "ready_for_phase_6h_controlled_runtime_routing_live_audit"
        if safe_to_start
        else "fix_ai_provider_env_before_dry_run"
    )
    return {
        "runtime": mask_ai_provider_env_status(),
        "tasks": routes,
        "safeToStartAiDryRun": safe_to_start,
        "blockers": blockers,
        "warnings": [],
        "nextAction": next_action,
        "dryRun": True,
        "liveCallWillBeMade": False,
    }


__all__ = (
    "AI_TASK_ROUTES",
    "AiTaskRoute",
    "get_ai_runtime_mode",
    "get_ai_task_route",
    "get_ai_task_max_tokens",
    "validate_ai_model_envs",
    "mask_ai_provider_env_status",
    "preview_ai_provider_route",
    "preview_all_ai_provider_routes",
)
