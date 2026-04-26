from __future__ import annotations

from django.urls import path

from .views import RtoRiskView

urlpatterns = [
    path("risk/", RtoRiskView.as_view({"get": "list"}), name="rto-risk"),
]
