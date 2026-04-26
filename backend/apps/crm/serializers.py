from __future__ import annotations

from rest_framework import serializers

from .models import Customer, Lead


class LeadSerializer(serializers.ModelSerializer):
    productInterest = serializers.CharField(source="product_interest")
    qualityScore = serializers.IntegerField(source="quality_score")
    createdAt = serializers.CharField(source="created_at_label")

    class Meta:
        model = Lead
        fields = (
            "id",
            "name",
            "phone",
            "state",
            "city",
            "language",
            "source",
            "campaign",
            "productInterest",
            "status",
            "quality",
            "qualityScore",
            "assignee",
            "duplicate",
            "createdAt",
        )


class CustomerSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id")
    productInterest = serializers.CharField(source="product_interest")
    diseaseCategory = serializers.CharField(source="disease_category")
    lifestyleNotes = serializers.CharField(source="lifestyle_notes")
    aiSummary = serializers.CharField(source="ai_summary")
    riskFlags = serializers.JSONField(source="risk_flags")
    reorderProbability = serializers.IntegerField(source="reorder_probability")
    consent = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            "id",
            "leadId",
            "name",
            "phone",
            "state",
            "city",
            "language",
            "productInterest",
            "diseaseCategory",
            "lifestyleNotes",
            "objections",
            "aiSummary",
            "riskFlags",
            "reorderProbability",
            "satisfaction",
            "consent",
        )

    def get_consent(self, obj: Customer) -> dict[str, bool]:
        return {
            "call": obj.consent_call,
            "whatsapp": obj.consent_whatsapp,
            "marketing": obj.consent_marketing,
        }
