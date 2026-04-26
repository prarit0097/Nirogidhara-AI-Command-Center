from __future__ import annotations

from rest_framework import serializers

from .models import RewardPenalty


class RewardPenaltySerializer(serializers.ModelSerializer):
    net = serializers.IntegerField(read_only=True)

    class Meta:
        model = RewardPenalty
        fields = ("name", "reward", "penalty", "net")
