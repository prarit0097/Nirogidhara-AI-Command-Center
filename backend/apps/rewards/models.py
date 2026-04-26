from __future__ import annotations

from django.db import models


class RewardPenalty(models.Model):
    """Blueprint Section 10 — leaderboard rows for the Reward & Penalty engine.

    Phase 2 adds the formula-driven calculator (Section 10.2). Today this is a
    seeded leaderboard so the page renders.
    """

    name = models.CharField(primary_key=True, max_length=120)
    reward = models.IntegerField(default=0)
    penalty = models.IntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    @property
    def net(self) -> int:
        return self.reward - self.penalty
