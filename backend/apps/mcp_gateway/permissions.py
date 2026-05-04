"""Phase 6M-0 — DRF permission for MCP gateway admin endpoints.

Mirrors the ``apps.saas.views.AdminSaasPermission`` shape: admin /
director / staff / superuser only. Phase 6M-0 ships no public
unauthenticated endpoint.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission


class McpAdminPermission(BasePermission):
    """Admin / director / staff / superuser only."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(
            user, "is_superuser", False
        ):
            return True
        role = getattr(user, "role", "") or ""
        return role in {"director", "admin"}


__all__ = ("McpAdminPermission",)
