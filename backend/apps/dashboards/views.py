from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditEvent

from .models import DashboardMetric
from .serializers import ActivityEventSerializer, DashboardMetricSerializer


class DashboardMetricsView(APIView):
    """Returns the Record<string, DashboardMetric> the frontend dashboard
    expects (keyed by KPI name)."""

    def get(self, _request):
        metrics = {
            row.key: DashboardMetricSerializer(row).data for row in DashboardMetric.objects.all()
        }
        return Response(metrics)


class ActivityFeedView(APIView):
    def get(self, _request):
        recent = AuditEvent.objects.order_by("-occurred_at")[:25]
        return Response(ActivityEventSerializer(recent, many=True).data)
