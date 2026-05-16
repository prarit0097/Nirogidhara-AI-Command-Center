"""Phase 11A — Celery tasks for the Vapi transcript ingestion pipeline.

Recommendations-only / write-transcript-only. NEVER sends WhatsApp,
makes a call, dispatches a shipment, or mutates `Order` / `Payment` /
`Customer` / `Lead` / `Shipment` rows. The only side effect is
`CallTranscriptLine` row creation + `Call.transcript_ingested_at` /
`Call.transcript_line_count` updates.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.conf import settings

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .quality_scorer import score_backlog
from .transcript_ingestion import ingest_backlog


logger = logging.getLogger(__name__)


def _kill_switch_blocked() -> bool:
    """Phase 7E-Live-B Hotfix-1 Postgres-safe kill switch pattern.

    A `RuntimeKillSwitch` row with `scope="global"` AND `enabled=False`
    ordered by `-pk` always wins over any seeded `enabled=True` default.
    """
    try:
        from apps.saas.models import RuntimeKillSwitch
    except Exception:  # noqa: BLE001 - app may not be migrated in some envs
        return False
    disabled = (
        RuntimeKillSwitch.objects.filter(scope="global", enabled=False)
        .order_by("-pk")
        .first()
    )
    if disabled is not None:
        return True
    enabled = (
        RuntimeKillSwitch.objects.filter(scope="global", enabled=True)
        .order_by("-pk")
        .first()
    )
    return enabled is None


def _sandbox_active() -> bool:
    try:
        from apps.ai_governance.sandbox import is_sandbox_enabled
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(is_sandbox_enabled())
    except Exception:  # noqa: BLE001
        return False


@shared_task(name="apps.calls.tasks.ingest_transcript_backlog_daily")
def ingest_transcript_backlog_daily(limit: int = 100) -> dict[str, Any]:
    """Daily 23:00 IST sweep — pull Vapi transcripts for the backlog.

    Refusal cases (all written to `AuditEvent` with kind
    `transcript.daily_ingest.blocked` for observability):

    - Kill switch disabled.
    - Sandbox mode active (no real Vapi REST calls allowed).
    - `VAPI_API_KEY` missing from settings.

    Successful runs (even with zero ingested calls) write
    `transcript.daily_ingest.completed` so the operator can see the
    sweep happened.
    """
    if _kill_switch_blocked():
        write_event(
            kind="transcript.daily_ingest.blocked",
            text="Phase 11A daily ingest blocked: runtime kill switch off.",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": "11A", "reason": "kill_switch_off"},
        )
        return {"ok": False, "skipped": True, "reason": "kill_switch_off"}

    if _sandbox_active():
        write_event(
            kind="transcript.daily_ingest.blocked",
            text="Phase 11A daily ingest blocked: sandbox mode active.",
            tone=AuditEvent.Tone.INFO,
            payload={"phase": "11A", "reason": "sandbox_mode"},
        )
        return {"ok": False, "skipped": True, "reason": "sandbox_mode"}

    api_key = getattr(settings, "VAPI_API_KEY", "") or ""
    if not api_key:
        write_event(
            kind="transcript.daily_ingest.blocked",
            text="Phase 11A daily ingest blocked: VAPI_API_KEY missing.",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": "11A", "reason": "vapi_api_key_missing"},
        )
        return {"ok": False, "skipped": True, "reason": "vapi_api_key_missing"}

    summary = ingest_backlog(limit=int(limit or 100))
    # Strip the per-call result list from the audit payload — keep
    # rolling counts only.
    audit_payload = {
        k: v for k, v in summary.items() if k != "results"
    }
    audit_payload["phase"] = "11A"
    write_event(
        kind="transcript.daily_ingest.completed",
        text=(
            f"Phase 11A daily ingest swept {summary['total']} calls "
            f"(ingested={summary['ingested']}, errors={summary['errors']})."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload=audit_payload,
    )
    return summary


@shared_task(name="apps.calls.tasks.score_call_transcripts_daily")
def score_call_transcripts_daily(limit: int = 100) -> dict[str, Any]:
    """Phase 11B daily 23:30 IST sweep — score ingested transcripts.

    Runs 30 minutes after `ingest_transcript_backlog_daily` so the
    newest transcripts get scored the same evening. Refuses (with
    `call_quality.daily_scoring.blocked` audit) when the runtime
    kill switch is off or sandbox mode is active. Successful runs
    (including zero-scored) write
    `call_quality.daily_scoring.completed`.

    NEVER sends WhatsApp, makes a call, dispatches a shipment, or
    mutates `Customer` / `Order` / `Payment` / `Lead` / `Shipment` /
    `DiscountOfferLog`.
    """
    if _kill_switch_blocked():
        write_event(
            kind="call_quality.daily_scoring.blocked",
            text="Phase 11B daily scoring blocked: runtime kill switch off.",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": "11B", "reason": "kill_switch_off"},
        )
        return {"ok": False, "skipped": True, "reason": "kill_switch_off"}

    if _sandbox_active():
        write_event(
            kind="call_quality.daily_scoring.blocked",
            text="Phase 11B daily scoring blocked: sandbox mode active.",
            tone=AuditEvent.Tone.INFO,
            payload={"phase": "11B", "reason": "sandbox_mode"},
        )
        return {"ok": False, "skipped": True, "reason": "sandbox_mode"}

    summary = score_backlog(limit=int(limit or 100))
    audit_payload = {k: v for k, v in summary.items() if k != "results"}
    audit_payload["phase"] = "11B"
    write_event(
        kind="call_quality.daily_scoring.completed",
        text=(
            f"Phase 11B daily scoring swept {summary['total']} calls "
            f"(scored={summary['scored']}, errors={summary['errors']}, "
            f"avg_composite={summary['avg_composite_score']})."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload=audit_payload,
    )
    return summary


__all__ = (
    "ingest_transcript_backlog_daily",
    "score_call_transcripts_daily",
)
