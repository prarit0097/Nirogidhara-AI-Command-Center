"""Phase 16F — DRF permissions for the pilot readiness surfaces.

Every endpoint requires authentication. Reads are open to any authenticated
user (read-only viewers may view readiness + dry-runs). Mutations (create a
dry-run, record a review) require director/admin — a dry-run never executes a
business action, but creating one is a Director-governance act.
"""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

_ADMIN_ROLES = {"director", "admin"}


def _is_admin_like(user) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return (getattr(user, "role", "") or "").lower() in _ADMIN_ROLES


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
