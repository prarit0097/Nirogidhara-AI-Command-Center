"""Phase 16E — Integration Hardening read-only API.

Two GET endpoints under ``/api/v1/integrations/payment-logistics/``:
  - ``readiness/``      — payment + logistics readiness + safety summary + gates
  - ``recent-events/``  — recent payment + shipment records (masked, safe display)

Both are strictly read-only. There is NO POST test-payment / test-shipment
endpoint in Phase 16E — per the directive's "if test actions are unsafe or
unclear, do not implement POST actions; return read-only readiness only".
Existing safe mock flows (``POST /api/payments/links/``, ``POST /api/shipments/``)
are unchanged except for the explicit-mode hardening on the shipment view.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .permissions import IsAuthenticatedReadOnly


class PaymentLogisticsReadinessView(APIView):
    """``GET /api/v1/integrations/payment-logistics/readiness/`` — read-only."""

    permission_classes = [IsAuthenticatedReadOnly]

    def get(self, request):
        return Response(services.payment_logistics_readiness())


class PaymentLogisticsRecentEventsView(APIView):
    """``GET /api/v1/integrations/payment-logistics/recent-events/`` — read-only."""

    permission_classes = [IsAuthenticatedReadOnly]

    def get(self, request):
        raw = request.query_params.get("limit")
        try:
            limit = int(raw) if raw is not None else 25
        except (TypeError, ValueError):
            limit = 25
        return Response(services.recent_events(limit=limit))
