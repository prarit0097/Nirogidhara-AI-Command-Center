from __future__ import annotations

from django.db import models


class RewardPenalty(models.Model):
    """Blueprint Section 10 — leaderboard rows for the Reward & Penalty engine.

    Phase 4B keeps this model as the agent-level **rollup** view (consumed by
    ``GET /api/rewards/``). The per-order scoring events live in
    :class:`RewardPenaltyEvent`. ``rebuild_agent_leaderboard`` aggregates
    events into rows here so the legacy endpoint stays compatible.
    """

    name = models.CharField(primary_key=True, max_length=120)
    reward = models.IntegerField(default=0)
    penalty = models.IntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)
    # Phase 4B — populated by the engine on every leaderboard rebuild.
    agent_id = models.CharField(max_length=64, blank=True, default="")
    agent_type = models.CharField(max_length=64, blank=True, default="")
    rewarded_orders = models.PositiveIntegerField(default=0)
    penalized_orders = models.PositiveIntegerField(default=0)
    last_calculated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("sort_order", "name")

    @property
    def net(self) -> int:
        return self.reward - self.penalty


class RewardPenaltyEvent(models.Model):
    """Phase 4B — one scoring event per (order, AI agent).

    The engine in :mod:`apps.rewards.engine` fans an
    :class:`apps.rewards.scoring.OrderRewardPenaltyResult` out across the
    relevant AI agents (CEO AI, Ads, Marketing, Sales Growth, Calling,
    Confirmation, RTO, Customer Success, Data Quality, Compliance) and
    persists one row per agent. Re-running the sweep updates rows in
    place via ``unique_key``.

    Hard rules (Phase 4B locked decisions):
    - Score AI agents only — no human staff in this phase.
    - For every RTO / cancelled order, CEO AI ALWAYS receives a net
      accountability penalty event (see ``apps.rewards.engine``).
    - CAIO never receives business reward / penalty (audit-only).
    - Missing data is recorded explicitly in ``missing_data``; never
      invented.
    """

    class EventType(models.TextChoices):
        REWARD = "reward", "Reward"
        PENALTY = "penalty", "Penalty"
        MIXED = "mixed", "Mixed"

    SOURCE_PHASE_4B_ENGINE = "phase4b_engine"

    id = models.CharField(primary_key=True, max_length=64)
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reward_penalty_events",
    )
    order_id_snapshot = models.CharField(max_length=32, blank=True, default="")
    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reward_penalty_events",
    )
    agent_name = models.CharField(max_length=120)
    agent_type = models.CharField(max_length=64, blank=True, default="")
    event_type = models.CharField(
        max_length=16, choices=EventType.choices, default=EventType.MIXED
    )
    reward_score = models.IntegerField(default=0)
    penalty_score = models.IntegerField(default=0)
    net_score = models.IntegerField(default=0)
    components = models.JSONField(default=list, blank=True)
    missing_data = models.JSONField(default=list, blank=True)
    attribution = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=40, default=SOURCE_PHASE_4B_ENGINE)
    triggered_by = models.CharField(max_length=120, blank=True, default="")
    calculated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)
    # Stable idempotency key. Format:
    # ``{source}:{order_id}:{agent_id_or_name}:{event_type}``.
    unique_key = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ("-calculated_at", "order_id_snapshot", "agent_name")
        indexes = (
            models.Index(fields=("agent_name",)),
            models.Index(fields=("event_type",)),
            models.Index(fields=("source",)),
            models.Index(fields=("order_id_snapshot",)),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"{self.unique_key} · {self.event_type} · "
            f"{self.reward_score:+d}/{-self.penalty_score:+d}"
        )
