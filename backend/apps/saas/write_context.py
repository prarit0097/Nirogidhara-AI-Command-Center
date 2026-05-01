"""Phase 6D — Org-Aware Write Path Assignment helpers.

Helpers that resolve and apply ``organization`` / ``branch`` context to
new model instances during create flows. Designed to compose with the
Phase 6C read-side helpers in :mod:`apps.saas.context`.

LOCKED rules for this phase:

- Helpers are pure on input — they never persist; they mutate the
  instance only when explicitly invoked by a caller that will save it.
- Models without an ``organization`` field pass through unchanged —
  the helpers never raise on global / system-level models.
- Existing org / branch values are NEVER overwritten unless the caller
  passes ``overwrite=True`` (and even then, only when an alternative
  resolves cleanly).
- Org / branch FKs stay nullable — Phase 6D does not enforce
  presence; it only attempts to fill the gap on create.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.db.models import Model
from django.utils import timezone

from .context import (
    get_default_branch,
    get_default_organization,
    get_user_active_branch,
    get_user_active_organization,
    resolve_request_branch,
    resolve_request_organization,
    user_has_org_access,
)
from .models import Branch, Organization


class OrgWriteAccessError(PermissionError):
    """Raised when a user tries to write into an org they cannot access."""


# ---------------------------------------------------------------------------
# Core resolvers
# ---------------------------------------------------------------------------


def resolve_write_organization(
    request=None,
    user=None,
    explicit_organization: Optional[Organization] = None,
) -> Optional[Organization]:
    """Resolve the organization to assign to a newly created instance.

    Order:

    1. ``explicit_organization`` if the user has access (or no user is
       given — system / management-command callers).
    2. ``request`` via :func:`resolve_request_organization`.
    3. ``user`` via :func:`get_user_active_organization`.
    4. Default org fallback so single-tenant production keeps working.
    """
    if explicit_organization is not None:
        if user is None or user_has_org_access(user, explicit_organization):
            return explicit_organization
    if request is not None:
        org = resolve_request_organization(request)
        if org is not None:
            return org
    if user is not None:
        org = get_user_active_organization(user)
        if org is not None:
            return org
    return get_default_organization()


def resolve_write_branch(
    request=None,
    user=None,
    organization: Optional[Organization] = None,
    explicit_branch: Optional[Branch] = None,
) -> Optional[Branch]:
    """Resolve the branch to assign. Honours an explicit branch if it
    matches the resolved organization; otherwise falls back to the
    user's branch and finally the default branch."""
    if explicit_branch is not None:
        if (
            organization is None
            or explicit_branch.organization_id == organization.id
        ):
            return explicit_branch
    if request is not None:
        branch = resolve_request_branch(request, organization=organization)
        if branch is not None:
            return branch
    if user is not None:
        branch = get_user_active_branch(user, organization=organization)
        if branch is not None:
            return branch
    return get_default_branch()


# ---------------------------------------------------------------------------
# Field introspection
# ---------------------------------------------------------------------------


def _has_field(instance: Model, field_name: str) -> bool:
    try:
        instance._meta.get_field(field_name)
    except Exception:  # noqa: BLE001
        return False
    return True


# ---------------------------------------------------------------------------
# Apply / inheritance
# ---------------------------------------------------------------------------


def apply_org_branch(
    instance: Model,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    *,
    request=None,
    user=None,
    overwrite: bool = False,
) -> Model:
    """Assign ``organization`` and (optionally) ``branch`` to ``instance``.

    - Returns the same instance for chaining.
    - Does NOT save — caller is responsible for the persist step.
    - For models without an ``organization`` field, returns unchanged.
    - When ``overwrite=False`` (default), an already-set FK is preserved.
    - When the resolved value would be ``None`` (no default org yet),
      the existing value is left untouched — the helper is additive.
    """
    if not _has_field(instance, "organization"):
        return instance

    resolved_org = organization
    if resolved_org is None and (request is not None or user is not None):
        resolved_org = resolve_write_organization(
            request=request, user=user
        )

    if resolved_org is None:
        # Last-resort fallback. Same shape as the audit signal: silently
        # skip when nothing is resolvable.
        resolved_org = get_default_organization()

    if resolved_org is not None:
        existing_org_id = getattr(instance, "organization_id", None)
        if overwrite or existing_org_id is None:
            instance.organization = resolved_org

    if _has_field(instance, "branch"):
        resolved_branch = branch
        if resolved_branch is None:
            resolved_branch = resolve_write_branch(
                request=request,
                user=user,
                organization=resolved_org,
            )
        if resolved_branch is not None:
            existing_branch_id = getattr(instance, "branch_id", None)
            if overwrite or existing_branch_id is None:
                instance.branch = resolved_branch

    return instance


def validate_org_write_access(user, organization: Optional[Organization]) -> bool:
    """Validate that ``user`` may write into ``organization``.

    Internal/system creates continue to work: no user or no org means the
    caller is not denied here. Authenticated users with no org access are
    blocked so safe create paths can opt into stricter enforcement.
    """
    if organization is None:
        return True
    if user is None or not getattr(user, "is_authenticated", False):
        return True
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    if user_has_org_access(user, organization):
        return True
    raise OrgWriteAccessError(
        f"User {getattr(user, 'id', None)} cannot write to "
        f"organization {organization.id}."
    )


def _is_system_global_exception(instance: Model) -> bool:
    return bool(getattr(instance, "_saas_system_global", False))


def ensure_org_branch_before_save(
    instance: Model,
    request=None,
    user=None,
    parent=None,
) -> Model:
    """Fill org/branch before a safe create save without overwriting.

    Parent context wins, then request/user/default fallback. The helper
    never saves and never changes an already-set org/branch.
    """
    if not _has_field(instance, "organization"):
        return instance
    if _is_system_global_exception(instance):
        return instance

    if parent is not None:
        assign_org_branch_from_parent(instance, parent)
    else:
        assign_org_branch_from_first_parent(instance)

    apply_org_branch(instance, request=request, user=user)
    validate_org_write_access(user, getattr(instance, "organization", None))
    return instance


def enforce_org_on_create(
    instance: Model,
    request=None,
    user=None,
    parent=None,
) -> Model:
    """Strict wrapper for Phase 6E safe create paths.

    The nullable DB schema stays unchanged. This helper enforces org
    presence only when explicitly invoked by a safe path, with default
    org fallback preserving current single-tenant production behavior.
    """
    if not _has_field(instance, "organization"):
        return instance
    state = getattr(instance, "_state", None)
    if state is not None and not getattr(state, "adding", True):
        validate_org_write_access(user, getattr(instance, "organization", None))
        return instance
    if _is_system_global_exception(instance):
        return instance

    ensure_org_branch_before_save(
        instance,
        request=request,
        user=user,
        parent=parent,
    )
    if getattr(instance, "organization_id", None) is None:
        raise OrgWriteAccessError(
            f"{instance._meta.label} cannot be created without organization."
        )
    return instance


# Common parent attribute names ordered by preference for inheritance.
_PARENT_INHERITANCE_ATTRS: tuple[str, ...] = (
    "conversation",
    "message",
    "order",
    "shipment",
    "payment",
    "call",
    "customer",
    "lead",
)


def get_parent_org_branch(
    parent_instance,
) -> tuple[Optional[Organization], Optional[Branch]]:
    """Return ``(organization, branch)`` from the parent — either may be
    ``None`` if the parent itself has no value or no field. Safe on any
    object (``None`` returns ``(None, None)``)."""
    if parent_instance is None:
        return None, None
    organization = None
    branch = None
    if _has_field(parent_instance, "organization"):
        organization = getattr(parent_instance, "organization", None)
    if _has_field(parent_instance, "branch"):
        branch = getattr(parent_instance, "branch", None)
    return organization, branch


def assign_org_branch_from_parent(
    child_instance: Model,
    parent_instance,
    *,
    overwrite: bool = False,
) -> Model:
    """Inherit org / branch from ``parent_instance`` onto ``child_instance``.

    Does not save. Returns the child for chaining. No-op when:

    - the child has no ``organization`` field,
    - the parent is ``None``,
    - the parent has no resolved org / branch.
    """
    if not _has_field(child_instance, "organization"):
        return child_instance
    organization, branch = get_parent_org_branch(parent_instance)

    if organization is not None:
        if (
            overwrite
            or getattr(child_instance, "organization_id", None) is None
        ):
            child_instance.organization = organization

    if branch is not None and _has_field(child_instance, "branch"):
        if (
            overwrite
            or getattr(child_instance, "branch_id", None) is None
        ):
            child_instance.branch = branch

    return child_instance


def assign_org_branch_from_first_parent(
    child_instance: Model,
    *,
    overwrite: bool = False,
) -> Model:
    """Walk the conventional parent attributes (``conversation`` →
    ``message`` → ``order`` → ``shipment`` → ``payment`` → ``call`` →
    ``customer`` → ``lead``) and inherit org / branch from the first
    parent that resolves a non-``None`` value.

    The helper is the workhorse for the pre-save signal — it lets the
    14 org-aware models share one set of inheritance rules without each
    model needing custom code.
    """
    if not _has_field(child_instance, "organization"):
        return child_instance

    needs_org = (
        getattr(child_instance, "organization_id", None) is None
        or overwrite
    )
    needs_branch = (
        _has_field(child_instance, "branch")
        and (
            getattr(child_instance, "branch_id", None) is None
            or overwrite
        )
    )

    if not needs_org and not needs_branch:
        return child_instance

    for attr in _PARENT_INHERITANCE_ATTRS:
        if not hasattr(child_instance, attr):
            continue
        try:
            parent = getattr(child_instance, attr, None)
        except Exception:  # noqa: BLE001 - lazy FK might raise
            parent = None
        if parent is None:
            continue
        organization, branch = get_parent_org_branch(parent)
        if needs_org and organization is not None:
            child_instance.organization = organization
            needs_org = False
        if needs_branch and branch is not None:
            child_instance.branch = branch
            needs_branch = False
        if not needs_org and not needs_branch:
            break

    return child_instance


def _resolve_model(app_label: str, model_name: str):
    from django.apps import apps as django_apps

    try:
        return django_apps.get_model(app_label, model_name)
    except LookupError:
        return None


def get_recent_unscoped_writes(hours: int = 24) -> dict:
    """Count recent safe-path rows that still lack org/branch context."""
    from .signals import ORG_AUTO_ASSIGN_MODELS

    since = timezone.now() - timedelta(hours=hours)
    rows: list[dict] = []
    total_without_org = 0
    total_without_branch = 0

    for app_label, model_name in ORG_AUTO_ASSIGN_MODELS:
        model = _resolve_model(app_label, model_name)
        if model is None:
            continue
        try:
            qs = model.objects.filter(created_at__gte=since)
        except Exception:  # noqa: BLE001
            continue

        without_org = 0
        without_branch = 0
        try:
            without_org = qs.filter(organization__isnull=True).count()
        except Exception:  # noqa: BLE001
            pass
        try:
            model._meta.get_field("branch")
            without_branch = qs.filter(branch__isnull=True).count()
        except Exception:  # noqa: BLE001
            pass

        total_without_org += without_org
        total_without_branch += without_branch
        if without_org or without_branch:
            rows.append(
                {
                    "model": f"{app_label}.{model_name}",
                    "withoutOrganization": without_org,
                    "withoutBranch": without_branch,
                }
            )

    return {
        "windowHours": hours,
        "totalWithoutOrganization": total_without_org,
        "totalWithoutBranch": total_without_branch,
        "rows": rows,
    }


__all__ = (
    "OrgWriteAccessError",
    "resolve_write_organization",
    "resolve_write_branch",
    "apply_org_branch",
    "validate_org_write_access",
    "ensure_org_branch_before_save",
    "enforce_org_on_create",
    "get_parent_org_branch",
    "assign_org_branch_from_parent",
    "assign_org_branch_from_first_parent",
    "get_recent_unscoped_writes",
)
