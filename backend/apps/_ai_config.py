"""AI provider configuration helpers — Phase 3+ scaffolding.

This module is the single seam Phase 3 LLM adapters will use to read which
provider is enabled, what model to call, and which key to authenticate with.

No SDK calls happen here. No ``openai``/``anthropic``/``xai_sdk`` import lives
in this file. Adapters land later in ``apps/integrations/ai/<provider>.py``
following the same pattern as ``apps/payments/integrations/razorpay_client.py``.

COMPLIANCE HARD STOP (Master Blueprint §26 #4):
    AI must speak ONLY from ``apps.compliance.Claim`` (Approved Claim Vault).
    Every prompt MUST be assembled with the relevant Claim entries injected
    before any provider call. CAIO Agent never executes business actions —
    it monitors / audits / suggests only.

Today ``current_config().enabled`` is ``False`` by default (provider=disabled
or empty key) so no agent in the codebase will dispatch an LLM call. Tests
patch ``current_config`` to inject mock providers.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

# Supported providers — keep in sync with .env.example documentation.
SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"disabled", "openai", "anthropic", "grok"})


@dataclass(frozen=True)
class AIConfig:
    """Resolved AI configuration for a single provider.

    ``enabled`` is True only when the provider is non-disabled AND a key was
    configured. Adapters should refuse to dispatch when ``enabled`` is False.
    """

    provider: str
    model: str
    api_key: str
    base_url: str
    extra: dict[str, str]
    temperature: float
    max_tokens: int
    timeout_seconds: int

    @property
    def enabled(self) -> bool:
        return self.provider != "disabled" and bool(self.api_key)


def current_config() -> AIConfig:
    """Read live settings and return the resolved AI config.

    Reads only the per-provider key matching ``settings.AI_PROVIDER``. Returns
    an ``AIConfig`` with ``enabled=False`` when the provider is disabled or
    when no key is configured.
    """
    provider = (getattr(settings, "AI_PROVIDER", "disabled") or "disabled").lower()
    if provider not in SUPPORTED_PROVIDERS:
        provider = "disabled"

    api_key = ""
    base_url = ""
    extra: dict[str, str] = {}

    if provider == "openai":
        api_key = settings.OPENAI_API_KEY
        base_url = settings.OPENAI_BASE_URL
        if settings.OPENAI_ORG_ID:
            extra["org_id"] = settings.OPENAI_ORG_ID
    elif provider == "anthropic":
        api_key = settings.ANTHROPIC_API_KEY
        base_url = settings.ANTHROPIC_BASE_URL
    elif provider == "grok":
        api_key = settings.GROK_API_KEY
        base_url = settings.GROK_BASE_URL

    return AIConfig(
        provider=provider,
        model=getattr(settings, "AI_MODEL", "") or "",
        api_key=api_key,
        base_url=base_url,
        extra=extra,
        temperature=getattr(settings, "AI_TEMPERATURE", 0.2),
        max_tokens=getattr(settings, "AI_MAX_TOKENS", 2000),
        timeout_seconds=getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 30),
    )


__all__ = ("AIConfig", "SUPPORTED_PROVIDERS", "current_config")
