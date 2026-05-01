"""Phase 6A — SaaS Foundation read-only selectors.

Tenant-context lookups consumed by the new DRF endpoints and any
downstream service that needs the default org without reaching for the
DB directly. None of these helpers mutate state.

Default-org constants:

- ``DEFAULT_ORGANIZATION_CODE`` = ``"nirogidhara"``
- ``DEFAULT_BRANCH_CODE`` = ``"main"``

The constants drive the ``ensure_default_organization`` management
command + every "give me a sane fallback" code path so the existing
single-tenant production keeps working when a request doesn't carry an
organization context.
"""
from __future__ import annotations

from typing import Iterable

from django.contrib.auth import get_user_model

from .models import (
    Branch,
    Organization,
    OrganizationFeatureFlag,
    OrganizationMembership,
    OrganizationSetting,
)


DEFAULT_ORGANIZATION_CODE: str = "nirogidhara"
DEFAULT_ORGANIZATION_NAME: str = "Nirogidhara Private Limited"
DEFAULT_ORGANIZATION_LEGAL_NAME: str = "Nirogidhara Private Limited"
DEFAULT_BRANCH_CODE: str = "main"
DEFAULT_BRANCH_NAME: str = "Main Branch"


def get_default_organization() -> Organization | None:
    """Return the seeded default organization (or ``None`` if not seeded yet)."""
    return Organization.objects.filter(code=DEFAULT_ORGANIZATION_CODE).first()


def get_default_branch() -> Branch | None:
    """Return the seeded default branch under the default organization."""
    org = get_default_organization()
    if org is None:
        return None
    return Branch.objects.filter(
        organization=org,
        code=DEFAULT_BRANCH_CODE,
    ).first()


def get_user_organizations(user) -> list[Organization]:
    """Every active organization the user is an active member of.

    Falls back to ``[default_org]`` when the user has no membership rows
    yet — Phase 6A keeps existing logins working under the default org
    even before memberships are explicitly granted.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    qs = (
        Organization.objects.filter(
            memberships__user=user,
            memberships__status=OrganizationMembership.Status.ACTIVE,
            status=Organization.Status.ACTIVE,
        )
        .distinct()
        .order_by("name")
    )
    orgs = list(qs)
    if orgs:
        return orgs
    default = get_default_organization()
    return [default] if default is not None else []


def get_active_organization_for_user(user) -> Organization | None:
    """Pick the user's primary org. Phase 6A returns the first match
    deterministically (alphabetical by name), or the default org as a
    fallback. Phase 6B+ may add a per-user "active org" preference.
    """
    orgs = get_user_organizations(user)
    return orgs[0] if orgs else None


def get_user_role_in_organization(user, organization: Organization) -> str:
    """Return the user's org-level role in ``organization`` or ``""``.

    Empty string means "no membership" — callers should assume the user
    has no in-org privileges. The user-level :attr:`User.role` still
    governs global API permissions independently.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    if organization is None:
        return ""
    membership = OrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=OrganizationMembership.Status.ACTIVE,
    ).first()
    return membership.role if membership is not None else ""


def get_organization_feature_flags(
    organization: Organization | None,
) -> dict[str, dict]:
    """Return ``{key: {"enabled": bool, "config": dict}}`` for the org.

    Returns an empty dict when ``organization`` is ``None``. ``config``
    is the row's JSON payload — never assume secrets live here.
    """
    if organization is None:
        return {}
    flags: dict[str, dict] = {}
    for flag in OrganizationFeatureFlag.objects.filter(
        organization=organization
    ):
        flags[flag.key] = {
            "enabled": bool(flag.enabled),
            "config": dict(flag.config or {}),
        }
    return flags


def is_feature_enabled(
    organization: Organization | None,
    key: str,
    default: bool = False,
) -> bool:
    """Boolean lookup. Returns ``default`` if the flag doesn't exist."""
    if organization is None or not key:
        return bool(default)
    flag = OrganizationFeatureFlag.objects.filter(
        organization=organization, key=key
    ).first()
    if flag is None:
        return bool(default)
    return bool(flag.enabled)


def get_non_sensitive_settings(
    organization: Organization | None,
) -> dict[str, object]:
    """Return ``{key: value}`` for non-sensitive settings only.

    Sensitive settings (``is_sensitive=True``) are intentionally OMITTED
    from the public-API surface. Ops scripts that legitimately need them
    must read :class:`OrganizationSetting` directly via the ORM.
    """
    if organization is None:
        return {}
    out: dict[str, object] = {}
    for setting in OrganizationSetting.objects.filter(
        organization=organization,
        is_sensitive=False,
    ):
        out[setting.key] = setting.value
    return out


def get_organization_membership_summary(
    organization: Organization,
) -> dict:
    """Counts of members by role + active count. Useful for the future
    SaaS admin panel; safe to expose since it carries no PII.
    """
    if organization is None:
        return {"total": 0, "active": 0, "byRole": {}}
    qs = OrganizationMembership.objects.filter(organization=organization)
    total = qs.count()
    active = qs.filter(status=OrganizationMembership.Status.ACTIVE).count()
    by_role: dict[str, int] = {}
    for row in qs.values_list("role", flat=True):
        by_role[row] = by_role.get(row, 0) + 1
    return {"total": total, "active": active, "byRole": by_role}


__all__ = (
    "DEFAULT_ORGANIZATION_CODE",
    "DEFAULT_ORGANIZATION_NAME",
    "DEFAULT_ORGANIZATION_LEGAL_NAME",
    "DEFAULT_BRANCH_CODE",
    "DEFAULT_BRANCH_NAME",
    "get_default_organization",
    "get_default_branch",
    "get_user_organizations",
    "get_active_organization_for_user",
    "get_user_role_in_organization",
    "get_organization_feature_flags",
    "is_feature_enabled",
    "get_non_sensitive_settings",
    "get_organization_membership_summary",
)
