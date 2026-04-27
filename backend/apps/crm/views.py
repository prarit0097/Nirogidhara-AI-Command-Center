from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission

from . import services
from .models import Customer, Lead
from .serializers import (
    CustomerSerializer,
    CustomerWriteSerializer,
    LeadAssignSerializer,
    LeadCreateSerializer,
    LeadSerializer,
    LeadUpdateSerializer,
)


class LeadViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    pagination_class = None
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def create(self, request):
        payload = LeadCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lead = services.create_lead(**payload.validated_data)
        return Response(LeadSerializer(lead).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist as exc:
            raise NotFound(f"Lead {pk} not found") from exc
        payload = LeadUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        lead = services.update_lead(lead, by_user=request.user, **payload.validated_data)
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist as exc:
            raise NotFound(f"Lead {pk} not found") from exc
        payload = LeadAssignSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lead = services.assign_lead(
            lead, assignee=payload.validated_data["assignee"], by_user=request.user
        )
        return Response(LeadSerializer(lead).data)


class CustomerViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    pagination_class = None
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def create(self, request):
        payload = CustomerWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        customer = services.upsert_customer(by_user=request.user, **payload.validated_data)
        return Response(CustomerSerializer(customer).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        if not Customer.objects.filter(pk=pk).exists():
            raise NotFound(f"Customer {pk} not found")
        payload = CustomerWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        customer = services.upsert_customer(
            by_user=request.user, customer_id=pk, **payload.validated_data
        )
        return Response(CustomerSerializer(customer).data)
