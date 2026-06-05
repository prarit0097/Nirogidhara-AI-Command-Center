"""Phase 16I — AI Copilot services (deterministic / mock by default).

**No function here calls a live AI/LLM provider, sends WhatsApp/Meta Cloud,
places a Vapi call, calls Razorpay/PayU/Delhivery, creates a payment link / AWB,
or mutates an `Order` / `Payment` / `Shipment` / `Customer` / `Lead` / the
Phase 15 safety shell.** Suggestions are generated deterministically from
existing safe data, sanitized (phones masked to last-4, no full address, no raw
payloads), and always stored with `provider_call_made=False` +
`external_action_allowed=False` + `external_action_taken=False` for human review.

A live LLM provider is gated behind a future, separately-approved phase; even
when a provider is configured, this phase reports it as ``live_gated`` and never
invokes it.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

# Deterministic compliance signal lists (no medical claims emitted here — these
# are *risk detectors* that flag forbidden vocabulary so a human can review).
_UNAPPROVED_CLAIM_TERMS = (
    "cure", "guaranteed", "guarantee", "100%", "permanent", "miracle",
    "no side effect", "clinically proven", "fda", "instant result",
)
_EMERGENCY_TERMS = (
    "chest pain", "emergency", "hospital", "bleeding", "suicide",
    "saans", "unconscious", "severe", "icu",
)
_DISCOUNT_MISUSE_TERMS = (
    "free", "100% off", "lifetime free", "biggest discount", "loot",
    "60% off", "70% off", "80% off", "90% off",
)
_TONE_RISK_TERMS = (
    "guarantee", "urgent", "last chance", "hurry", "limited stock", "!!!",
)


def _flag(name: str, default: bool = False) -> bool:
    return bool(getattr(settings, name, default))


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not digits:
        return ""
    return f"*****{digits[-4:]}" if len(digits) >= 4 else "*****"


def _sandbox_on() -> bool:
    try:
        from apps.ai_governance.sandbox import is_sandbox_enabled

        return bool(is_sandbox_enabled())
    except Exception:  # noqa: BLE001
        return False


def ai_copilot_mode() -> str:
    """The deterministic generation mode actually used this phase.

    Always ``mock`` (deterministic) unless sandbox is ON, in which case it is
    ``sandbox`` (still deterministic). A live provider is never used here.
    """
    return "sandbox" if _sandbox_on() else "mock"


def _live_provider_status() -> str:
    """Capability of the (never-invoked) live AI provider — display only."""
    provider = (getattr(settings, "AI_PROVIDER", "disabled") or "disabled").lower()
    live_gate = _flag("AI_COPILOT_LIVE_ENABLED")  # default False; not invoked
    has_key = bool(
        getattr(settings, "OPENAI_API_KEY", "")
        or getattr(settings, "ANTHROPIC_API_KEY", "")
    )
    if provider != "disabled" and has_key and live_gate:
        return "live_gated"
    if provider != "disabled" and has_key:
        return "live_gated"
    return "unavailable"


def get_ai_copilot_status() -> dict[str, Any]:
    """Read-only AI Copilot safety + mode status (no mutation, no provider call)."""
    from apps.integration_hardening import services as hardening

    safety = hardening.safety_summary()
    return {
        "aiPaused": safety["aiPaused"],
        "sandboxOn": safety["sandboxOn"],
        "syncLive": True,
        "providerLiveActionsLocked": True,
        "liveAutonomousExecutionLocked": True,
        "phase15ShellFrozen": True,
        "aiMode": ai_copilot_mode(),
        "liveProviderStatus": _live_provider_status(),
        "aiProvider": (getattr(settings, "AI_PROVIDER", "disabled") or "disabled"),
        "humanApprovalRequired": True,
        "noProviderCallMade": True,
        "phase": "16I",
    }


# ---------------------------------------------------------------------------
# Source resolution (read-only; references existing rows, never mutates)
# ---------------------------------------------------------------------------


def _resolve_source(source_type: str, source_id: str):
    """Best-effort load of a source row; returns None if missing/unknown."""
    if not source_id:
        return None
    try:
        from django.apps import apps as django_apps

        model_map = {
            "lead": ("crm", "Lead"),
            "customer": ("crm", "Customer"),
            "order": ("orders", "Order"),
            "imported_queue_item": ("data_imports", "ImportedCallQueueItem"),
            "pilot_plan": ("pilot", "PilotPlan"),
            "pilot_task": ("pilot", "PilotTask"),
        }
        if source_type not in model_map:
            return None
        app_label, model_name = model_map[source_type]
        model = django_apps.get_model(app_label, model_name)
        return model.objects.filter(pk=source_id).first()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Deterministic generators — each returns a sanitized suggestion payload dict
# ---------------------------------------------------------------------------


def _payload(*, title, summary, recommendation, risk_flags=None, detail=None, confidence=0.6):
    return {
        "title": str(title)[:200],
        "summary": str(summary),
        "recommendation": str(recommendation),
        "risk_flags": list(risk_flags or []),
        "detail": dict(detail or {}),
        "confidence_score": float(confidence),
    }


def generate_lead_summary(source_type: str, source_id: str) -> dict[str, Any]:
    obj = _resolve_source(source_type, source_id)
    if obj is None:
        return _payload(
            title="Lead summary (no source)",
            summary="No matching lead/customer found; provide a valid source id.",
            recommendation="Select a lead or customer to summarise.",
            risk_flags=["source_not_found"],
            confidence=0.2,
        )
    name = getattr(obj, "name", "") or "Customer"
    phone = _mask_phone(getattr(obj, "phone", ""))
    status = getattr(obj, "status", "") or ""
    product = getattr(obj, "product_interest", "") or getattr(obj, "product", "") or ""
    disease = getattr(obj, "disease_category", "") or ""
    state = getattr(obj, "state", "") or ""
    consent_call = bool(getattr(obj, "consent_call", False))
    risk: list[str] = []
    if not consent_call:
        risk.append("call_consent_not_recorded")
    if getattr(obj, "duplicate", False):
        risk.append("possible_duplicate")
    nba = "Call to understand the problem; do not pitch price first." if consent_call else (
        "Confirm call consent before any outreach."
    )
    return _payload(
        title=f"Lead summary — {name}",
        summary=(
            f"{name} (phone {phone}) from {state or 'unknown'}; status '{status or 'new'}'. "
            f"Interest: {product or 'unspecified'}{(', category ' + disease) if disease else ''}. "
            "Internal analysis only — no message has been sent."
        ),
        recommendation=nba,
        risk_flags=risk,
        detail={
            "phoneMasked": phone, "status": status, "product": product,
            "diseaseCategory": disease, "consentCall": consent_call,
        },
        confidence=0.65,
    )


def generate_call_priority(source_type: str, source_id: str) -> dict[str, Any]:
    obj = _resolve_source(source_type, source_id)
    score = 50
    factors: list[str] = []
    if obj is not None:
        status = (getattr(obj, "status", "") or "").lower()
        if status in {"interested", "callback required", "callback_required"}:
            score += 30
            factors.append("warm_status")
        if getattr(obj, "quality", "") in {"hot", "HOT"}:
            score += 15
            factors.append("hot_quality")
        if getattr(obj, "consent_call", False):
            score += 5
            factors.append("call_consent")
        else:
            score -= 10
            factors.append("no_call_consent")
    score = max(0, min(100, score))
    band = "high" if score >= 70 else "medium" if score >= 40 else "low"
    return _payload(
        title=f"Call priority — {band.upper()} ({score})",
        summary=f"Deterministic priority score {score}/100 (band: {band}).",
        recommendation=(
            "Prioritise in today's calling queue." if band == "high"
            else "Queue normally." if band == "medium"
            else "Low priority; revisit after higher-intent leads."
        ),
        risk_flags=[] if getattr(obj, "consent_call", True) else ["no_call_consent"],
        detail={"score": score, "band": band, "factors": factors},
        confidence=0.7,
    )


def generate_call_script_draft(source_type: str, source_id: str) -> dict[str, Any]:
    obj = _resolve_source(source_type, source_id)
    name = getattr(obj, "name", "") or "ji"
    # Safe, generic Hinglish opener — NO medical claim, NO discount promise.
    opener = (
        f"Namaste {name}, main Nirogidhara se baat kar raha/rahi hoon. "
        "Aapne humse sampark kiya tha — main samajhna chahta/chahti hoon ki "
        "aapki sabse badi problem kya hai, taaki sahi guidance de saku."
    )
    objections = [
        "Price: pehle value + process samjhaayein; discount ka zikr na karein.",
        "Trust: brand + doctor-review process + approved info hi share karein.",
        "Doubt: customer ki problem suno; approved Claim Vault content hi bolo.",
    ]
    return _payload(
        title="Suggested call opening + objection points",
        summary="Internal draft script (deterministic). Not sent anywhere.",
        recommendation=opener,
        risk_flags=["use_approved_claim_vault_only", "no_discount_promise_upfront"],
        detail={"opener": opener, "objectionPoints": objections},
        confidence=0.6,
    )


def generate_objection_handling(source_type: str, source_id: str) -> dict[str, Any]:
    points = [
        "Value over price: explain the standard ₹3000 / 30-capsule course + process.",
        "Trust: cite doctor-review process; share only approved Claim Vault content.",
        "Urgency without pressure: invite a next step; never promise a cure.",
        "Discount discipline: do NOT offer a discount upfront; handle the objection first.",
    ]
    return _payload(
        title="Objection handling points",
        summary="Deterministic objection-handling guidance for internal calling agents.",
        recommendation="Lead with value + trust; keep discount discipline (50% total cap).",
        risk_flags=["no_discount_promise_upfront", "no_medical_claim_outside_claim_vault"],
        detail={"points": points},
        confidence=0.6,
    )


def generate_compliance_risk_review(text: str = "", source_type: str = "manual", source_id: str = "") -> dict[str, Any]:
    sample = str(text or "")
    if not sample and source_id:
        obj = _resolve_source(source_type, source_id)
        sample = " ".join(
            str(getattr(obj, f, "") or "")
            for f in ("notes", "summary", "recommendation")
        ) if obj is not None else ""
    low = sample.lower()
    risk: list[str] = []
    if any(t in low for t in _UNAPPROVED_CLAIM_TERMS):
        risk.append("unapproved_claim_risk")
    if any(t in low for t in _EMERGENCY_TERMS):
        risk.append("emergency_escalation_risk")
    if any(t in low for t in _DISCOUNT_MISUSE_TERMS):
        risk.append("discount_misuse_risk")
    if any(t in low for t in _TONE_RISK_TERMS):
        risk.append("tone_risk")
    verdict = "clean" if not risk else "review_required"
    return _payload(
        title=f"Compliance risk review — {verdict}",
        summary=(
            "No forbidden vocabulary detected in the sampled text."
            if not risk else
            f"{len(risk)} risk signal(s) detected; human compliance review required."
        ),
        recommendation=(
            "No action — text appears within approved bounds (still human-reviewed)."
            if not risk else
            "Route to QA/Compliance; do NOT use until approved. Replace any claim with Claim Vault content."
        ),
        risk_flags=risk,
        detail={"verdict": verdict, "signalCount": len(risk)},
        confidence=0.75 if risk else 0.6,
    )


def generate_pilot_recommendations(source_type: str = "manual", source_id: str = "") -> dict[str, Any]:
    plan = None
    if source_type == "pilot_plan" and source_id:
        plan = _resolve_source("pilot_plan", source_id)
    try:
        from apps.pilot.services import get_execution_summary

        summary = get_execution_summary(plan)
    except Exception:  # noqa: BLE001
        summary = {"byTeam": [], "overall": {"total": 0, "done": 0, "blocked": 0, "progressPct": 0}}

    by_team = summary.get("byTeam", [])
    overall = summary.get("overall", {})
    bottlenecks = [
        t for t in by_team
        if (t.get("blocked", 0) > 0) or (t.get("inProgress", 0) > t.get("done", 0))
    ]
    risk: list[str] = []
    if overall.get("blocked", 0) > 0:
        risk.append("blocked_tasks_present")
    if overall.get("total", 0) == 0:
        risk.append("no_tasks_generated")
    rec_lines = []
    for t in bottlenecks[:6]:
        rec_lines.append(
            f"{t.get('teamLabel', t.get('teamRole'))}: {t.get('blocked', 0)} blocked / "
            f"{t.get('inProgress', 0)} in-progress — review assignment."
        )
    return _payload(
        title="Pilot execution recommendations",
        summary=(
            f"Overall {overall.get('done', 0)}/{overall.get('total', 0)} tasks done "
            f"({overall.get('progressPct', 0)}%); {overall.get('blocked', 0)} blocked."
        ),
        recommendation=(
            "; ".join(rec_lines) if rec_lines
            else "No bottlenecks detected; continue internal execution."
        ),
        risk_flags=risk,
        detail={"byTeam": by_team, "overall": overall},
        confidence=0.65,
    )


def generate_director_briefing(source_type: str = "manual", source_id: str = "") -> dict[str, Any]:
    status = get_ai_copilot_status()
    pilot = generate_pilot_recommendations()
    return _payload(
        title="Director briefing recommendation",
        summary=(
            f"Safety: AI {'Paused' if status['aiPaused'] else 'Running'}, "
            f"Sandbox {'ON' if status['sandboxOn'] else 'OFF'}, live actions locked. "
            f"Pilot: {pilot['summary']}"
        ),
        recommendation=(
            "Review pilot bottlenecks internally; keep live provider actions locked "
            "until a separate Director live-gate directive."
        ),
        risk_flags=pilot["risk_flags"],
        detail={"safety": status, "pilot": pilot["detail"]},
        confidence=0.6,
    )


def _draft_message(kind: str, source_type: str, source_id: str) -> dict[str, Any]:
    """Internal-only draft message — never sent; no live link/amount embedded."""
    obj = _resolve_source(source_type, source_id)
    name = getattr(obj, "name", "") or getattr(obj, "customer_name", "") or "ji"
    bodies = {
        "whatsapp_draft": (
            f"{name} ji, Nirogidhara se namaste. Aapki query ke liye dhanyavaad — "
            "hamari team aapse jaldi sampark karegi. (Internal draft — not sent.)"
        ),
        "payment_followup_draft": (
            f"{name} ji, aapka order pending hai. Hamari team aapko process samjhaayegi. "
            "Payment link Director ke approval ke baad hi bheja jayega. (Internal draft — not sent.)"
        ),
        "rto_rescue_draft": (
            f"{name} ji, aapka parcel wapas aa raha tha. Hum dobara delivery arrange kar sakte hain — "
            "team confirm karegi. (Internal draft — not sent.)"
        ),
    }
    body = bodies.get(kind, "(Internal draft — not sent.)")
    return _payload(
        title=f"{kind.replace('_', ' ').title()} (internal draft)",
        summary="Draft only. This message is NOT sent and no payment link / AWB is created.",
        recommendation=body,
        risk_flags=["draft_only_not_sent", "no_live_provider_action", "human_approval_required"],
        detail={"draftBody": body, "channel": kind},
        confidence=0.55,
    )


_GENERATORS = {
    "lead_summary": lambda st, sid, text: generate_lead_summary(st, sid),
    "call_priority": lambda st, sid, text: generate_call_priority(st, sid),
    "call_script": lambda st, sid, text: generate_call_script_draft(st, sid),
    "objection_handling": lambda st, sid, text: generate_objection_handling(st, sid),
    "compliance_risk": lambda st, sid, text: generate_compliance_risk_review(text, st, sid),
    "pilot_recommendation": lambda st, sid, text: generate_pilot_recommendations(st, sid),
    "task_recommendation": lambda st, sid, text: generate_pilot_recommendations(st, sid),
    "director_briefing": lambda st, sid, text: generate_director_briefing(st, sid),
    "whatsapp_draft": lambda st, sid, text: _draft_message("whatsapp_draft", st, sid),
    "payment_followup_draft": lambda st, sid, text: _draft_message("payment_followup_draft", st, sid),
    "rto_rescue_draft": lambda st, sid, text: _draft_message("rto_rescue_draft", st, sid),
}

SUGGESTION_TYPES = tuple(_GENERATORS.keys())


def create_ai_suggestion(
    *, suggestion_type: str, source_type: str = "manual", source_id: str = "",
    text: str = "", created_by=None,
):
    """Generate (deterministically) + persist a copilot suggestion for review.

    NEVER calls a provider or takes an external action. Returns the row.
    """
    from .models import AiCopilotReviewEvent, AiCopilotSuggestion

    gen = _GENERATORS.get(suggestion_type)
    if gen is None:
        raise ValueError(f"unknown_suggestion_type:{suggestion_type}")

    payload = gen(source_type, source_id, text)
    actor = created_by if (created_by and getattr(created_by, "is_authenticated", False)) else None

    suggestion = AiCopilotSuggestion.objects.create(
        suggestion_type=suggestion_type,
        source_type=source_type if source_type else "manual",
        source_id=str(source_id or "")[:64],
        title=payload["title"],
        summary=payload["summary"],
        recommendation=payload["recommendation"],
        risk_flags=payload["risk_flags"],
        detail=payload["detail"],
        confidence_score=payload["confidence_score"],
        ai_mode=ai_copilot_mode(),
        status=AiCopilotSuggestion.Status.PENDING_REVIEW,
        provider_call_made=False,
        external_action_allowed=False,
        external_action_taken=False,
        created_by=actor,
    )
    AiCopilotReviewEvent.objects.create(
        suggestion=suggestion, action="generated", actor=actor,
        note=f"Generated deterministically (mode={suggestion.ai_mode}).",
    )
    return suggestion


_REVIEW_ACTIONS = {"approve", "reject", "comment", "apply_internal"}
_ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "apply_internal": "applied_internal",
}
_ACTION_TO_EVENT = {
    "approve": "approved",
    "reject": "rejected",
    "comment": "commented",
    "apply_internal": "applied_internal",
}


class AiCopilotReviewError(Exception):
    """Raised on an invalid copilot review action."""


def review_ai_suggestion(suggestion, *, action: str, note: str = "", reviewed_by=None):
    """Record an internal human review decision (no external action, ever)."""
    from .models import AiCopilotReviewEvent

    if action not in _REVIEW_ACTIONS:
        raise AiCopilotReviewError(f"unknown_action:{action}")

    actor = reviewed_by if (reviewed_by and getattr(reviewed_by, "is_authenticated", False)) else None
    new_status = _ACTION_TO_STATUS.get(action)
    if new_status is not None:
        suggestion.status = new_status
    if note:
        suggestion.reviewer_note = str(note)[:4000]
    if actor:
        suggestion.reviewed_by = actor
    # The locked contract holds regardless of approval — "applied_internal" is an
    # internal acknowledgement only; it never authorises an external action.
    suggestion.provider_call_made = False
    suggestion.external_action_allowed = False
    suggestion.external_action_taken = False
    suggestion.save()

    AiCopilotReviewEvent.objects.create(
        suggestion=suggestion, action=_ACTION_TO_EVENT[action], actor=actor,
        note=str(note or "")[:4000],
    )
    return suggestion


# ---------------------------------------------------------------------------
# Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge
# ---------------------------------------------------------------------------
#
# Convert an APPROVED AI suggestion into a safe, internal-only work item, and
# apply it WITHOUT any provider/external action. Applying an action may create
# an internal DB object (a pilot task, or an internal note/result record) but
# NEVER sends WhatsApp, places a call, creates a payment link, books a shipment,
# calls a live AI/LLM provider, mutates order/payment/shipment state, or changes
# `RuntimeKillSwitch` / `SandboxState`. Every action keeps
# `provider_action_attempted=False` + `provider_action_taken=False` +
# `external_action_allowed=False` + `external_action_taken=False`.


class AiActionError(Exception):
    """Raised on an invalid AI-action-queue operation."""


# action_type → the PilotTeamRole used when materialising a pilot task.
_ACTION_TEAM_ROLE = {
    "create_calling_followup_task": "calling_agent",
    "create_qa_review_task": "qa_compliance",
    "create_pilot_task": "director_admin",
    "create_callback_item": "calling_agent",
    "create_rto_review_task": "delivery_rto",
    "create_payment_followup_task": "finance_accounts",
    "create_dispatch_review_task": "warehouse_dispatch",
    "create_director_review_item": "director_admin",
    "create_customer_note": "qa_compliance",
    "create_order_note": "qa_compliance",
}


def _action_actor(user):
    return user if (user and getattr(user, "is_authenticated", False)) else None


def _record_action_event(action, event_type: str, *, actor=None, note: str = "") -> None:
    from .models import AiApprovedActionEvent

    AiApprovedActionEvent.objects.create(
        action=action, event_type=event_type, actor=_action_actor(actor),
        note=str(note or "")[:4000],
    )


def create_action_from_approved_suggestion(
    *, suggestion, action_type: str, title: str = "", description: str = "",
    assigned_team: str = "", priority: str = "normal", created_by=None,
):
    """Queue an internal action from an APPROVED suggestion. No provider call."""
    from .models import AiApprovedAction, AiCopilotSuggestion

    valid_types = {c for c, _ in AiApprovedAction.ActionType.choices}
    if action_type not in valid_types:
        raise AiActionError(f"unknown_action_type:{action_type}")
    if suggestion.status != AiCopilotSuggestion.Status.APPROVED:
        # Only an approved suggestion may become an action. draft / pending /
        # rejected / applied_internal are refused.
        raise AiActionError(f"suggestion_not_approved:{suggestion.status}")

    valid_priority = {c for c, _ in AiApprovedAction.Priority.choices}
    if priority not in valid_priority:
        priority = AiApprovedAction.Priority.NORMAL

    actor = _action_actor(created_by)
    action = AiApprovedAction.objects.create(
        source_suggestion=suggestion,
        action_type=action_type,
        source_type=suggestion.source_type,
        source_id=suggestion.source_id,
        title=(title or suggestion.title)[:200],
        description=description or suggestion.recommendation,
        assigned_team=str(assigned_team or "")[:64],
        priority=priority,
        status=AiApprovedAction.Status.PENDING_INTERNAL_ACTION,
        provider_action_attempted=False,
        provider_action_taken=False,
        external_action_allowed=False,
        external_action_taken=False,
        safety_snapshot=_safety_snapshot_for_action(),
        approved_by=suggestion.reviewed_by,
        created_by=actor,
    )
    _record_action_event(action, "created", actor=actor, note="Queued from approved AI suggestion.")
    return action


def _safety_snapshot_for_action() -> dict[str, Any]:
    try:
        from apps.integration_hardening import services as hardening

        s = hardening.safety_summary()
        return {
            "aiPaused": s["aiPaused"],
            "sandboxOn": s["sandboxOn"],
            "providerLiveActionsLocked": True,
            "liveAutonomousExecutionLocked": True,
            "capturedAt": "internal",
        }
    except Exception:  # noqa: BLE001
        return {"providerLiveActionsLocked": True, "liveAutonomousExecutionLocked": True}


def _materialise_pilot_task(action) -> dict[str, Any] | None:
    """Best-effort create an internal PilotTask for a resolvable pilot plan.

    Returns a result dict on success, or None if no pilot plan applies (the
    caller then falls back to a record-only internal result).
    """
    if action.source_type != "pilot_plan" or not action.source_id:
        return None
    try:
        from apps.pilot.models import PilotPlan, PilotTeamRole
        from apps.pilot.services import create_pilot_task

        plan = PilotPlan.objects.filter(pk=action.source_id).first()
        if plan is None:
            return None
        valid_roles = {c for c, _ in PilotTeamRole.choices}
        team_role = _ACTION_TEAM_ROLE.get(action.action_type, "director_admin")
        if team_role not in valid_roles:
            team_role = "director_admin"
        task = create_pilot_task(
            plan, team_role=team_role,
            title=f"[AI] {action.title}"[:200],
            created_by=action.applied_by or action.created_by,
            description=action.description,
            priority="normal",
            assigned_team_label=action.assigned_team,
        )
        return {
            "kind": "pilot_task",
            "pilotTaskId": task.pk,
            "pilotPlanId": plan.pk,
            "teamRole": team_role,
            "providerActionsBlocked": True,
        }
    except Exception:  # noqa: BLE001
        return None


def apply_internal_action(action, *, applied_by=None, note: str = ""):
    """Apply an internal action (DB-only). NEVER calls a provider."""
    from django.utils import timezone

    from .models import AiApprovedAction

    if action.status != AiApprovedAction.Status.PENDING_INTERNAL_ACTION:
        raise AiActionError(f"invalid_status:{action.status}")

    actor = _action_actor(applied_by)
    action.applied_by = actor

    # Try to materialise a real internal pilot task when the action targets a
    # pilot plan; otherwise record an internal-only result payload.
    result = _materialise_pilot_task(action)
    if result is None:
        result = {
            "kind": "internal_action_record",
            "actionType": action.action_type,
            "assignedTeam": action.assigned_team,
            "priority": action.priority,
            "note": "Recorded as an internal work item (no external action, no provider call).",
            "providerActionsBlocked": True,
        }

    # Locked contract — always re-asserted, regardless of result.
    action.provider_action_attempted = False
    action.provider_action_taken = False
    action.external_action_allowed = False
    action.external_action_taken = False
    action.result_payload = result
    action.status = AiApprovedAction.Status.APPLIED_INTERNAL
    action.applied_at = timezone.now()
    action.save()
    _record_action_event(action, "applied_internal", actor=actor, note=note or result.get("kind", ""))
    return action


def reject_internal_action(action, *, actor=None, note: str = ""):
    from .models import AiApprovedAction

    if action.status not in {
        AiApprovedAction.Status.PENDING_INTERNAL_ACTION,
    }:
        raise AiActionError(f"invalid_status:{action.status}")
    action.status = AiApprovedAction.Status.REJECTED
    action.external_action_allowed = False
    action.external_action_taken = False
    action.provider_action_taken = False
    action.save()
    _record_action_event(action, "rejected", actor=actor, note=note)
    return action


def cancel_internal_action(action, *, actor=None, note: str = ""):
    from .models import AiApprovedAction

    if action.status not in {
        AiApprovedAction.Status.PENDING_INTERNAL_ACTION,
    }:
        raise AiActionError(f"invalid_status:{action.status}")
    action.status = AiApprovedAction.Status.CANCELLED
    action.external_action_allowed = False
    action.external_action_taken = False
    action.provider_action_taken = False
    action.save()
    _record_action_event(action, "cancelled", actor=actor, note=note)
    return action


def list_ai_action_queue(*, status: str = "", action_type: str = "", limit: int = 100):
    from .models import AiApprovedAction

    qs = AiApprovedAction.objects.all().order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    if action_type:
        qs = qs.filter(action_type=action_type)
    return qs[: max(1, min(200, int(limit or 100)))]


def get_ai_action_summary() -> dict[str, Any]:
    from django.db.models import Count

    from .models import AiApprovedAction

    counts = {c: 0 for c, _ in AiApprovedAction.Status.choices}
    for row in AiApprovedAction.objects.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]
    return {
        "statusCounts": counts,
        "total": sum(counts.values()),
        "providerActionsLocked": True,
        "liveAutonomousExecutionLocked": True,
        "noProviderActionTaken": True,
        "phase": "16J",
    }


# ---------------------------------------------------------------------------
# Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer
# ---------------------------------------------------------------------------
#
# Make an existing AI-approved internal action assignable, ownable, trackable
# and closeable across internal departments. Every transition is INTERNAL/
# DB-only: it NEVER sends WhatsApp/Meta Cloud, places a Vapi call, calls
# Razorpay/PayU/Delhivery, creates a payment link / AWB, mutates an
# `Order` / `Payment` / `Shipment` / `Customer` / `Lead`, or changes the
# Phase 15 safety shell. Completing a workboard item is internal-only. Every
# touched action keeps `provider_action_attempted=False` +
# `provider_action_taken=False` + `external_action_allowed=False` +
# `external_action_taken=False`.

_SLA_DUE_SOON_SECONDS = 24 * 3600


def compute_sla_status(action, *, now=None) -> str:
    """Service-level SLA indicator from ``due_at`` (no DB column).

    Returns one of ``no_due_date`` / ``on_track`` / ``due_soon`` / ``overdue``.
    Closed work items (completed/rejected/cancelled) are never ``overdue``.
    """
    from django.utils import timezone

    from .models import AiApprovedAction

    if action.due_at is None:
        return "no_due_date"
    terminal = {
        AiApprovedAction.WorkStatus.COMPLETED_INTERNAL,
        AiApprovedAction.WorkStatus.REJECTED,
        AiApprovedAction.WorkStatus.CANCELLED,
    }
    if action.work_status in terminal:
        return "on_track"
    now = now or timezone.now()
    delta = (action.due_at - now).total_seconds()
    if delta < 0:
        return "overdue"
    if delta <= _SLA_DUE_SOON_SECONDS:
        return "due_soon"
    return "on_track"


def _valid_department(value: str) -> str:
    from .models import AiApprovedAction

    allowed = {c for c, _ in AiApprovedAction.Department.choices if c}
    return value if value in allowed else ""


def _record_work_event(action, event_type: str, *, actor=None, note: str = "", metadata=None) -> None:
    from .models import AiActionWorkEvent

    AiActionWorkEvent.objects.create(
        action=action, event_type=event_type, actor=_action_actor(actor),
        note=str(note or "")[:4000], metadata=dict(metadata or {}),
    )


def _reassert_locked_contract(action) -> None:
    """A workboard transition NEVER flips any provider/external flag true."""
    action.provider_action_attempted = False
    action.provider_action_taken = False
    action.external_action_allowed = False
    action.external_action_taken = False


def _assert_workable(action, *, allowed_from: set[str]) -> None:
    """Guard a workboard transition.

    Refuses if the Phase 16J queue status is terminal (rejected/cancelled) or
    the current ``work_status`` is not an allowed source state. This prevents
    accidentally re-opening a closed item.
    """
    from .models import AiApprovedAction

    if action.status in {
        AiApprovedAction.Status.REJECTED,
        AiApprovedAction.Status.CANCELLED,
    }:
        raise AiActionError(f"action_queue_terminal:{action.status}")
    if action.work_status not in allowed_from:
        raise AiActionError(f"invalid_work_status:{action.work_status}")


def _save_workboard(action, fields: list[str]) -> None:
    from django.utils import timezone

    _reassert_locked_contract(action)
    action.last_activity_at = timezone.now()
    base = [
        "provider_action_attempted", "provider_action_taken",
        "external_action_allowed", "external_action_taken", "last_activity_at",
    ]
    action.save(update_fields=list(dict.fromkeys(fields + base)))


_WS = None  # lazy alias for AiApprovedAction.WorkStatus


def _ws():
    global _WS
    if _WS is None:
        from .models import AiApprovedAction

        _WS = AiApprovedAction.WorkStatus
    return _WS


def assign_action(action, *, department: str = "", assignee=None, actor=None, due_at=None, note: str = ""):
    """Assign an action to a department (+ optional assignee). Internal-only."""
    ws = _ws()
    _assert_workable(action, allowed_from={ws.UNASSIGNED, ws.ASSIGNED, ws.IN_PROGRESS, ws.BLOCKED})
    dept = _valid_department(str(department or ""))
    if not dept and not action.department:
        raise AiActionError("department_required")
    if dept:
        action.department = dept
        action.assigned_team = dept  # keep the legacy free-text label in sync
    if assignee is not None:
        action.assignee_user = _action_actor(assignee)
    if due_at is not None:
        action.due_at = due_at
    action.work_status = ws.ASSIGNED
    _save_workboard(action, ["department", "assigned_team", "assignee_user", "due_at", "work_status"])
    _record_work_event(action, "assigned", actor=actor, note=note,
                        metadata={"department": action.department})
    return action


def claim_action(action, *, user=None, note: str = ""):
    """Claim an unassigned action for the current user. Internal-only."""
    ws = _ws()
    _assert_workable(action, allowed_from={ws.UNASSIGNED, ws.ASSIGNED})
    action.assignee_user = _action_actor(user)
    action.work_status = ws.ASSIGNED
    _save_workboard(action, ["assignee_user", "work_status"])
    _record_work_event(action, "claimed", actor=user, note=note)
    return action


def start_action(action, *, actor=None, note: str = ""):
    """Move an assigned action to in_progress. Internal-only."""
    ws = _ws()
    _assert_workable(action, allowed_from={ws.ASSIGNED})
    action.work_status = ws.IN_PROGRESS
    _save_workboard(action, ["work_status"])
    _record_work_event(action, "started", actor=actor, note=note)
    return action


def block_action(action, *, reason: str = "", actor=None):
    """Block an assigned/in-progress action (requires a reason). Internal-only."""
    ws = _ws()
    _assert_workable(action, allowed_from={ws.ASSIGNED, ws.IN_PROGRESS})
    reason = str(reason or "").strip()
    if not reason:
        raise AiActionError("blocker_reason_required")
    action.work_status = ws.BLOCKED
    action.blocker_reason = reason[:300]
    _save_workboard(action, ["work_status", "blocker_reason"])
    _record_work_event(action, "blocked", actor=actor, note=reason)
    return action


def unblock_action(action, *, actor=None, note: str = ""):
    """Unblock a blocked action back to in_progress. Internal-only."""
    ws = _ws()
    _assert_workable(action, allowed_from={ws.BLOCKED})
    action.work_status = ws.IN_PROGRESS
    action.blocker_reason = ""
    _save_workboard(action, ["work_status", "blocker_reason"])
    _record_work_event(action, "unblocked", actor=actor, note=note)
    return action


def complete_internal_action(action, *, actor=None, note: str = ""):
    """Mark a workboard item completed (internal-only — NEVER calls a provider)."""
    from django.utils import timezone

    ws = _ws()
    _assert_workable(action, allowed_from={ws.ASSIGNED, ws.IN_PROGRESS, ws.BLOCKED})
    action.work_status = ws.COMPLETED_INTERNAL
    action.completed_by = _action_actor(actor)
    action.completed_at = timezone.now()
    action.blocker_reason = ""
    _save_workboard(action, ["work_status", "completed_by", "completed_at", "blocker_reason"])
    _record_work_event(action, "completed_internal", actor=actor, note=note,
                        metadata={"providerActionsBlocked": True})
    return action


def reassign_action(action, *, department: str = "", assignee=None, actor=None, note: str = ""):
    """Reassign an active action to another department/owner. Internal-only."""
    ws = _ws()
    _assert_workable(action, allowed_from={ws.UNASSIGNED, ws.ASSIGNED, ws.IN_PROGRESS, ws.BLOCKED})
    dept = _valid_department(str(department or ""))
    if dept:
        action.department = dept
        action.assigned_team = dept
    action.assignee_user = _action_actor(assignee)
    action.work_status = ws.ASSIGNED
    _save_workboard(action, ["department", "assigned_team", "assignee_user", "work_status"])
    _record_work_event(action, "reassigned", actor=actor, note=note,
                        metadata={"department": action.department})
    return action


def add_action_note(action, *, note: str = "", actor=None, director_review: bool = False):
    """Add an internal workboard note (and optionally flag for Director review)."""
    note = str(note or "").strip()
    if not note and not director_review:
        raise AiActionError("note_required")
    event_type = "director_review_requested" if director_review else "note_added"
    _save_workboard(action, [])
    _record_work_event(action, event_type, actor=actor, note=note)
    return action


def list_department_workboard(
    *, department: str = "", work_status: str = "", priority: str = "",
    sla_status: str = "", assignee: str = "", search: str = "", limit: int = 200,
):
    """Read-only workboard query over AI-approved internal actions."""
    from .models import AiApprovedAction

    qs = AiApprovedAction.objects.all().select_related(
        "assignee_user", "completed_by", "approved_by"
    ).order_by("-created_at")
    if department:
        qs = qs.filter(department=department)
    if work_status:
        qs = qs.filter(work_status=work_status)
    if priority:
        qs = qs.filter(priority=priority)
    if assignee:
        qs = qs.filter(assignee_user__username=assignee)
    if search:
        qs = qs.filter(title__icontains=search)
    rows = list(qs[: max(1, min(500, int(limit or 200)))])
    if sla_status:
        rows = [a for a in rows if compute_sla_status(a) == sla_status]
    return rows


def get_department_summary() -> dict[str, Any]:
    """Read-only workboard counts by work_status / department / SLA."""
    from django.db.models import Count

    from .models import AiApprovedAction

    ws = _ws()
    status_counts = {c: 0 for c, _ in AiApprovedAction.WorkStatus.choices}
    for row in AiApprovedAction.objects.values("work_status").annotate(n=Count("id")):
        status_counts[row["work_status"]] = row["n"]

    dept_counts: dict[str, int] = {}
    for row in AiApprovedAction.objects.values("department").annotate(n=Count("id")):
        dept_counts[row["department"] or "unassigned"] = row["n"]

    # Overdue is SLA-derived → compute in Python over non-terminal rows with a due date.
    terminal = {ws.COMPLETED_INTERNAL, ws.REJECTED, ws.CANCELLED}
    overdue = 0
    for a in AiApprovedAction.objects.exclude(due_at=None).exclude(work_status__in=terminal):
        if compute_sla_status(a) == "overdue":
            overdue += 1

    director_attention = len(get_director_attention_queue())
    total = sum(status_counts.values())
    return {
        "total": total,
        "unassigned": status_counts.get(ws.UNASSIGNED, 0),
        "assigned": status_counts.get(ws.ASSIGNED, 0),
        "inProgress": status_counts.get(ws.IN_PROGRESS, 0),
        "blocked": status_counts.get(ws.BLOCKED, 0),
        "completedInternal": status_counts.get(ws.COMPLETED_INTERNAL, 0),
        "overdue": overdue,
        "directorAttention": director_attention,
        "byWorkStatus": status_counts,
        "byDepartment": dept_counts,
        "providerActionsLocked": True,
        "liveAutonomousExecutionLocked": True,
        "noProviderActionTaken": True,
        "phase": "16K",
    }


# ---------------------------------------------------------------------------
# Phase 16L — Scoped Team Member Work Permissions + My Work Queue
# ---------------------------------------------------------------------------
#
# Decide who may CLAIM / WORK an already-created internal action, and surface a
# per-user "My Work" view. Director/Admin/Superuser keep full control; a
# non-admin may only work an action they are assigned to, or claim an
# unassigned action in a department they hold active membership for. Nothing
# here calls a provider, changes the safety shell, or takes an external action.


class WorkPermissionError(Exception):
    """Raised when a user is not permitted to perform a scoped workboard op."""


def _is_admin_like(user) -> bool:
    # Reuse the single source of truth from the permissions module.
    from .permissions import _is_admin_like as _admin

    return _admin(user)


def _active_membership(user, department: str):
    """The user's active membership for a department, or None."""
    from .models import AiWorkboardDepartmentMember

    uid = getattr(user, "id", None)
    if not uid or not department:
        return None
    return (
        AiWorkboardDepartmentMember.objects.filter(
            user_id=uid, department=department, is_active=True
        )
        .order_by("-created_at")
        .first()
    )


def _is_terminal_action(action) -> bool:
    """A queue-terminal (rejected/cancelled) or closed work item cannot be worked."""
    from .models import AiApprovedAction

    ws = _ws()
    if action.status in {AiApprovedAction.Status.REJECTED, AiApprovedAction.Status.CANCELLED}:
        return True
    return action.work_status in {ws.COMPLETED_INTERNAL, ws.REJECTED, ws.CANCELLED}


def can_user_claim_action(user, action) -> tuple[bool, str]:
    """Whether ``user`` may claim ``action`` (admin, or active dept member)."""
    ws = _ws()
    if _is_admin_like(user):
        return (True, "admin")
    if _is_terminal_action(action):
        return (False, "action_terminal_or_closed")
    if not action.department:
        return (False, "no_department")
    if action.work_status not in {ws.UNASSIGNED, ws.ASSIGNED}:
        return (False, "not_claimable_state")
    # Only unclaimed (no current owner) work can be claimed by a member.
    if action.assignee_user_id is not None:
        return (False, "already_assigned")
    membership = _active_membership(user, action.department)
    if membership is None:
        return (False, "no_active_membership")
    if not membership.can_claim:
        return (False, "membership_cannot_claim")
    return (True, "department_member")


def can_user_work_action(user, action, operation: str) -> tuple[bool, str]:
    """Whether ``user`` may perform ``operation`` on ``action``.

    operation ∈ {claim, start, block, unblock, complete, note, assign, reassign}.
    """
    if _is_admin_like(user):
        return (True, "admin")
    if operation in {"assign", "reassign"}:
        return (False, "admin_required")
    if operation == "claim":
        return can_user_claim_action(user, action)
    if _is_terminal_action(action):
        return (False, "action_terminal_or_closed")
    # start / block / unblock / complete / note — must be the directly assigned user.
    if action.assignee_user_id != getattr(user, "id", None):
        return (False, "not_assignee")
    membership = _active_membership(user, action.department)
    if operation == "complete":
        if membership is not None and not membership.can_complete:
            return (False, "membership_cannot_complete")
        return (True, "assignee")
    # start / block / unblock / note
    if membership is not None and not membership.can_work:
        return (False, "membership_cannot_work")
    return (True, "assignee")


def action_permission_booleans(user, action) -> dict[str, bool]:
    """Safe per-action permission booleans for the frontend (no PII)."""
    from .models import AiApprovedAction

    ws = _ws()
    admin = _is_admin_like(user)
    terminal = _is_terminal_action(action)
    queue_terminal = action.status in {
        AiApprovedAction.Status.REJECTED, AiApprovedAction.Status.CANCELLED,
    }
    return {
        "canClaim": can_user_claim_action(user, action)[0],
        "canStart": action.work_status == ws.ASSIGNED
        and can_user_work_action(user, action, "start")[0],
        "canBlock": action.work_status in {ws.ASSIGNED, ws.IN_PROGRESS}
        and can_user_work_action(user, action, "block")[0],
        "canUnblock": action.work_status == ws.BLOCKED
        and can_user_work_action(user, action, "unblock")[0],
        "canCompleteInternal": action.work_status
        in {ws.ASSIGNED, ws.IN_PROGRESS, ws.BLOCKED}
        and can_user_work_action(user, action, "complete")[0],
        "canAddNote": (not terminal) and can_user_work_action(user, action, "note")[0],
        "canAssign": admin and not queue_terminal,
        "canReassign": admin and not terminal,
    }


def get_user_work_permissions(user) -> dict[str, Any]:
    """Global, safe permission summary for the current user."""
    from .models import AiWorkboardDepartmentMember

    admin = _is_admin_like(user)
    departments = []
    if not admin:
        for m in AiWorkboardDepartmentMember.objects.filter(
            user_id=getattr(user, "id", None), is_active=True
        ).order_by("department"):
            departments.append({
                "department": m.department,
                "canClaim": m.can_claim,
                "canWork": m.can_work,
                "canComplete": m.can_complete,
            })
    return {
        "isAdmin": admin,
        "canViewWorkboard": True,
        "canAssign": admin,
        "canReassign": admin,
        "canManageMembership": admin,
        "departments": departments,
        "providerActionsLocked": True,
        "liveAutonomousExecutionLocked": True,
        "phase": "16L",
    }


# ----- Department membership management (Director/Admin only at the view) -----


def create_department_membership(
    *, user, department: str, created_by=None,
    can_claim: bool = True, can_work: bool = True, can_complete: bool = True,
):
    """Create (or reactivate) a scoped department membership for a user."""
    from .models import AiApprovedAction, AiWorkboardDepartmentMember

    valid = {c for c, _ in AiApprovedAction.Department.choices if c}
    if department not in valid:
        raise WorkPermissionError(f"invalid_department:{department}")
    if user is None:
        raise WorkPermissionError("user_required")

    existing = AiWorkboardDepartmentMember.objects.filter(
        user=user, department=department, is_active=True
    ).first()
    if existing is not None:
        existing.can_claim = bool(can_claim)
        existing.can_work = bool(can_work)
        existing.can_complete = bool(can_complete)
        existing.save(update_fields=["can_claim", "can_work", "can_complete", "updated_at"])
        return existing, False
    member = AiWorkboardDepartmentMember.objects.create(
        user=user, department=department,
        can_claim=bool(can_claim), can_work=bool(can_work), can_complete=bool(can_complete),
        created_by=_action_actor(created_by), is_active=True,
    )
    return member, True


def deactivate_department_membership(member):
    member.is_active = False
    member.save(update_fields=["is_active", "updated_at"])
    return member


def activate_department_membership(member):
    member.is_active = True
    member.save(update_fields=["is_active", "updated_at"])
    return member


# ----- My Work queue -----


def list_my_work(user, *, work_status: str = "", limit: int = 200):
    """Internal actions assigned to ``user`` (the user's own work)."""
    from .models import AiApprovedAction

    uid = getattr(user, "id", None)
    if not uid:
        return []
    qs = AiApprovedAction.objects.filter(assignee_user_id=uid).select_related(
        "assignee_user", "completed_by"
    ).order_by("-created_at")
    if work_status:
        qs = qs.filter(work_status=work_status)
    return list(qs[: max(1, min(500, int(limit or 200)))])


def get_my_work_summary(user) -> dict[str, Any]:
    """Counts over the current user's assigned work (+ SLA breakdown)."""
    from .models import AiApprovedAction

    ws = _ws()
    uid = getattr(user, "id", None)
    counts = {c: 0 for c, _ in AiApprovedAction.WorkStatus.choices}
    due_soon = 0
    overdue = 0
    if uid:
        rows = AiApprovedAction.objects.filter(assignee_user_id=uid)
        for a in rows:
            counts[a.work_status] = counts.get(a.work_status, 0) + 1
            sla = compute_sla_status(a)
            if sla == "due_soon":
                due_soon += 1
            elif sla == "overdue":
                overdue += 1
    total = sum(counts.values())
    return {
        "total": total,
        "assigned": counts.get(ws.ASSIGNED, 0),
        "inProgress": counts.get(ws.IN_PROGRESS, 0),
        "blocked": counts.get(ws.BLOCKED, 0),
        "completedInternal": counts.get(ws.COMPLETED_INTERNAL, 0),
        "dueSoon": due_soon,
        "overdue": overdue,
        "byWorkStatus": counts,
        "providerActionsLocked": True,
        "noProviderActionTaken": True,
        "phase": "16L",
    }


def get_director_attention_queue(*, limit: int = 100) -> list:
    """Read-only list of actions that need Director attention.

    Includes: blocked actions, overdue actions, and unassigned high/urgent
    priority actions. Each entry carries a ``reason`` for the surfacing. Closed
    (completed/rejected/cancelled) work items are excluded. Returns a list of
    ``(action, reason)`` tuples (the view serializes them).
    """
    from .models import AiApprovedAction

    ws = _ws()
    terminal = {ws.COMPLETED_INTERNAL, ws.REJECTED, ws.CANCELLED}
    out: list[tuple] = []
    seen: set[int] = set()

    def _add(action, reason: str) -> None:
        if action.pk in seen:
            return
        seen.add(action.pk)
        out.append((action, reason))

    qs = AiApprovedAction.objects.exclude(
        status__in=[AiApprovedAction.Status.REJECTED, AiApprovedAction.Status.CANCELLED]
    ).exclude(work_status__in=terminal).select_related("assignee_user")

    for a in qs:
        if a.work_status == ws.BLOCKED:
            _add(a, "blocked")
    for a in qs:
        if a.due_at is not None and compute_sla_status(a) == "overdue":
            _add(a, "overdue")
    for a in qs:
        if a.work_status == ws.UNASSIGNED and a.priority in {
            AiApprovedAction.Priority.HIGH, AiApprovedAction.Priority.URGENT
        }:
            _add(a, "unassigned_high_priority")

    return out[: max(1, min(200, int(limit or 100)))]


# ---------------------------------------------------------------------------
# Phase 16M — Workboard Analytics + SLA Throughput Dashboard
# ---------------------------------------------------------------------------
#
# A READ-ONLY analytics layer over the existing Phase 16J/16K/16L workboard
# data. It NEVER writes any row, NEVER imports/queues a provider, NEVER sends
# WhatsApp/Meta Cloud, places a Vapi call, calls Razorpay/PayU/Delhivery, creates
# a payment link / AWB, mutates an `Order` / `Payment` / `Shipment` / `Customer`
# / `Lead`, enqueues a business Celery job, or changes the Phase 15 safety shell
# (`RuntimeKillSwitch` / `SandboxState`). Every value is derived from existing
# fields on `AiApprovedAction` / `AiActionWorkEvent` / `AiApprovedActionEvent`.

_ANALYTICS_BLOCKER_REASON_MAX = 80
_ANALYTICS_TOP_BLOCKERS = 8


def _hours_between(earlier, later) -> float | None:
    """Whole-ish hours between two aware datetimes (1 dp), or None."""
    if earlier is None or later is None:
        return None
    delta = (later - earlier).total_seconds()
    if delta < 0:
        return 0.0
    return round(delta / 3600.0, 1)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def get_workboard_analytics(*, window_days: int = 14) -> dict[str, Any]:
    """Read-only workboard analytics + SLA throughput (no mutation, no provider).

    Derives summary / per-department / per-member / SLA / blocker / throughput
    analytics from the existing AI-approved internal action workboard. Safe to
    call by any authenticated user; it only reads rows.
    """
    from django.utils import timezone

    from .models import AiActionWorkEvent, AiApprovedAction

    window_days = max(1, min(90, int(window_days or 14)))
    ws = _ws()
    now = timezone.now()
    window_start = now - timezone.timedelta(days=window_days)

    terminal_ws = {ws.COMPLETED_INTERNAL, ws.REJECTED, ws.CANCELLED}
    queue_terminal = {
        AiApprovedAction.Status.REJECTED, AiApprovedAction.Status.CANCELLED,
    }
    dept_label = {c: lbl for c, lbl in AiApprovedAction.Department.choices}

    actions = list(
        AiApprovedAction.objects.select_related("assignee_user").all()
    )

    # ----- per-action SLA cache (one compute per row) -----
    sla_of = {a.pk: compute_sla_status(a, now=now) for a in actions}

    def _dept_key(a) -> str:
        return a.department or "unassigned"

    def _is_open(a) -> bool:
        return a.work_status not in terminal_ws and a.status not in queue_terminal

    # ----- summary -----
    status_counts = {c: 0 for c, _ in AiApprovedAction.WorkStatus.choices}
    sla_counts = {"overdue": 0, "due_soon": 0, "on_track": 0, "no_due_date": 0}
    completion_hours_all: list[float] = []
    closed = 0
    for a in actions:
        status_counts[a.work_status] = status_counts.get(a.work_status, 0) + 1
        sla_counts[sla_of[a.pk]] = sla_counts.get(sla_of[a.pk], 0) + 1
        if a.work_status in terminal_ws or a.status in queue_terminal:
            closed += 1
        if a.work_status == ws.COMPLETED_INTERNAL and a.completed_at:
            h = _hours_between(a.created_at, a.completed_at)
            if h is not None:
                completion_hours_all.append(h)

    open_actions = sum(1 for a in actions if _is_open(a))
    director_attention = len(get_director_attention_queue())

    summary = {
        "total": len(actions),
        "openActions": open_actions,
        "unassigned": status_counts.get(ws.UNASSIGNED, 0),
        "assigned": status_counts.get(ws.ASSIGNED, 0),
        "inProgress": status_counts.get(ws.IN_PROGRESS, 0),
        "blocked": status_counts.get(ws.BLOCKED, 0),
        "completedInternal": status_counts.get(ws.COMPLETED_INTERNAL, 0),
        "overdue": sla_counts["overdue"],
        "dueSoon": sla_counts["due_soon"],
        "noDueDate": sla_counts["no_due_date"],
        "directorAttention": director_attention,
        "closed": closed,
        "avgCompletionHours": _avg(completion_hours_all),
    }

    # ----- per-department analytics -----
    dept_acc: dict[str, dict[str, Any]] = {}

    def _dept(key: str) -> dict[str, Any]:
        if key not in dept_acc:
            dept_acc[key] = {
                "department": key,
                "label": dept_label.get("" if key == "unassigned" else key, key),
                "total": 0, "open": 0, "assigned": 0, "inProgress": 0,
                "blocked": 0, "completedInternal": 0, "overdue": 0,
                "dueSoon": 0, "noDueDate": 0,
                "_completionHours": [], "_oldestOpenAge": None,
            }
        return dept_acc[key]

    for a in actions:
        d = _dept(_dept_key(a))
        d["total"] += 1
        if a.work_status == ws.ASSIGNED:
            d["assigned"] += 1
        elif a.work_status == ws.IN_PROGRESS:
            d["inProgress"] += 1
        elif a.work_status == ws.BLOCKED:
            d["blocked"] += 1
        elif a.work_status == ws.COMPLETED_INTERNAL:
            d["completedInternal"] += 1
        sla = sla_of[a.pk]
        if sla == "overdue":
            d["overdue"] += 1
        elif sla == "due_soon":
            d["dueSoon"] += 1
        elif sla == "no_due_date":
            d["noDueDate"] += 1
        if _is_open(a):
            d["open"] += 1
            age = _hours_between(a.created_at, now)
            if age is not None and (d["_oldestOpenAge"] is None or age > d["_oldestOpenAge"]):
                d["_oldestOpenAge"] = age
        if a.work_status == ws.COMPLETED_INTERNAL and a.completed_at:
            h = _hours_between(a.created_at, a.completed_at)
            if h is not None:
                d["_completionHours"].append(h)

    departments = []
    for d in dept_acc.values():
        comp = d["completedInternal"]
        rate = round(comp / d["total"], 2) if d["total"] else 0.0
        departments.append({
            "department": d["department"], "label": d["label"],
            "total": d["total"], "open": d["open"], "assigned": d["assigned"],
            "inProgress": d["inProgress"], "blocked": d["blocked"],
            "completedInternal": comp, "overdue": d["overdue"],
            "dueSoon": d["dueSoon"], "noDueDate": d["noDueDate"],
            "completionRate": rate,
            "avgCompletionHours": _avg(d["_completionHours"]),
            "oldestOpenAgeHours": d["_oldestOpenAge"],
        })
    departments.sort(key=lambda x: (-x["open"], -x["total"], x["department"]))

    # ----- per-member workload analytics -----
    member_acc: dict[int, dict[str, Any]] = {}
    for a in actions:
        uid = a.assignee_user_id
        if not uid:
            continue
        m = member_acc.get(uid)
        if m is None:
            m = member_acc[uid] = {
                "userId": uid,
                "username": a.assignee_user.username if a.assignee_user_id else None,
                "_departments": set(), "assignedOpen": 0, "inProgress": 0,
                "blocked": 0, "overdue": 0, "completedInternalRecent": 0,
                "_completionHours": [],
            }
        if a.department:
            m["_departments"].add(a.department)
        if a.work_status == ws.ASSIGNED and _is_open(a):
            m["assignedOpen"] += 1
        elif a.work_status == ws.IN_PROGRESS:
            m["inProgress"] += 1
        elif a.work_status == ws.BLOCKED:
            m["blocked"] += 1
        if sla_of[a.pk] == "overdue":
            m["overdue"] += 1
        if a.work_status == ws.COMPLETED_INTERNAL and a.completed_at:
            if a.completed_at >= window_start:
                m["completedInternalRecent"] += 1
            h = _hours_between(a.created_at, a.completed_at)
            if h is not None:
                m["_completionHours"].append(h)

    members = []
    for m in member_acc.values():
        members.append({
            "userId": m["userId"], "username": m["username"],
            "departments": sorted(m["_departments"]),
            "assignedOpen": m["assignedOpen"], "inProgress": m["inProgress"],
            "blocked": m["blocked"], "overdue": m["overdue"],
            "completedInternalRecent": m["completedInternalRecent"],
            "avgCompletionHours": _avg(m["_completionHours"]),
        })
    members.sort(key=lambda x: (-(x["assignedOpen"] + x["inProgress"] + x["blocked"]),
                                x["username"] or ""))

    # ----- SLA analytics -----
    overdue_by_dept: dict[str, int] = {}
    due_soon_by_dept: dict[str, int] = {}
    for a in actions:
        sla = sla_of[a.pk]
        if sla == "overdue":
            overdue_by_dept[_dept_key(a)] = overdue_by_dept.get(_dept_key(a), 0) + 1
        elif sla == "due_soon":
            due_soon_by_dept[_dept_key(a)] = due_soon_by_dept.get(_dept_key(a), 0) + 1
    highest_risk = max(overdue_by_dept, key=overdue_by_dept.get) if overdue_by_dept else (
        max(due_soon_by_dept, key=due_soon_by_dept.get) if due_soon_by_dept else ""
    )
    sla = {
        "overdue": sla_counts["overdue"], "dueSoon": sla_counts["due_soon"],
        "onTrack": sla_counts["on_track"], "noDueDate": sla_counts["no_due_date"],
        "overdueByDepartment": overdue_by_dept,
        "dueSoonByDepartment": due_soon_by_dept,
        "highestRiskDepartment": highest_risk,
    }

    # ----- blocker analytics -----
    reason_counts: dict[str, int] = {}
    blocked_by_dept: dict[str, int] = {}
    oldest_blocked_age = None
    blocked_count = 0
    for a in actions:
        if a.work_status != ws.BLOCKED:
            continue
        blocked_count += 1
        blocked_by_dept[_dept_key(a)] = blocked_by_dept.get(_dept_key(a), 0) + 1
        reason = (a.blocker_reason or "(no reason)").strip()[:_ANALYTICS_BLOCKER_REASON_MAX]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        age = _hours_between(a.last_activity_at or a.created_at, now)
        if age is not None and (oldest_blocked_age is None or age > oldest_blocked_age):
            oldest_blocked_age = age
    top_reasons = [
        {"reason": r, "count": c}
        for r, c in sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:_ANALYTICS_TOP_BLOCKERS]
    blockers = {
        "blockedCount": blocked_count, "topBlockerReasons": top_reasons,
        "blockedByDepartment": blocked_by_dept,
        "oldestBlockedAgeHours": oldest_blocked_age,
    }

    # ----- throughput trend (daily buckets, last window_days) -----
    day_keys = [
        (timezone.localtime(now) - timezone.timedelta(days=i)).date().isoformat()
        for i in range(window_days - 1, -1, -1)
    ]
    day_index = {k: i for i, k in enumerate(day_keys)}
    buckets = [
        {"date": k, "created": 0, "assigned": 0, "started": 0,
         "blocked": 0, "completedInternal": 0}
        for k in day_keys
    ]

    def _bucket_for(dt):
        if dt is None or dt < window_start:
            return None
        key = timezone.localtime(dt).date().isoformat()
        idx = day_index.get(key)
        return buckets[idx] if idx is not None else None

    total_events = 0
    for a in actions:
        b = _bucket_for(a.created_at)
        if b is not None:
            b["created"] += 1
            total_events += 1

    _EVENT_FIELD = {
        AiActionWorkEvent.EventType.ASSIGNED: "assigned",
        AiActionWorkEvent.EventType.STARTED: "started",
        AiActionWorkEvent.EventType.BLOCKED: "blocked",
        AiActionWorkEvent.EventType.COMPLETED_INTERNAL: "completedInternal",
    }
    for ev in AiActionWorkEvent.objects.filter(
        created_at__gte=window_start, event_type__in=list(_EVENT_FIELD)
    ).only("event_type", "created_at"):
        b = _bucket_for(ev.created_at)
        if b is not None:
            b[_EVENT_FIELD[ev.event_type]] += 1
            total_events += 1

    trend = {
        "windowDays": window_days,
        "hasData": total_events > 0,
        "reason": "" if total_events > 0 else "insufficient_event_data",
        "days": buckets,
    }

    return {
        "summary": summary,
        "departments": departments,
        "members": members,
        "sla": sla,
        "blockers": blockers,
        "trend": trend,
        "generatedAt": now,
        "windowDays": window_days,
        "readonly": True,
        "internalOnly": True,
        "providerActionAttempted": False,
        "providerActionTaken": False,
        "externalActionAllowed": False,
        "externalActionTaken": False,
        "phase": "16M",
    }
