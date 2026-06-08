"""Phase 16O — Director Briefing Snapshot History + Acknowledgement Trail.

INTERNAL-ONLY history / acknowledgement layer over the Phase 16N Director AI
briefing. It saves a point-in-time copy of `briefing.get_director_ai_briefing`,
lets the Director acknowledge / mark-follow-up / archive / annotate it, and keeps
a review-event trail.

**Nothing here calls a live AI/LLM provider, sends WhatsApp/Meta Cloud, places a
Vapi call, calls Razorpay/PayU/Delhivery, creates a payment link / AWB, mutates
an `Order` / `Payment` / `Shipment` / `Customer` / `Lead` / `AiApprovedAction`,
enqueues a business Celery job, or touches `RuntimeKillSwitch` / `SandboxState`.**
The only rows written are `AiDirectorBriefingSnapshot` + its
`AiDirectorBriefingSnapshotEvent` review trail. Every saved payload preserves the
locked safety flags and is sanitized (no raw prompts, secrets, full phones,
addresses, or customer PII — the briefing service already enforces this).
"""
from __future__ import annotations

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from . import briefing


class BriefingSnapshotError(Exception):
    """Raised on an invalid briefing-snapshot operation."""


def _json_safe(obj):
    """Round-trip through DjangoJSONEncoder so datetimes become ISO strings.

    The Phase 16N briefing carries ``generatedAt`` datetimes; a plain JSONField
    cannot store those directly. This makes the payload pure JSON-serializable.
    """
    return json.loads(json.dumps(obj, cls=DjangoJSONEncoder))


def _actor(user):
    return user if (user and getattr(user, "is_authenticated", False)) else None


def _record_event(snapshot, event_type: str, *, actor=None, note: str = "", metadata=None) -> None:
    from .models import AiDirectorBriefingSnapshotEvent

    AiDirectorBriefingSnapshotEvent.objects.create(
        snapshot=snapshot, event_type=event_type, actor=_actor(actor),
        note=str(note or "")[:4000], metadata=dict(metadata or {}),
    )


def _default_title(window_days: int) -> str:
    from django.utils import timezone

    stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")
    return f"Director AI briefing — {stamp} (last {window_days}d)"


def create_director_briefing_snapshot(*, user=None, window_days: int = 7, title: str = ""):
    """Save the current Phase 16N briefing as an internal snapshot (DB-only)."""
    from .models import AiDirectorBriefingSnapshot

    window_days = max(1, min(30, int(window_days or 7)))
    # Reuse the Phase 16N briefing service — deterministic, no provider call.
    # Normalize to pure JSON (datetimes → ISO strings) before persisting.
    payload = _json_safe(briefing.get_director_ai_briefing(window_days=window_days))

    # Defensive: the persisted snapshot ALWAYS carries the locked flags,
    # regardless of what the payload claims.
    snapshot = AiDirectorBriefingSnapshot.objects.create(
        title=(title or _default_title(window_days))[:200],
        window_days=window_days,
        briefing_payload=payload,
        executive_summary=list(payload.get("executiveSummary", [])),
        attention_items=dict(payload.get("attentionItems", {})),
        recommendations=list(payload.get("safeRecommendations", [])),
        blocked_live_actions=list(payload.get("blockedLiveActions", [])),
        safety_snapshot=dict(payload.get("safetySnapshot", {})),
        ai_mode=str(payload.get("briefingStatus", {}).get("aiMode", "mock"))[:12],
        readonly=True,
        internal_only=True,
        provider_call_made=False,
        external_action_taken=False,
        live_autonomous_locked=True,
        status=AiDirectorBriefingSnapshot.Status.UNREVIEWED,
        created_by=_actor(user),
    )
    _record_event(snapshot, "created", actor=user, note="Saved current Director AI briefing.")
    return snapshot


def list_director_briefing_snapshots(*, status: str = "", created_by: str = "", limit: int = 100):
    from .models import AiDirectorBriefingSnapshot

    qs = AiDirectorBriefingSnapshot.objects.select_related(
        "created_by", "acknowledged_by"
    ).order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    if created_by:
        qs = qs.filter(created_by__username=created_by)
    return list(qs[: max(1, min(200, int(limit or 100)))])


def get_director_briefing_snapshot(snapshot_id):
    from .models import AiDirectorBriefingSnapshot

    return AiDirectorBriefingSnapshot.objects.filter(pk=snapshot_id).first()


def _guard_not_archived(snapshot) -> None:
    from .models import AiDirectorBriefingSnapshot

    if snapshot.status == AiDirectorBriefingSnapshot.Status.ARCHIVED:
        raise BriefingSnapshotError("snapshot_archived")


def acknowledge_director_briefing_snapshot(snapshot, *, user=None, note: str = ""):
    """Mark a snapshot acknowledged (internal-only review state)."""
    from django.utils import timezone

    from .models import AiDirectorBriefingSnapshot

    _guard_not_archived(snapshot)
    snapshot.status = AiDirectorBriefingSnapshot.Status.ACKNOWLEDGED
    snapshot.acknowledged_by = _actor(user)
    snapshot.acknowledged_at = timezone.now()
    if note:
        snapshot.director_note = str(note)[:4000]
    # Re-assert the locked flags on every transition.
    snapshot.provider_call_made = False
    snapshot.external_action_taken = False
    snapshot.live_autonomous_locked = True
    snapshot.save(update_fields=[
        "status", "acknowledged_by", "acknowledged_at", "director_note",
        "provider_call_made", "external_action_taken", "live_autonomous_locked",
        "updated_at",
    ])
    _record_event(snapshot, "acknowledged", actor=user, note=note)
    return snapshot


def mark_briefing_needs_follow_up(snapshot, *, user=None, note: str = ""):
    from .models import AiDirectorBriefingSnapshot

    _guard_not_archived(snapshot)
    snapshot.status = AiDirectorBriefingSnapshot.Status.NEEDS_FOLLOW_UP
    if note:
        snapshot.director_note = str(note)[:4000]
    snapshot.provider_call_made = False
    snapshot.external_action_taken = False
    snapshot.live_autonomous_locked = True
    snapshot.save(update_fields=[
        "status", "director_note",
        "provider_call_made", "external_action_taken", "live_autonomous_locked",
        "updated_at",
    ])
    _record_event(snapshot, "marked_needs_follow_up", actor=user, note=note)
    return snapshot


def archive_director_briefing_snapshot(snapshot, *, user=None, note: str = ""):
    from .models import AiDirectorBriefingSnapshot

    snapshot.status = AiDirectorBriefingSnapshot.Status.ARCHIVED
    if note:
        snapshot.director_note = str(note)[:4000]
    snapshot.provider_call_made = False
    snapshot.external_action_taken = False
    snapshot.live_autonomous_locked = True
    snapshot.save(update_fields=[
        "status", "director_note",
        "provider_call_made", "external_action_taken", "live_autonomous_locked",
        "updated_at",
    ])
    _record_event(snapshot, "archived", actor=user, note=note)
    return snapshot


def add_director_briefing_note(snapshot, *, user=None, note: str = ""):
    note = str(note or "").strip()
    if not note:
        raise BriefingSnapshotError("note_required")
    # Append to the running director note (keeps history human-readable).
    existing = (snapshot.director_note or "").strip()
    snapshot.director_note = (f"{existing}\n{note}" if existing else note)[:8000]
    snapshot.save(update_fields=["director_note", "updated_at"])
    _record_event(snapshot, "note_added", actor=user, note=note)
    return snapshot


def get_director_briefing_snapshot_summary() -> dict[str, Any]:
    from django.db.models import Count

    from .models import AiDirectorBriefingSnapshot

    counts = {c: 0 for c, _ in AiDirectorBriefingSnapshot.Status.choices}
    for row in AiDirectorBriefingSnapshot.objects.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]
    latest = AiDirectorBriefingSnapshot.objects.order_by("-created_at").first()
    return {
        "total": sum(counts.values()),
        "unreviewed": counts.get("unreviewed", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "needsFollowUp": counts.get("needs_follow_up", 0),
        "archived": counts.get("archived", 0),
        "lastSnapshotAt": latest.created_at if latest else None,
        "byStatus": counts,
        "readonly": True,
        "internalOnly": True,
        "providerCallMade": False,
        "externalActionTaken": False,
        "liveAutonomousLocked": True,
        "phase": "16O",
    }


def build_safe_text(snapshot) -> str:
    """A sanitized, internal-only plain-text summary (no PII, never sent)."""
    lines: list[str] = []
    lines.append(f"DIRECTOR AI BRIEFING SNAPSHOT (internal-only) — {snapshot.title}")
    lines.append(
        f"Status: {snapshot.status} | Window: {snapshot.window_days}d | "
        f"AI mode: {snapshot.ai_mode}"
    )
    lines.append(
        "Safety: readonly=true, internalOnly=true, providerCallMade=false, "
        "externalActionTaken=false, liveAutonomousLocked=true, "
        "phase15ShellFrozenCommit=eefd8b3"
    )
    lines.append("")
    lines.append("EXECUTIVE SUMMARY:")
    for b in (snapshot.executive_summary or []):
        lines.append(f"  - {b}")
    att = snapshot.attention_items or {}
    lines.append("")
    lines.append(
        "ATTENTION: "
        f"blocked={att.get('blockedCount', 0)}, overdue={att.get('overdueCount', 0)}, "
        f"dueSoon={att.get('dueSoonCount', 0)}, unassignedHighPriority="
        f"{att.get('unassignedHighPriority', 0)}, pendingSuggestions="
        f"{att.get('pendingSuggestions', 0)}, pendingInternalActions="
        f"{att.get('pendingInternalActions', 0)}, slaRisk={att.get('slaRiskCount', 0)}"
    )
    lines.append("")
    lines.append("SAFE INTERNAL RECOMMENDATIONS:")
    for r in (snapshot.recommendations or []):
        lines.append(
            f"  - [{r.get('priority', '')}] {r.get('recommendationType', '')}: "
            f"{r.get('reason', '')} (next: {r.get('permittedAction', '')})"
        )
    lines.append("")
    lines.append("BLOCKED LIVE ACTIONS (all locked): " + ", ".join(
        b.get("channel", "") for b in (snapshot.blocked_live_actions or [])
    ))
    if (snapshot.director_note or "").strip():
        lines.append("")
        lines.append("DIRECTOR NOTE:")
        lines.append(f"  {snapshot.director_note.strip()}")
    lines.append("")
    lines.append("(Internal record only — never sent to any customer or external service.)")
    return "\n".join(lines)
