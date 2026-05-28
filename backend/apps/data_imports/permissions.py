"""Phase 16D — DRF permissions for the data-imports surfaces.

All endpoints require authentication (no anonymous reads). Writes are gated:
``AuthedReadAdminWrite`` (upload dataset / create campaign) needs director or
admin; ``AuthedReadAgentWrite`` (record outcome / create order) additionally
allows the operations role (the manual calling agent).
"""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

_ADMIN_ROLES = {"director", "admin"}
_AGENT_ROLES = {"director", "admin", "operations"}


def _role(user) -> str:
    return (getattr(user, "role", "") or "").lower()


class AuthedReadAdminWrite(BasePermission):
    """Read = any authenticated user; write = director/admin/superuser."""

    message = "Director/Admin role required for this action."

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        if getattr(user, "is_superuser", False):
            return True
        return _role(user) in _ADMIN_ROLES


class AuthedReadAgentWrite(BasePermission):
    """Read = any authenticated user; write = director/admin/operations/superuser."""

    message = "Director/Admin/Operations role required for this action."

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        if getattr(user, "is_superuser", False):
            return True
        return _role(user) in _AGENT_ROLES
