from __future__ import annotations

from rest_framework import mixins, viewsets

from .models import Claim
from .serializers import ClaimSerializer


class ClaimViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Claim.objects.all()
    serializer_class = ClaimSerializer
    pagination_class = None
