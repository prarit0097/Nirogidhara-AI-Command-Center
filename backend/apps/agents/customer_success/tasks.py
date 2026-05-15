"""Phase 9A — Customer Success / Reorder Agent V1 Celery task.

Daily recommendations-only sweep over delivered customers in the last
60 days. Persists one ``CustomerSuccessSnapshot`` + ``AgentRun`` +
``AuditEvent`` per customer. Honors the kill switch with the same
Postgres-safe pattern as Phase 7E-Live-B Hotfix-1: a global
``RuntimeKillSwitch`` row with ``enabled=False`` (ordered by ``-pk``)
wins over the seeded enabled default. NEVER sends WhatsApp, never
calls Vapi/Razorpay/Delhivery/Meta Cloud, never mutates business
state.
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
from apps.crm.models import Customer
from apps.orders.models import Order

from .models import CustomerSuccessSnapshot
from .service import (
    AGENT_NAME,
    DELIVERED_STAGES,
    MODEL_USED,
    build_snapshot,
    compute_signals,
)


logger = logging.getLogger(__name__)

AUDIT_KIND_SNAPSHOT = "customer_success.snapshot.created"
AUDIT_KIND_COMPLETED = "customer_success.daily_run.completed"
AUDIT_KIND_BLOCKED = "customer_success.daily_run.blocked"


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


def _candidate_customer_ids(*, since_days: int = 60) -> list[str]:
    cutoff = timezone.now() - timedelta(days=since_days)
    return list(
        Order.objects.filter(
            stage__in=DELIVERED_STAGES, created_at__gte=cutoff
        )
        .values_list("phone", flat=True)
        .distinct()
    )


def _customers_for_phones(phones: list[str]) -> list[Customer]:
    return list(Customer.objects.filter(phone__in=phones).order_by("id"))


def _serialize_snapshot(snapshot: CustomerSuccessSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "customer_id": snapshot.customer_id,
        "score": snapshot.score,
        "lifecycle_stage": snapshot.lifecycle_stage,
        "days_since_delivery": snapshot.days_since_delivery,
        "in_reorder_window": snapshot.in_reorder_window,
        "reorder_candidate": snapshot.reorder_candidate,
        "at_risk": snapshot.at_risk,
        "risk_reasons": list(snapshot.risk_reasons or []),
        "recommendation_kind": snapshot.recommendation_kind,
        "recommendation_text": snapshot.recommendation_text,
        "sandbox": snapshot.sandbox,
        "signals": dict(snapshot.signals or {}),
    }


def _persist_snapshot_with_run(
    customer: Customer,
    *,
    sandbox: bool,
    triggered_by: str,
) -> CustomerSuccessSnapshot | None:
    started = time.monotonic()
    signals = compute_signals(customer)
    snapshot = build_snapshot(customer, signals, sandbox=sandbox)
    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(
                id=next_id("AR", AgentRun, base=70000),
                agent=AgentRun.Agent.CUSTOMER_SUCCESS,
                prompt_version="v1.0-phase9a",
                input_payload={
                    "customer_id": customer.id,
                    "signals": signals.to_payload(),
                },
                output_payload={
                    "snapshot": {
                        "score": snapshot.score,
                        "lifecycle_stage": snapshot.lifecycle_stage,
                        "days_since_delivery": snapshot.days_since_delivery,
                        "recommendation_kind": snapshot.recommendation_kind,
                        "reorder_candidate": snapshot.reorder_candidate,
                        "at_risk": snapshot.at_risk,
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
            "phase9a snapshot persist failed customer_id=%s", customer.id
        )
        return None
    write_event(
        kind=AUDIT_KIND_SNAPSHOT,
        text=(
            f"Customer success snapshot {snapshot.pk} for {customer.id} - "
            f"{snapshot.lifecycle_stage} - {snapshot.recommendation_kind}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "customer_id": customer.id,
            "score": snapshot.score,
            "lifecycle_stage": snapshot.lifecycle_stage,
            "recommendation_kind": snapshot.recommendation_kind,
            "agent_run_id": snapshot.agent_run_id,
            "sandbox": snapshot.sandbox,
        },
    )
    return snapshot


@shared_task(name="apps.agents.customer_success.tasks.run_customer_success_agent_daily")
def run_customer_success_agent_daily(
    *, triggered_by: str = "celery_beat_daily"
) -> dict[str, Any]:
    """Daily recommendations-only sweep. RECOMMENDATIONS-ONLY."""
    started = time.monotonic()
    blocked, kill_state = _kill_switch_blocked()
    if blocked:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="Customer success daily run blocked by kill switch",
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
    phones = _candidate_customer_ids()
    customers = _customers_for_phones(phones)
    stage_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    snapshot_ids: list[int] = []
    for customer in customers:
        snapshot = _persist_snapshot_with_run(
            customer, sandbox=sandbox, triggered_by=triggered_by
        )
        if snapshot is None:
            continue
        snapshot_ids.append(snapshot.pk)
        stage_counts[snapshot.lifecycle_stage] = (
            stage_counts.get(snapshot.lifecycle_stage, 0) + 1
        )
        kind_counts[snapshot.recommendation_kind] = (
            kind_counts.get(snapshot.recommendation_kind, 0) + 1
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    summary = {
        "agent": AGENT_NAME,
        "status": "completed",
        "snapshot_count": len(snapshot_ids),
        "customer_count": len(customers),
        "stage_counts": stage_counts,
        "recommendation_counts": kind_counts,
        "duration_ms": duration_ms,
        "sandbox": sandbox,
    }
    write_event(
        kind=AUDIT_KIND_COMPLETED,
        text=(
            f"Customer success daily run completed: "
            f"{len(snapshot_ids)} snapshots in {duration_ms}ms"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "counts": stage_counts,
            "recommendation_counts": kind_counts,
            "duration_ms": duration_ms,
            "snapshot_count": len(snapshot_ids),
            "sandbox": sandbox,
        },
    )
    return summary
