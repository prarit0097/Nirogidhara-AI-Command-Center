from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ActiveCallTranscriptView, ActiveCallView, CallViewSet

router = DefaultRouter()
router.register("", CallViewSet, basename="call")

urlpatterns = [
    path("active/", ActiveCallView.as_view(), name="active-call"),
    path("active/transcript/", ActiveCallTranscriptView.as_view(), name="active-call-transcript"),
] + router.urls
