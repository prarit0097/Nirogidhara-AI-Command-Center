from __future__ import annotations

from rest_framework import mixins, viewsets

from .models import Payment
from .serializers import PaymentSerializer


class PaymentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    pagination_class = None
