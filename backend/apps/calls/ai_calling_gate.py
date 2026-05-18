"""Phase 12A — AI Calling Campaign Gate V1 (Director-approved Vapi outbound).

Wraps the existing ``apps.calls.services.trigger_call_for_lead``
entrypoint in a Director-approved campaign gate so AI outbound calls
land on real leads safely. The gate enforces:

- structured 30-minute Director UTC window
  (``apps.saas.utc_window.validate_within_director_window`` with
  ``max_window_seconds=1800``).
- ``AI_CALLING_ENABLED=true`` runtime env flag (defaults LOCKED off).
- ``--confirm-ai-calling-campaign`` explicit CLI flag.
- Postgres-safe ``RuntimeKillSwitch`` enabled (same `-pk` pattern as
  every Phase 7-11 task).
- Sandbox-aware skip (``apps.ai_governance.sandbox.is_sandbox_enabled``).
- ``VAPI_MODE=live`` at execute time. ``mock`` / ``test`` paths skip
  the real Vapi API but still record per-lead skip audits.
- Stage eligibility (default allowed Lead.Status =
  ``{New, AI Calling Started, Interested, Callback Required}``).
- Frequency limit (skip leads with a Call row in the last 24h).
- Single active campaign — refuses prepare if any draft/approved/
  executing gate exists.

NEVER sends WhatsApp / payments / shipments / Razorpay. The only
side effect on execute is calling ``trigger_call_for_lead`` per
eligible lead — and only when every guard above is satisfied.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Lead

from .models import AiCallCampaignGate, Call


logger = logging.getLogger(__name__)


# Lead.Status values that are eligible by default. Anything else is
# either already converted (Payment Link Sent, Order Punched) or opted
# out (Not Interested, Invalid).
DEFAULT_ALLOWED_STAGES: tuple[str, ...] = (
    Lead.Status.NEW.value,
    Lead.Status.AI_CALLING_STARTED.value,
    Lead.Status.INTERESTED.value,
    Lead.Status.CALLBACK_REQUIRED.value,
)
BLOCKED_STAGES: frozenset[str] = frozenset(
    {
        Lead.Status.PAYMENT_LINK_SENT.value,
        Lead.Status.ORDER_PUNCHED.value,
        Lead.Status.NOT_INTERESTED.value,
        Lead.Status.INVALID.value,
    }
)

# 30 minute structured UTC window (vs 15 min for payment gates).
MAX_WINDOW_SECONDS = 1800

ACTIVE_STATUSES = (
    AiCallCampaignGate.Status.DRAFT.value,
    AiCallCampaignGate.Status.APPROVED.value,
    AiCallCampaignGate.Status.EXECUTING.value,
)

# Audit kinds (each ≤ 64 chars).
AUDIT_PREPARED = "ai_calling.campaign.prepared"
AUDIT_APPROVED = "ai_calling.campaign.approved"
AUDIT_EXECUTED = "ai_calling.campaign.executed"
AUDIT_CANCELLED = "ai_calling.campaign.cancelled"
AUDIT_REFUSED = "ai_calling.campaign.refused"
AUDIT_LEAD_DISPATCHED = "ai_calling.campaign.lead.dispatched"
AUDIT_LEAD_SKIPPED = "ai_calling.campaign.lead.skipped"


class AiCallCampaignGateError(Exception):
    """Raised when a gate transition / execute is refused."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_phone(phone: str) -> str:
    phone = (phone or "").strip()
    return phone[-4:] if phone else ""


def _kill_switch_blocked() -> tuple[bool, dict[str, Any]]:
    """Phase 7E-Live-B Hotfix-1 Postgres-safe pattern."""
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


def _sandbox_active() -> bool:
    try:
        from apps.ai_governance.sandbox import is_sandbox_enabled
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(is_sandbox_enabled())
    except Exception:  # noqa: BLE001
        return False


def _frequency_cutoff() -> Any:
    hours = int(
        getattr(settings, "AI_CALLING_FREQUENCY_LIMIT_HOURS", 24) or 24
    )
    return timezone.now() - timedelta(hours=hours)


def _was_recently_called(lead_id: str) -> bool:
    cutoff = _frequency_cutoff()
    return Call.objects.filter(
        lead_id=lead_id, created_at__gte=cutoff
    ).exists()


def _vapi_mode() -> str:
    return (getattr(settings, "VAPI_MODE", "mock") or "mock").lower()


def _ai_calling_enabled() -> bool:
    return bool(getattr(settings, "AI_CALLING_ENABLED", False))


def _active_gate_exists() -> AiCallCampaignGate | None:
    return (
        AiCallCampaignGate.objects.filter(status__in=ACTIVE_STATUSES)
        .order_by("-pk")
        .first()
    )


def _summary_payload(gate: AiCallCampaignGate) -> dict[str, Any]:
    return {
        "phase": "12A",
        "gate_id": gate.pk,
        "status": gate.status,
        "operator_name": gate.operator_name,
        "stage_filter": list(gate.stage_filter or []),
        "max_leads": int(gate.max_leads or 0),
        "leads_selected_count": len(gate.leads_selected or []),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_campaign_gate(
    *,
    operator_name: str,
    stage_filter: list[str] | None = None,
    max_leads: int | None = None,
    ai_assistant_id: str = "",
    operator_note: str = "",
) -> dict[str, Any]:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise AiCallCampaignGateError(
            "operator_name_required", "operator_name is required."
        )

    active = _active_gate_exists()
    if active is not None:
        raise AiCallCampaignGateError(
            "active_campaign_exists",
            (
                f"AI calling campaign gate {active.pk} is in status "
                f"'{active.status}'. Cancel or complete it before "
                "preparing a new one."
            ),
        )

    if stage_filter is None or len(stage_filter) == 0:
        effective_stages = list(DEFAULT_ALLOWED_STAGES)
    else:
        effective_stages = [str(s).strip() for s in stage_filter if str(s).strip()]
        if any(s in BLOCKED_STAGES for s in effective_stages):
            raise AiCallCampaignGateError(
                "stage_filter_includes_blocked_stage",
                (
                    "stage_filter cannot include blocked stages "
                    f"{sorted(BLOCKED_STAGES)}."
                ),
            )

    configured_max = int(
        getattr(settings, "AI_CALLING_MAX_PER_CAMPAIGN", 20) or 20
    )
    if max_leads is None or max_leads <= 0:
        effective_max = configured_max
    else:
        effective_max = min(int(max_leads), configured_max)

    assistant_id = (
        ai_assistant_id
        or (getattr(settings, "VAPI_ASSISTANT_ID", "") or "")
    )

    # Eligible leads: stage in filter, non-empty phone, not recently called.
    candidate_qs = Lead.objects.filter(
        status__in=effective_stages,
    ).exclude(phone="")
    cutoff = _frequency_cutoff()
    recently_called_ids = set(
        Call.objects.filter(
            lead_id__in=candidate_qs.values_list("id", flat=True),
            created_at__gte=cutoff,
        ).values_list("lead_id", flat=True)
    )

    selected_ids: list[str] = []
    for lead_id in candidate_qs.order_by("-created_at").values_list(
        "id", flat=True
    ):
        if lead_id in recently_called_ids:
            continue
        selected_ids.append(lead_id)
        if len(selected_ids) >= effective_max:
            break

    gate = AiCallCampaignGate.objects.create(
        status=AiCallCampaignGate.Status.DRAFT.value,
        ai_assistant_id=assistant_id[:120],
        stage_filter=effective_stages,
        max_leads=effective_max,
        leads_selected=selected_ids,
        operator_name=operator_name[:120],
        operator_note=operator_note or "",
        prepared_at=timezone.now(),
        sandbox=_sandbox_active(),
    )
    write_event(
        kind=AUDIT_PREPARED,
        text=(
            f"AI calling campaign gate {gate.pk} prepared "
            f"({len(selected_ids)} leads selected)."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            **_summary_payload(gate),
            "operator_note": (operator_note or "")[:240],
        },
    )
    return {
        "ok": True,
        "gate_id": gate.pk,
        "status": gate.status,
        "stage_filter": list(gate.stage_filter or []),
        "max_leads": int(gate.max_leads or 0),
        "leads_selected_count": len(selected_ids),
        "ai_assistant_id_present": bool(assistant_id),
        "blockers": [],
        "next_action": (
            "Run inspect_ai_calling_campaign + then "
            "approve_ai_calling_campaign with a 30-min "
            "BEGIN_UTC/END_UTC window."
        ),
    }


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


def approve_campaign_gate(
    *,
    gate_id: int,
    operator_name: str,
    intent: str,
    director_signoff: str,
) -> dict[str, Any]:
    from apps.saas.utc_window import (
        parse_director_signoff_window,
        validate_within_director_window,
    )

    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise AiCallCampaignGateError(
            "operator_name_required", "operator_name is required."
        )
    intent = (intent or "").strip()
    if not intent:
        raise AiCallCampaignGateError(
            "intent_required", "Director intent is required."
        )

    gate = AiCallCampaignGate.objects.filter(pk=gate_id).first()
    if gate is None:
        raise AiCallCampaignGateError(
            "gate_not_found", f"AiCallCampaignGate {gate_id} not found."
        )
    if gate.status != AiCallCampaignGate.Status.DRAFT.value:
        raise AiCallCampaignGateError(
            "gate_not_draft",
            (
                f"Gate {gate.pk} is in status '{gate.status}', expected "
                "'draft'."
            ),
        )

    parsed = parse_director_signoff_window(director_signoff or "")
    if parsed is None:
        raise AiCallCampaignGateError(
            "director_signoff_missing_utc_window",
            (
                "Director sign-off must contain BEGIN_UTC=<ISO-Z> and "
                "END_UTC=<ISO-Z> markers."
            ),
        )
    validation = validate_within_director_window(
        parsed, max_window_seconds=MAX_WINDOW_SECONDS, now=timezone.now()
    )
    # The execute path checks `now ∈ [start, end]`; at approve time we
    # only require the window to be well-formed and ≤ 30 min. So if the
    # only validation error is `before_start`, that's actually OK for
    # approval (the window is in the future).
    if not validation.valid:
        bad_codes = set(validation.blockers or [])
        # Accept "now before window start" — Director is approving ahead
        # of the window. Reject everything else (malformed / stale /
        # too-long / window already ended).
        only_before_start = bad_codes == {
            "now_outside_director_signoff_utc_window_before_start"
        }
        if not only_before_start:
            raise AiCallCampaignGateError(
                "director_signoff_window_invalid",
                (
                    "Director sign-off UTC window failed validation: "
                    + ", ".join(sorted(bad_codes))
                ),
            )

    gate.status = AiCallCampaignGate.Status.APPROVED.value
    gate.intent = intent
    gate.director_signoff = director_signoff
    gate.recorded_signoff_window_start_utc = parsed.window_start_utc
    gate.recorded_signoff_window_end_utc = parsed.window_end_utc
    gate.recorded_signoff_window_valid = True
    gate.approved_at = timezone.now()
    # Operator name on a re-approve attempt always overwrites — the
    # latest Director name is the one we want to audit.
    gate.operator_name = operator_name[:120]
    gate.save(
        update_fields=[
            "status",
            "intent",
            "director_signoff",
            "recorded_signoff_window_start_utc",
            "recorded_signoff_window_end_utc",
            "recorded_signoff_window_valid",
            "approved_at",
            "operator_name",
            "updated_at",
        ]
    )
    write_event(
        kind=AUDIT_APPROVED,
        text=(
            f"AI calling campaign gate {gate.pk} approved by "
            f"{operator_name}."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            **_summary_payload(gate),
            "intent_excerpt": intent[:240],
            "window_start_utc": (
                gate.recorded_signoff_window_start_utc.isoformat()
                if gate.recorded_signoff_window_start_utc
                else None
            ),
            "window_end_utc": (
                gate.recorded_signoff_window_end_utc.isoformat()
                if gate.recorded_signoff_window_end_utc
                else None
            ),
        },
    )
    return {
        "ok": True,
        "gate_id": gate.pk,
        "status": gate.status,
        "recorded_signoff_window_valid": True,
        "window_start_utc": (
            gate.recorded_signoff_window_start_utc.isoformat()
            if gate.recorded_signoff_window_start_utc
            else None
        ),
        "window_end_utc": (
            gate.recorded_signoff_window_end_utc.isoformat()
            if gate.recorded_signoff_window_end_utc
            else None
        ),
        "next_action": (
            "Inside the approved UTC window: AI_CALLING_ENABLED=true "
            "VAPI_MODE=live python manage.py execute_ai_calling_campaign "
            f"{gate.pk} --operator-name '<NAME>' "
            "--confirm-ai-calling-campaign"
        ),
    }


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def _refuse_execute(gate, code: str, message: str) -> AiCallCampaignGateError:
    write_event(
        kind=AUDIT_REFUSED,
        text=f"AI calling campaign gate {gate.pk} execute refused: {code}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            **_summary_payload(gate),
            "blocker_code": code,
        },
    )
    return AiCallCampaignGateError(code, message)


def execute_campaign_gate(
    *,
    gate_id: int,
    operator_name: str,
    confirm_ai_calling: bool = False,
) -> dict[str, Any]:
    from apps.saas.utc_window import validate_within_director_window

    started_ms = time.monotonic()
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise AiCallCampaignGateError(
            "operator_name_required", "operator_name is required."
        )

    gate = AiCallCampaignGate.objects.filter(pk=gate_id).first()
    if gate is None:
        raise AiCallCampaignGateError(
            "gate_not_found", f"AiCallCampaignGate {gate_id} not found."
        )
    if gate.status != AiCallCampaignGate.Status.APPROVED.value:
        raise AiCallCampaignGateError(
            "gate_not_approved",
            (
                f"Gate {gate.pk} is in status '{gate.status}', expected "
                "'approved'."
            ),
        )

    if not confirm_ai_calling:
        raise _refuse_execute(
            gate,
            "confirm_ai_calling_campaign_flag_required",
            "Pass --confirm-ai-calling-campaign to execute.",
        )
    if not _ai_calling_enabled():
        raise _refuse_execute(
            gate,
            "ai_calling_not_enabled",
            (
                "AI_CALLING_ENABLED=true must be set in the runtime env "
                "prefix (never edit .env.production)."
            ),
        )

    blocked, kill_state = _kill_switch_blocked()
    if blocked:
        raise _refuse_execute(
            gate,
            "runtime_kill_switch_disabled",
            f"Runtime kill switch disabled: {kill_state}.",
        )

    # Window check: now must be inside [start, end].
    if not (
        gate.recorded_signoff_window_start_utc
        and gate.recorded_signoff_window_end_utc
    ):
        raise _refuse_execute(
            gate,
            "approval_window_not_recorded",
            "Approval window missing on the gate; re-approve first.",
        )

    # Build a synthetic ParsedWindow-like object and re-validate via the
    # shared helper so the same rules apply (≤ 30 min, fresh, now-inside).
    from apps.saas.utc_window import ParsedWindow

    parsed = ParsedWindow(
        window_start_utc=gate.recorded_signoff_window_start_utc,
        window_end_utc=gate.recorded_signoff_window_end_utc,
        raw_signoff_text_truncated="",
    )
    window_check = validate_within_director_window(
        parsed,
        max_window_seconds=MAX_WINDOW_SECONDS,
        now=timezone.now(),
    )
    if not window_check.valid:
        raise _refuse_execute(
            gate,
            "approval_window_invalid_at_execute",
            (
                "Approval UTC window invalid at execute time: "
                + ", ".join(sorted(window_check.blockers or []))
            ),
        )

    vapi_mode = _vapi_mode()
    sandbox = _sandbox_active()

    gate.status = AiCallCampaignGate.Status.EXECUTING.value
    gate.executed_at = timezone.now()
    gate.vapi_mode_at_execute = vapi_mode[:20]
    if sandbox:
        gate.sandbox = True
    gate.save(
        update_fields=[
            "status",
            "executed_at",
            "vapi_mode_at_execute",
            "sandbox",
            "updated_at",
        ]
    )

    leads_attempted: list[str] = []
    dispatched = 0
    skipped = 0
    skip_reasons: dict[str, int] = {}

    def _bump_skip(reason: str) -> None:
        nonlocal skipped
        skipped += 1
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    # Lazy import so tests patching the symbol at this path resolve to
    # the same callable the live path uses.
    from apps.calls import services as call_services

    for lead_id in list(gate.leads_selected or []):
        lead = Lead.objects.filter(pk=lead_id).first()
        if lead is None:
            _bump_skip("lead_not_found")
            write_event(
                kind=AUDIT_LEAD_SKIPPED,
                text=f"AI calling campaign {gate.pk}: lead {lead_id} not found.",
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "gate_id": gate.pk,
                    "lead_id": lead_id,
                    "reason": "lead_not_found",
                },
            )
            continue
        # Re-validate stage (stage may have changed since prepare).
        if lead.status not in (gate.stage_filter or []):
            _bump_skip("stage_no_longer_eligible")
            write_event(
                kind=AUDIT_LEAD_SKIPPED,
                text=(
                    f"AI calling campaign {gate.pk}: lead {lead.id} stage "
                    f"changed to {lead.status}; skipping."
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "gate_id": gate.pk,
                    "lead_id": lead.id,
                    "phone_last4": _mask_phone(lead.phone),
                    "current_stage": lead.status,
                    "reason": "stage_no_longer_eligible",
                },
            )
            continue
        if _was_recently_called(lead.id):
            _bump_skip("recently_called")
            write_event(
                kind=AUDIT_LEAD_SKIPPED,
                text=(
                    f"AI calling campaign {gate.pk}: lead {lead.id} "
                    "called within frequency window; skipping."
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "gate_id": gate.pk,
                    "lead_id": lead.id,
                    "phone_last4": _mask_phone(lead.phone),
                    "reason": "recently_called",
                },
            )
            continue
        if sandbox:
            _bump_skip("sandbox_skip")
            leads_attempted.append(lead.id)
            write_event(
                kind=AUDIT_LEAD_SKIPPED,
                text=(
                    f"AI calling campaign {gate.pk}: sandbox mode — "
                    f"skipping Vapi call for lead {lead.id}."
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "gate_id": gate.pk,
                    "lead_id": lead.id,
                    "phone_last4": _mask_phone(lead.phone),
                    "reason": "sandbox_skip",
                },
            )
            continue
        if vapi_mode != "live":
            _bump_skip("vapi_not_live_skip")
            leads_attempted.append(lead.id)
            write_event(
                kind=AUDIT_LEAD_SKIPPED,
                text=(
                    f"AI calling campaign {gate.pk}: VAPI_MODE={vapi_mode} "
                    f"(not 'live') — skipping Vapi call for lead {lead.id}."
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "gate_id": gate.pk,
                    "lead_id": lead.id,
                    "phone_last4": _mask_phone(lead.phone),
                    "vapi_mode": vapi_mode,
                    "reason": "vapi_not_live_skip",
                },
            )
            continue
        # Live dispatch.
        try:
            call = call_services.trigger_call_for_lead(
                lead=lead,
                by_user=type(
                    "_SyntheticUser",
                    (),
                    {"username": f"ai_calling_campaign_{gate.pk}"},
                )(),
                purpose="sales_call",
            )
        except Exception as exc:  # noqa: BLE001 - one failure must not kill the loop
            _bump_skip("vapi_error")
            leads_attempted.append(lead.id)
            logger.warning(
                "phase12a: trigger_call_for_lead failed for %s: %s",
                lead.id,
                exc,
            )
            write_event(
                kind=AUDIT_LEAD_SKIPPED,
                text=(
                    f"AI calling campaign {gate.pk}: Vapi dispatch failed "
                    f"for lead {lead.id} ({exc})."
                ),
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "gate_id": gate.pk,
                    "lead_id": lead.id,
                    "phone_last4": _mask_phone(lead.phone),
                    "reason": "vapi_error",
                    "error_excerpt": str(exc)[:240],
                },
            )
            continue
        dispatched += 1
        leads_attempted.append(lead.id)
        write_event(
            kind=AUDIT_LEAD_DISPATCHED,
            text=(
                f"AI calling campaign {gate.pk}: dispatched call for "
                f"lead {lead.id} (call {call.id})."
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "gate_id": gate.pk,
                "lead_id": lead.id,
                "phone_last4": _mask_phone(lead.phone),
                "call_id": call.id,
                "provider_call_id_last4": (call.provider_call_id or "")[-4:],
                "vapi_mode": vapi_mode,
            },
        )

    gate.leads_attempted = leads_attempted
    gate.calls_attempted = len(leads_attempted)
    gate.calls_dispatched = dispatched
    gate.calls_skipped = skipped
    gate.status = AiCallCampaignGate.Status.COMPLETED.value
    gate.completed_at = timezone.now()
    gate.save(
        update_fields=[
            "leads_attempted",
            "calls_attempted",
            "calls_dispatched",
            "calls_skipped",
            "status",
            "completed_at",
            "updated_at",
        ]
    )
    duration_ms = int((time.monotonic() - started_ms) * 1000)
    write_event(
        kind=AUDIT_EXECUTED,
        text=(
            f"AI calling campaign gate {gate.pk} completed: "
            f"dispatched={dispatched} skipped={skipped} "
            f"vapi_mode={vapi_mode}."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            **_summary_payload(gate),
            "calls_attempted": len(leads_attempted),
            "calls_dispatched": dispatched,
            "calls_skipped": skipped,
            "skip_reasons": skip_reasons,
            "vapi_mode_at_execute": vapi_mode,
            "sandbox": sandbox,
            "duration_ms": duration_ms,
        },
    )
    return {
        "ok": True,
        "gate_id": gate.pk,
        "status": gate.status,
        "calls_attempted": len(leads_attempted),
        "calls_dispatched": dispatched,
        "calls_skipped": skipped,
        "skip_reasons": skip_reasons,
        "vapi_mode_at_execute": vapi_mode,
        "sandbox": sandbox,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Inspect + Cancel
# ---------------------------------------------------------------------------


def inspect_campaign_gate(gate_id: int) -> dict[str, Any]:
    gate = AiCallCampaignGate.objects.filter(pk=gate_id).first()
    if gate is None:
        raise AiCallCampaignGateError(
            "gate_not_found", f"AiCallCampaignGate {gate_id} not found."
        )
    lead_rows: list[dict[str, Any]] = []
    cutoff = _frequency_cutoff()
    lead_ids = list(gate.leads_selected or [])
    leads_map = {lead.id: lead for lead in Lead.objects.filter(pk__in=lead_ids)}
    recently_called = set(
        Call.objects.filter(
            lead_id__in=lead_ids, created_at__gte=cutoff
        ).values_list("lead_id", flat=True)
    )
    for lead_id in lead_ids:
        lead = leads_map.get(lead_id)
        if lead is None:
            lead_rows.append(
                {
                    "lead_id": lead_id,
                    "status": "missing",
                    "phone_last4": "",
                    "recently_called": False,
                }
            )
            continue
        lead_rows.append(
            {
                "lead_id": lead.id,
                "status": lead.status,
                "phone_last4": _mask_phone(lead.phone),
                "recently_called": lead.id in recently_called,
            }
        )
    return {
        "gate_id": gate.pk,
        "status": gate.status,
        "operator_name": gate.operator_name,
        "stage_filter": list(gate.stage_filter or []),
        "max_leads": int(gate.max_leads or 0),
        "ai_assistant_id_last4": (gate.ai_assistant_id or "")[-4:],
        "leads_selected_count": len(lead_ids),
        "leads_attempted_count": len(gate.leads_attempted or []),
        "calls_dispatched": int(gate.calls_dispatched or 0),
        "calls_skipped": int(gate.calls_skipped or 0),
        "prepared_at": gate.prepared_at,
        "approved_at": gate.approved_at,
        "executed_at": gate.executed_at,
        "completed_at": gate.completed_at,
        "cancelled_at": gate.cancelled_at,
        "recorded_signoff_window_start_utc": (
            gate.recorded_signoff_window_start_utc
        ),
        "recorded_signoff_window_end_utc": (
            gate.recorded_signoff_window_end_utc
        ),
        "recorded_signoff_window_valid": bool(
            gate.recorded_signoff_window_valid
        ),
        "vapi_mode_at_execute": gate.vapi_mode_at_execute,
        "sandbox": bool(gate.sandbox),
        "intent": gate.intent,
        "leads": lead_rows,
    }


def cancel_campaign_gate(
    *, gate_id: int, operator_name: str, reason: str = ""
) -> dict[str, Any]:
    operator_name = (operator_name or "").strip()
    if not operator_name:
        raise AiCallCampaignGateError(
            "operator_name_required", "operator_name is required."
        )
    gate = AiCallCampaignGate.objects.filter(pk=gate_id).first()
    if gate is None:
        raise AiCallCampaignGateError(
            "gate_not_found", f"AiCallCampaignGate {gate_id} not found."
        )
    if gate.status not in {
        AiCallCampaignGate.Status.DRAFT.value,
        AiCallCampaignGate.Status.APPROVED.value,
    }:
        raise AiCallCampaignGateError(
            "gate_not_cancellable",
            (
                f"Gate {gate.pk} is in status '{gate.status}'; only "
                "draft or approved gates can be cancelled."
            ),
        )
    gate.status = AiCallCampaignGate.Status.CANCELLED.value
    gate.cancelled_at = timezone.now()
    if reason:
        meta = dict(gate.metadata or {})
        meta["cancel_reason"] = reason[:240]
        gate.metadata = meta
    gate.save(
        update_fields=["status", "cancelled_at", "metadata", "updated_at"]
    )
    write_event(
        kind=AUDIT_CANCELLED,
        text=f"AI calling campaign gate {gate.pk} cancelled by {operator_name}.",
        tone=AuditEvent.Tone.WARNING,
        payload={
            **_summary_payload(gate),
            "cancelled_by": operator_name,
            "reason": (reason or "")[:240],
        },
    )
    return {
        "ok": True,
        "gate_id": gate.pk,
        "status": gate.status,
        "reason": reason,
    }


__all__ = (
    "DEFAULT_ALLOWED_STAGES",
    "BLOCKED_STAGES",
    "MAX_WINDOW_SECONDS",
    "AiCallCampaignGateError",
    "prepare_campaign_gate",
    "approve_campaign_gate",
    "execute_campaign_gate",
    "inspect_campaign_gate",
    "cancel_campaign_gate",
)
