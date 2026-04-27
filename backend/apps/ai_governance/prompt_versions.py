"""PromptVersion lifecycle services — Phase 3D.

Pure functions called by the views. The DB enforces ``one active per
agent`` via a partial unique constraint; this module wraps the
state-machine transitions in transactions and writes audit-ledger rows.

Compliance: a PromptVersion CANNOT skip the Approved Claim Vault block
in ``apps.ai_governance.prompting``. Even when an active PromptVersion
overrides ``system_policy`` / ``role_prompt``, the prompt builder always
appends the relevant Claim entries on top. PromptVersion must NOT store
API keys, secrets, or business-state mutation instructions — the model
is for content + role, not for execution intents.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import AgentRun, PromptVersion

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


@transaction.atomic
def create_prompt_version(
    *,
    agent: str,
    version: str,
    title: str = "",
    system_policy: str = "",
    role_prompt: str = "",
    instruction_payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    by_user: "User" | None = None,
) -> PromptVersion:
    """Insert a draft PromptVersion + write a ``ai.prompt_version.created`` row."""
    if agent not in AgentRun.Agent.values:
        raise ValueError(f"Unknown agent: {agent!r}")
    if not version:
        raise ValueError("version is required")

    pv = PromptVersion.objects.create(
        id=next_id("PV", PromptVersion, base=80000),
        agent=agent,
        version=version,
        title=title or "",
        system_policy=system_policy or "",
        role_prompt=role_prompt or "",
        instruction_payload=dict(instruction_payload or {}),
        is_active=False,
        status=PromptVersion.Status.DRAFT,
        created_by=getattr(by_user, "username", "") or "",
        metadata=dict(metadata or {}),
    )
    write_event(
        kind="ai.prompt_version.created",
        text=f"PromptVersion {pv.id} created · {agent}:{version}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "prompt_version_id": pv.id,
            "agent": agent,
            "version": version,
            "by": getattr(by_user, "username", "") or "",
        },
    )
    return pv


@transaction.atomic
def activate_prompt_version(
    *,
    prompt_version_id: str,
    by_user: "User" | None = None,
) -> PromptVersion:
    """Make ``prompt_version_id`` the active version for its agent.

    Any prior active PromptVersion for the same agent is flipped to
    ``is_active=False`` and ``status=ARCHIVED`` so the partial unique
    constraint stays satisfied.
    """
    pv = PromptVersion.objects.select_for_update().get(pk=prompt_version_id)

    # Flip the previously active version off (if any).
    PromptVersion.objects.select_for_update().filter(
        agent=pv.agent, is_active=True
    ).exclude(pk=pv.pk).update(
        is_active=False, status=PromptVersion.Status.ARCHIVED
    )

    pv.is_active = True
    pv.status = PromptVersion.Status.ACTIVE
    pv.activated_at = timezone.now()
    pv.save(update_fields=["is_active", "status", "activated_at"])

    write_event(
        kind="ai.prompt_version.activated",
        text=f"PromptVersion {pv.id} activated · {pv.agent}:{pv.version}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "prompt_version_id": pv.id,
            "agent": pv.agent,
            "version": pv.version,
            "by": getattr(by_user, "username", "") or "",
        },
    )
    return pv


@transaction.atomic
def rollback_prompt_version(
    *,
    target_version_id: str,
    reason: str,
    by_user: "User" | None = None,
) -> PromptVersion:
    """Roll the agent back to a previous PromptVersion.

    The currently-active version is flipped to ``is_active=False`` /
    ``status=ROLLED_BACK`` (with the reason recorded). The target version
    is re-activated. A ``ai.prompt_version.rolled_back`` audit row is
    written. ``reason`` is required so operators always have context.
    """
    if not reason:
        raise ValueError("rollback_reason is required")

    target = PromptVersion.objects.select_for_update().get(pk=target_version_id)

    previous = (
        PromptVersion.objects.select_for_update()
        .filter(agent=target.agent, is_active=True)
        .exclude(pk=target.pk)
        .first()
    )
    if previous is not None:
        previous.is_active = False
        previous.status = PromptVersion.Status.ROLLED_BACK
        previous.rolled_back_at = timezone.now()
        previous.rollback_reason = reason
        previous.save(
            update_fields=["is_active", "status", "rolled_back_at", "rollback_reason"]
        )

    target.is_active = True
    target.status = PromptVersion.Status.ACTIVE
    target.activated_at = timezone.now()
    target.rolled_back_at = None
    target.rollback_reason = ""
    target.save(
        update_fields=["is_active", "status", "activated_at", "rolled_back_at", "rollback_reason"]
    )

    write_event(
        kind="ai.prompt_version.rolled_back",
        text=(
            f"Agent {target.agent} rolled back to {target.version} "
            f"(prev {previous.version if previous else 'none'})"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "agent": target.agent,
            "target_version_id": target.id,
            "target_version": target.version,
            "previous_version_id": getattr(previous, "id", None),
            "previous_version": getattr(previous, "version", None),
            "reason": reason,
            "by": getattr(by_user, "username", "") or "",
        },
    )
    return target


def get_active_prompt_version(agent: str) -> PromptVersion | None:
    """Return the currently-active PromptVersion for ``agent`` (or None)."""
    return PromptVersion.objects.filter(agent=agent, is_active=True).first()


def list_prompt_versions(*, agent: str | None = None) -> list[PromptVersion]:
    qs = PromptVersion.objects.all()
    if agent:
        qs = qs.filter(agent=agent)
    return list(qs.order_by("agent", "-created_at"))


__all__ = (
    "create_prompt_version",
    "activate_prompt_version",
    "rollback_prompt_version",
    "get_active_prompt_version",
    "list_prompt_versions",
)
