from __future__ import annotations

from rest_framework import serializers

from .models import (
    AgentBudget,
    AgentRun,
    CaioAudit,
    CeoBriefing,
    CeoRecommendation,
    PromptVersion,
    SandboxState,
)


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
    # Phase 3D
    sandboxMode = serializers.BooleanField(source="sandbox_mode", read_only=True)
    promptVersionRef = serializers.CharField(
        source="prompt_version_ref_id", read_only=True
    )
    budgetStatus = serializers.CharField(source="budget_status", read_only=True)
    budgetSnapshot = serializers.JSONField(source="budget_snapshot", read_only=True)

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
            "sandboxMode",
            "promptVersionRef",
            "budgetStatus",
            "budgetSnapshot",
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


# ----- Phase 3D — PromptVersion, AgentBudget, SandboxState -----


class PromptVersionSerializer(serializers.ModelSerializer):
    systemPolicy = serializers.CharField(source="system_policy", read_only=True)
    rolePrompt = serializers.CharField(source="role_prompt", read_only=True)
    instructionPayload = serializers.JSONField(
        source="instruction_payload", read_only=True
    )
    isActive = serializers.BooleanField(source="is_active", read_only=True)
    createdBy = serializers.CharField(source="created_by", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    activatedAt = serializers.DateTimeField(source="activated_at", read_only=True)
    rolledBackAt = serializers.DateTimeField(source="rolled_back_at", read_only=True)
    rollbackReason = serializers.CharField(source="rollback_reason", read_only=True)

    class Meta:
        model = PromptVersion
        fields = (
            "id",
            "agent",
            "version",
            "title",
            "systemPolicy",
            "rolePrompt",
            "instructionPayload",
            "isActive",
            "status",
            "createdBy",
            "metadata",
            "createdAt",
            "activatedAt",
            "rolledBackAt",
            "rollbackReason",
        )


class PromptVersionCreateSerializer(serializers.Serializer):
    agent = serializers.ChoiceField(choices=AgentRun.Agent.choices)
    version = serializers.CharField(max_length=24)
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    systemPolicy = serializers.CharField(required=False, allow_blank=True, default="")
    rolePrompt = serializers.CharField(required=False, allow_blank=True, default="")
    instructionPayload = serializers.JSONField(required=False, default=dict)
    metadata = serializers.JSONField(required=False, default=dict)


class PromptVersionRollbackSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AgentBudgetSerializer(serializers.ModelSerializer):
    dailyBudgetUsd = serializers.DecimalField(
        source="daily_budget_usd", max_digits=10, decimal_places=4
    )
    monthlyBudgetUsd = serializers.DecimalField(
        source="monthly_budget_usd", max_digits=10, decimal_places=4
    )
    isEnforced = serializers.BooleanField(source="is_enforced")
    alertThresholdPct = serializers.IntegerField(source="alert_threshold_pct")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = AgentBudget
        fields = (
            "id",
            "agent",
            "dailyBudgetUsd",
            "monthlyBudgetUsd",
            "isEnforced",
            "alertThresholdPct",
            "createdAt",
            "updatedAt",
        )


class SandboxStateSerializer(serializers.ModelSerializer):
    isEnabled = serializers.BooleanField(source="is_enabled")
    updatedBy = serializers.CharField(source="updated_by", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = SandboxState
        fields = ("isEnabled", "note", "updatedBy", "updatedAt")


class SandboxPatchSerializer(serializers.Serializer):
    isEnabled = serializers.BooleanField()
    note = serializers.CharField(
        max_length=240, required=False, allow_blank=True, default=""
    )
