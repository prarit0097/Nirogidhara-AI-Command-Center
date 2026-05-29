from __future__ import annotations

from django.conf import settings
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


def _delhivery_mode() -> str:
    return (getattr(settings, "DELHIVERY_MODE", "mock") or "mock").lower()


class ShipmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Shipment.objects.all()
    serializer_class = ShipmentSerializer
    pagination_class = None
    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def create(self, request):
        """Phase 16E — explicit mode dispatch (no accidental LIVE booking).

        Before Phase 16E this view always called ``create_mock_shipment`` (an
        alias for ``create_shipment``), which silently delegated to the
        Delhivery adapter and *would* hit the real Delhivery **production**
        network whenever ``DELHIVERY_MODE`` was ``live``. Phase 16E makes the
        mode explicit and blocks live booking from the HTTP endpoint:

          - ``mock``  → create the shipment (deterministic AWB, no network).
          - ``test``  → create via the Delhivery **staging** adapter (safe test
            mode — staging API, not production, not a real customer). This
            preserves the existing Phase 2C test-mode capability.
          - ``live``  → BLOCKED from the HTTP endpoint (HTTP 409) — a Director
            live gate is required (the controlled CLI-only Phase 7G-Live path).
          - unknown   → HTTP 400.

        This guarantees the HTTP shipment-create endpoint never books a LIVE
        production Delhivery AWB. Mock + staging-test behaviour is preserved.
        """
        payload = ShipmentCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order_id = payload.validated_data["orderId"]
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise NotFound(f"Order {order_id} not found") from exc

        mode = _delhivery_mode()
        if mode == "live":
            return Response(
                {
                    "detail": "live_delhivery_booking_blocked",
                    "message": (
                        "Live Delhivery booking blocked — Director live gate "
                        "required."
                    ),
                    "delhiveryMode": mode,
                },
                status=status.HTTP_409_CONFLICT,
            )
        if mode not in {"mock", "test"}:
            return Response(
                {
                    "detail": "unknown_delhivery_mode",
                    "message": f"Unknown DELHIVERY_MODE: {mode!r}.",
                    "delhiveryMode": mode,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # mock → deterministic AWB (no network); test → staging adapter. The
        # service delegates to the Delhivery adapter, which only reaches the
        # staging API in test mode (never production). Behaviour preserved.
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
