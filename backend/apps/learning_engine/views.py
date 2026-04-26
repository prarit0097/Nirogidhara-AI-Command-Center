from __future__ import annotations

from rest_framework import mixins, viewsets

from .models import LearningRecording
from .serializers import LearningRecordingSerializer


class LearningRecordingViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = LearningRecording.objects.all()
    serializer_class = LearningRecordingSerializer
    pagination_class = None
