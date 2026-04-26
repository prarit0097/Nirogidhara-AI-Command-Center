from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ActiveCall, Call
from .serializers import ActiveCallSerializer, CallSerializer, TranscriptLineSerializer


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
