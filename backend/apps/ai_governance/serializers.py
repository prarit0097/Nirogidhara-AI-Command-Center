from __future__ import annotations

from rest_framework import serializers

from .models import CaioAudit, CeoBriefing, CeoRecommendation


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
