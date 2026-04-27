from __future__ import annotations

from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    orderId = serializers.CharField(source="order_id")
    gatewayReferenceId = serializers.CharField(source="gateway_reference_id", read_only=True)
    paymentUrl = serializers.URLField(source="payment_url", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "orderId",
            "customer",
            "amount",
            "gateway",
            "status",
            "type",
            "time",
            "gatewayReferenceId",
            "paymentUrl",
        )


class PaymentLinkSerializer(serializers.Serializer):
    """Inbound payload for POST /api/payments/links/.

    ``customerName`` / ``customerPhone`` / ``customerEmail`` are forwarded to
    Razorpay. They're optional in mock mode but required-ish in live mode —
    we let the service / SDK decide.
    """

    orderId = serializers.CharField(max_length=32)
    amount = serializers.IntegerField(min_value=1)
    gateway = serializers.ChoiceField(
        choices=Payment.Gateway.choices, default=Payment.Gateway.RAZORPAY
    )
    type = serializers.ChoiceField(
        choices=Payment.Type.choices, default=Payment.Type.ADVANCE
    )
    customerName = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default=""
    )
    customerPhone = serializers.CharField(
        max_length=24, required=False, allow_blank=True, default=""
    )
    customerEmail = serializers.EmailField(required=False, allow_blank=True, default="")
