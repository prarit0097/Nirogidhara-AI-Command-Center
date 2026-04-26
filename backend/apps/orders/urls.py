from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ConfirmationQueueView, OrderViewSet

router = DefaultRouter()
router.register("orders", OrderViewSet, basename="order")

urlpatterns = router.urls + [
    path(
        "confirmation/queue/",
        ConfirmationQueueView.as_view({"get": "list"}),
        name="confirmation-queue",
    ),
]
