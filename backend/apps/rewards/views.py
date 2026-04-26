from __future__ import annotations

from rest_framework import mixins, viewsets

from .models import RewardPenalty
from .serializers import RewardPenaltySerializer


class RewardPenaltyViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = RewardPenalty.objects.all()
    serializer_class = RewardPenaltySerializer
    pagination_class = None
