"""Phase 6C — Org-Scoped API Filtering Plan.

Active-organization resolution + safe queryset scoping helpers. Every
function in this module is read-only — no DB writes, no audit rows.

LOCKED rules for this phase:

- Resolvers fall back to the seeded default organization when no
  membership exists, so single-tenant production keeps working
  unchanged.
- Inactive / archived organizations are NEVER returned to a normal
  caller (they are still resolvable through the default-org path
  if the default org itself is inactive — that's a deliberate
  diagnostic surface).
- Queryset scoping is OPT-IN — call sites explicitly invoke the
  helpers. Phase 6C does NOT add a global queryset-filtering
  middleware; that's Phase 6D / 6E.
- Models without an ``organization`` field are returned unchanged
  by the helpers. Callers that need to scope a queryset built
  on such a model must do so explicitly.
"""
from __future__ import annotations

from typing import Optional

from django.db.models import QuerySet

from .models import (
    Branch,
    Organization,
    OrganizationMembership,
)
from .selectors import (
    DEFAULT_ORGANIZATION_CODE,
    get_default_branch as _get_default_branch_selector,
    get_default_organization as _get_default_org_selector,
)


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


def get_default_organization() -> Optional[Organization]:
    """Re-export of the Phase 6A selector for ergonomics."""
    return _get_default_org_selector()


def get_default_branch() -> Optional[Branch]:
    """Re-export of the Phase 6A selector for ergonomics."""
    return _get_default_branch_selector()


def get_user_active_organization(user) -> Optional[Organization]:
    """Resolve the user's primary active organization.

    Lookup order:

    1. The first ``OrganizationMembership(status=ACTIVE)`` for the user
       whose organization is itself ``ACTIVE``.
    2. If the user is staff / superuser and has no membership, fall
       back to the default organization (existing single-tenant
       admins keep their current view).
    3. Otherwise fall back to the default org as well — Phase 6C must
       not break logins for users who have not yet been attached to a
       membership.

    Returns ``None`` only when the default org itself is missing
    (operator must run ``ensure_default_organization``).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    membership = (
        OrganizationMembership.objects.filter(
            user=user,
            status=OrganizationMembership.Status.ACTIVE,
            organization__status=Organization.Status.ACTIVE,
        )
        .select_related("organization")
        .order_by("organization__name")
        .first()
    )
    if membership is not None:
        return membership.organization
    return _get_default_org_selector()


def get_user_active_branch(
    user, organization: Optional[Organization] = None
) -> Optional[Branch]:
    """Resolve the user's active branch within an organization.

    Phase 6C does not store a per-user "active branch" preference — we
    return the default branch (``code='main'``) under the resolved org.
    Future phases may add user-specific branch selection.
    """
    org = organization or get_user_active_organization(user)
    if org is None:
        return None
    branch = (
        Branch.objects.filter(
            organization=org,
            status=Branch.Status.ACTIVE,
        )
        .order_by("code")
        .first()
    )
    if branch is not None:
        return branch
    # Last-resort fallback to the seeded default branch (single-tenant
    # backstop — same reasoning as the org resolver).
    return _get_default_branch_selector()


def resolve_request_organization(request) -> Optional[Organization]:
    """Resolve the active organization for a DRF request.

    Order:

    1. ``request.organization`` if a future middleware has stamped it.
    2. ``get_user_active_organization(request.user)``.
    3. Default org fallback for unauthenticated requests is NOT
       provided — DRF auth must be enforced at the view layer.
    """
    if request is None:
        return None
    pre = getattr(request, "organization", None)
    if isinstance(pre, Organization):
        return pre
    user = getattr(request, "user", None)
    return get_user_active_organization(user)


def resolve_request_branch(
    request, organization: Optional[Organization] = None
) -> Optional[Branch]:
    if request is None:
        return None
    pre = getattr(request, "branch", None)
    if isinstance(pre, Branch):
        return pre
    user = getattr(request, "user", None)
    org = organization or resolve_request_organization(request)
    return get_user_active_branch(user, organization=org)


def user_has_org_access(user, organization: Optional[Organization]) -> bool:
    """``True`` when the user belongs to the org (active membership) or
    is a superuser. Default-org members are treated like real members
    once the membership row is created."""
    if user is None or organization is None:
        return False
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return OrganizationMembership.objects.filter(
        user=user,
        organization=organization,
        status=OrganizationMembership.Status.ACTIVE,
    ).exists()


# ---------------------------------------------------------------------------
# Queryset helpers
# ---------------------------------------------------------------------------


def model_has_organization_field(model) -> bool:
    try:
        model._meta.get_field("organization")
    except Exception:  # noqa: BLE001 - model may not have the FK
        return False
    return True


def filter_queryset_by_organization(
    queryset: QuerySet, organization: Optional[Organization]
) -> QuerySet:
    """Filter ``queryset`` by ``organization`` if both:

    - the queryset's model has an ``organization`` field, and
    - ``organization`` is not None.

    Otherwise the queryset is returned unchanged. The helper deliberately
    NEVER raises — callers can wrap any queryset and the behaviour is a
    no-op when the model is global / system-level.
    """
    if organization is None:
        return queryset
    model = getattr(queryset, "model", None)
    if model is None:
        return queryset
    if not model_has_organization_field(model):
        return queryset
    return queryset.filter(organization=organization)


def attach_default_org_filter_if_model_supports_org(
    queryset: QuerySet,
) -> QuerySet:
    """For background / system code that wants single-tenant semantics
    without resolving a user. No-op when the default org doesn't exist."""
    org = get_default_organization()
    return filter_queryset_by_organization(queryset, org)


def scoped_queryset_for_user(
    queryset: QuerySet,
    user,
    organization: Optional[Organization] = None,
) -> QuerySet:
    """Scope ``queryset`` to the user's active organization.

    Phase 6C semantics:

    - If the model has no ``organization`` field → return as-is.
    - If the user is a superuser → return as-is (cross-tenant
      visibility for diagnostics; Phase 6E will tighten this).
    - Otherwise, return ``queryset.filter(organization=<active org>)``.
    """
    model = getattr(queryset, "model", None)
    if model is None or not model_has_organization_field(model):
        return queryset
    if user is not None and getattr(user, "is_superuser", False):
        return queryset
    org = organization or get_user_active_organization(user)
    if org is None:
        return queryset
    return queryset.filter(organization=org)


def scoped_queryset_for_request(
    queryset: QuerySet, request
) -> QuerySet:
    user = getattr(request, "user", None)
    org = resolve_request_organization(request)
    return scoped_queryset_for_user(queryset, user, organization=org)


__all__ = (
    "DEFAULT_ORGANIZATION_CODE",
    "get_default_organization",
    "get_default_branch",
    "get_user_active_organization",
    "get_user_active_branch",
    "resolve_request_organization",
    "resolve_request_branch",
    "user_has_org_access",
    "model_has_organization_field",
    "filter_queryset_by_organization",
    "attach_default_org_filter_if_model_supports_org",
    "scoped_queryset_for_user",
    "scoped_queryset_for_request",
)
