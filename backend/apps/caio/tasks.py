"""Phase 11C — CAIO Audit Agent V1 Celery task.

Daily governance audit producing one :class:`apps.caio.models.CaioAuditSnapshot`
+ one ``AgentRun`` + audit events per invocation. Honors the
Postgres-safe kill switch from Phase 7E-Live-B Hotfix-1.

CAIO has NO direct execution power. This task NEVER triggers
WhatsApp / makes a call / dispatches a shipment / mutates
`Customer` / `Order` / `Payment` / `Lead` / `Shipment` /
`DiscountOfferLog` / any Phase 9 snapshot row.
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
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import CaioAuditSnapshot
from .service import AGENT_NAME, MODEL_USED, build_snapshot


logger = logging.getLogger(__name__)


AUDIT_KIND_SNAPSHOT = "caio.audit.snapshot.created"
AUDIT_KIND_COMPLETED = "caio.audit.daily_run.completed"
AUDIT_KIND_BLOCKED = "caio.audit.daily_run.blocked"


def _kill_switch_blocked() -> tuple[bool, dict[str, Any]]:
    """Phase 7E-Live-B Hotfix-1 Postgres-safe kill switch.

    A `RuntimeKillSwitch` row with `scope="global"` AND
    `enabled=False`, ordered by `-pk`, always wins over a seeded
    `enabled=True` default.
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
        return False, {
            "enabled": True,
            "model": "lookup_failed_treated_as_enabled",
        }
    if row is None:
        return False, {
            "enabled": True,
            "model": "no_row_treated_as_enabled",
        }
    return (not bool(row.enabled)), {
        "enabled": bool(row.enabled),
        "model": "RuntimeKillSwitch",
        "id": row.pk,
    }


def _serialize_snapshot(snapshot: CaioAuditSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.pk,
        "snapshot_at": snapshot.snapshot_at.isoformat(),
        "window_days": snapshot.window_days,
        "severity": snapshot.severity,
        "compliance_risk_call_count": snapshot.compliance_risk_call_count,
        "compliance_risk_agent_labels": list(
            snapshot.compliance_risk_agent_labels or []
        ),
        "transcript_backlog_count": snapshot.transcript_backlog_count,
        "call_quality_trend": snapshot.call_quality_trend,
        "agent_data_gaps": snapshot.agent_data_gaps,
        "agent_data_gap_names": list(snapshot.agent_data_gap_names or []),
        "agent_anomaly_flags": dict(snapshot.agent_anomaly_flags or {}),
        "weak_learning_indicators": list(
            snapshot.weak_learning_indicators or []
        ),
        "ceo_audit_notes": list(snapshot.ceo_audit_notes or []),
        "recommendation_text": snapshot.recommendation_text,
        "audited_agents": list(snapshot.audited_agents or []),
        "sandbox": snapshot.sandbox,
        "agent_run_id": snapshot.agent_run_id,
    }


@shared_task(name="apps.caio.tasks.run_caio_audit_agent_daily")
def run_caio_audit_agent_daily(
    *,
    window_days: int = 30,
    triggered_by: str = "celery_beat_daily",
) -> dict[str, Any]:
    """Daily CAIO governance audit. RECOMMENDATIONS-ONLY.

    Refusal paths (write `caio.audit.daily_run.blocked` audit):

    - Postgres-safe `RuntimeKillSwitch` disabled.

    Sandbox mode does NOT block the audit (governance must run even
    in sandbox) — instead it propagates to `snapshot.sandbox=True`
    and the linked `AgentRun.sandbox_mode=True`.
    """
    started = time.monotonic()
    blocked, kill_state = _kill_switch_blocked()
    if blocked:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="CAIO daily audit blocked: runtime kill switch off.",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "11C",
                "reason": "runtime_kill_switch_disabled",
                "kill": kill_state,
            },
        )
        return {
            "agent": AGENT_NAME,
            "status": "blocked",
            "reason": "runtime_kill_switch_disabled",
            "kill": kill_state,
        }

    compute_started = time.monotonic()
    snapshot_obj = build_snapshot(window_days=window_days)
    compute_latency_ms = int((time.monotonic() - compute_started) * 1000)
    sandbox = bool(snapshot_obj.sandbox)

    snapshot: CaioAuditSnapshot | None = None
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(
                id=next_id("AR", AgentRun, base=72000),
                agent=AgentRun.Agent.CAIO,
                prompt_version="v1.0-phase11c",
                input_payload={
                    "window_days": int(window_days),
                    "audited_agents": list(snapshot_obj.audited_agents or []),
                },
                output_payload={
                    "snapshot": {
                        "severity": snapshot_obj.severity,
                        "compliance_risk_call_count": (
                            snapshot_obj.compliance_risk_call_count
                        ),
                        "agent_data_gaps": snapshot_obj.agent_data_gaps,
                        "transcript_backlog_count": (
                            snapshot_obj.transcript_backlog_count
                        ),
                        "weak_learning_count": len(
                            snapshot_obj.weak_learning_indicators or []
                        ),
                        "anomaly_agent_count": len(
                            snapshot_obj.agent_anomaly_flags or {}
                        ),
                    }
                },
                status=AgentRun.Status.SUCCESS,
                provider="disabled",
                model=MODEL_USED,
                latency_ms=compute_latency_ms,
                cost_usd=Decimal("0"),
                dry_run=True,
                triggered_by=triggered_by,
                sandbox_mode=sandbox,
                completed_at=timezone.now(),
            )
            snapshot_obj.agent_run = run
            snapshot_obj.save()
            snapshot = snapshot_obj
    except Exception:  # pragma: no cover - defensive
        logger.exception("phase11c snapshot persist failed")
        return {
            "agent": AGENT_NAME,
            "status": "failed",
            "reason": "persist_failed",
        }

    write_event(
        kind=AUDIT_KIND_SNAPSHOT,
        text=(
            f"CAIO audit snapshot {snapshot.pk} - severity={snapshot.severity} "
            f"compliance_risk={snapshot.compliance_risk_call_count} "
            f"data_gaps={snapshot.agent_data_gaps}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "11C",
            "snapshot_id": snapshot.pk,
            "severity": snapshot.severity,
            "compliance_risk_call_count": (
                snapshot.compliance_risk_call_count
            ),
            "agent_data_gaps": snapshot.agent_data_gaps,
            "transcript_backlog_count": snapshot.transcript_backlog_count,
            "call_quality_trend": snapshot.call_quality_trend,
            "anomaly_agent_count": len(snapshot.agent_anomaly_flags or {}),
            "weak_learning_count": len(snapshot.weak_learning_indicators or []),
            "agent_run_id": snapshot.agent_run_id,
            "sandbox": snapshot.sandbox,
        },
    )

    duration_ms = int((time.monotonic() - started) * 1000)
    write_event(
        kind=AUDIT_KIND_COMPLETED,
        text=(
            f"CAIO daily audit completed in {duration_ms}ms - "
            f"snapshot_id={snapshot.pk} severity={snapshot.severity}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "phase": "11C",
            "snapshot_id": snapshot.pk,
            "severity": snapshot.severity,
            "duration_ms": duration_ms,
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


__all__ = ("run_caio_audit_agent_daily",)
