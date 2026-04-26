from __future__ import annotations

from rest_framework import serializers

from .models import ActiveCall, Call, CallTranscriptLine


class CallSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id")
    scriptCompliance = serializers.IntegerField(source="script_compliance")
    paymentLinkSent = serializers.BooleanField(source="payment_link_sent")

    class Meta:
        model = Call
        fields = (
            "id",
            "leadId",
            "customer",
            "phone",
            "agent",
            "language",
            "duration",
            "status",
            "sentiment",
            "scriptCompliance",
            "paymentLinkSent",
        )


class TranscriptLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallTranscriptLine
        fields = ("who", "text")


class ActiveCallSerializer(serializers.ModelSerializer):
    scriptCompliance = serializers.IntegerField(source="script_compliance")
    detectedObjections = serializers.JSONField(source="detected_objections")
    approvedClaimsUsed = serializers.JSONField(source="approved_claims_used")
    transcript = TranscriptLineSerializer(source="transcript_lines", many=True, read_only=True)

    class Meta:
        model = ActiveCall
        fields = (
            "id",
            "customer",
            "phone",
            "agent",
            "language",
            "duration",
            "stage",
            "sentiment",
            "scriptCompliance",
            "transcript",
            "detectedObjections",
            "approvedClaimsUsed",
        )
