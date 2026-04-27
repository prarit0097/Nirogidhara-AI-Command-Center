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
    confirmationOutcome = serializers.CharField(source="confirmation_outcome", read_only=True)
    confirmationNotes = serializers.CharField(source="confirmation_notes", read_only=True)

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
            "confirmationOutcome",
            "confirmationNotes",
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


# ----- Phase 2A — write input serializers -----


class OrderCreateSerializer(serializers.Serializer):
    customerName = serializers.CharField(max_length=120, source="customer_name")
    phone = serializers.CharField(max_length=24)
    product = serializers.CharField(max_length=120)
    quantity = serializers.IntegerField(required=False, default=1, min_value=1)
    amount = serializers.IntegerField(required=False, default=3000, min_value=0)
    discountPct = serializers.IntegerField(
        required=False, default=0, min_value=0, max_value=30, source="discount_pct"
    )
    advancePaid = serializers.BooleanField(required=False, default=False, source="advance_paid")
    advanceAmount = serializers.IntegerField(
        required=False, default=0, min_value=0, source="advance_amount"
    )
    paymentStatus = serializers.ChoiceField(
        choices=Order.PaymentStatus.choices,
        required=False,
        default=Order.PaymentStatus.PENDING,
        source="payment_status",
    )
    state = serializers.CharField(max_length=60)
    city = serializers.CharField(max_length=80)
    rtoRisk = serializers.ChoiceField(
        choices=Order.RtoRisk.choices,
        required=False,
        default=Order.RtoRisk.LOW,
        source="rto_risk",
    )
    rtoScore = serializers.IntegerField(
        required=False, default=10, min_value=0, max_value=100, source="rto_score"
    )
    agent = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    stage = serializers.ChoiceField(
        choices=Order.Stage.choices, required=False, default=Order.Stage.ORDER_PUNCHED
    )


class OrderTransitionSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=Order.Stage.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class OrderConfirmSerializer(serializers.Serializer):
    OUTCOMES = (
        ("confirmed", "Confirmed"),
        ("rescue_needed", "Rescue Needed"),
        ("cancelled", "Cancelled"),
    )
    outcome = serializers.ChoiceField(choices=OUTCOMES)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
