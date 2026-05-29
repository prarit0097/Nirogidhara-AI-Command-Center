"""Phase 16E — DRF permission for the Integration Hardening read surfaces.

Every endpoint requires authentication. The Phase 16E dashboard is read-only,
so any authenticated user (including read-only viewers) may view readiness;
there are no mutation endpoints to gate. (If a future phase adds a test-mode
mutation, gate it behind director/admin via a separate write permission.)
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsAuthenticatedReadOnly(BasePermission):
    """Authenticated users may read; no method mutates in Phase 16E."""

    message = "Authentication required."

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        return bool(user and user.is_authenticated)
