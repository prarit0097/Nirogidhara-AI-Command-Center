from __future__ import annotations

from rest_framework import serializers

from .models import RewardPenalty, RewardPenaltyEvent


class RewardPenaltySerializer(serializers.ModelSerializer):
    """Phase 1 / 4B agent-level rollup row.

    Backwards-compatible shape (``name``, ``reward``, ``penalty``, ``net``)
    plus Phase 4B fields (``agentId``, ``agentType``, ``rewardedOrders``,
    ``penalizedOrders``, ``lastCalculatedAt``).
    """

    net = serializers.IntegerField(read_only=True)
    agentId = serializers.CharField(source="agent_id", read_only=True)
    agentType = serializers.CharField(source="agent_type", read_only=True)
    rewardedOrders = serializers.IntegerField(source="rewarded_orders", read_only=True)
    penalizedOrders = serializers.IntegerField(source="penalized_orders", read_only=True)
    lastCalculatedAt = serializers.DateTimeField(
        source="last_calculated_at", read_only=True
    )

    class Meta:
        model = RewardPenalty
        fields = (
            "name",
            "reward",
            "penalty",
            "net",
            "agentId",
            "agentType",
            "rewardedOrders",
            "penalizedOrders",
            "lastCalculatedAt",
        )


class RewardPenaltyEventSerializer(serializers.ModelSerializer):
    """Phase 4B per-order, per-AI-agent scoring event."""

    orderIdSnapshot = serializers.CharField(source="order_id_snapshot", read_only=True)
    agentId = serializers.CharField(source="agent_id", allow_null=True, read_only=True)
    agentName = serializers.CharField(source="agent_name", read_only=True)
    agentType = serializers.CharField(source="agent_type", read_only=True)
    eventType = serializers.CharField(source="event_type", read_only=True)
    rewardScore = serializers.IntegerField(source="reward_score", read_only=True)
    penaltyScore = serializers.IntegerField(source="penalty_score", read_only=True)
    netScore = serializers.IntegerField(source="net_score", read_only=True)
    missingData = serializers.JSONField(source="missing_data", read_only=True)
    triggeredBy = serializers.CharField(source="triggered_by", read_only=True)
    calculatedAt = serializers.DateTimeField(source="calculated_at", read_only=True)
    uniqueKey = serializers.CharField(source="unique_key", read_only=True)
    orderId = serializers.CharField(source="order_id", read_only=True)

    class Meta:
        model = RewardPenaltyEvent
        fields = (
            "id",
            "orderId",
            "orderIdSnapshot",
            "agentId",
            "agentName",
            "agentType",
            "eventType",
            "rewardScore",
            "penaltyScore",
            "netScore",
            "components",
            "missingData",
            "attribution",
            "source",
            "triggeredBy",
            "calculatedAt",
            "metadata",
            "uniqueKey",
        )


class RewardPenaltySweepRequestSerializer(serializers.Serializer):
    startDate = serializers.DateField(required=False, allow_null=True)
    endDate = serializers.DateField(required=False, allow_null=True)
    orderId = serializers.CharField(required=False, allow_blank=True, default="")
    dryRun = serializers.BooleanField(required=False, default=False)
