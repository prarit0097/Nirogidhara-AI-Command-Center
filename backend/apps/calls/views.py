from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission
from apps.crm.models import Lead

from . import services
from .integrations.vapi_client import VapiClientError
from .models import ActiveCall, Call
from .serializers import (
    ActiveCallSerializer,
    CallSerializer,
    CallTriggerSerializer,
    TranscriptLineSerializer,
)


class CallViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Call.objects.all()
    serializer_class = CallSerializer
    pagination_class = None


def _latest_active_call() -> ActiveCall | None:
    return ActiveCall.objects.order_by("-updated_at").first()


class ActiveCallView(APIView):
    def get(self, _request):
        call = _latest_active_call()
        if call is None:
            # Frontend expects an object; return a sensible empty default.
            return Response(
                {
                    "id": "",
                    "customer": "",
                    "phone": "",
                    "agent": "",
                    "language": "",
                    "duration": "0:00",
                    "stage": "",
                    "sentiment": "",
                    "scriptCompliance": 0,
                    "transcript": [],
                    "detectedObjections": [],
                    "approvedClaimsUsed": [],
                }
            )
        return Response(ActiveCallSerializer(call).data)


class ActiveCallTranscriptView(APIView):
    def get(self, _request):
        call = _latest_active_call()
        lines = call.transcript_lines.all() if call else []
        return Response(TranscriptLineSerializer(lines, many=True).data)


class _GatewayUnavailable(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "voice provider unavailable"
    default_code = "vapi_unavailable"


class CallTriggerView(APIView):
    """``POST /api/calls/trigger/`` — start a Vapi outbound call for a lead.

    Request body: ``{ leadId, purpose? }``. Returns the Call row + Vapi
    provider id. Mock mode (``VAPI_MODE=mock``) keeps this network-free.
    """

    permission_classes = [RoleBasedPermission]
    allowed_write_roles = OPERATIONS_AND_UP

    def post(self, request):
        payload = CallTriggerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lead_id = payload.validated_data["leadId"]
        purpose = payload.validated_data.get("purpose", "sales_call")

        try:
            lead = Lead.objects.get(pk=lead_id)
        except Lead.DoesNotExist as exc:
            raise NotFound(f"Lead {lead_id} not found") from exc

        try:
            call = services.trigger_call_for_lead(
                lead=lead, by_user=request.user, purpose=purpose
            )
        except VapiClientError as exc:
            raise _GatewayUnavailable(detail=str(exc)) from exc

        return Response(
            {
                "callId": call.id,
                "provider": call.provider,
                "status": call.status.lower(),
                "leadId": call.lead_id,
                "providerCallId": call.provider_call_id,
            },
            status=status.HTTP_201_CREATED,
        )
