from __future__ import annotations

from django.urls import path

from .views import (
    CurrentOrganizationView,
    FeatureFlagsView,
    MyOrganizationsView,
)


urlpatterns = [
    path(
        "current-organization/",
        CurrentOrganizationView.as_view(),
        name="saas-current-organization",
    ),
    path(
        "my-organizations/",
        MyOrganizationsView.as_view(),
        name="saas-my-organizations",
    ),
    path(
        "feature-flags/",
        FeatureFlagsView.as_view(),
        name="saas-feature-flags",
    ),
]
