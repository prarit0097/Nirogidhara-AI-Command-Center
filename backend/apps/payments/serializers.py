from __future__ import annotations

from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    orderId = serializers.CharField(source="order_id")

    class Meta:
        model = Payment
        fields = ("id", "orderId", "customer", "amount", "gateway", "status", "type", "time")
