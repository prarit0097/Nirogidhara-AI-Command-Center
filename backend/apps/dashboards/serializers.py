from __future__ import annotations

from rest_framework import serializers

from apps.audit.models import AuditEvent

from .models import DashboardMetric


class DashboardMetricSerializer(serializers.ModelSerializer):
    deltaPct = serializers.FloatField(source="delta_pct", required=False, allow_null=True)

    class Meta:
        model = DashboardMetric
        fields = ("value", "deltaPct", "completed", "pending", "alerts")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return {k: v for k, v in data.items() if v is not None}


class ActivityEventSerializer(serializers.ModelSerializer):
    time = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = ("time", "icon", "text", "tone")

    def get_time(self, obj: AuditEvent) -> str:
        # Compact "Nm ago" / "Nh ago" labels — easier than stringly typed dates
        # in the Recharts/list components.
        from django.utils import timezone

        delta = timezone.now() - obj.occurred_at
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
