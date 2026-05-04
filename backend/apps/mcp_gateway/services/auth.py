"""Phase 6M-0 — MCP auth foundation (placeholder).

Phase 6M-0 ships only a thin auth shim:

- An ``McpClientApp`` row carries provisional ``allowed_scopes`` /
  ``denied_scopes`` and an ``is_active`` flag.
- A trusted internal caller may pass ``actor=<User>`` to the
  executor; the executor consults this module to decide whether the
  caller has the requested scopes.
- No public-facing token issuer exists yet. Future phases (6M-Auth /
  6N) will own real OAuth + bearer-token flows.

Hard rules:

- Active external clients NEVER auto-grant a write or provider scope.
- Phase 6M-0 returns False for any write / provider scope request.
- The default caller is treated as ``internal_only`` — the SaaS-admin
  permission class on the API endpoint is the authoritative gate.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .schemas import (
    ENABLED_SCOPES,
    FUTURE_DISABLED_SCOPES,
    is_enabled_scope,
    is_future_disabled_scope,
)


def _normalize_scopes(scopes: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not scopes:
        return ()
    return tuple(s for s in scopes if isinstance(s, str) and s)


def is_scope_allowed_in_phase_6m_0(scope: str) -> bool:
    """A scope is allowed in Phase 6M-0 only if it is in the read-only
    enabled list AND not in the future-disabled list."""
    return is_enabled_scope(scope) and not is_future_disabled_scope(scope)


def filter_scopes_to_enabled(
    scopes: Optional[Iterable[str]],
) -> tuple[str, ...]:
    """Drop any scope that isn't currently enabled in Phase 6M-0."""
    return tuple(
        s for s in _normalize_scopes(scopes) if is_scope_allowed_in_phase_6m_0(s)
    )


def required_scopes_satisfied(
    required_scopes: Iterable[str],
    granted_scopes: Iterable[str],
) -> bool:
    """All required scopes must be in the granted set AND must be in
    the Phase 6M-0 enabled list."""
    required = _normalize_scopes(required_scopes)
    granted = set(filter_scopes_to_enabled(granted_scopes))
    if not required:
        return True
    for scope in required:
        if scope not in granted:
            return False
        if not is_scope_allowed_in_phase_6m_0(scope):
            return False
    return True


def grants_for_internal_admin() -> tuple[str, ...]:
    """Internal admin / staff caller in Phase 6M-0 gets the full
    read-only scope set — never a write or provider scope."""
    return ENABLED_SCOPES


__all__ = (
    "is_scope_allowed_in_phase_6m_0",
    "filter_scopes_to_enabled",
    "required_scopes_satisfied",
    "grants_for_internal_admin",
)
