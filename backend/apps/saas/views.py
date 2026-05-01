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

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .coverage import compute_default_organization_coverage
from .models import Organization, OrganizationMembership
from .selectors import (
    get_active_organization_for_user,
    get_default_branch,
    get_organization_feature_flags,
    get_organization_membership_summary,
    get_user_organizations,
    get_user_role_in_organization,
    get_non_sensitive_settings,
)


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


__all__ = (
    "CurrentOrganizationView",
    "MyOrganizationsView",
    "FeatureFlagsView",
    "DataCoverageView",
)
