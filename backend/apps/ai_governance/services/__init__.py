"""AgentRun lifecycle services — Phase 3A.

Pure functions called by the views. Three concerns:

1. ``create_agent_run`` / ``complete_agent_run`` / ``fail_agent_run`` are the
   plain CRUD lifecycle helpers — every dispatch writes one row, every
   completion flips status + writes an AuditEvent.
2. ``run_readonly_agent_analysis`` is the end-to-end "build prompt → dispatch
   → persist result" entry point used by ``POST /api/ai/agent-runs/``. It is
   read-only by construction: the only side effects are the AgentRun row
   and the AuditEvent ledger entries.
3. ``CAIO_FORBIDDEN_INTENTS`` enforces the blueprint's hard stop that CAIO
   never executes business actions. If a payload sent to the CAIO agent
   carries any write-style intent the run is rejected with a ``failed``
   status before we even call the LLM.

Compliance hard stop (Master Blueprint §26 #4):
- Every prompt is built via ``apps.ai_governance.prompting.build_messages``
  which fails closed (``ClaimVaultMissing``) when medical/product context
  has no Claim Vault grounding.
- This module never writes to leads, orders, payments, shipments, calls,
  or any business-state model. All it touches is ``AgentRun`` + audit.
"""
from __future__ import annotations

from datetime import timezone as _tz
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.integrations.ai.dispatch import dispatch_messages

from apps.ai_governance.models import AgentRun
from apps.ai_governance.prompting import ClaimVaultMissing, build_messages


# CAIO is read-only. If the payload includes any of these keys we refuse to
# run — the blueprint's hard stop is enforced here, not in the LLM prompt.
CAIO_FORBIDDEN_INTENTS: frozenset[str] = frozenset(
    {
        "execute",
        "apply",
        "send",
        "create_order",
        "create_payment",
        "create_shipment",
        "trigger_call",
        "assign_lead",
        "approve",
        "transition",
    }
)


class AgentExecutionRefused(Exception):
    """Raised when CAIO is asked to execute something it must never execute."""


# ----- CRUD lifecycle helpers -----


@transaction.atomic
def create_agent_run(
    *,
    agent: str,
    input_payload: dict[str, Any],
    triggered_by: str = "",
    dry_run: bool = True,
    prompt_version: str | None = None,
) -> AgentRun:
    """Insert a ``pending`` AgentRun row + write an audit-ledger event."""
    if agent not in AgentRun.Agent.values:
        raise ValueError(f"Unknown agent: {agent!r}")

    run = AgentRun.objects.create(
        id=next_id("AR", AgentRun, base=70000),
        agent=agent,
        prompt_version=prompt_version or "v1.0-phase3a",
        input_payload=dict(input_payload or {}),
        status=AgentRun.Status.PENDING,
        dry_run=dry_run,
        triggered_by=triggered_by,
    )
    write_event(
        kind="ai.agent_run.created",
        text=f"AgentRun {run.id} created · agent={agent} · dry_run={dry_run}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "run_id": run.id,
            "agent": agent,
            "dry_run": dry_run,
            "triggered_by": triggered_by,
        },
    )
    return run


def _coerce_cost(value: float | None) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@transaction.atomic
def complete_agent_run(run: AgentRun, *, result: AdapterResult) -> AgentRun:
    """Persist a successful (or skipped) adapter result on the run row.

    Phase 3C also stores token usage, the per-provider attempt log, the
    pricing snapshot used for cost calculation, and a ``fallback_used``
    flag so audit can replay every dispatch.
    """
    run.status = (
        AgentRun.Status.SUCCESS
        if result.status == AdapterStatus.SUCCESS
        else AgentRun.Status.SKIPPED
    )
    run.provider = result.provider or run.provider
    run.model = result.model or run.model
    run.output_payload = dict(result.output or {})
    run.latency_ms = result.latency_ms
    run.cost_usd = _coerce_cost(result.cost_usd)
    run.prompt_tokens = result.prompt_tokens
    run.completion_tokens = result.completion_tokens
    run.total_tokens = result.total_tokens
    run.pricing_snapshot = dict(result.pricing_snapshot or {})
    run.provider_attempts = list((result.raw or {}).get("provider_attempts") or [])
    run.fallback_used = bool((result.raw or {}).get("fallback_used") or False)
    run.completed_at = timezone.now()
    if result.error_message:
        run.error_message = result.error_message
    run.save(
        update_fields=[
            "status",
            "provider",
            "model",
            "output_payload",
            "latency_ms",
            "cost_usd",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "pricing_snapshot",
            "provider_attempts",
            "fallback_used",
            "completed_at",
            "error_message",
        ]
    )

    if run.fallback_used and run.status == AgentRun.Status.SUCCESS:
        write_event(
            kind="ai.provider.fallback_used",
            text=(
                f"AgentRun {run.id} succeeded after fallback · "
                f"provider={run.provider}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "run_id": run.id,
                "agent": run.agent,
                "winning_provider": run.provider,
                "attempts": run.provider_attempts,
            },
        )

    if run.cost_usd is not None and run.status == AgentRun.Status.SUCCESS:
        write_event(
            kind="ai.cost_tracked",
            text=(
                f"AgentRun {run.id} cost ${run.cost_usd} · "
                f"{run.total_tokens or 0} tokens · model={run.model}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "run_id": run.id,
                "agent": run.agent,
                "provider": run.provider,
                "model": run.model,
                "cost_usd": str(run.cost_usd),
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "total_tokens": run.total_tokens,
            },
        )

    write_event(
        kind="ai.agent_run.completed",
        text=(
            f"AgentRun {run.id} {run.status} · provider={run.provider} · "
            f"latency={run.latency_ms}ms"
        ),
        tone=AuditEvent.Tone.SUCCESS
        if run.status == AgentRun.Status.SUCCESS
        else AuditEvent.Tone.INFO,
        payload={
            "run_id": run.id,
            "agent": run.agent,
            "status": run.status,
            "provider": run.provider,
            "latency_ms": run.latency_ms,
            "fallback_used": run.fallback_used,
            "cost_usd": str(run.cost_usd) if run.cost_usd is not None else None,
        },
    )
    return run


@transaction.atomic
def fail_agent_run(run: AgentRun, *, error_message: str, provider: str = "") -> AgentRun:
    """Mark a run as ``failed`` and write a danger-tone audit event."""
    run.status = AgentRun.Status.FAILED
    run.error_message = (error_message or "")[:5000]
    if provider:
        run.provider = provider
    run.completed_at = timezone.now()
    run.save(
        update_fields=["status", "error_message", "provider", "completed_at"]
    )
    write_event(
        kind="ai.agent_run.failed",
        text=f"AgentRun {run.id} failed · {run.error_message}",
        tone=AuditEvent.Tone.DANGER,
        payload={
            "run_id": run.id,
            "agent": run.agent,
            "provider": run.provider,
            "error": run.error_message,
        },
    )
    return run


# ----- High-level entry point used by the view -----


def _payload_has_forbidden_intent(payload: dict[str, Any]) -> str | None:
    """Return the offending key when CAIO is asked to execute, else None."""
    keys = {str(k).lower() for k in (payload or {}).keys()}
    intent = (payload or {}).get("intent") or ""
    if isinstance(intent, str):
        keys.add(intent.lower())
    forbidden = keys & CAIO_FORBIDDEN_INTENTS
    if forbidden:
        return next(iter(sorted(forbidden)))
    return None


def run_readonly_agent_analysis(
    *,
    agent: str,
    input_payload: dict[str, Any],
    triggered_by: str = "",
    dry_run: bool = True,
) -> AgentRun:
    """Build prompt → dispatch → persist result in one call.

    Phase 3A is dry-run only. The function never returns control to a write
    path — even if the LLM suggests an action, the runtime won't execute it
    until Phase 5 wires the approval-matrix middleware.
    """
    if not dry_run:
        # Phase 3A guardrail: even if a caller asks for non-dry-run, we
        # short-circuit and persist a failed row. Phase 5 will wire the
        # approval matrix.
        run = create_agent_run(
            agent=agent,
            input_payload=input_payload,
            triggered_by=triggered_by,
            dry_run=False,
        )
        return fail_agent_run(
            run,
            error_message="Phase 3A enforces dry-run only; non-dry-run "
            "execution requires the approval-matrix middleware (Phase 5).",
            provider="disabled",
        )

    # CAIO hard stop: never execute, never simulate execution.
    if agent == AgentRun.Agent.CAIO:
        offending = _payload_has_forbidden_intent(input_payload)
        if offending:
            run = create_agent_run(
                agent=agent,
                input_payload=input_payload,
                triggered_by=triggered_by,
                dry_run=True,
            )
            return fail_agent_run(
                run,
                error_message=(
                    f"CAIO never executes business actions — refused intent "
                    f"{offending!r}. (Master Blueprint §26 #6.3.)"
                ),
                provider="disabled",
            )

    run = create_agent_run(
        agent=agent,
        input_payload=input_payload,
        triggered_by=triggered_by,
        dry_run=dry_run,
    )

    # Compliance gate: build messages with mandatory Claim Vault grounding.
    try:
        bundle = build_messages(agent=agent, input_payload=input_payload)
    except ClaimVaultMissing as exc:
        return fail_agent_run(run, error_message=str(exc), provider="disabled")
    except ValueError as exc:
        return fail_agent_run(run, error_message=str(exc), provider="disabled")

    run.prompt_version = bundle.prompt_version
    run.save(update_fields=["prompt_version"])

    # Dispatch through the provider router — disabled / no-key path returns
    # a skipped result and we persist that as-is.
    result = dispatch_messages(bundle.messages)
    if result.status == AdapterStatus.FAILED:
        return fail_agent_run(
            run,
            error_message=result.error_message or "adapter returned failed",
            provider=result.provider,
        )
    return complete_agent_run(run, result=result)


__all__ = (
    "AgentExecutionRefused",
    "CAIO_FORBIDDEN_INTENTS",
    "create_agent_run",
    "complete_agent_run",
    "fail_agent_run",
    "run_readonly_agent_analysis",
)
