"""OpenAI Chat Completions adapter — Phase 3A + 3C cost tracking.

Lazy SDK import: ``openai`` is NEVER imported until ``dispatch`` actually
runs in test/live mode. The disabled / no-key path short-circuits with
``skipped_result`` so dev runs and CI do not need the package installed.

Phase 3C extends the result with model-wise token usage + cost via
``apps.integrations.ai.pricing.calculate_openai_cost``. The pricing
snapshot used at the time of the call is stored on every ``AgentRun``
so an audit a year from now can replay the math against today's rates.

Tests patch this module's ``dispatch`` (or ``current_config``) so the real
network is never touched from the test suite. We never log the API key.
"""
from __future__ import annotations

import time
from typing import Any

from apps._ai_config import AIConfig

from .base import AdapterResult, AdapterStatus, skipped_result
from .pricing import build_pricing_snapshot, calculate_openai_cost


def _resolve_model(config: AIConfig) -> str:
    from django.conf import settings

    return (
        config.model
        or getattr(settings, "OPENAI_FALLBACK_MODEL", "")
        or "gpt-5.1"
    )


def build_request_kwargs(
    *,
    messages: list[dict[str, str]],
    model: str,
    config: AIConfig,
) -> dict[str, Any]:
    """Phase 5E-Smoke-Fix-2 — assemble the kwargs for
    ``client.chat.completions.create(...)``.

    Modern OpenAI Chat Completions models (gpt-4o, gpt-5, o1, o3, …)
    REJECT the legacy ``max_tokens`` parameter and require
    ``max_completion_tokens``. We always use ``max_completion_tokens``;
    callers running deprecated gpt-3.5 / gpt-4-original models can swap
    via env or move to a supported model.

    Never sends both ``max_tokens`` and ``max_completion_tokens`` —
    OpenAI rejects the combination.
    """
    return {
        "model": model,
        "messages": list(messages),
        "temperature": config.temperature,
        "max_completion_tokens": int(config.max_tokens or 0) or None,
    }


def dispatch(messages: list[dict[str, str]], *, config: AIConfig) -> AdapterResult:
    """Send ``messages`` to OpenAI and return the normalised result.

    Returns ``skipped`` when the provider is disabled or the key is empty.
    Returns ``failed`` (with ``error_message``) on any SDK exception so the
    AgentRun row captures the error without crashing the request.
    """
    if config.provider != "openai" or not config.enabled:
        return skipped_result(
            provider="openai",
            reason="provider disabled or OPENAI_API_KEY not configured",
        )

    model = _resolve_model(config)

    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model=model,
            error_message=f"openai SDK not installed: {exc}",
            pricing_snapshot=build_pricing_snapshot(
                provider="openai", model=model, table=None
            ),
        )

    client_kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": float(config.timeout_seconds),
    }
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    org_id = (config.extra or {}).get("org_id", "")
    if org_id:
        client_kwargs["organization"] = org_id

    started = time.monotonic()
    request_kwargs = build_request_kwargs(
        messages=messages, model=model, config=config
    )
    # Drop None-valued keys so OpenAI doesn't reject explicit nulls.
    request_kwargs = {k: v for k, v in request_kwargs.items() if v is not None}
    try:
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(  # pragma: no cover
            **request_kwargs,
        )
    except Exception as exc:  # pragma: no cover - real-network path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
            pricing_snapshot=build_pricing_snapshot(
                provider="openai", model=model, table=None
            ),
        )

    latency_ms = int((time.monotonic() - started) * 1000)  # pragma: no cover
    choice = response.choices[0]  # pragma: no cover
    usage = getattr(response, "usage", None)  # pragma: no cover
    raw_usage = (  # pragma: no cover
        usage.__dict__
        if usage is not None and hasattr(usage, "__dict__")
        else dict(usage or {})
    )
    prompt_tokens = int(  # pragma: no cover
        raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens") or 0
    )
    completion_tokens = int(  # pragma: no cover
        raw_usage.get("completion_tokens") or raw_usage.get("output_tokens") or 0
    )
    total_tokens = int(  # pragma: no cover
        raw_usage.get("total_tokens")
        or (prompt_tokens + completion_tokens)
        or 0
    )
    # Cached input tokens land under ``prompt_tokens_details.cached_tokens``
    # in current OpenAI responses.
    details = raw_usage.get("prompt_tokens_details") or {}  # pragma: no cover
    cached_input = int(  # pragma: no cover
        details.get("cached_tokens") if isinstance(details, dict) else 0
    ) or 0

    cost_usd, snapshot = calculate_openai_cost(  # pragma: no cover
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_input_tokens=cached_input,
    )

    return AdapterResult(  # pragma: no cover
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model=getattr(response, "model", model),
        output={
            "text": choice.message.content or "",
            "finish_reason": choice.finish_reason,
        },
        raw={
            "id": getattr(response, "id", ""),
        },
        raw_usage=raw_usage,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=float(cost_usd) if cost_usd is not None else None,
        pricing_snapshot=snapshot,
    )


__all__ = ("build_request_kwargs", "dispatch")
