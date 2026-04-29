from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission

from . import services
from . import rescue_discount as rescue_module
from .models import DiscountOfferLog, Order
from .serializers import (
    ConfirmationQueueSerializer,
    CreateRescueOfferPayloadSerializer,
    DiscountOfferSerializer,
    OrderConfirmSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    OrderTransitionSerializer,
    RescueOfferDecisionPayloadSerializer,
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

    # ----- Phase 5E — Rescue discount endpoints -----

    @action(detail=True, methods=["get"], url_path="discount-offers")
    def list_discount_offers(self, request, pk=None):
        order = self._get_order(pk)
        offers = order.discount_offers.all().order_by("-created_at")[:200]
        cap = rescue_module.cap_status(order)
        return Response(
            {
                "orderId": order.id,
                "currentDiscountPct": int(order.discount_pct or 0),
                "cap": cap.to_dict(),
                "offers": DiscountOfferSerializer(offers, many=True).data,
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="discount-offers/rescue",
    )
    def create_rescue_offer(self, request, pk=None):
        order = self._get_order(pk)
        payload = CreateRescueOfferPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        conversation = None
        conv_id = (data.get("conversationId") or "").strip()
        if conv_id:
            try:
                from apps.whatsapp.models import WhatsAppConversation

                conversation = WhatsAppConversation.objects.filter(pk=conv_id).first()
            except Exception:  # noqa: BLE001 - whatsapp app optional in audit
                conversation = None

        actor_role = (getattr(request.user, "role", "") or "").lower() or "operations"

        log = rescue_module.create_rescue_discount_offer(
            order=order,
            stage=data["stage"],
            source_channel=data["sourceChannel"],
            trigger_reason=data["triggerReason"],
            refusal_count=int(data.get("refusalCount") or 1),
            risk_level=str(data.get("riskLevel") or ""),
            requested_pct=data.get("requestedPct"),
            actor_role=actor_role,
            actor_agent="operator",
            conversation=conversation,
            metadata=dict(data.get("metadata") or {}),
        )
        return Response(
            DiscountOfferSerializer(log).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"discount-offers/(?P<offer_id>\d+)/accept",
    )
    def accept_discount_offer(self, request, pk=None, offer_id=None):
        order = self._get_order(pk)
        offer = self._get_offer(order, offer_id)
        try:
            log = rescue_module.accept_rescue_discount_offer(
                offer=offer,
                actor_role=(getattr(request.user, "role", "") or "operations"),
                actor=request.user,
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(DiscountOfferSerializer(log).data)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"discount-offers/(?P<offer_id>\d+)/reject",
    )
    def reject_discount_offer(self, request, pk=None, offer_id=None):
        order = self._get_order(pk)
        offer = self._get_offer(order, offer_id)
        payload = RescueOfferDecisionPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            log = rescue_module.reject_rescue_discount_offer(
                offer=offer,
                note=payload.validated_data.get("note") or "",
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(DiscountOfferSerializer(log).data)

    def _get_offer(self, order: Order, offer_id) -> DiscountOfferLog:
        try:
            return order.discount_offers.get(pk=offer_id)
        except DiscountOfferLog.DoesNotExist as exc:
            raise NotFound(f"DiscountOfferLog {offer_id} not found") from exc


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
