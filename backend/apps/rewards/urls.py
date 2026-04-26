from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .views import RewardPenaltyViewSet

router = DefaultRouter()
router.register("", RewardPenaltyViewSet, basename="reward")

urlpatterns = router.urls
