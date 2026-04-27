"""Provider-agnostic interface for Phase 3 LLM adapters.

Each adapter under ``apps/integrations/ai/<provider>_client.py`` implements
``dispatch(messages, *, config) -> AdapterResult`` so the agent service can
swap providers via ``settings.AI_PROVIDER`` (and the Phase 3C fallback
chain ``settings.AI_PROVIDER_FALLBACKS``) without touching call sites.

Compliance hard stop (Master Blueprint §26 #4):
    The base interface is provider-agnostic and never injects medical text.
    Callers MUST hand it messages already enriched with the relevant
    ``apps.compliance.Claim`` entries via ``apps/ai_governance/prompting.py``.
    CAIO never executes business actions; nothing in this module routes
    through CAIO write paths.

Today no adapter dispatches a real call when ``config.enabled`` is False —
that's the disabled / no-key default and it returns ``status="skipped"``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apps._ai_config import AIConfig


class AdapterStatus:
    """String constants matching ``AgentRun.Status`` for cross-module use."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AdapterResult:
    """Normalised result every adapter returns.

    Phase 3C extends this with per-call token usage and cost tracking. The
    fields are nullable so adapters that haven't (or can't) populate them
    don't break callers — services that persist into ``AgentRun`` skip
    fields that come back as ``None``.
    """

    status: str
    provider: str
    model: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    raw_usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    pricing_snapshot: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""


class Adapter(Protocol):
    """Every concrete adapter implements this single method."""

    def dispatch(
        self, messages: list[dict[str, str]], *, config: AIConfig
    ) -> AdapterResult:  # pragma: no cover - structural typing
        ...


def skipped_result(*, provider: str, reason: str) -> AdapterResult:
    """Helper to short-circuit when the provider is disabled or unconfigured."""
    return AdapterResult(
        status=AdapterStatus.SKIPPED,
        provider=provider,
        output={},
        raw={"reason": reason},
        error_message=reason,
    )


__all__ = ("Adapter", "AdapterResult", "AdapterStatus", "skipped_result")
