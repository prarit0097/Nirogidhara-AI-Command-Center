"""Provider routing — single seam for the agent service.

``dispatch_messages`` looks at ``apps._ai_config.current_config()`` and
sends the message list to the right adapter (``openai_client``,
``anthropic_client``, ``grok_client``) or short-circuits with a
``skipped`` result when the provider is disabled.

Centralising routing here keeps the agent service free of provider-specific
imports and gives tests a single patch point.
"""
from __future__ import annotations

from apps._ai_config import current_config

from . import anthropic_client, grok_client, openai_client
from .base import AdapterResult, skipped_result


def dispatch_messages(messages: list[dict[str, str]]) -> AdapterResult:
    """Route ``messages`` to the configured adapter and return its result."""
    config = current_config()
    if not config.enabled:
        return skipped_result(
            provider=config.provider,
            reason="AI provider disabled or no API key configured",
        )
    if config.provider == "openai":
        return openai_client.dispatch(messages, config=config)
    if config.provider == "anthropic":
        return anthropic_client.dispatch(messages, config=config)
    if config.provider == "grok":
        return grok_client.dispatch(messages, config=config)
    return skipped_result(
        provider=config.provider,
        reason=f"unsupported provider: {config.provider!r}",
    )


__all__ = ("dispatch_messages",)
