"""Anthropic Messages adapter — Phase 3A + 3C cost tracking.

Lazy SDK import: ``anthropic`` is never imported until ``dispatch`` runs in
test/live mode. Disabled / no-key path returns ``skipped_result`` without
network access.

Phase 3C extends the result with model-wise token usage + cost via
``apps.integrations.ai.pricing.calculate_anthropic_cost``. Anthropic
reports cache-creation + cache-read tokens separately; we charge each at
its own rate from the pricing table.

Tests patch this module's ``dispatch`` so the real Anthropic API is never
called from the suite. We never log the API key.
"""
from __future__ import annotations

import time
from typing import Any

from apps._ai_config import AIConfig

from .base import AdapterResult, AdapterStatus, skipped_result
from .pricing import build_pricing_snapshot, calculate_anthropic_cost


def _resolve_model(config: AIConfig) -> str:
    from django.conf import settings

    return (
        config.model
        or getattr(settings, "ANTHROPIC_MODEL", "")
        or "claude-sonnet-4-6"
    )


def dispatch(messages: list[dict[str, str]], *, config: AIConfig) -> AdapterResult:
    if config.provider != "anthropic" or not config.enabled:
        return skipped_result(
            provider="anthropic",
            reason="provider disabled or ANTHROPIC_API_KEY not configured",
        )

    model = _resolve_model(config)

    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="anthropic",
            model=model,
            error_message=f"anthropic SDK not installed: {exc}",
            pricing_snapshot=build_pricing_snapshot(
                provider="anthropic", model=model, table=None
            ),
        )

    # Anthropic distinguishes between system + per-turn messages. Walk the
    # incoming list once and split them.
    system_text = ""
    chat_messages: list[dict[str, str]] = []
    for message in messages:
        if message.get("role") == "system":
            system_text = (system_text + "\n" + message.get("content", "")).strip()
        else:
            chat_messages.append(
                {
                    "role": message.get("role", "user"),
                    "content": message.get("content", ""),
                }
            )

    client_kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": float(config.timeout_seconds),
    }
    if config.base_url:
        client_kwargs["base_url"] = config.base_url

    started = time.monotonic()
    try:
        client = anthropic.Anthropic(**client_kwargs)  # pragma: no cover
        response = client.messages.create(  # pragma: no cover
            model=model,
            messages=chat_messages,
            system=system_text or None,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    except Exception as exc:  # pragma: no cover - real-network path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="anthropic",
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
            pricing_snapshot=build_pricing_snapshot(
                provider="anthropic", model=model, table=None
            ),
        )

    latency_ms = int((time.monotonic() - started) * 1000)  # pragma: no cover
    text = ""  # pragma: no cover
    for block in getattr(response, "content", []):  # pragma: no cover
        if getattr(block, "type", "") == "text":
            text += getattr(block, "text", "")

    usage = getattr(response, "usage", None)  # pragma: no cover
    raw_usage = (  # pragma: no cover
        usage.__dict__
        if usage is not None and hasattr(usage, "__dict__")
        else dict(usage or {})
    )
    input_tokens = int(raw_usage.get("input_tokens") or 0)  # pragma: no cover
    output_tokens = int(raw_usage.get("output_tokens") or 0)  # pragma: no cover
    cache_creation = int(  # pragma: no cover
        raw_usage.get("cache_creation_input_tokens") or 0
    )
    cache_read = int(  # pragma: no cover
        raw_usage.get("cache_read_input_tokens") or 0
    )
    total_tokens = input_tokens + output_tokens + cache_creation + cache_read  # pragma: no cover

    cost_usd, snapshot = calculate_anthropic_cost(  # pragma: no cover
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
    )

    return AdapterResult(  # pragma: no cover
        status=AdapterStatus.SUCCESS,
        provider="anthropic",
        model=getattr(response, "model", model),
        output={
            "text": text,
            "finish_reason": getattr(response, "stop_reason", ""),
        },
        raw={
            "id": getattr(response, "id", ""),
        },
        raw_usage=raw_usage,
        latency_ms=latency_ms,
        prompt_tokens=input_tokens + cache_creation + cache_read,
        completion_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=float(cost_usd) if cost_usd is not None else None,
        pricing_snapshot=snapshot,
    )


__all__ = ("dispatch",)
