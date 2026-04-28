from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    RewardPenaltyEventListView,
    RewardPenaltySummaryView,
    RewardPenaltySweepView,
    RewardPenaltyViewSet,
)

router = DefaultRouter()
router.register("", RewardPenaltyViewSet, basename="reward")

# Phase 4B routes are mounted explicitly so the /api/rewards/ list at
# ``RewardPenaltyViewSet`` keeps its public read behaviour unchanged.
urlpatterns = [
    path("events/", RewardPenaltyEventListView.as_view(), name="reward-events"),
    path("summary/", RewardPenaltySummaryView.as_view(), name="reward-summary"),
    path("sweep/", RewardPenaltySweepView.as_view(), name="reward-sweep"),
] + router.urls
