"""Phase 3 scaffolding tests — confirms the AI provider config is read
correctly from Django settings and that the ``disabled`` default really
short-circuits.

No SDK is installed or imported here. These tests must stay green even
when ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` / ``GROK_API_KEY`` are
empty (the dev / CI default).
"""
from __future__ import annotations

import pytest

from apps._ai_config import SUPPORTED_PROVIDERS, current_config


def test_default_provider_is_disabled(settings) -> None:
    settings.AI_PROVIDER = "disabled"
    settings.OPENAI_API_KEY = ""
    cfg = current_config()
    assert cfg.provider == "disabled"
    assert cfg.enabled is False


def test_unknown_provider_falls_back_to_disabled(settings) -> None:
    settings.AI_PROVIDER = "totally-not-a-provider"
    cfg = current_config()
    assert cfg.provider == "disabled"
    assert cfg.enabled is False


def test_openai_enabled_when_key_present(settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test-key"
    settings.AI_MODEL = "gpt-4o-mini"
    cfg = current_config()
    assert cfg.provider == "openai"
    assert cfg.enabled is True
    assert cfg.api_key == "sk-test-key"
    assert cfg.model == "gpt-4o-mini"


def test_anthropic_routing(settings) -> None:
    settings.AI_PROVIDER = "anthropic"
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.OPENAI_API_KEY = "should-not-leak"
    cfg = current_config()
    assert cfg.provider == "anthropic"
    assert cfg.enabled is True
    assert cfg.api_key == "sk-ant-test"
    # OpenAI key never leaks into the resolved config when Anthropic is selected.
    assert "should-not-leak" not in cfg.api_key
    assert "should-not-leak" not in cfg.base_url
    assert "should-not-leak" not in str(cfg.extra)


def test_grok_routing(settings) -> None:
    settings.AI_PROVIDER = "grok"
    settings.GROK_API_KEY = "xai-test"
    settings.GROK_BASE_URL = "https://api.x.ai/v1"
    cfg = current_config()
    assert cfg.provider == "grok"
    assert cfg.enabled is True
    assert cfg.api_key == "xai-test"
    assert cfg.base_url == "https://api.x.ai/v1"


def test_provider_with_empty_key_stays_disabled(settings) -> None:
    """Even if AI_PROVIDER=openai, a missing key must keep enabled=False."""
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = ""
    cfg = current_config()
    assert cfg.provider == "openai"
    assert cfg.enabled is False


def test_supported_providers_set() -> None:
    assert {"disabled", "openai", "anthropic", "grok"} == set(SUPPORTED_PROVIDERS)
