from __future__ import annotations

from rest_framework import mixins, viewsets

from .models import Customer, Lead
from .serializers import CustomerSerializer, LeadSerializer


class LeadViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    pagination_class = None


class CustomerViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    pagination_class = None
