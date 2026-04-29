from __future__ import annotations

from django.urls import path

from .views import ClaimVaultCoverageView, ClaimViewSet

urlpatterns = [
    path("claims/", ClaimViewSet.as_view({"get": "list"}), name="claim-vault"),
    # Phase 5D — coverage audit (admin / director only).
    path(
        "claim-coverage/",
        ClaimVaultCoverageView.as_view(),
        name="claim-vault-coverage",
    ),
]
