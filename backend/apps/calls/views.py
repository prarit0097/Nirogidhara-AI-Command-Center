from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import OPERATIONS_AND_UP, RoleBasedPermission
from apps.crm.models import Lead

from . import services
from .integrations.vapi_client import VapiClientError
from .models import ActiveCall, Call, CallTranscriptLine
from .serializers import (
    ActiveCallSerializer,
    CallSerializer,
    CallTriggerSerializer,
    TranscriptLineSerializer,
)
from .transcript_ingestion import (
    DEFAULT_WINDOW_DAYS,
    get_backlog_overview,
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


# ----- Phase 11A — Transcript ingestion read-only views -----


class _AdminTranscriptPermission(BasePermission):
    """Admin / director / owner / superuser only. Read-only routes."""

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = getattr(user, "role", "") or ""
        return role.lower() in {"admin", "director", "owner"}


def _parse_window_days(raw, default: int = DEFAULT_WINDOW_DAYS) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(1, min(180, value))


class TranscriptBacklogView(APIView):
    """``GET /api/v1/calls/transcript-backlog/?window_days=N``.

    Read-only backlog summary for the Director / operator dashboard.
    Returns total calls in window, ingested count, backlog count,
    backlog ratio, oldest + newest backlog, plus top-10 backlog ids
    (masked: id + created_at + provider_call_id last-4 only). No
    PII. Admin+ only. POST/PATCH/DELETE → 405.
    """

    permission_classes = [_AdminTranscriptPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        overview = get_backlog_overview(
            window_days=_parse_window_days(
                request.query_params.get("window_days")
            )
        )
        # Datetime → ISO strings so the JSON renderer sees a clean shape.
        result = dict(overview)
        for key in (
            "now",
            "window_start",
            "grace_cutoff_utc",
            "oldest_backlog_at",
            "newest_backlog_at",
        ):
            value = result.get(key)
            if value is not None:
                result[key] = value.isoformat()
        result["top_backlog"] = [
            {
                "callId": row["call_id"],
                "createdAt": row["created_at"].isoformat()
                if row["created_at"] is not None
                else None,
                "providerCallIdLast4": row["provider_call_id_last4"],
            }
            for row in overview["top_backlog"]
        ]
        return Response(result)


class CallTranscriptDetailView(APIView):
    """``GET /api/v1/calls/transcripts/<call_id>/``.

    Read-only list of ``CallTranscriptLine`` rows for one Call. Admin+
    only. POST/PATCH/DELETE → 405.
    """

    permission_classes = [_AdminTranscriptPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, _request, call_id: str):
        call = Call.objects.filter(pk=call_id).first()
        if call is None:
            raise NotFound(f"Call {call_id} not found")
        lines = (
            CallTranscriptLine.objects.filter(call=call)
            .order_by("order")
        )
        return Response(
            {
                "callId": call.id,
                "providerCallIdLast4": (call.provider_call_id or "")[-4:],
                "transcriptIngestedAt": (
                    call.transcript_ingested_at.isoformat()
                    if call.transcript_ingested_at is not None
                    else None
                ),
                "transcriptLineCount": int(call.transcript_line_count or 0),
                "lines": TranscriptLineSerializer(lines, many=True).data,
            }
        )
