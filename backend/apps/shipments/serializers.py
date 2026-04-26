from __future__ import annotations

from rest_framework import serializers

from .models import Shipment, WorkflowStep


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
