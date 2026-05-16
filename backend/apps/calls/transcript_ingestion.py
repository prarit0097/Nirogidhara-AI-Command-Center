"""Phase 11A — Transcript Ingestion Pipeline V1.

Active-pull layer that fetches Vapi call transcripts via the REST API
and stores them as :class:`apps.calls.models.CallTranscriptLine` rows.
Phase 2D already persists transcript lines from inbound Vapi webhooks;
Phase 11A handles the *backlog* case — calls that completed without a
webhook landing (Vapi outage, queue lag, calls predating the webhook
config). This module NEVER triggers an outbound call, sends WhatsApp,
mutates payments, or dispatches shipments — it is strictly a read /
write-transcript-only path.

Reuses existing infrastructure:

- ``Call.provider_call_id`` — the Vapi call id we look up.
- ``CallTranscriptLine`` — the persisted utterance rows (legacy
  ``order`` / ``who`` / ``text`` shape from Phase 2D).
- ``settings.VAPI_API_KEY`` / ``settings.VAPI_API_BASE_URL`` — same
  credentials used by ``apps.calls.integrations.vapi_client``.

New Phase 11A fields on ``Call``:

- ``transcript_ingested_at`` — set to ``now()`` on a successful pull.
- ``transcript_line_count`` — denormalized count (also drives the
  Phase 9E backlog query).
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import Call, CallTranscriptLine


logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 30
RECENT_CALL_GRACE_HOURS = 24
VAPI_TIMEOUT_SECONDS = 30


def _vapi_base_url() -> str:
    base = (getattr(settings, "VAPI_API_BASE_URL", "") or "").rstrip("/")
    return base or "https://api.vapi.ai"


def _vapi_api_key() -> str:
    return getattr(settings, "VAPI_API_KEY", "") or ""


def _normalize_utterance(raw: dict[str, Any], fallback_order: int) -> dict[str, Any] | None:
    """Map a Vapi response utterance shape onto our (order, who, text) row.

    Vapi has shipped several response shapes over the years; we accept
    each one we have seen in the wild:

    - ``{"role": "assistant"|"user", "message": "..."}`` (chat-messages)
    - ``{"role": "...", "text": "..."}`` (legacy)
    - ``{"who": "Agent"|"Customer", "text": "..."}`` (our own seed shape)
    - ``{"speaker": "agent"|"customer", "transcript": "..."}`` (analyzer)
    """
    if not isinstance(raw, dict):
        return None
    text = (
        raw.get("message")
        or raw.get("text")
        or raw.get("content")
        or raw.get("transcript")
        or ""
    )
    text = str(text).strip()
    if not text:
        return None
    who_raw = (
        raw.get("role")
        or raw.get("who")
        or raw.get("speaker")
        or "unknown"
    )
    who = str(who_raw).strip()[:40] or "unknown"
    order_value = raw.get("order")
    try:
        order = int(order_value) if order_value is not None else int(fallback_order)
    except (TypeError, ValueError):
        order = int(fallback_order)
    return {"order": max(0, order), "who": who, "text": text}


def fetch_vapi_transcript(vapi_call_id: str) -> list[dict[str, Any]] | None:
    """Pull the transcript for a single Vapi call id.

    Returns a list of normalized utterance dicts (``order``, ``who``,
    ``text``) on success, or ``None`` on any non-success outcome
    (missing key, missing id, 404, network error, malformed body).
    Never raises — backlog runs must continue on per-call failure.
    """
    vapi_call_id = (vapi_call_id or "").strip()
    if not vapi_call_id:
        return None
    api_key = _vapi_api_key()
    if not api_key:
        logger.warning("phase11a: VAPI_API_KEY not configured; skipping fetch")
        return None
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - missing-dep path
        logger.warning("phase11a: requests not installed; skipping fetch")
        return None

    url = f"{_vapi_base_url()}/call/{vapi_call_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=VAPI_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - network errors are non-fatal
        logger.warning("phase11a: Vapi fetch network error for %s: %s", vapi_call_id, exc)
        return None
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        logger.warning(
            "phase11a: Vapi fetch %s returned %s",
            vapi_call_id,
            response.status_code,
        )
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None

    # Vapi's preferred field is ``messages`` for chat-style transcripts;
    # older calls may expose ``transcript`` (string or list) or
    # ``artifact.messages``.
    candidate: Any = body.get("messages")
    if not candidate:
        artifact = body.get("artifact")
        if isinstance(artifact, dict):
            candidate = artifact.get("messages") or artifact.get("transcript")
    if not candidate:
        candidate = body.get("transcript") or body.get("lines")
    if isinstance(candidate, str):
        # Some legacy shapes return the full transcript as one string.
        candidate = [{"who": "transcript", "text": candidate}]
    if not isinstance(candidate, list):
        return None

    utterances: list[dict[str, Any]] = []
    for idx, raw in enumerate(candidate):
        normalized = _normalize_utterance(raw, fallback_order=idx)
        if normalized is not None:
            utterances.append(normalized)
    return utterances or None


def ingest_call_transcript(
    call_id: str, *, dry_run: bool = False
) -> dict[str, Any]:
    """Pull + persist the transcript for one ``Call`` row.

    Returns a result dict whose ``skipped`` / ``ok`` keys describe the
    outcome. Never raises on per-call failures (DB rollback inside the
    atomic block on persistence error).
    """
    started_ms = time.monotonic()
    call = Call.objects.filter(pk=call_id).first()
    if call is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "call_not_found",
            "call_id": call_id,
        }
    if not (call.provider_call_id or "").strip():
        return {
            "ok": False,
            "skipped": True,
            "reason": "no_vapi_id",
            "call_id": call.id,
        }
    if call.transcript_ingested_at is not None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "already_ingested",
            "call_id": call.id,
            "line_count": int(call.transcript_line_count or 0),
        }

    utterances = fetch_vapi_transcript(call.provider_call_id)
    if not utterances:
        return {
            "ok": False,
            "skipped": True,
            "reason": "no_transcript_from_vapi",
            "call_id": call.id,
        }

    if dry_run:
        return {
            "ok": True,
            "skipped": False,
            "dry_run": True,
            "call_id": call.id,
            "line_count": len(utterances),
            "duration_ms": int((time.monotonic() - started_ms) * 1000),
        }

    try:
        with transaction.atomic():
            # Phase 2D's webhook handler may have stored partial transcript
            # lines already; replace them with the canonical REST pull.
            CallTranscriptLine.objects.filter(call=call).delete()
            rows = [
                CallTranscriptLine(
                    call=call,
                    order=int(u["order"]),
                    who=str(u["who"])[:40],
                    text=str(u["text"]),
                )
                for u in utterances
            ]
            CallTranscriptLine.objects.bulk_create(rows)
            call.transcript_ingested_at = timezone.now()
            call.transcript_line_count = len(rows)
            call.save(
                update_fields=[
                    "transcript_ingested_at",
                    "transcript_line_count",
                    "updated_at",
                ]
            )
    except Exception as exc:  # noqa: BLE001 - rollback already happened
        logger.exception("phase11a: ingest failed for call %s: %s", call.id, exc)
        return {
            "ok": False,
            "skipped": True,
            "reason": "ingest_error",
            "call_id": call.id,
            "error": str(exc),
        }

    provider_last4 = (call.provider_call_id or "")[-4:]
    write_event(
        kind="transcript.ingested",
        text=(
            f"Phase 11A ingested {len(utterances)} transcript lines for "
            f"call {call.id} (vapi …{provider_last4})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "11A",
            "call_id": call.id,
            "line_count": len(utterances),
            "vapi_call_id_last4": provider_last4,
        },
    )
    return {
        "ok": True,
        "skipped": False,
        "call_id": call.id,
        "line_count": len(utterances),
        "duration_ms": int((time.monotonic() - started_ms) * 1000),
    }


def get_transcript_backlog(window_days: int = DEFAULT_WINDOW_DAYS) -> QuerySet[Call]:
    """Return Calls that need transcript ingestion.

    A Call is in the backlog when:

    1. ``created_at`` is inside the rolling window (default 30 days).
    2. ``created_at`` is older than 24h (give Vapi time to flush the
       transcript via webhook before pulling).
    3. ``transcript_ingested_at`` is NULL **or** ``transcript_line_count
       == 0`` (the denormalized signal).
    4. ``provider_call_id`` is non-empty (no point pulling from Vapi
       without a referenceable id).

    Ordered newest-first so the most likely "Vapi has it" candidates
    run first.
    """
    now = timezone.now()
    return (
        Call.objects.filter(
            created_at__gte=now - timedelta(days=window_days),
            created_at__lt=now - timedelta(hours=RECENT_CALL_GRACE_HOURS),
        )
        .filter(
            Q(transcript_ingested_at__isnull=True)
            | Q(transcript_line_count=0)
        )
        .exclude(provider_call_id="")
        .order_by("-created_at")
    )


def ingest_backlog(
    *,
    limit: int = 50,
    dry_run: bool = False,
    sandbox: bool = False,
) -> dict[str, Any]:
    """Drive transcript ingestion for the current backlog.

    Counts every termination outcome separately so the daily summary
    can flag operational issues (e.g. lots of ``no_transcript_from_vapi``
    skips would mean the Vapi account is wrong).
    """
    started_ms = time.monotonic()
    summary: dict[str, Any] = {
        "total": 0,
        "ingested": 0,
        "skipped_no_id": 0,
        "skipped_already_done": 0,
        "skipped_no_transcript": 0,
        "errors": 0,
        "sandbox": bool(sandbox),
        "dry_run": bool(dry_run),
        "duration_ms": 0,
        "results": [],
    }
    if sandbox:
        # Sandbox-aware: never touch the live Vapi REST API.
        summary["duration_ms"] = int((time.monotonic() - started_ms) * 1000)
        summary["skipped_reason"] = "sandbox_mode"
        return summary

    backlog = list(get_transcript_backlog()[: max(1, int(limit))])
    summary["total"] = len(backlog)
    for call in backlog:
        result = ingest_call_transcript(call.id, dry_run=dry_run)
        summary["results"].append(result)
        if result.get("ok") and not result.get("skipped"):
            summary["ingested"] += 1
        elif result.get("reason") == "no_vapi_id":
            summary["skipped_no_id"] += 1
        elif result.get("reason") == "already_ingested":
            summary["skipped_already_done"] += 1
        elif result.get("reason") == "no_transcript_from_vapi":
            summary["skipped_no_transcript"] += 1
        elif result.get("reason") == "ingest_error":
            summary["errors"] += 1
    summary["duration_ms"] = int((time.monotonic() - started_ms) * 1000)
    return summary


def get_backlog_overview(window_days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    """Read-only diagnostic snapshot used by the inspector CLI + API."""
    now = timezone.now()
    window_start = now - timedelta(days=window_days)
    grace_cutoff = now - timedelta(hours=RECENT_CALL_GRACE_HOURS)
    window_qs = Call.objects.filter(created_at__gte=window_start)
    ingestible_qs = window_qs.filter(created_at__lt=grace_cutoff)
    backlog_qs = get_transcript_backlog(window_days=window_days)
    ingested_qs = window_qs.filter(transcript_ingested_at__isnull=False)
    total = window_qs.count()
    backlog_count = backlog_qs.count()
    ingested_count = ingested_qs.count()
    oldest = backlog_qs.order_by("created_at").first()
    newest = backlog_qs.first()
    backlog_ratio = (
        round(backlog_count / max(1, ingestible_qs.count()), 4)
        if ingestible_qs.exists()
        else 0.0
    )
    sample = [
        {
            "call_id": c.id,
            "created_at": c.created_at,
            "provider_call_id_last4": (c.provider_call_id or "")[-4:],
        }
        for c in backlog_qs[:10]
    ]
    return {
        "window_days": window_days,
        "now": now,
        "window_start": window_start,
        "grace_cutoff_utc": grace_cutoff,
        "total_calls_in_window": total,
        "ingested_count": ingested_count,
        "backlog_count": backlog_count,
        "backlog_ratio": backlog_ratio,
        "oldest_backlog_at": oldest.created_at if oldest else None,
        "newest_backlog_at": newest.created_at if newest else None,
        "top_backlog": sample,
    }


__all__ = (
    "DEFAULT_WINDOW_DAYS",
    "RECENT_CALL_GRACE_HOURS",
    "fetch_vapi_transcript",
    "ingest_call_transcript",
    "get_transcript_backlog",
    "ingest_backlog",
    "get_backlog_overview",
)
