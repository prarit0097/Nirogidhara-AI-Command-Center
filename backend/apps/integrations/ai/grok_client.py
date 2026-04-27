"""xAI Grok adapter — Phase 3A.

Grok exposes an OpenAI-compatible chat-completions API at
``https://api.x.ai/v1``. We re-use the ``openai`` SDK (lazy import) pointed
at xAI's base URL so we don't ship a second client. Disabled / no-key path
returns ``skipped_result`` without any network access.

Tests patch this module's ``dispatch`` so the real Grok API is never called
from the suite. We never log the API key.
"""
from __future__ import annotations

import time
from typing import Any

from apps._ai_config import AIConfig

from .base import AdapterResult, AdapterStatus, skipped_result


_DEFAULT_BASE_URL = "https://api.x.ai/v1"


def dispatch(messages: list[dict[str, str]], *, config: AIConfig) -> AdapterResult:
    if config.provider != "grok" or not config.enabled:
        return skipped_result(
            provider="grok",
            reason="provider disabled or GROK_API_KEY not configured",
        )

    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="grok",
            model=config.model,
            error_message=f"openai SDK not installed (Grok uses the OpenAI client): {exc}",
        )

    client_kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "base_url": config.base_url or _DEFAULT_BASE_URL,
        "timeout": float(config.timeout_seconds),
    }

    started = time.monotonic()
    try:
        client = OpenAI(**client_kwargs)  # pragma: no cover
        response = client.chat.completions.create(  # pragma: no cover
            model=config.model or "grok-2-latest",
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    except Exception as exc:  # pragma: no cover - real-network path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="grok",
            model=config.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )

    latency_ms = int((time.monotonic() - started) * 1000)  # pragma: no cover
    choice = response.choices[0]  # pragma: no cover
    return AdapterResult(  # pragma: no cover
        status=AdapterStatus.SUCCESS,
        provider="grok",
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
