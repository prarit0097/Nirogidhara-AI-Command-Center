"""OpenAI Chat Completions adapter — Phase 3A.

Lazy SDK import: ``openai`` is NEVER imported until ``dispatch`` actually
runs in test/live mode. The disabled / no-key path short-circuits with
``skipped_result`` so dev runs and CI do not need the package installed.

Tests patch this module's ``dispatch`` (or ``current_config``) so the real
network is never touched from the test suite. We never log the API key.
"""
from __future__ import annotations

import time
from typing import Any

from apps._ai_config import AIConfig

from .base import AdapterResult, AdapterStatus, skipped_result


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

    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model=config.model,
            error_message=f"openai SDK not installed: {exc}",
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
    try:
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(  # pragma: no cover
            model=config.model or "gpt-4o-mini",
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    except Exception as exc:  # pragma: no cover - real-network path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model=config.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )

    latency_ms = int((time.monotonic() - started) * 1000)  # pragma: no cover
    choice = response.choices[0]  # pragma: no cover
    return AdapterResult(  # pragma: no cover
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model=getattr(response, "model", config.model),
        output={
            "text": choice.message.content or "",
            "finish_reason": choice.finish_reason,
        },
        raw={
            "id": getattr(response, "id", ""),
            "usage": getattr(response, "usage", {}).__dict__
            if getattr(response, "usage", None)
            else {},
        },
        latency_ms=latency_ms,
    )


__all__ = ("dispatch",)
