"""Provider-agnostic interface for Phase 3 LLM adapters.

Each adapter under ``apps/integrations/ai/<provider>_client.py`` implements
``dispatch(messages, *, config) -> AdapterResult`` so the agent service can
swap providers via ``settings.AI_PROVIDER`` without touching call sites.

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

    ``status`` is one of ``success``/``failed``/``skipped``. ``output`` is the
    structured payload Phase 3 service code persists into
    ``AgentRun.output_payload``. ``raw`` carries any provider-specific
    metadata (token usage, finish reason) that audit can replay later.
    """

    status: str
    provider: str
    model: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    cost_usd: float | None = None
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
