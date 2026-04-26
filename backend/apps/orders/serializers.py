from __future__ import annotations

from rest_framework import serializers

from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    customerName = serializers.CharField(source="customer_name")
    discountPct = serializers.IntegerField(source="discount_pct")
    advancePaid = serializers.BooleanField(source="advance_paid")
    advanceAmount = serializers.IntegerField(source="advance_amount")
    paymentStatus = serializers.CharField(source="payment_status")
    rtoRisk = serializers.CharField(source="rto_risk")
    rtoScore = serializers.IntegerField(source="rto_score")
    ageHours = serializers.IntegerField(source="age_hours")
    createdAt = serializers.CharField(source="created_at_label")

    class Meta:
        model = Order
        fields = (
            "id",
            "customerName",
            "phone",
            "product",
            "quantity",
            "amount",
            "discountPct",
            "advancePaid",
            "advanceAmount",
            "paymentStatus",
            "state",
            "city",
            "rtoRisk",
            "rtoScore",
            "agent",
            "stage",
            "awb",
            "ageHours",
            "createdAt",
        )


class ConfirmationQueueSerializer(OrderSerializer):
    hoursWaiting = serializers.IntegerField(source="hours_waiting")
    addressConfidence = serializers.IntegerField(source="address_confidence")
    checklist = serializers.JSONField(source="confirmation_checklist")

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ("hoursWaiting", "addressConfidence", "checklist")


class RtoRiskSerializer(OrderSerializer):
    riskReasons = serializers.JSONField(source="risk_reasons")
    rescueStatus = serializers.CharField(source="rescue_status")

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ("riskReasons", "rescueStatus")
