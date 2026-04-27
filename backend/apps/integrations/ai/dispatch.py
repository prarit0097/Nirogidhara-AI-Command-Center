"""Provider routing + Phase 3C fallback chain.

``dispatch_messages`` walks ``settings.AI_PROVIDER_FALLBACKS`` left → right
and returns the first adapter result with ``status == success``. Every
attempt — successful, failed, or skipped — is recorded on the result so
the agent service can persist a full attempt log on the ``AgentRun`` row.

Compliance hard stop (Master Blueprint §26 #4):
    The dispatcher does not run when ``AI_PROVIDER == "disabled"``: every
    call short-circuits with a single ``skipped`` attempt. ``ClaimVaultMissing``
    is raised earlier in the prompt builder (in
    ``apps.ai_governance.prompting``) and the services layer fails the run
    before this dispatcher is even called — fallback NEVER triggers for a
    compliance refusal.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

from apps._ai_config import AIConfig, config_for_provider, current_config

from . import anthropic_client, grok_client, openai_client
from .base import AdapterResult, AdapterStatus, skipped_result


def _adapter_for(provider: str):
    """Return the adapter ``dispatch`` callable for ``provider``.

    Resolved at call time (not import time) so ``mock.patch`` of
    ``apps.integrations.ai.<provider>_client.dispatch`` propagates to the
    test suite without any extra plumbing.
    """
    if provider == "openai":
        return openai_client.dispatch
    if provider == "anthropic":
        return anthropic_client.dispatch
    if provider == "grok":
        return grok_client.dispatch
    return None


def _resolve_chain() -> list[str]:
    """Build the ordered list of providers we will attempt.

    The Phase 3C contract:
    - ``AI_PROVIDER == "disabled"`` → empty chain → ``skipped`` short-circuit.
    - ``AI_PROVIDER_FALLBACKS`` non-empty → use it verbatim (deduped, lower-cased).
    - Otherwise → single-provider chain made of just ``AI_PROVIDER`` (this
      preserves the Phase 3A/3B test fixtures that set just ``AI_PROVIDER``).
    """
    provider = (
        getattr(settings, "AI_PROVIDER", "disabled") or "disabled"
    ).lower()
    if provider == "disabled":
        return []

    raw_chain = getattr(settings, "AI_PROVIDER_FALLBACKS", []) or []
    chain: list[str] = []
    for item in raw_chain:
        name = (item or "").strip().lower()
        if name and name != "disabled" and name not in chain:
            chain.append(name)

    if not chain:
        chain = [provider]
    return chain


def _attempt_record(
    *,
    config: AIConfig,
    result: AdapterResult,
) -> dict[str, Any]:
    return {
        "provider": config.provider,
        "model": result.model or config.model,
        "status": result.status,
        "error": result.error_message,
        "latency_ms": result.latency_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "cost_usd": result.cost_usd,
    }


def dispatch_messages(messages: list[dict[str, str]]) -> AdapterResult:
    """Route ``messages`` through the configured fallback chain.

    Phase 3C semantics:
    - Walk the chain left → right.
    - Return the FIRST attempt whose ``status == success``.
    - When multiple attempts are made and a non-first one succeeds, set
      ``fallback_used = True`` on the result via ``provider_attempts``.
    - If every attempt fails / skips, return the LAST attempt's result so
      the caller sees the most recent error message — but with the FULL
      attempt log so the audit row captures what we tried.
    - When the chain is empty (``AI_PROVIDER=disabled``) return a single
      ``skipped`` result — no attempts are recorded as "tried".
    """
    chain = _resolve_chain()
    if not chain:
        result = skipped_result(
            provider="disabled",
            reason="AI provider disabled via settings.AI_PROVIDER",
        )
        # Carry the empty attempt list explicitly for transparency.
        return AdapterResult(
            status=result.status,
            provider=result.provider,
            model=result.model,
            output=result.output,
            raw=result.raw,
            raw_usage=result.raw_usage,
            error_message=result.error_message,
            pricing_snapshot=result.pricing_snapshot,
        )

    attempts: list[dict[str, Any]] = []
    last_failed: AdapterResult | None = None

    for index, provider_name in enumerate(chain):
        config = config_for_provider(provider_name)
        adapter = _adapter_for(provider_name)

        if adapter is None:
            attempts.append(
                {
                    "provider": provider_name,
                    "model": config.model,
                    "status": AdapterStatus.SKIPPED,
                    "error": f"unsupported provider: {provider_name!r}",
                    "latency_ms": 0,
                }
            )
            continue

        if not config.enabled:
            attempts.append(
                {
                    "provider": provider_name,
                    "model": config.model,
                    "status": AdapterStatus.SKIPPED,
                    "error": f"{provider_name} disabled or no API key",
                    "latency_ms": 0,
                }
            )
            continue

        result = adapter(messages, config=config)
        attempts.append(_attempt_record(config=config, result=result))

        if result.status == AdapterStatus.SUCCESS:
            fallback_used = index > 0 or any(
                a["status"] != AdapterStatus.SUCCESS for a in attempts[:-1]
            )
            return _result_with(
                base=result,
                provider_attempts=attempts,
                fallback_used=fallback_used,
            )

        if result.status == AdapterStatus.FAILED:
            last_failed = result
            # Continue to next provider in the chain.
            continue

        # SKIPPED — also try the next provider.

    # All providers exhausted. Return the most recent FAILED if we have
    # one, otherwise a SKIPPED reflecting the final state of the chain.
    if last_failed is not None:
        return _result_with(
            base=last_failed,
            provider_attempts=attempts,
            fallback_used=False,
        )

    skip_reason = "all providers in fallback chain are disabled or unconfigured"
    base = skipped_result(provider="disabled", reason=skip_reason)
    return _result_with(
        base=base, provider_attempts=attempts, fallback_used=False
    )


def _result_with(
    *,
    base: AdapterResult,
    provider_attempts: list[dict[str, Any]],
    fallback_used: bool,
) -> AdapterResult:
    """Return a copy of ``base`` with the provider-attempts metadata stamped on.

    AdapterResult is a frozen dataclass so we can't mutate it; building a
    new one keeps the immutability guarantee while letting the dispatcher
    forward the attempt log without changing the adapter contract.
    """
    raw = dict(base.raw or {})
    raw["provider_attempts"] = provider_attempts
    raw["fallback_used"] = fallback_used
    return AdapterResult(
        status=base.status,
        provider=base.provider,
        model=base.model,
        output=base.output,
        raw=raw,
        raw_usage=base.raw_usage,
        latency_ms=base.latency_ms,
        prompt_tokens=base.prompt_tokens,
        completion_tokens=base.completion_tokens,
        total_tokens=base.total_tokens,
        cost_usd=base.cost_usd,
        pricing_snapshot=base.pricing_snapshot,
        error_message=base.error_message,
    )


__all__ = ("dispatch_messages",)
