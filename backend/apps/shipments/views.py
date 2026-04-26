from __future__ import annotations

from rest_framework import mixins, viewsets

from apps.orders.serializers import RtoRiskSerializer
from apps.orders.views import RtoRiskView as OrdersRtoRiskView

from .models import Shipment
from .serializers import ShipmentSerializer


class ShipmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Shipment.objects.all()
    serializer_class = ShipmentSerializer
    pagination_class = None


# Re-export the RTO risk view from the orders app at /api/rto/risk/.
# Keeping the implementation in one place (orders) avoids duplication;
# `config/urls.py` mounts it under /api/rto/.
RtoRiskView = OrdersRtoRiskView


__all__ = ("ShipmentViewSet", "RtoRiskView", "RtoRiskSerializer")
