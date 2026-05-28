from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission

from . import services
from .models import Customer, Lead
from .serializers import (
    CustomerSerializer,
    CustomerWriteSerializer,
    LeadAssignSerializer,
    LeadCreateSerializer,
    LeadImportCsvPayloadSerializer,
    LeadImportResultSerializer,
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
        try:
            lead = services.create_lead(**payload.validated_data)
        except services.LeadDuplicateError as exc:
            # Phase 16B-Hotfix-2: clean 409 with the existing lead id so the
            # operator can navigate to the duplicate. Lead uniqueness is
            # phone-only, so the field is always "phone" and the message is
            # fixed. No full PII in the response (existing lead id only).
            return Response(
                {
                    "detail": "Duplicate phone blocked — existing lead found.",
                    "duplicate": True,
                    "field": "phone",
                    "duplicate_field": "phone",
                    "existingLeadId": exc.existing_lead_id,
                    "existing_lead_id": exc.existing_lead_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
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

    @action(detail=True, methods=["get"], url_path="timeline")
    def timeline(self, request, pk=None):
        """Phase 16B — Customer 360 unified timeline (READ-ONLY).

        Returns related calls / orders / payments / shipments for the given
        customer in a single response so the Customer 360 page can hydrate
        all four tabs in one round-trip.

        Matching strategy (defensive, multiple FKs are CharField across
        apps): match on ``customer_phone`` (Payment) / ``phone``
        (Order, Shipment, Call) using the Customer's phone, AND on the
        denormalized customer FK / customer name where available.
        Phones are NOT masked in the response — the Customer 360 page
        already enforces the existing display masking policy.
        """
        try:
            customer = Customer.objects.get(pk=pk)
        except Customer.DoesNotExist as exc:
            raise NotFound(f"Customer {pk} not found") from exc

        # Lazy local imports so cross-app schema mismatches surface as 500
        # instead of breaking app loading for unrelated tests.
        from apps.calls.models import Call
        from apps.orders.models import Order
        from apps.payments.models import Payment
        from apps.shipments.models import Shipment

        phone = (customer.phone or "").strip()
        name = (customer.name or "").strip()

        calls = (
            list(Call.objects.filter(phone=phone).order_by("-created_at")[:50])
            if phone
            else []
        )
        orders = (
            list(Order.objects.filter(phone=phone).order_by("-created_at")[:50])
            if phone
            else []
        )
        payments_qs = Payment.objects.none()
        if phone:
            payments_qs = Payment.objects.filter(customer_phone=phone)
        if name:
            payments_qs = payments_qs | Payment.objects.filter(customer=name)
        payments = list(
            payments_qs.distinct().order_by("-created_at")[:50]
        ) if (phone or name) else []
        shipments = []
        if orders:
            # Shipments do not carry phone; join via order_id.
            order_ids = [o.id for o in orders]
            shipments_qs = Shipment.objects.filter(order_id__in=order_ids)
            shipments = list(shipments_qs.order_by("-created_at")[:50])

        # Inline lightweight serialisation (defensive: don't depend on
        # cross-app serializers because their shape may evolve under
        # phases other than 16B; we only surface the subset the UI needs).
        def _call_dict(c):
            return {
                "id": c.id,
                "createdAt": c.created_at.isoformat() if c.created_at else "",
                "agent": c.agent or "",
                "status": c.status or "",
                "duration": c.duration or "",
                "sentiment": getattr(c, "sentiment", "") or "",
                "summary": (c.summary or "")[:240],
            }

        def _order_dict(o):
            return {
                "id": o.id,
                "createdAt": o.created_at.isoformat() if o.created_at else "",
                "stage": o.stage,
                "product": o.product or "",
                "quantity": o.quantity,
                "amount": o.amount,
                "paymentStatus": o.payment_status,
                "rtoRisk": o.rto_risk,
                "agent": o.agent or "",
            }

        def _payment_dict(p):
            return {
                "id": p.id,
                "createdAt": p.created_at.isoformat() if p.created_at else "",
                "orderId": p.order_id,
                "amount": p.amount,
                "status": p.status,
                "gateway": p.gateway,
                "type": p.type,
            }

        def _shipment_dict(s):
            return {
                "awb": s.awb,
                "orderId": s.order_id,
                "status": s.status,
                "courier": s.courier or "",
                "eta": s.eta or "",
                # ``deliveredAt`` is unset for in-flight shipments. Phase 16B
                # frontend renders this only when status == "Delivered"; we
                # expose ``createdAt`` instead so the table shows a sensible
                # date column either way.
                "deliveredAt": "",
                "createdAt": s.created_at.isoformat() if getattr(s, "created_at", None) else "",
                "trackingUrl": s.tracking_url or "",
            }

        return Response(
            {
                "customerId": customer.id,
                "calls": [_call_dict(c) for c in calls],
                "orders": [_order_dict(o) for o in orders],
                "payments": [_payment_dict(p) for p in payments],
                "shipments": [_shipment_dict(s) for s in shipments],
            }
        )


class LeadImportCsvView(APIView):
    """Phase 16B — CSV Lead Import endpoint.

    POST ``/api/leads/import-csv/`` with payload::

        { "csv": "<raw csv string>", "source": "<optional source label>" }

    Returns a summary with ``createdCount`` / ``duplicateCount`` /
    ``errorCount`` plus a sanitised ``rowErrors`` list (phones masked to
    last-4). The handler NEVER sends WhatsApp, NEVER calls a customer,
    NEVER triggers any external provider — it only inserts Lead rows via
    ``services.create_lead`` (which itself enforces phone/email dedup).
    """

    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def post(self, request):
        payload = LeadImportCsvPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        raw_csv = payload.validated_data["csv"]
        default_source = payload.validated_data.get("source") or "CSV Import"
        result = services.import_leads_csv(
            raw_csv=raw_csv,
            by_user=request.user,
            default_source=default_source,
        )
        return Response(
            LeadImportResultSerializer(result).data,
            status=status.HTTP_200_OK,
        )
