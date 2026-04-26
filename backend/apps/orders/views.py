from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Order
from .serializers import (
    ConfirmationQueueSerializer,
    OrderSerializer,
    RtoRiskSerializer,
)


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    pagination_class = None

    @action(detail=False, methods=["get"], url_path="pipeline")
    def pipeline(self, request):
        # The frontend's `getOrderPipeline` returns the same shape as `getOrders`,
        # ordered by stage, so a Kanban view can group by stage client-side.
        qs = self.get_queryset().order_by("stage", "-created_at")
        return Response(self.get_serializer(qs, many=True).data)


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
