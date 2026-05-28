"""Phase 16C — DRF permissions for the Director Operations surfaces.

Both classes require authentication for every method (no anonymous reads).
``AdminOnly`` gates every method behind the director/admin User.role; it is
used for the briefing surfaces, which expose the internal CEO briefing body.
``AuthenticatedReadAdminWrite`` lets any authenticated user read but only
director/admin (or superuser) mutate — used for the team-roles surface.
"""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

_ADMIN_ROLES = {"director", "admin"}


def _is_admin_like(user) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return (getattr(user, "role", "") or "").lower() in _ADMIN_ROLES


class AdminOnly(BasePermission):
    """Authenticated director / admin / superuser only — for every method."""

    message = "Director/Admin role required."

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return _is_admin_like(user)


class AuthenticatedReadAdminWrite(BasePermission):
    """Read = any authenticated user; write = director/admin/superuser only."""

    message = "Director/Admin role required for this action."

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return _is_admin_like(user)
