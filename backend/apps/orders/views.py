from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission

from . import services
from .models import Order
from .serializers import (
    ConfirmationQueueSerializer,
    OrderConfirmSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    OrderTransitionSerializer,
    RtoRiskSerializer,
)
from .services import OrderTransitionError


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    pagination_class = None
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    @action(detail=False, methods=["get"], url_path="pipeline")
    def pipeline(self, request):
        # The frontend's `getOrderPipeline` returns the same shape as `getOrders`,
        # ordered by stage, so a Kanban view can group by stage client-side.
        qs = self.get_queryset().order_by("stage", "-created_at")
        return Response(self.get_serializer(qs, many=True).data)

    # ----- Phase 2A writes -----

    def create(self, request):
        payload = OrderCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order = services.create_order(**payload.validated_data)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        order = self._get_order(pk)
        payload = OrderTransitionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            order = services.transition_order(
                order,
                payload.validated_data["stage"],
                by_user=request.user,
                notes=payload.validated_data.get("notes", ""),
            )
        except OrderTransitionError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="move-to-confirmation")
    def move_to_confirmation(self, request, pk=None):
        order = self._get_order(pk)
        try:
            order = services.move_to_confirmation(order, by_user=request.user)
        except OrderTransitionError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        order = self._get_order(pk)
        payload = OrderConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            order = services.record_confirmation_outcome(
                order,
                outcome=payload.validated_data["outcome"],
                by_user=request.user,
                notes=payload.validated_data.get("notes", ""),
            )
        except (OrderTransitionError, ValueError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(OrderSerializer(order).data)

    # ----- helpers -----

    def _get_order(self, pk: str | None) -> Order:
        try:
            return Order.objects.get(pk=pk)
        except Order.DoesNotExist as exc:
            raise NotFound(f"Order {pk} not found") from exc


class ConfirmationQueueView(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = ConfirmationQueueSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Order.objects.filter(stage=Order.Stage.CONFIRMATION_PENDING)
            .order_by("-hours_waiting", "-created_at")
        )


class RtoRiskView(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = RtoRiskSerializer
    pagination_class = None

    def get_queryset(self):
        return Order.objects.exclude(risk_reasons=[]).order_by("-rto_score")
