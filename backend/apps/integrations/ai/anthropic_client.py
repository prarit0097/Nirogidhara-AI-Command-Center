"""Anthropic Messages adapter — Phase 3A.

Lazy SDK import: ``anthropic`` is never imported until ``dispatch`` runs in
test/live mode. Disabled / no-key path returns ``skipped_result`` without
network access.

Tests patch this module's ``dispatch`` so the real Anthropic API is never
called from the suite. We never log the API key.
"""
from __future__ import annotations

import time
from typing import Any

from apps._ai_config import AIConfig

from .base import AdapterResult, AdapterStatus, skipped_result


def dispatch(messages: list[dict[str, str]], *, config: AIConfig) -> AdapterResult:
    if config.provider != "anthropic" or not config.enabled:
        return skipped_result(
            provider="anthropic",
            reason="provider disabled or ANTHROPIC_API_KEY not configured",
        )

    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="anthropic",
            model=config.model,
            error_message=f"anthropic SDK not installed: {exc}",
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
            model=config.model or "claude-3-5-sonnet-latest",
            messages=chat_messages,
            system=system_text or None,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    except Exception as exc:  # pragma: no cover - real-network path
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="anthropic",
            model=config.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )

    latency_ms = int((time.monotonic() - started) * 1000)  # pragma: no cover
    text = ""  # pragma: no cover
    for block in getattr(response, "content", []):  # pragma: no cover
        if getattr(block, "type", "") == "text":
            text += getattr(block, "text", "")

    return AdapterResult(  # pragma: no cover
        status=AdapterStatus.SUCCESS,
        provider="anthropic",
        model=getattr(response, "model", config.model),
        output={
            "text": text,
            "finish_reason": getattr(response, "stop_reason", ""),
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
