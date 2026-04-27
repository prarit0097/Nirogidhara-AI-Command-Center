"""Model-wise USD pricing for the LLM adapters.

Prices are quoted **per 1,000,000 tokens** in USD. Source: the published
pricing pages for OpenAI (https://openai.com/api/pricing/) and Anthropic
(https://www.anthropic.com/pricing). The numbers below are the figures we
froze at the start of Phase 3C; they MUST be reviewed periodically and
updated whenever the provider publishes new prices.

When a model isn't in the table, ``calculate_*_cost`` returns ``None`` for
the cost — the AgentRun row will store the token usage anyway so audit can
backfill the price after the fact.

Compliance note: pricing is intentionally **not** secret. The frontend
Scheduler Status page surfaces ``cost_usd`` per run so the operator can
see what the AI spent. API keys still live server-side only — pricing
metadata does not leak credentials.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# ----- OpenAI pricing — per 1M tokens (USD) -----
# input         = standard prompt tokens
# cached_input  = tokens served from OpenAI's prompt-cache (much cheaper)
# output        = completion tokens
OPENAI_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.1": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.40},
    "gpt-4.1": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
}

# ----- Anthropic pricing — per 1M tokens (USD) -----
# input            = standard prompt tokens
# cache_write_5m   = prompt-caching write (5-minute TTL)
# cache_read       = prompt-caching read
# output           = completion tokens
ANTHROPIC_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cache_write_5m": 3.75,
        "cache_read": 0.30,
        "output": 15.00,
    },
    "claude-sonnet-4-5": {
        "input": 3.00,
        "cache_write_5m": 3.75,
        "cache_read": 0.30,
        "output": 15.00,
    },
    "claude-opus-4-6": {
        "input": 5.00,
        "cache_write_5m": 6.25,
        "cache_read": 0.50,
        "output": 25.00,
    },
    "claude-opus-4-5": {
        "input": 5.00,
        "cache_write_5m": 6.25,
        "cache_read": 0.50,
        "output": 25.00,
    },
}


_PER_MILLION = Decimal("1000000")


def _quantize(value: Decimal) -> Decimal:
    """Round to 6 decimal places for the AgentRun.cost_usd Decimal column."""
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def get_pricing(provider: str, model: str) -> dict[str, float] | None:
    """Return the per-1M pricing dict for ``provider``+``model``, or None."""
    if not provider or not model:
        return None
    if provider == "openai":
        return OPENAI_PRICING.get(model)
    if provider == "anthropic":
        return ANTHROPIC_PRICING.get(model)
    return None


def build_pricing_snapshot(
    *,
    provider: str,
    model: str,
    table: dict[str, float] | None,
) -> dict[str, Any]:
    """Snapshot stored on every AgentRun so future audit can replay costs."""
    return {
        "provider": provider,
        "model": model,
        "unit": "per_1M_tokens",
        "currency": "USD",
        "rates": dict(table or {}),
        "source": "frozen Phase 3C — review periodically",
    }


def calculate_openai_cost(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_input_tokens: int = 0,
) -> tuple[Decimal | None, dict[str, Any]]:
    """Return ``(cost_usd, pricing_snapshot)`` for an OpenAI call.

    ``cached_input_tokens`` is the subset of prompt tokens served from the
    prompt cache. ``prompt_tokens`` is the *total* — non-cached and cached
    combined — exactly as OpenAI reports it. We charge the non-cached
    portion at ``input`` and the cached portion at ``cached_input``.
    """
    table = get_pricing("openai", model)
    snapshot = build_pricing_snapshot(provider="openai", model=model, table=table)
    if table is None:
        return None, snapshot

    cached = max(0, int(cached_input_tokens or 0))
    non_cached = max(0, int(prompt_tokens or 0) - cached)
    output = max(0, int(completion_tokens or 0))

    cost = (
        _to_decimal(table.get("input", 0)) * Decimal(non_cached)
        + _to_decimal(table.get("cached_input", 0)) * Decimal(cached)
        + _to_decimal(table.get("output", 0)) * Decimal(output)
    ) / _PER_MILLION
    return _quantize(cost), snapshot


def calculate_anthropic_cost(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> tuple[Decimal | None, dict[str, Any]]:
    """Return ``(cost_usd, pricing_snapshot)`` for an Anthropic call.

    Anthropic reports cache creation + read tokens **separately** from the
    standard ``input_tokens``. We charge each at its own rate. ``input_tokens``
    is the non-cached prompt portion as Anthropic returns it.
    """
    table = get_pricing("anthropic", model)
    snapshot = build_pricing_snapshot(provider="anthropic", model=model, table=table)
    if table is None:
        return None, snapshot

    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    cache_w = max(0, int(cache_creation_tokens or 0))
    cache_r = max(0, int(cache_read_tokens or 0))

    cost = (
        _to_decimal(table.get("input", 0)) * Decimal(inp)
        + _to_decimal(table.get("cache_write_5m", 0)) * Decimal(cache_w)
        + _to_decimal(table.get("cache_read", 0)) * Decimal(cache_r)
        + _to_decimal(table.get("output", 0)) * Decimal(out)
    ) / _PER_MILLION
    return _quantize(cost), snapshot


__all__ = (
    "ANTHROPIC_PRICING",
    "OPENAI_PRICING",
    "build_pricing_snapshot",
    "calculate_anthropic_cost",
    "calculate_openai_cost",
    "get_pricing",
)
