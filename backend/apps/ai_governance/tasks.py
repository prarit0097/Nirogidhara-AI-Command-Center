"""Celery tasks — Phase 3C scheduler.

The scheduled tasks are read-only by construction: they wrap the Phase 3B
``ceo`` and ``caio`` runtime services, both of which dispatch through
``run_readonly_agent_analysis`` and never write to leads / orders /
payments / shipments / calls.

Local dev never has to start a worker because
``CELERY_TASK_ALWAYS_EAGER=true`` (the default for tests) makes ``.delay()``
run synchronously. The same call site works in production with a real
worker — Celery flips eager mode off automatically when started with
``celery -A config worker -B``.

Compliance hard stop (Master Blueprint §26 #4):
- CAIO never executes. The CAIO sweep payload contains no execution
  intents, the prompt builder reminds the model, and
  ``services.CAIO_FORBIDDEN_INTENTS`` would refuse one anyway.
- Approved Claim Vault grounding is enforced by the prompt builder; the
  scheduler does not bypass it.
"""
from __future__ import annotations

from typing import Any

from celery import shared_task

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event


_VALID_SLOTS = ("morning", "evening")


@shared_task(name="apps.ai_governance.tasks.run_daily_ai_briefing_task")
def run_daily_ai_briefing_task(slot: str = "morning") -> dict[str, Any]:
    """Run the CEO daily briefing + CAIO audit sweep for ``slot``.

    Returns a dict with the two AgentRun ids so the Celery result backend
    can surface them to the operator. Errors inside an agent module are
    captured into ``AgentRun`` rows by ``run_readonly_agent_analysis`` —
    this task only fails if Django itself can't import the agent modules.
    """
    if slot not in _VALID_SLOTS:
        slot = "morning"

    write_event(
        kind="ai.scheduler.daily_briefing.started",
        text=f"Daily AI briefing started · slot={slot}",
        tone=AuditEvent.Tone.INFO,
        payload={"slot": slot},
    )

    try:
        # Import inside the task so Celery autodiscover doesn't pull in
        # the entire services chain at module import time.
        from apps.ai_governance.services.agents import caio, ceo

        ceo_run = ceo.run(triggered_by=f"scheduler:{slot}")
        caio_run = caio.run(triggered_by=f"scheduler:{slot}")
    except Exception as exc:  # pragma: no cover - defensive belt-and-braces
        write_event(
            kind="ai.scheduler.daily_briefing.failed",
            text=f"Daily AI briefing failed · slot={slot} · {exc}",
            tone=AuditEvent.Tone.DANGER,
            payload={"slot": slot, "error": str(exc)},
        )
        raise

    write_event(
        kind="ai.scheduler.daily_briefing.completed",
        text=(
            f"Daily AI briefing completed · slot={slot} · "
            f"ceo={ceo_run.id} ({ceo_run.status}) · "
            f"caio={caio_run.id} ({caio_run.status})"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "slot": slot,
            "ceo_run_id": ceo_run.id,
            "ceo_status": ceo_run.status,
            "caio_run_id": caio_run.id,
            "caio_status": caio_run.status,
        },
    )
    return {
        "slot": slot,
        "ceo_run_id": ceo_run.id,
        "ceo_status": ceo_run.status,
        "caio_run_id": caio_run.id,
        "caio_status": caio_run.status,
    }


__all__ = ("run_daily_ai_briefing_task",)
