from __future__ import annotations

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UserSerializer


class MeView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# Read-only mock for /api/settings/. Mirrors the shape getSettingsMock() returns
# in the frontend service layer (approval matrix + integration flags).
class SettingsView(APIView):
    permission_classes = (AllowAny,)

    def get(self, _request):
        return Response(
            {
                "approvalMatrix": [
                    {"action": "Lead call", "approval": "Auto"},
                    {"action": "Payment link send", "approval": "Auto"},
                    {"action": "10% discount", "approval": "Auto within rules"},
                    {"action": "30% discount", "approval": "CEO AI approval or rule-based limit"},
                    {"action": "New medical claim", "approval": "Doctor + Compliance approval"},
                    {"action": "New ad creative", "approval": "CEO/Prarit initially"},
                    {"action": "Ad budget increase", "approval": "Prarit approval"},
                    {"action": "Refund", "approval": "Human/Prarit approval"},
                    {"action": "Emergency case", "approval": "Human/doctor handoff"},
                ],
                "integrations": [
                    {"name": "Vapi", "status": "planned", "category": "Voice AI"},
                    {"name": "Razorpay", "status": "planned", "category": "Payments"},
                    {"name": "PayU", "status": "planned", "category": "Payments"},
                    {"name": "Delhivery", "status": "planned", "category": "Courier"},
                    {"name": "Meta Lead Ads", "status": "planned", "category": "Ads"},
                ],
                "killSwitch": {
                    "aiCalling": "active",
                    "paymentLinks": "active",
                    "autoDispatch": "active",
                    "autoDiscount": "active",
                    "campaignRecommendations": "active",
                },
            }
        )
