"""Phase 6A — SaaS Foundation read-only DRF endpoints.

Three endpoints under ``/api/v1/saas/``:

- ``GET /api/v1/saas/current-organization/`` — the user's active org.
- ``GET /api/v1/saas/my-organizations/`` — every active org the user
  belongs to (or the default org as a fallback).
- ``GET /api/v1/saas/feature-flags/`` — non-sensitive feature flag map
  for the user's current org.

All endpoints require an authenticated user. None of them mutate state.
``OrganizationSetting`` rows flagged ``is_sensitive=True`` never appear
in any response.
"""
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .admin_readiness import get_saas_admin_overview
from .coverage import compute_default_organization_coverage
from .integration_runtime import get_all_provider_runtime_previews
from .integration_settings import (
    get_org_integration_readiness,
    get_org_integration_settings,
    serialize_integration_setting,
)
from .readiness import compute_org_scoped_api_readiness
from .write_readiness import compute_org_write_path_readiness
from .models import Organization, OrganizationIntegrationSetting
from .selectors import (
    get_active_organization_for_user,
    get_default_organization,
    get_default_branch,
    get_organization_feature_flags,
    get_organization_membership_summary,
    get_user_organizations,
    get_user_role_in_organization,
    get_non_sensitive_settings,
)


class AdminSaasPermission(BasePermission):
    """Staff/superuser/global director/admin only."""

    def has_permission(self, request, view):
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(
            user, "is_superuser", False
        ):
            return True
        role = getattr(user, "role", "")
        return role in {"director", "admin"}


def _serialize_organization(
    org: Organization | None,
    *,
    user=None,
) -> dict[str, Any] | None:
    """Common, secret-free serialization shape."""
    if org is None:
        return None
    branch = None
    default_branch = (
        org.branches.filter(code="main").first()
        if hasattr(org, "branches")
        else None
    )
    if default_branch is not None:
        branch = {
            "id": default_branch.id,
            "code": default_branch.code,
            "name": default_branch.name,
            "status": default_branch.status,
        }
    role = ""
    if user is not None:
        role = get_user_role_in_organization(user, org)
    return {
        "id": org.id,
        "code": org.code,
        "name": org.name,
        "legalName": org.legal_name,
        "status": org.status,
        "timezone": org.timezone,
        "country": org.country,
        "defaultBranch": branch,
        "userOrgRole": role,
        "createdAt": (
            org.created_at.isoformat() if org.created_at else None
        ),
    }


class CurrentOrganizationView(APIView):
    """``GET /api/v1/saas/current-organization/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = get_active_organization_for_user(user)
        payload: dict[str, Any] = {
            "organization": _serialize_organization(org, user=user),
            "membershipSummary": (
                get_organization_membership_summary(org)
                if org is not None
                else {"total": 0, "active": 0, "byRole": {}}
            ),
            "settings": get_non_sensitive_settings(org),
            "featureFlags": get_organization_feature_flags(org),
        }
        return Response(payload)


class MyOrganizationsView(APIView):
    """``GET /api/v1/saas/my-organizations/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        orgs = get_user_organizations(user)
        return Response(
            {
                "count": len(orgs),
                "organizations": [
                    _serialize_organization(org, user=user) for org in orgs
                ],
            }
        )


class FeatureFlagsView(APIView):
    """``GET /api/v1/saas/feature-flags/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = get_active_organization_for_user(user)
        return Response(
            {
                "organization": _serialize_organization(org, user=user),
                "featureFlags": get_organization_feature_flags(org),
            }
        )


class DataCoverageView(APIView):
    """``GET /api/v1/saas/data-coverage/`` — Phase 6B coverage report.

    Read-only. Mirrors the ``inspect_default_organization_coverage``
    management command's JSON output. Auth required; the response
    carries no secrets and no full phone numbers (it's row counts only).
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(compute_default_organization_coverage())


class OrgScopeReadinessView(APIView):
    """``GET /api/v1/saas/org-scope-readiness/`` — Phase 6C diagnostic.

    Read-only. Mirrors the ``inspect_org_scoped_api_readiness``
    management command. Auth required; carries no secrets / no PII.
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(compute_org_scoped_api_readiness())


class WritePathReadinessView(APIView):
    """``GET /api/v1/saas/write-path-readiness/`` — Phase 6D diagnostic.

    Read-only. Mirrors the ``inspect_org_write_path_readiness``
    management command. Auth required; carries no secrets / no PII.
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(compute_org_write_path_readiness())


def _get_admin_org(request) -> Organization | None:
    org_id = request.query_params.get("organizationId")
    if org_id:
        return Organization.objects.filter(id=org_id).first()
    return get_default_organization()


def _integration_payload(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "providerType": "provider_type",
        "status": "status",
        "displayName": "display_name",
        "config": "config",
        "secretRefs": "secret_refs",
        "isActive": "is_active",
        "lastValidatedAt": "last_validated_at",
        "validationStatus": "validation_status",
        "validationMessage": "validation_message",
        "metadata": "metadata",
    }
    payload: dict[str, Any] = {}
    for source, target in allowed.items():
        if source in data:
            payload[target] = data[source]
    return payload


class SaasAdminOverviewView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(get_saas_admin_overview())


class SaasAdminOrganizationsView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request):
        orgs = Organization.objects.order_by("name")
        return Response(
            {
                "count": orgs.count(),
                "organizations": [
                    _serialize_organization(org, user=request.user)
                    | {
                        "membershipSummary": (
                            get_organization_membership_summary(org)
                        ),
                        "featureFlags": get_organization_feature_flags(org),
                        "integrationSettingsCount": (
                            org.integration_settings.count()
                        ),
                    }
                    for org in orgs
                ],
            }
        )


class SaasAdminOrganizationDetailView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request, organization_id):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            return Response(
                {"detail": "Organization not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "organization": _serialize_organization(org, user=request.user),
                "membershipSummary": get_organization_membership_summary(org),
                "featureFlags": get_organization_feature_flags(org),
                "integrationSettings": get_org_integration_settings(org),
                "integrationReadiness": get_org_integration_readiness(org),
            }
        )


class SaasIntegrationSettingsView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(
            {
                "organization": _serialize_organization(
                    org,
                    user=request.user,
                ),
                "settings": get_org_integration_settings(org),
                "runtimeUsesPerOrgSettings": False,
            }
        )

    def post(self, request):
        org_id = request.data.get("organizationId")
        org = (
            Organization.objects.filter(id=org_id).first()
            if org_id
            else get_default_organization()
        )
        if org is None:
            return Response(
                {"detail": "Organization not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = _integration_payload(dict(request.data))
        payload["organization"] = org
        try:
            setting = OrganizationIntegrationSetting.objects.create(**payload)
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            serialize_integration_setting(setting),
            status=status.HTTP_201_CREATED,
        )


class SaasIntegrationSettingDetailView(APIView):
    permission_classes = [AdminSaasPermission]

    def patch(self, request, setting_id):
        setting = OrganizationIntegrationSetting.objects.filter(
            id=setting_id
        ).first()
        if setting is None:
            return Response(
                {"detail": "Integration setting not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = _integration_payload(dict(request.data))
        payload.pop("provider_type", None)
        for field, value in payload.items():
            setattr(setting, field, value)
        try:
            setting.save()
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_integration_setting(setting))


class SaasIntegrationReadinessView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(get_org_integration_readiness(org))


class RuntimeRoutingReadinessView(APIView):
    """``GET /api/v1/saas/runtime-routing-readiness/`` — Phase 6F preview.

    Read-only. Returns the per-provider runtime preview for the current
    admin's organization (or the default org). Strict invariants:

    - ``runtimeUsesPerOrgSettings=False`` always in this phase.
    - No raw secrets returned. ENV: refs return presence (true/false)
      and a masked label only.
    - No external provider calls.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(get_all_provider_runtime_previews(org))


__all__ = (
    "CurrentOrganizationView",
    "MyOrganizationsView",
    "FeatureFlagsView",
    "DataCoverageView",
    "OrgScopeReadinessView",
    "WritePathReadinessView",
    "SaasAdminOverviewView",
    "SaasAdminOrganizationsView",
    "SaasAdminOrganizationDetailView",
    "SaasIntegrationSettingsView",
    "SaasIntegrationSettingDetailView",
    "SaasIntegrationReadinessView",
    "RuntimeRoutingReadinessView",
)
