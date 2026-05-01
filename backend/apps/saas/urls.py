from __future__ import annotations

from django.urls import path

from .views import (
    CurrentOrganizationView,
    DataCoverageView,
    FeatureFlagsView,
    MyOrganizationsView,
    OrgScopeReadinessView,
    SaasAdminOrganizationDetailView,
    SaasAdminOrganizationsView,
    SaasAdminOverviewView,
    SaasIntegrationReadinessView,
    SaasIntegrationSettingDetailView,
    SaasIntegrationSettingsView,
    WritePathReadinessView,
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
    path(
        "data-coverage/",
        DataCoverageView.as_view(),
        name="saas-data-coverage",
    ),
    path(
        "org-scope-readiness/",
        OrgScopeReadinessView.as_view(),
        name="saas-org-scope-readiness",
    ),
    path(
        "write-path-readiness/",
        WritePathReadinessView.as_view(),
        name="saas-write-path-readiness",
    ),
    path(
        "admin/overview/",
        SaasAdminOverviewView.as_view(),
        name="saas-admin-overview",
    ),
    path(
        "admin/organizations/",
        SaasAdminOrganizationsView.as_view(),
        name="saas-admin-organizations",
    ),
    path(
        "admin/organizations/<int:organization_id>/",
        SaasAdminOrganizationDetailView.as_view(),
        name="saas-admin-organization-detail",
    ),
    path(
        "admin/integration-settings/",
        SaasIntegrationSettingsView.as_view(),
        name="saas-admin-integration-settings",
    ),
    path(
        "admin/integration-settings/<int:setting_id>/",
        SaasIntegrationSettingDetailView.as_view(),
        name="saas-admin-integration-setting-detail",
    ),
    path(
        "admin/integration-readiness/",
        SaasIntegrationReadinessView.as_view(),
        name="saas-admin-integration-readiness",
    ),
]
