from __future__ import annotations

from rest_framework import serializers

from .models import Customer, Lead


class LeadSerializer(serializers.ModelSerializer):
    productInterest = serializers.CharField(source="product_interest")
    qualityScore = serializers.IntegerField(source="quality_score")
    createdAt = serializers.CharField(source="created_at_label")
    metaLeadgenId = serializers.CharField(source="meta_leadgen_id", read_only=True)
    metaPageId = serializers.CharField(source="meta_page_id", read_only=True)
    metaFormId = serializers.CharField(source="meta_form_id", read_only=True)
    metaAdId = serializers.CharField(source="meta_ad_id", read_only=True)
    metaCampaignId = serializers.CharField(source="meta_campaign_id", read_only=True)
    sourceDetail = serializers.CharField(source="source_detail", read_only=True)

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
            "metaLeadgenId",
            "metaPageId",
            "metaFormId",
            "metaAdId",
            "metaCampaignId",
            "sourceDetail",
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


# ----- Phase 2A — write input serializers -----


class LeadCreateSerializer(serializers.Serializer):
    """Inbound payload for POST /api/leads/. camelCase field names."""

    name = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=24)
    state = serializers.CharField(max_length=60)
    city = serializers.CharField(max_length=80)
    language = serializers.CharField(max_length=40, required=False, default="Hinglish")
    source = serializers.CharField(max_length=60, required=False, default="Manual")
    campaign = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    productInterest = serializers.CharField(
        max_length=80,
        required=False,
        allow_blank=True,
        default="",
        source="product_interest",
    )
    quality = serializers.ChoiceField(
        choices=Lead.Quality.choices, required=False, default=Lead.Quality.WARM
    )
    qualityScore = serializers.IntegerField(
        required=False, default=50, min_value=0, max_value=100, source="quality_score"
    )
    assignee = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    duplicate = serializers.BooleanField(required=False, default=False)


class LeadUpdateSerializer(serializers.Serializer):
    """Patchable lead fields. Every field is optional."""

    name = serializers.CharField(max_length=120, required=False)
    phone = serializers.CharField(max_length=24, required=False)
    state = serializers.CharField(max_length=60, required=False)
    city = serializers.CharField(max_length=80, required=False)
    language = serializers.CharField(max_length=40, required=False)
    source = serializers.CharField(max_length=60, required=False)
    campaign = serializers.CharField(max_length=120, required=False, allow_blank=True)
    productInterest = serializers.CharField(
        max_length=80, required=False, source="product_interest"
    )
    status = serializers.ChoiceField(choices=Lead.Status.choices, required=False)
    quality = serializers.ChoiceField(choices=Lead.Quality.choices, required=False)
    qualityScore = serializers.IntegerField(
        required=False, min_value=0, max_value=100, source="quality_score"
    )
    assignee = serializers.CharField(max_length=80, required=False, allow_blank=True)
    duplicate = serializers.BooleanField(required=False)


class LeadAssignSerializer(serializers.Serializer):
    assignee = serializers.CharField(max_length=80)


class CustomerWriteSerializer(serializers.Serializer):
    """Create/update payload for /api/customers/. ``leadId`` optional."""

    leadId = serializers.CharField(
        max_length=32, required=False, allow_blank=True, source="lead_id"
    )
    name = serializers.CharField(max_length=120, required=False)
    phone = serializers.CharField(max_length=24, required=False)
    state = serializers.CharField(max_length=60, required=False)
    city = serializers.CharField(max_length=80, required=False)
    language = serializers.CharField(max_length=40, required=False)
    productInterest = serializers.CharField(
        max_length=80, required=False, source="product_interest"
    )
    diseaseCategory = serializers.CharField(
        max_length=80, required=False, source="disease_category"
    )
    lifestyleNotes = serializers.CharField(
        required=False, allow_blank=True, source="lifestyle_notes"
    )
    objections = serializers.ListField(child=serializers.CharField(), required=False)
    aiSummary = serializers.CharField(required=False, allow_blank=True, source="ai_summary")
    riskFlags = serializers.ListField(
        child=serializers.CharField(), required=False, source="risk_flags"
    )
    reorderProbability = serializers.IntegerField(
        required=False, min_value=0, max_value=100, source="reorder_probability"
    )
    satisfaction = serializers.IntegerField(required=False, min_value=0, max_value=5)
    consent = serializers.DictField(child=serializers.BooleanField(), required=False)

    def to_internal_value(self, data):
        validated = super().to_internal_value(data)
        # Flatten {call,whatsapp,marketing} into the three booleans.
        consent = validated.pop("consent", None)
        if consent is not None:
            if "call" in consent:
                validated["consent_call"] = consent["call"]
            if "whatsapp" in consent:
                validated["consent_whatsapp"] = consent["whatsapp"]
            if "marketing" in consent:
                validated["consent_marketing"] = consent["marketing"]
        return validated
