from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from .models import KPITrend
from .serializers import KPITrendSerializer


def _series(name: str) -> list[dict]:
    qs = KPITrend.objects.filter(series=name).order_by("sort_order")
    return KPITrendSerializer(qs, many=True).data


class FunnelView(APIView):
    def get(self, _request):
        return Response(_series(KPITrend.Series.FUNNEL))


class RevenueTrendView(APIView):
    def get(self, _request):
        return Response(_series(KPITrend.Series.REVENUE))


class StateRtoView(APIView):
    def get(self, _request):
        return Response(_series(KPITrend.Series.STATE_RTO))


class ProductPerformanceView(APIView):
    def get(self, _request):
        return Response(_series(KPITrend.Series.PRODUCT_PERFORMANCE))


class AnalyticsCompositeView(APIView):
    """Bundles every analytics series + the discount impact study used by
    the Analytics page. Mirrors `getAnalyticsData()` in api.ts."""

    def get(self, _request):
        return Response(
            {
                "funnel": _series(KPITrend.Series.FUNNEL),
                "revenueTrend": _series(KPITrend.Series.REVENUE),
                "stateRto": _series(KPITrend.Series.STATE_RTO),
                "productPerformance": _series(KPITrend.Series.PRODUCT_PERFORMANCE),
                "discountImpact": [
                    {"discount": "0%", "delivered": 62, "rto": 18},
                    {"discount": "10%", "delivered": 71, "rto": 14},
                    {"discount": "15%", "delivered": 78, "rto": 12},
                    {"discount": "20%", "delivered": 81, "rto": 14},
                    {"discount": "25%", "delivered": 76, "rto": 22},
                    {"discount": "30%", "delivered": 64, "rto": 31},
                ],
            }
        )
