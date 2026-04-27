from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PaymentLinkView, PaymentViewSet

router = DefaultRouter()
router.register("", PaymentViewSet, basename="payment")

urlpatterns = [
    path("links/", PaymentLinkView.as_view(), name="payment-link-create"),
] + router.urls
