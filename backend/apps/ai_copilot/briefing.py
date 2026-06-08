"""Phase 16N — Director AI Daily Briefing Real Data Wiring + Safe Recommendation Pack.

A READ-ONLY, INTERNAL-ONLY decision layer on top of the existing Phase
16I/16J/16K/16L/16M workboard data. It composes the Phase 16M analytics
(`services.get_workboard_analytics`), the Phase 16K director-attention queue
(`services.get_director_attention_queue`), and the pending AI-suggestion /
internal-action counts into a deterministic, Director-facing "AI briefing" pack —
executive summary, attention items, department/member focus, and SAFE internal-
only recommendations.

**Nothing here calls a live AI/LLM provider, sends WhatsApp/Meta Cloud, places a
Vapi call, calls Razorpay/PayU/Delhivery, creates a payment link / AWB, auto-
confirms/cancels an order, auto-applies a discount, enqueues a business Celery
job, mutates any business / workboard row, or touches `RuntimeKillSwitch` /
`SandboxState`.** Every response carries the locked guarantees `readonly` /
`internalOnly` / `providerCallMade=false` / `externalActionTaken=false` /
`liveAutonomousLocked`. Text is generated deterministically ("mock") — no live
AI provider, no medical claim, no customer-facing instruction, and no PII beyond
the existing username display convention.
"""
from __future__ import annotations

from typing import Any

from . import services

# The only permitted "next step" verbs a recommendation may carry. NONE of these
# authorise a live provider or customer-facing action — they are internal-only.
PERMITTED_ACTIONS = (
    "internal_review", "assign_internal", "create_internal_action",
    "review_blocker", "no_external_action",
)

# Static contract — every live/customer-facing channel stays LOCKED this phase.
BLOCKED_LIVE_ACTIONS = [
    {"channel": "whatsapp", "label": "WhatsApp / Meta Cloud", "locked": True,
     "reason": "Customer messaging is not approved; no send path is invoked."},
    {"channel": "payment", "label": "Razorpay / PayU payment", "locked": True,
     "reason": "No live payment, payment link, capture or refund is performed."},
    {"channel": "courier", "label": "Delhivery courier / AWB", "locked": True,
     "reason": "No live shipment or AWB is booked."},
    {"channel": "vapi", "label": "Vapi / voice call", "locked": True,
     "reason": "No outbound voice call is placed."},
    {"channel": "live_ai", "label": "Live AI / LLM provider", "locked": True,
     "reason": "Briefing text is deterministic; no live AI/LLM provider is called."},
]


def _attention_item(action, reason: str, *, now=None) -> dict[str, Any]:
    """Sanitized attention-item dict (internal task title only — no customer PII)."""
    return {
        "id": action.pk,
        "title": action.title,
        "department": action.department or "unassigned",
        "workStatus": action.work_status,
        "priority": action.priority,
        "slaStatus": services.compute_sla_status(action, now=now),
        "assigneeUser": action.assignee_user.username if action.assignee_user_id else None,
        "reason": reason,
    }


def _safety_snapshot() -> dict[str, Any]:
    status = services.get_ai_copilot_status()
    return {
        "aiPaused": status["aiPaused"],
        "sandboxOn": status["sandboxOn"],
        "syncLive": status["syncLive"],
        "aiMode": status["aiMode"],
        "liveAutonomousExecutionLocked": status["liveAutonomousExecutionLocked"],
        "providerLiveActionsLocked": status["providerLiveActionsLocked"],
        "humanApprovalRequired": status["humanApprovalRequired"],
        "providerCallMade": False,
        "externalActionTaken": False,
        "phase15ShellFrozen": True,
        "phase15ShellFrozenCommit": "eefd8b3",
    }


def _executive_summary(*, analytics, pending_suggestions, pending_actions,
                       unassigned_high, attention_total) -> list[str]:
    """Deterministic, internal-only executive-summary bullets (3-8)."""
    s = analytics["summary"]
    sla = analytics["sla"]
    bullets: list[str] = []
    bullets.append(
        f"{s['openActions']} open internal action(s): {s['overdue']} overdue, "
        f"{s['blocked']} blocked, {s['dueSoon']} due soon."
    )
    if pending_suggestions or pending_actions:
        bullets.append(
            f"{pending_suggestions} AI suggestion(s) await human review; "
            f"{pending_actions} internal action(s) pending."
        )
    if unassigned_high:
        bullets.append(
            f"{unassigned_high} high/urgent internal action(s) are unassigned - "
            "assign to a department to start work."
        )
    depts = analytics["departments"]
    busiest = max(depts, key=lambda d: d["open"], default=None) if depts else None
    if busiest and busiest["open"] > 0:
        bullets.append(
            f"Highest internal load: {busiest['label'] or busiest['department']} "
            f"({busiest['open']} open, {busiest['blocked']} blocked, {busiest['overdue']} overdue)."
        )
    if sla["highestRiskDepartment"]:
        bullets.append(
            f"Highest SLA risk department: {sla['highestRiskDepartment']} "
            f"({sla['overdue']} overdue, {sla['dueSoon']} due soon overall)."
        )
    if attention_total == 0:
        bullets.append("No items currently need Director attention.")
    bullets.append(
        "All live/customer-facing automation remains LOCKED (AI Paused, Sandbox OFF, "
        "Live Autonomous Locked); this briefing is internal-only and read-only."
    )
    return bullets[:8]


def _recommendations(*, analytics, pending_suggestions, pending_actions,
                     unassigned_high) -> list[dict[str, Any]]:
    """Deterministic SAFE internal-only recommendations (never external)."""
    s = analytics["summary"]
    sla = analytics["sla"]
    blockers = analytics["blockers"]
    recs: list[dict[str, Any]] = []

    if s["blocked"] > 0:
        top = blockers["topBlockerReasons"][0]["reason"] if blockers["topBlockerReasons"] else ""
        recs.append({
            "recommendationType": "review_blocked_actions",
            "priority": "high",
            "reason": (
                f"{s['blocked']} internal action(s) are blocked and stopping work"
                + (f" (top reason: {top})." if top else ".")
            ),
            "linkedMetric": "blockers.blockedCount",
            "permittedAction": "review_blocker",
        })
    if s["overdue"] > 0:
        worst = sla["highestRiskDepartment"] or "the affected departments"
        recs.append({
            "recommendationType": "review_overdue_actions",
            "priority": "high" if s["overdue"] >= 3 else "medium",
            "reason": f"{s['overdue']} internal action(s) are overdue (highest risk: {worst}).",
            "linkedMetric": "summary.overdue",
            "permittedAction": "internal_review",
        })
    if unassigned_high > 0:
        recs.append({
            "recommendationType": "assign_unassigned_high_priority",
            "priority": "high",
            "reason": f"{unassigned_high} high/urgent internal action(s) are unassigned.",
            "linkedMetric": "attention.unassignedHighPriority",
            "permittedAction": "assign_internal",
        })
    if pending_suggestions > 0:
        recs.append({
            "recommendationType": "review_pending_ai_suggestions",
            "priority": "medium",
            "reason": (
                f"{pending_suggestions} AI suggestion(s) await human review before any "
                "internal action is created."
            ),
            "linkedMetric": "suggestions.pendingReview",
            "permittedAction": "internal_review",
        })
    if pending_actions > 0:
        recs.append({
            "recommendationType": "process_pending_internal_actions",
            "priority": "medium",
            "reason": f"{pending_actions} internal action(s) are pending apply/reject (internal-only).",
            "linkedMetric": "actions.pendingInternal",
            "permittedAction": "create_internal_action",
        })
    if s["dueSoon"] > 0 and s["overdue"] == 0:
        recs.append({
            "recommendationType": "watch_due_soon",
            "priority": "low",
            "reason": f"{s['dueSoon']} internal action(s) are due soon - progress before they slip.",
            "linkedMetric": "summary.dueSoon",
            "permittedAction": "internal_review",
        })
    if not recs:
        recs.append({
            "recommendationType": "all_clear",
            "priority": "low",
            "reason": "No urgent internal items detected; continue normal internal execution.",
            "linkedMetric": "summary.openActions",
            "permittedAction": "no_external_action",
        })
    # Defence: every recommendation must carry a permitted (internal-only) action.
    for r in recs:
        if r["permittedAction"] not in PERMITTED_ACTIONS:
            r["permittedAction"] = "internal_review"
    return recs


def _department_focus(departments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for d in departments:
        if d["overdue"] > 0:
            focus = f"Clear {d['overdue']} overdue item(s)."
        elif d["blocked"] > 0:
            focus = f"Unblock {d['blocked']} blocked item(s)."
        elif d["dueSoon"] > 0:
            focus = f"Progress {d['dueSoon']} due-soon item(s)."
        elif d["open"] > 0:
            focus = f"Progress {d['open']} open item(s)."
        else:
            focus = "On track."
        out.append({
            "department": d["department"], "label": d["label"],
            "open": d["open"], "assigned": d["assigned"], "inProgress": d["inProgress"],
            "blocked": d["blocked"], "overdue": d["overdue"], "dueSoon": d["dueSoon"],
            "completedInternal": d["completedInternal"], "recommendedFocus": focus,
        })
    return out


def get_director_ai_briefing(*, window_days: int = 7) -> dict[str, Any]:
    """Read-only Director AI briefing composed from existing internal data.

    NEVER calls a provider, mutates a row, or takes an external action.
    """
    from django.utils import timezone

    from .models import AiApprovedAction, AiCopilotSuggestion

    window_days = max(1, min(30, int(window_days or 7)))
    now = timezone.now()

    analytics = services.get_workboard_analytics(window_days=window_days)
    attention = services.get_director_attention_queue()

    pending_suggestions = AiCopilotSuggestion.objects.filter(
        status=AiCopilotSuggestion.Status.PENDING_REVIEW
    ).count()
    pending_actions = AiApprovedAction.objects.filter(
        status=AiApprovedAction.Status.PENDING_INTERNAL_ACTION
    ).count()

    attention_items = [
        _attention_item(action, reason, now=now) for action, reason in attention
    ]
    blocked_items = [i for i in attention_items if i["reason"] == "blocked"]
    overdue_items = [i for i in attention_items if i["reason"] == "overdue"]
    unassigned_high_items = [
        i for i in attention_items if i["reason"] == "unassigned_high_priority"
    ]

    s = analytics["summary"]
    sla = analytics["sla"]
    attention_block = {
        "total": len(attention_items),
        "blockedCount": s["blocked"],
        "overdueCount": s["overdue"],
        "dueSoonCount": s["dueSoon"],
        "unassignedHighPriority": len(unassigned_high_items),
        "pendingSuggestions": pending_suggestions,
        "pendingInternalActions": pending_actions,
        "slaRiskCount": sla["overdue"] + sla["dueSoon"],
        "blocked": blocked_items,
        "overdue": overdue_items,
        "unassignedHigh": unassigned_high_items,
        "items": attention_items,
    }

    executive_summary = _executive_summary(
        analytics=analytics, pending_suggestions=pending_suggestions,
        pending_actions=pending_actions, unassigned_high=len(unassigned_high_items),
        attention_total=len(attention_items),
    )
    recommendations = _recommendations(
        analytics=analytics, pending_suggestions=pending_suggestions,
        pending_actions=pending_actions, unassigned_high=len(unassigned_high_items),
    )

    return {
        "briefingStatus": {
            "generatedAt": now,
            "windowDays": window_days,
            "aiMode": services.ai_copilot_mode(),
            "internalOnly": True,
            "readonly": True,
            "providerCallMade": False,
            "externalActionTaken": False,
            "liveAutonomousLocked": True,
            "phase": "16N",
        },
        "executiveSummary": executive_summary,
        "attentionItems": attention_block,
        "departmentSummary": _department_focus(analytics["departments"]),
        "memberSummary": analytics["members"],
        "safeRecommendations": recommendations,
        "slaSummary": sla,
        "blockedLiveActions": BLOCKED_LIVE_ACTIONS,
        "safetySnapshot": _safety_snapshot(),
        # Top-level locked guarantees (mirror the Phase 16M shape).
        "generatedAt": now,
        "windowDays": window_days,
        "readonly": True,
        "internalOnly": True,
        "providerCallMade": False,
        "providerActionTaken": False,
        "externalActionAllowed": False,
        "externalActionTaken": False,
        "liveAutonomousLocked": True,
        "phase": "16N",
    }


def get_director_ai_briefing_summary(*, window_days: int = 7) -> dict[str, Any]:
    """Lighter briefing payload - status + executive summary + headline counts."""
    full = get_director_ai_briefing(window_days=window_days)
    a = full["attentionItems"]
    sla = full["slaSummary"]
    return {
        "briefingStatus": full["briefingStatus"],
        "executiveSummary": full["executiveSummary"],
        "headline": {
            "openActions": sla["overdue"] + sla["dueSoon"] + sla["onTrack"] + sla["noDueDate"],
            "blocked": a["blockedCount"],
            "overdue": a["overdueCount"],
            "dueSoon": a["dueSoonCount"],
            "unassignedHighPriority": a["unassignedHighPriority"],
            "pendingSuggestions": a["pendingSuggestions"],
            "pendingInternalActions": a["pendingInternalActions"],
            "slaRiskCount": a["slaRiskCount"],
            "directorAttentionTotal": a["total"],
        },
        "safetySnapshot": full["safetySnapshot"],
        "readonly": True,
        "internalOnly": True,
        "providerCallMade": False,
        "externalActionTaken": False,
        "liveAutonomousLocked": True,
        "phase": "16N",
    }


def get_director_ai_briefing_recommendations(*, window_days: int = 7) -> dict[str, Any]:
    """Just the safe internal-only recommendations + locked-live-action contract."""
    full = get_director_ai_briefing(window_days=window_days)
    return {
        "briefingStatus": full["briefingStatus"],
        "safeRecommendations": full["safeRecommendations"],
        "blockedLiveActions": full["blockedLiveActions"],
        "permittedActions": list(PERMITTED_ACTIONS),
        "readonly": True,
        "internalOnly": True,
        "providerCallMade": False,
        "externalActionTaken": False,
        "liveAutonomousLocked": True,
        "phase": "16N",
    }
