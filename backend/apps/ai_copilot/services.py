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
