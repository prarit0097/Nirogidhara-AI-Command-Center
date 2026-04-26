from __future__ import annotations

from rest_framework import serializers

from .models import LearningRecording


class LearningRecordingSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningRecording
        fields = ("id", "agent", "duration", "date", "stage", "qa", "compliance", "outcome")
