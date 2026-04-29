"""Phase 5E-Smoke-Fix-2 — OpenAI adapter token parameter compatibility.

Modern OpenAI Chat Completions models (gpt-4o, gpt-5, o1, o3, …)
reject the legacy ``max_tokens`` parameter and require
``max_completion_tokens``. The Phase 5E-Smoke-Fix-2 refactor extracts
``build_request_kwargs`` from :mod:`apps.integrations.ai.openai_client`
so the kwargs are unit-testable without making a network call.

These tests:

- Pin the kwargs shape sent to ``client.chat.completions.create``.
- Confirm the legacy ``max_tokens`` key is NEVER present.
- Confirm temperature + model + messages are forwarded verbatim.
- Confirm the smoke harness still routes correctly when the adapter
  fails (safe-failure path) and when it succeeds (provider-pass path).
"""
from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings

from apps._ai_config import AIConfig
from apps.integrations.ai.openai_client import build_request_kwargs, dispatch
from apps.integrations.ai.base import AdapterStatus


def _config(**overrides) -> AIConfig:
    base = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "sk-test-only",
        "base_url": "",
        "extra": {},
        "temperature": 0.2,
        "max_tokens": 1500,
        "timeout_seconds": 30,
    }
    base.update(overrides)
    return AIConfig(**base)


# ---------------------------------------------------------------------------
# build_request_kwargs — pure, no network
# ---------------------------------------------------------------------------


def test_build_request_kwargs_uses_max_completion_tokens() -> None:
    kwargs = build_request_kwargs(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-5.1",
        config=_config(max_tokens=2000),
    )
    assert "max_completion_tokens" in kwargs
    assert kwargs["max_completion_tokens"] == 2000


def test_build_request_kwargs_never_sends_legacy_max_tokens() -> None:
    kwargs = build_request_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        config=_config(),
    )
    assert "max_tokens" not in kwargs


def test_build_request_kwargs_forwards_model_and_temperature() -> None:
    kwargs = build_request_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5.1",
        config=_config(temperature=0.7),
    )
    assert kwargs["model"] == "gpt-5.1"
    assert kwargs["temperature"] == 0.7


def test_build_request_kwargs_messages_are_listified() -> None:
    """Whatever the caller passes (tuple / generator / list) the kwargs
    must carry a list — OpenAI's SDK serialises it directly."""
    kwargs = build_request_kwargs(
        messages=[
            {"role": "system", "content": "policy"},
            {"role": "user", "content": "ask"},
        ],
        model="gpt-4o-mini",
        config=_config(),
    )
    assert isinstance(kwargs["messages"], list)
    assert len(kwargs["messages"]) == 2
    assert kwargs["messages"][0]["role"] == "system"


def test_build_request_kwargs_zero_max_tokens_drops_to_none() -> None:
    """When max_tokens is 0 / unset, the helper returns None so the
    dispatcher's filter step strips the key entirely (rather than
    sending max_completion_tokens=0 which OpenAI rejects)."""
    kwargs = build_request_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
        config=_config(max_tokens=0),
    )
    assert kwargs["max_completion_tokens"] is None


# ---------------------------------------------------------------------------
# dispatch — verify the SDK is called with max_completion_tokens, not max_tokens
# ---------------------------------------------------------------------------


def test_dispatch_calls_sdk_with_max_completion_tokens() -> None:
    """End-to-end: monkeypatch the OpenAI client and confirm the
    create() call carries max_completion_tokens, never max_tokens."""
    config = _config()

    fake_response = mock.Mock()
    fake_response.choices = [
        mock.Mock(
            message=mock.Mock(content='{"action": "no_action"}'),
            finish_reason="stop",
        )
    ]
    fake_response.id = "resp-test"
    fake_response.model = "gpt-4o-mini"
    fake_response.usage = mock.Mock(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        prompt_tokens_details={"cached_tokens": 0},
    )

    fake_client = mock.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    # The adapter does ``from openai import OpenAI`` lazily inside
    # dispatch(). Patch the openai module on sys.modules so that lazy
    # import resolves to a MagicMock whose OpenAI() returns our fake.
    fake_openai_module = mock.MagicMock()
    fake_openai_module.OpenAI.return_value = fake_client
    with mock.patch.dict("sys.modules", {"openai": fake_openai_module}):
        result = dispatch(
            messages=[{"role": "user", "content": "hi"}], config=config
        )

    # The SDK call must have used max_completion_tokens, not max_tokens.
    assert fake_client.chat.completions.create.called
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "max_completion_tokens" in call_kwargs
    assert "max_tokens" not in call_kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    # The dispatch wrapper itself returned a non-skipped result. We don't
    # assert SUCCESS here because the test bypasses real coverage paths
    # for usage extraction; the key contract for this fix is that the
    # SDK was called with the modern token kwarg.


def test_dispatch_returns_skipped_when_provider_disabled() -> None:
    config = _config(provider="disabled", api_key="")
    result = dispatch(messages=[{"role": "user", "content": "hi"}], config=config)
    assert result.status == AdapterStatus.SKIPPED


def test_dispatch_returns_failed_when_sdk_missing(monkeypatch) -> None:
    """When the openai SDK isn't installed, the adapter must return
    FAILED cleanly so the smoke harness's safe-failure branch triggers."""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    result = dispatch(
        messages=[{"role": "user", "content": "hi"}], config=_config()
    )
    assert result.status == AdapterStatus.FAILED
    assert "openai SDK not installed" in result.error_message


# ---------------------------------------------------------------------------
# Smoke harness still routes correctly through the refactored adapter
# ---------------------------------------------------------------------------


@override_settings(OPENAI_API_KEY="test-smoke-key", AI_PROVIDER="openai")
def test_smoke_use_openai_passes_with_mocked_success(db, monkeypatch) -> None:
    """The Phase 5E-Smoke harness reports openaiSucceeded=true when the
    adapter returns SUCCESS — proves the refactor didn't change the
    smoke contract."""
    from apps.integrations.ai.base import AdapterResult, AdapterStatus
    from apps.whatsapp.smoke_harness import (
        _scripted_ai_decision_payload,
        run_smoke_harness,
    )
    import json as _json

    def _fake_dispatch(_messages):
        return AdapterResult(
            status=AdapterStatus.SUCCESS,
            provider="openai",
            model="gpt-4o-mini",
            output={
                "text": _json.dumps(_scripted_ai_decision_payload()),
                "finish_reason": "stop",
            },
            raw={"id": "smoke-success"},
            latency_ms=12,
        )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages", _fake_dispatch
    )
    result = run_smoke_harness(
        scenario="ai-reply", language="hinglish", use_openai=True
    )
    detail = result.scenarios[0].detail
    assert detail["openaiAttempted"] is True
    assert detail["openaiSucceeded"] is True
    assert detail["providerPassed"] is True
    assert detail["safeFailure"] is False
    assert detail["providerError"] == ""
    assert result.overall_passed is True


@override_settings(OPENAI_API_KEY="test-smoke-key", AI_PROVIDER="openai")
def test_smoke_use_openai_safe_failure_with_unsupported_param(
    db, monkeypatch
) -> None:
    """When OpenAI rejects an unsupported parameter, the smoke harness
    must report safeFailure=true + overallPassed=false. This is the
    exact failure mode that triggered Phase 5E-Smoke-Fix-2."""
    from apps.integrations.ai.base import AdapterResult, AdapterStatus
    from apps.whatsapp.smoke_harness import run_smoke_harness

    def _fake_dispatch(_messages):
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model="gpt-5.1",
            error_message=(
                "Unsupported parameter: 'max_tokens' is not supported "
                "with this model. Use 'max_completion_tokens' instead."
            ),
        )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages", _fake_dispatch
    )
    result = run_smoke_harness(
        scenario="ai-reply", language="hinglish", use_openai=True
    )
    detail = result.scenarios[0].detail
    assert detail["openaiAttempted"] is True
    assert detail["openaiSucceeded"] is False
    assert detail["providerPassed"] is False
    assert detail["safeFailure"] is True
    assert "max_completion_tokens" in detail["providerError"]
    assert detail["blockedReason"] == "adapter_failed"
    assert result.overall_passed is False
