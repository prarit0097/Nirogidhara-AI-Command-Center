from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import RescueAttemptViewSet, RtoRiskView

router = DefaultRouter()
router.register("rescue", RescueAttemptViewSet, basename="rescue-attempt")

urlpatterns = [
    path("risk/", RtoRiskView.as_view({"get": "list"}), name="rto-risk"),
] + router.urls
