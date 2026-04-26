from __future__ import annotations

from rest_framework import serializers

from .models import KPITrend


class KPITrendSerializer(serializers.ModelSerializer):
    """Serialize a row, dropping null fields so the JSON matches the frontend
    `KPITrend` shape (a loose union)."""

    rtoPct = serializers.FloatField(source="rto_pct", required=False, allow_null=True)
    netProfit = serializers.IntegerField(source="net_profit", required=False, allow_null=True)

    class Meta:
        model = KPITrend
        fields = (
            "d",
            "stage",
            "state",
            "product",
            "value",
            "revenue",
            "profit",
            "leads",
            "orders",
            "delivered",
            "rto",
            "rtoPct",
            "netProfit",
        )

    def to_representation(self, instance):  # noqa: D401 - DRF override
        data = super().to_representation(instance)
        return {k: v for k, v in data.items() if v not in (None, "")}
