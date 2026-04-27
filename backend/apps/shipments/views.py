from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission
from apps.orders.models import Order
from apps.orders.serializers import RtoRiskSerializer
from apps.orders.views import RtoRiskView as OrdersRtoRiskView

from . import services
from .models import RescueAttempt, Shipment
from .serializers import (
    RescueAttemptCreateSerializer,
    RescueAttemptSerializer,
    RescueAttemptUpdateSerializer,
    ShipmentCreateSerializer,
    ShipmentSerializer,
)


class ShipmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Shipment.objects.all()
    serializer_class = ShipmentSerializer
    pagination_class = None
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def create(self, request):
        payload = ShipmentCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order_id = payload.validated_data["orderId"]
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise NotFound(f"Order {order_id} not found") from exc
        shipment = services.create_mock_shipment(order=order, by_user=request.user)
        return Response(ShipmentSerializer(shipment).data, status=status.HTTP_201_CREATED)


class RescueAttemptViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = RescueAttempt.objects.all()
    serializer_class = RescueAttemptSerializer
    pagination_class = None
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def create(self, request):
        payload = RescueAttemptCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order_id = payload.validated_data["orderId"]
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise NotFound(f"Order {order_id} not found") from exc
        try:
            attempt = services.create_rescue_attempt(
                order=order,
                channel=payload.validated_data["channel"],
                by_user=request.user,
                notes=payload.validated_data.get("notes", ""),
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(RescueAttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            attempt = RescueAttempt.objects.get(pk=pk)
        except RescueAttempt.DoesNotExist as exc:
            raise NotFound(f"RescueAttempt {pk} not found") from exc
        payload = RescueAttemptUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            attempt = services.update_rescue_outcome(
                attempt=attempt,
                outcome=payload.validated_data["outcome"],
                by_user=request.user,
                notes=payload.validated_data.get("notes", ""),
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(RescueAttemptSerializer(attempt).data)


# Re-export the RTO risk view from the orders app at /api/rto/risk/.
# Keeping the implementation in one place (orders) avoids duplication;
# `config/urls.py` mounts it under /api/rto/.
RtoRiskView = OrdersRtoRiskView


__all__ = (
    "ShipmentViewSet",
    "RescueAttemptViewSet",
    "RtoRiskView",
    "RtoRiskSerializer",
)
