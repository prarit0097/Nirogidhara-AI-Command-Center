"""Role-based DRF permission for Phase 2A write endpoints.

The blueprint §8 permission matrix maps actions to user roles. We encode the
matrix here as role-set constants and a single ``BasePermission`` subclass.
ViewSets opt in by setting ``allowed_write_roles`` and listing this class in
``permission_classes``.

Reads stay open via ``IsAuthenticatedOrReadOnly`` (set globally in
``config/settings.py``) — this permission only fires on unsafe methods.

CAIO is intentionally absent from every role-set: CAIO is an AI-agent identity,
not a user role, and per blueprint §6.3 it must never execute business actions.
"""
from __future__ import annotations

from typing import FrozenSet

from rest_framework import permissions

from .models import User


# Role sets used by ViewSets. Frozen so they can't be mutated at import time.
DIRECTOR_ONLY: FrozenSet[str] = frozenset({User.Role.DIRECTOR})
ADMIN_AND_UP: FrozenSet[str] = frozenset({User.Role.DIRECTOR, User.Role.ADMIN})
COMPLIANCE_AND_UP: FrozenSet[str] = frozenset(
    {User.Role.DIRECTOR, User.Role.ADMIN, User.Role.COMPLIANCE}
)
OPERATIONS_AND_UP: FrozenSet[str] = frozenset(
    {User.Role.DIRECTOR, User.Role.ADMIN, User.Role.OPERATIONS}
)


class RoleBasedPermission(permissions.BasePermission):
    """Allow safe methods for everyone; require role membership for writes.

    ViewSets configure the allowed role set via either:
      - ``view.allowed_write_roles`` attribute (preferred), or
      - the class default ``allowed_roles`` set on a subclass.
    """

    allowed_roles: FrozenSet[str] = OPERATIONS_AND_UP
    message = "Your role is not allowed to perform this action."

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        roles = getattr(view, "allowed_write_roles", self.allowed_roles)
        return getattr(request.user, "role", None) in roles
