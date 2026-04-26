from __future__ import annotations

from django.urls import path

from .views import LearningRecordingViewSet

urlpatterns = [
    path("recordings/", LearningRecordingViewSet.as_view({"get": "list"}), name="learning-recordings"),
]
