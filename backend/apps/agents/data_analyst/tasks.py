"""Phase 9D — Data Analyst Agent V1 Celery task.

Daily operational analytics snapshot. Writes exactly one
``DataAnalystSnapshot`` + ``AgentRun`` + ``AuditEvent`` per
invocation. Honors the kill switch with the same Postgres-safe
pattern as Phase 7E-Live-B Hotfix-1 / 9A / 9B / 9C. NEVER triggers
any outbound side effect.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import is_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import DataAnalystSnapshot
from .service import (
    AGENT_NAME,
    MODEL_USED,
    WINDOW_DAYS,
    build_snapshot,
    compute_signals,
)


logger = logging.getLogger(__name__)

AUDIT_KIND_SNAPSHOT = "data_analyst.snapshot.created"
AUDIT_KIND_COMPLETED = "data_analyst.daily_run.completed"
AUDIT_KIND_BLOCKED = "data_analyst.daily_run.blocked"


def _kill_switch_blocked() -> tuple[bool, dict[str, Any]]:
    """Phase 7E-Live-B Hotfix-1 pattern (Postgres-safe)."""
    try:
        from apps.saas.models import RuntimeKillSwitch

        disabled = (
            RuntimeKillSwitch.objects.filter(scope="global", enabled=False)
            .order_by("-pk")
            .first()
        )
        if disabled is not None:
            return True, {
                "enabled": False,
                "model": "RuntimeKillSwitch",
                "id": disabled.pk,
            }
        row = (
            RuntimeKillSwitch.objects.filter(scope="global")
            .order_by("-pk")
            .first()
        )
    except Exception:  # pragma: no cover - defensive
        return False, {"enabled": True, "model": "lookup_failed_treated_as_enabled"}
    if row is None:
        return False, {"enabled": True, "model": "no_row_treated_as_enabled"}
    return (not bool(row.enabled)), {
        "enabled": bool(row.enabled),
        "model": "RuntimeKillSwitch",
        "id": row.pk,
    }


def _serialize_snapshot(snapshot: DataAnalystSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "snapshot_at": snapshot.snapshot_at.isoformat(),
        "lead_count_30d": snapshot.lead_count_30d,
        "call_count_30d": snapshot.call_count_30d,
        "confirmed_order_count_30d": snapshot.confirmed_order_count_30d,
        "delivered_order_count_30d": snapshot.delivered_order_count_30d,
        "reorder_count_30d": snapshot.reorder_count_30d,
        "lead_to_call_rate": snapshot.lead_to_call_rate,
        "call_to_confirmed_rate": snapshot.call_to_confirmed_rate,
        "confirmed_to_delivered_rate": snapshot.confirmed_to_delivered_rate,
        "delivered_to_reorder_rate": snapshot.delivered_to_reorder_rate,
        "top_states": list(snapshot.top_states or []),
        "day_of_week_counts": dict(snapshot.day_of_week_counts or {}),
        "alerts": list(snapshot.alerts or []),
        "alert_text": snapshot.alert_text,
        "sandbox": snapshot.sandbox,
    }


@shared_task(name="apps.agents.data_analyst.tasks.run_data_analyst_agent_daily")
def run_data_analyst_agent_daily(
    *, triggered_by: str = "celery_beat_daily"
) -> dict[str, Any]:
    """Daily operational analytics snapshot. RECOMMENDATIONS-ONLY."""
    started = time.monotonic()
    blocked, kill_state = _kill_switch_blocked()
    if blocked:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="Data Analyst daily run blocked by kill switch",
            tone=AuditEvent.Tone.WARNING,
            payload={"reason": "runtime_kill_switch_disabled", "kill": kill_state},
        )
        return {
            "agent": AGENT_NAME,
            "status": "blocked",
            "reason": "runtime_kill_switch_disabled",
            "kill": kill_state,
        }
    sandbox = bool(is_sandbox_enabled())
    snapshot: DataAnalystSnapshot | None = None
    compute_started = time.monotonic()
    signals = compute_signals(now=timezone.now())
    compute_latency_ms = int((time.monotonic() - compute_started) * 1000)
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(
                id=next_id("AR", AgentRun, base=70000),
                agent=AgentRun.Agent.DATA_ANALYST,
                prompt_version="v1.0-phase9d",
                input_payload={"window_days": WINDOW_DAYS},
                output_payload={"snapshot": signals.to_payload()},
                status=AgentRun.Status.SUCCESS,
                provider="disabled",
                model=MODEL_USED,
                latency_ms=compute_latency_ms,
                cost_usd=Decimal("0"),
                dry_run=True,
                triggered_by=triggered_by,
                sandbox_mode=bool(sandbox),
                completed_at=timezone.now(),
            )
            snapshot = build_snapshot(signals, sandbox=sandbox)
            snapshot.agent_run = run
            snapshot.save()
    except Exception:  # pragma: no cover - defensive
        logger.exception("phase9d snapshot persist failed")
        return {
            "agent": AGENT_NAME,
            "status": "failed",
            "reason": "persist_failed",
        }
    write_event(
        kind=AUDIT_KIND_SNAPSHOT,
        text=(
            f"Data Analyst snapshot {snapshot.pk} - "
            f"alerts={','.join(snapshot.alerts) or 'none'}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "snapshot_id": snapshot.pk,
            "top_alerts": list(snapshot.alerts or []),
            "lead_count_30d": snapshot.lead_count_30d,
            "confirmed_order_count_30d": snapshot.confirmed_order_count_30d,
            "agent_run_id": snapshot.agent_run_id,
            "sandbox": snapshot.sandbox,
        },
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    write_event(
        kind=AUDIT_KIND_COMPLETED,
        text=(
            f"Data Analyst daily run completed in {duration_ms}ms - "
            f"snapshot_id={snapshot.pk}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "snapshot_id": snapshot.pk,
            "duration_ms": duration_ms,
            "alerts": list(snapshot.alerts or []),
            "sandbox": snapshot.sandbox,
        },
    )
    return {
        "agent": AGENT_NAME,
        "status": "completed",
        "snapshot": _serialize_snapshot(snapshot),
        "duration_ms": duration_ms,
        "sandbox": sandbox,
    }
