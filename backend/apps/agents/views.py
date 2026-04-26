from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Agent
from .serializers import AgentSerializer


class AgentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer
    pagination_class = None


class AgentHierarchyView(APIView):
    """Match the inline hierarchy shape returned by `getAgentHierarchy()`."""

    def get(self, _request):
        agents = AgentSerializer(Agent.objects.all(), many=True).data
        departments = [a for a in agents if a["id"] not in {"ceo", "caio"}]
        return Response(
            {
                "root": "Prarit Sidana (Director)",
                "ceo": "CEO AI Agent",
                "caio": "CAIO Agent",
                "departments": departments,
            }
        )
