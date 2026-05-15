"""Phase 9B — RTO Prevention Agent V1 Celery task.

Daily recommendations-only sweep over in-flight orders. Persists one
``RtoRiskSnapshot`` + ``AgentRun`` + ``AuditEvent`` per eligible
order. Honors the kill switch with the same Postgres-safe pattern as
Phase 7E-Live-B Hotfix-1 / Phase 9A: a global ``RuntimeKillSwitch``
row with ``enabled=False`` (ordered by ``-pk``) wins over the seeded
enabled default. NEVER triggers calls / WhatsApp / discount creation
/ shipment mutation / payment mutation.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import is_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order

from .models import RtoRiskSnapshot
from .service import (
    AGENT_NAME,
    IN_FLIGHT_STAGES,
    MODEL_USED,
    ORDER_AGE_WINDOW_DAYS,
    TERMINAL_STAGES,
    build_snapshot,
    compute_signals,
)


logger = logging.getLogger(__name__)

AUDIT_KIND_SNAPSHOT = "rto_prevention.snapshot.created"
AUDIT_KIND_COMPLETED = "rto_prevention.daily_run.completed"
AUDIT_KIND_BLOCKED = "rto_prevention.daily_run.blocked"


def _kill_switch_blocked() -> tuple[bool, dict[str, Any]]:
    """Phase 7E-Live-B Hotfix-1 pattern (Postgres-safe).

    Returns ``(blocked, state)``. Blocked when any global kill switch
    row has ``enabled=False``; ordered by ``-pk`` for determinism.
    """
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


def _in_flight_orders() -> list[Order]:
    cutoff = timezone.now() - timedelta(days=ORDER_AGE_WINDOW_DAYS)
    return list(
        Order.objects.filter(
            stage__in=IN_FLIGHT_STAGES,
            created_at__gte=cutoff,
        )
        .exclude(stage__in=TERMINAL_STAGES)
        .order_by("created_at")
    )


def _persist_snapshot_with_run(
    order: Order,
    *,
    sandbox: bool,
    triggered_by: str,
) -> RtoRiskSnapshot | None:
    started = time.monotonic()
    signals = compute_signals(order)
    snapshot = build_snapshot(order, signals, sandbox=sandbox)
    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(
                id=next_id("AR", AgentRun, base=70000),
                agent=AgentRun.Agent.RTO_PREVENTION,
                prompt_version="v1.0-phase9b",
                input_payload={
                    "order_id": order.id,
                    "signals": signals.to_payload(),
                },
                output_payload={
                    "snapshot": {
                        "risk_score": snapshot.risk_score,
                        "risk_tier": snapshot.risk_tier,
                        "lifecycle_stage": snapshot.lifecycle_stage,
                        "days_since_order": snapshot.days_since_order,
                        "recommendation_kind": snapshot.recommendation_kind,
                    }
                },
                status=AgentRun.Status.SUCCESS,
                provider="disabled",
                model=MODEL_USED,
                latency_ms=latency_ms,
                cost_usd=0,
                dry_run=True,
                triggered_by=triggered_by,
                sandbox_mode=bool(sandbox),
                completed_at=timezone.now(),
            )
            snapshot.agent_run = run
            snapshot.save()
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "phase9b snapshot persist failed order_id=%s", order.id
        )
        return None
    write_event(
        kind=AUDIT_KIND_SNAPSHOT,
        text=(
            f"RTO risk snapshot {snapshot.pk} for {order.id} - "
            f"{snapshot.risk_tier} - {snapshot.recommendation_kind}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "order_id": order.id,
            "risk_score": snapshot.risk_score,
            "risk_tier": snapshot.risk_tier,
            "recommendation_kind": snapshot.recommendation_kind,
            "agent_run_id": snapshot.agent_run_id,
            "sandbox": snapshot.sandbox,
        },
    )
    return snapshot


@shared_task(name="apps.agents.rto_prevention.tasks.run_rto_prevention_agent_daily")
def run_rto_prevention_agent_daily(
    *, triggered_by: str = "celery_beat_daily"
) -> dict[str, Any]:
    """Daily recommendations-only sweep over in-flight orders."""
    started = time.monotonic()
    blocked, kill_state = _kill_switch_blocked()
    if blocked:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="RTO prevention daily run blocked by kill switch",
            tone=AuditEvent.Tone.WARNING,
            payload={"reason": "runtime_kill_switch_disabled", "kill": kill_state},
        )
        return {
            "agent": AGENT_NAME,
            "status": "blocked",
            "reason": "runtime_kill_switch_disabled",
            "kill": kill_state,
            "counts": {},
        }
    sandbox = bool(is_sandbox_enabled())
    orders = _in_flight_orders()
    tier_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    snapshot_ids: list[int] = []
    for order in orders:
        snapshot = _persist_snapshot_with_run(
            order, sandbox=sandbox, triggered_by=triggered_by
        )
        if snapshot is None:
            continue
        snapshot_ids.append(snapshot.pk)
        tier_counts[snapshot.risk_tier] = (
            tier_counts.get(snapshot.risk_tier, 0) + 1
        )
        kind_counts[snapshot.recommendation_kind] = (
            kind_counts.get(snapshot.recommendation_kind, 0) + 1
        )
        stage_counts[snapshot.lifecycle_stage] = (
            stage_counts.get(snapshot.lifecycle_stage, 0) + 1
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    summary = {
        "agent": AGENT_NAME,
        "status": "completed",
        "snapshot_count": len(snapshot_ids),
        "order_count": len(orders),
        "tier_counts": tier_counts,
        "recommendation_counts": kind_counts,
        "stage_counts": stage_counts,
        "duration_ms": duration_ms,
        "sandbox": sandbox,
    }
    write_event(
        kind=AUDIT_KIND_COMPLETED,
        text=(
            f"RTO prevention daily run completed: "
            f"{len(snapshot_ids)} snapshots in {duration_ms}ms"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "tier_counts": tier_counts,
            "recommendation_counts": kind_counts,
            "stage_counts": stage_counts,
            "duration_ms": duration_ms,
            "snapshot_count": len(snapshot_ids),
            "sandbox": sandbox,
        },
    )
    return summary
