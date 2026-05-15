"""Phase 9F — CEO AI Orchestration V1 Celery task.

Daily synthesis snapshot rolling up Phase 9A-9E agent output. Writes
exactly one ``CeoOrchestrationSnapshot`` + ``AgentRun`` +
``AuditEvent`` per invocation. Honors the kill switch with the same
Postgres-safe pattern as Phase 7E-Live-B Hotfix-1 / 9A-9E. NEVER
triggers any outbound side effect.

Phase 9F does NOT touch the legacy ``ai_governance.CeoBriefing``
model or its scheduled tasks.
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

from .models import CeoOrchestrationSnapshot
from .service import (
    AGENT_KEYS,
    AGENT_NAME,
    MODEL_USED,
    build_snapshot,
)


logger = logging.getLogger(__name__)

AUDIT_KIND_SNAPSHOT = "ceo_orchestration.snapshot.created"
AUDIT_KIND_COMPLETED = "ceo_orchestration.daily_run.completed"
AUDIT_KIND_BLOCKED = "ceo_orchestration.daily_run.blocked"


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


def _serialize_snapshot(snapshot: CeoOrchestrationSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "snapshot_at": snapshot.snapshot_at.isoformat(),
        "business_health_score": snapshot.business_health_score,
        "health_tier": snapshot.health_tier,
        "customer_success_snapshot_id": snapshot.customer_success_snapshot_id,
        "rto_snapshot_id": snapshot.rto_snapshot_id,
        "cfo_snapshot_id": snapshot.cfo_snapshot_id,
        "data_analyst_snapshot_id": snapshot.data_analyst_snapshot_id,
        "calling_team_leader_snapshot_id": (
            snapshot.calling_team_leader_snapshot_id
        ),
        "cross_cutting_alerts": list(snapshot.cross_cutting_alerts or []),
        "top_3_priorities": list(snapshot.top_3_priorities or []),
        "agent_status_summary": dict(snapshot.agent_status_summary or {}),
        "briefing_text": snapshot.briefing_text,
        "alerts": list(snapshot.alerts or []),
        "sandbox": snapshot.sandbox,
    }


@shared_task(
    name="apps.agents.ceo_orchestration.tasks.run_ceo_orchestration_agent_daily"
)
def run_ceo_orchestration_agent_daily(
    *, triggered_by: str = "celery_beat_daily"
) -> dict[str, Any]:
    """Daily CEO synthesis snapshot. RECOMMENDATIONS-ONLY."""
    started = time.monotonic()
    blocked, kill_state = _kill_switch_blocked()
    if blocked:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="CEO orchestration daily run blocked by kill switch",
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
    snapshot: CeoOrchestrationSnapshot | None = None
    compute_started = time.monotonic()
    snapshot_obj, _bundle = build_snapshot(
        now=timezone.now(), sandbox=sandbox
    )
    compute_latency_ms = int((time.monotonic() - compute_started) * 1000)
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(
                id=next_id("AR", AgentRun, base=70000),
                agent=AgentRun.Agent.CEO,
                prompt_version="v1.0-phase9f",
                input_payload={
                    "sources": list(AGENT_KEYS),
                },
                output_payload={
                    "snapshot": {
                        "business_health_score": (
                            snapshot_obj.business_health_score
                        ),
                        "health_tier": snapshot_obj.health_tier,
                        "alert_count": len(
                            snapshot_obj.cross_cutting_alerts or []
                        ),
                        "priority_count": len(
                            snapshot_obj.top_3_priorities or []
                        ),
                        "alerts": list(snapshot_obj.alerts or []),
                    }
                },
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
            snapshot_obj.agent_run = run
            snapshot_obj.save()
            snapshot = snapshot_obj
    except Exception:  # pragma: no cover - defensive
        logger.exception("phase9f snapshot persist failed")
        return {
            "agent": AGENT_NAME,
            "status": "failed",
            "reason": "persist_failed",
        }
    write_event(
        kind=AUDIT_KIND_SNAPSHOT,
        text=(
            f"CEO orchestration snapshot {snapshot.pk} - "
            f"score={snapshot.business_health_score} tier={snapshot.health_tier}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "snapshot_id": snapshot.pk,
            "health_score": snapshot.business_health_score,
            "health_tier": snapshot.health_tier,
            "alert_count": len(snapshot.cross_cutting_alerts or []),
            "top_priority_count": len(snapshot.top_3_priorities or []),
            "agent_run_id": snapshot.agent_run_id,
            "sandbox": snapshot.sandbox,
        },
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    write_event(
        kind=AUDIT_KIND_COMPLETED,
        text=(
            f"CEO orchestration daily run completed in {duration_ms}ms - "
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
