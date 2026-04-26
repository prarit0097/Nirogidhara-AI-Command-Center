from __future__ import annotations

from django.urls import path

from .views import ClaimViewSet

urlpatterns = [
    path("claims/", ClaimViewSet.as_view({"get": "list"}), name="claim-vault"),
]
