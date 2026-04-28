from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission
from apps.ai_governance import approval_engine
from apps.orders.models import Order

from . import services
from .integrations.razorpay_client import RazorpayClientError
from .models import Payment
from .policies import FIXED_ADVANCE_AMOUNT_INR
from .serializers import PaymentLinkSerializer, PaymentSerializer


class _GatewayUnavailable(APIException):
    """502 — gateway adapter raised an error (misconfig or upstream failure)."""

    status_code = 502
    default_detail = "Payment gateway unavailable."
    default_code = "gateway_unavailable"


class PaymentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    pagination_class = None


class PaymentLinkView(APIView):
    """POST /api/payments/links/ — Razorpay payment-link generator.

    Supports three modes via ``settings.RAZORPAY_MODE``: ``mock`` (default,
    no network), ``test`` (Razorpay sandbox), ``live`` (production).
    Frontend never sees keys or signatures — secrets stay server-side.
    """

    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def post(self, request):
        payload = PaymentLinkSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order_id = payload.validated_data["orderId"]
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise NotFound(f"Order {order_id} not found") from exc

        # Phase 4C — gate the action through the approval matrix.
        # ``payment.link.advance_499`` is auto; ``payment.link.custom_amount``
        # requires admin approval. The serializer defaults Advance amount
        # to 0 → the service resolves it to ₹499 — so we route the matrix
        # action accordingly.
        amount_in = int(payload.validated_data.get("amount") or 0)
        type_in = payload.validated_data.get("type") or Payment.Type.ADVANCE
        is_standard_advance = (
            type_in == Payment.Type.ADVANCE
            and (amount_in == 0 or amount_in == FIXED_ADVANCE_AMOUNT_INR)
        )
        evaluation = approval_engine.enforce_or_queue(
            action=(
                "payment.link.advance_499"
                if is_standard_advance
                else "payment.link.custom_amount"
            ),
            payload={
                "orderId": order_id,
                "amount": amount_in or FIXED_ADVANCE_AMOUNT_INR,
                "type": type_in,
            },
            actor_role=getattr(request.user, "role", "") or "",
            target={"app": "payments", "model": "Order", "id": order_id},
            by_user=request.user,
        )
        if not evaluation.allowed:
            from rest_framework.exceptions import PermissionDenied as _PD

            raise _PD(detail={
                "detail": evaluation.reason,
                "approvalRequestId": evaluation.approval_request_id,
                "mode": evaluation.mode,
                "action": evaluation.action,
            })

        try:
            payment, payment_url = services.create_payment_link(
                order=order,
                amount=payload.validated_data["amount"],
                by_user=request.user,
                gateway=payload.validated_data["gateway"],
                type=payload.validated_data["type"],
                customer_name=payload.validated_data.get("customerName") or "",
                customer_phone=payload.validated_data.get("customerPhone") or "",
                customer_email=payload.validated_data.get("customerEmail") or "",
            )
        except RazorpayClientError as exc:
            raise _GatewayUnavailable(detail=str(exc)) from exc

        body = {
            # New flat fields per the Phase 2B spec.
            "paymentId": payment.id,
            "gateway": payment.gateway.lower(),
            "status": payment.status.lower(),
            "paymentUrl": payment_url,
            "gatewayReferenceId": payment.gateway_reference_id,
            # Phase 2A backward-compatible nested payload — kept so existing
            # frontend code and tests don't break.
            "payment": PaymentSerializer(payment).data,
        }
        return Response(body, status=status.HTTP_201_CREATED)
