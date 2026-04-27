"""Sandbox state singleton — Phase 3D.

The DB-backed ``SandboxState`` row holds the live toggle. The first read
seeds the singleton from ``settings.AI_SANDBOX_MODE`` so a fresh
deployment honours the env default without needing a manual PATCH.

When sandbox is enabled:
- AgentRuns still execute end-to-end and persist normally.
- ``sandbox_mode=True`` is stamped on every AgentRun for that period.
- The CEO success path skips the ``CeoBriefing`` refresh — sandbox runs
  do NOT mutate visible business state.
- CAIO remains read-only regardless of sandbox state.

Compliance: Sandbox is an additional safety layer, not a replacement
for Claim Vault enforcement. The prompt builder still requires Claim
Vault grounding for medical/product reasoning even in sandbox mode.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import SandboxState

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


def get_state() -> SandboxState:
    """Return the singleton row, seeding from settings the first time."""
    state, created = SandboxState.objects.get_or_create(
        pk=1,
        defaults={"is_enabled": bool(getattr(settings, "AI_SANDBOX_MODE", False))},
    )
    return state


def is_sandbox_enabled() -> bool:
    return get_state().is_enabled


@transaction.atomic
def set_sandbox_enabled(
    *,
    enabled: bool,
    note: str = "",
    by_user: "User" | None = None,
) -> SandboxState:
    state = get_state()
    if state.is_enabled == bool(enabled) and not note:
        return state
    state.is_enabled = bool(enabled)
    state.note = (note or "")[:240]
    state.updated_by = getattr(by_user, "username", "") or ""
    state.save(update_fields=["is_enabled", "note", "updated_by", "updated_at"])

    write_event(
        kind="ai.sandbox.enabled" if state.is_enabled else "ai.sandbox.disabled",
        text=(
            f"AI sandbox {'enabled' if state.is_enabled else 'disabled'} by "
            f"{state.updated_by or 'system'}"
        ),
        tone=AuditEvent.Tone.WARNING if state.is_enabled else AuditEvent.Tone.INFO,
        payload={
            "enabled": state.is_enabled,
            "note": state.note,
            "by": state.updated_by,
        },
    )
    return state


__all__ = ("get_state", "is_sandbox_enabled", "set_sandbox_enabled")
