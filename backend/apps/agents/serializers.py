from __future__ import annotations

from rest_framework import serializers

from .models import Agent


class AgentSerializer(serializers.ModelSerializer):
    lastAction = serializers.CharField(source="last_action")

    class Meta:
        model = Agent
        fields = (
            "id",
            "name",
            "role",
            "status",
            "health",
            "reward",
            "penalty",
            "lastAction",
            "critical",
            "group",
        )
