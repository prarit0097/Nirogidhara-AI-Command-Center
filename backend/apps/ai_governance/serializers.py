from __future__ import annotations

from rest_framework import serializers

from .models import AgentRun, CaioAudit, CeoBriefing, CeoRecommendation


class CeoRecommendationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="id_str")

    class Meta:
        model = CeoRecommendation
        fields = ("id", "title", "reason", "impact", "requires")


class CeoBriefingSerializer(serializers.ModelSerializer):
    recommendations = CeoRecommendationSerializer(many=True, read_only=True)

    class Meta:
        model = CeoBriefing
        fields = ("date", "headline", "summary", "recommendations", "alerts")


class CaioAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaioAudit
        fields = ("agent", "issue", "severity", "suggestion", "status")


# ----- Phase 3A — AgentRun -----


class AgentRunSerializer(serializers.ModelSerializer):
    inputPayload = serializers.JSONField(source="input_payload", read_only=True)
    outputPayload = serializers.JSONField(source="output_payload", read_only=True)
    promptVersion = serializers.CharField(source="prompt_version", read_only=True)
    latencyMs = serializers.IntegerField(source="latency_ms", read_only=True)
    costUsd = serializers.DecimalField(
        source="cost_usd", max_digits=10, decimal_places=6, read_only=True
    )
    errorMessage = serializers.CharField(source="error_message", read_only=True)
    dryRun = serializers.BooleanField(source="dry_run", read_only=True)
    triggeredBy = serializers.CharField(source="triggered_by", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    completedAt = serializers.DateTimeField(source="completed_at", read_only=True)
    # Phase 3C — token usage + fallback bookkeeping.
    promptTokens = serializers.IntegerField(source="prompt_tokens", read_only=True)
    completionTokens = serializers.IntegerField(
        source="completion_tokens", read_only=True
    )
    totalTokens = serializers.IntegerField(source="total_tokens", read_only=True)
    providerAttempts = serializers.JSONField(
        source="provider_attempts", read_only=True
    )
    fallbackUsed = serializers.BooleanField(source="fallback_used", read_only=True)
    pricingSnapshot = serializers.JSONField(source="pricing_snapshot", read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "agent",
            "promptVersion",
            "inputPayload",
            "outputPayload",
            "status",
            "provider",
            "model",
            "latencyMs",
            "costUsd",
            "errorMessage",
            "dryRun",
            "triggeredBy",
            "createdAt",
            "completedAt",
            "promptTokens",
            "completionTokens",
            "totalTokens",
            "providerAttempts",
            "fallbackUsed",
            "pricingSnapshot",
        )


class AgentRunCreateSerializer(serializers.Serializer):
    """Inbound payload for ``POST /api/ai/agent-runs/``.

    Phase 3A always coerces ``dryRun`` to True before dispatch — the field
    is accepted from the client only so the contract is forward-compatible
    with Phase 5 (approval-matrix execution).
    """

    agent = serializers.ChoiceField(choices=AgentRun.Agent.choices)
    input = serializers.JSONField(required=False, default=dict)
    dryRun = serializers.BooleanField(required=False, default=True)
