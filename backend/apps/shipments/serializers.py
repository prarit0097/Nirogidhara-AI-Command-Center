from __future__ import annotations

from rest_framework import serializers

from .models import RescueAttempt, Shipment, WorkflowStep


class WorkflowStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowStep
        fields = ("step", "at", "done")


class ShipmentSerializer(serializers.ModelSerializer):
    orderId = serializers.CharField(source="order_id")
    timeline = WorkflowStepSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = ("awb", "orderId", "customer", "state", "city", "status", "eta", "courier", "timeline")


# ----- Phase 2A — write input + rescue attempt -----


class ShipmentCreateSerializer(serializers.Serializer):
    orderId = serializers.CharField(max_length=32)


class RescueAttemptSerializer(serializers.ModelSerializer):
    """Read serializer for /api/rto/rescue/ list + detail responses."""

    orderId = serializers.CharField(source="order_id")
    attemptedAt = serializers.DateTimeField(source="attempted_at", read_only=True)

    class Meta:
        model = RescueAttempt
        fields = ("id", "orderId", "channel", "outcome", "notes", "attemptedAt")


class RescueAttemptCreateSerializer(serializers.Serializer):
    orderId = serializers.CharField(max_length=32)
    channel = serializers.ChoiceField(
        choices=RescueAttempt.Channel.choices, default=RescueAttempt.Channel.AI_CALL
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class RescueAttemptUpdateSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=RescueAttempt.Outcome.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
