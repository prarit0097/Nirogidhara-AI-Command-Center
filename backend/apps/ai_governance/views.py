from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CaioAudit, CeoBriefing
from .serializers import CaioAuditSerializer, CeoBriefingSerializer


class CeoBriefingView(APIView):
    """Latest briefing only — frontend treats this as the daily brief."""

    def get(self, _request):
        briefing = CeoBriefing.objects.order_by("-updated_at").first()
        if briefing is None:
            return Response(
                {
                    "date": "",
                    "headline": "",
                    "summary": "",
                    "recommendations": [],
                    "alerts": [],
                }
            )
        return Response(CeoBriefingSerializer(briefing).data)


class CaioAuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = CaioAudit.objects.all()
    serializer_class = CaioAuditSerializer
    pagination_class = None
