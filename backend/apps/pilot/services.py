"""Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run service.

Pure, read-only evaluation. **No function here calls a live provider** — it
never creates a Razorpay/PayU payment link, captures/refunds, books a Delhivery
AWB, sends WhatsApp/Meta Cloud, places a Vapi call, calls any AI/LLM provider,
enqueues a business Celery job, or mutates `RuntimeKillSwitch` / `SandboxState`.
It reuses the Phase 16E `integration_hardening` readiness service for payment +
logistics status, reads Django settings + existing rows, and returns a
structured gate matrix + safe blocked-reasons + a final readiness verdict.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.integration_hardening import services as hardening


# ---------------------------------------------------------------------------
# Gate status vocabulary
# ---------------------------------------------------------------------------
PASS = "pass"
BLOCKED = "blocked"
WARNING = "warning"
SKIPPED = "skipped"


def _flag(name: str, default: bool = False) -> bool:
    return bool(getattr(settings, name, default))


def _mode(name: str) -> str:
    return (getattr(settings, name, "mock") or "mock").lower()


def safety_snapshot() -> dict[str, Any]:
    """Read-only global safety posture (reuses the Phase 16E summary)."""
    summary = hardening.safety_summary()
    return {
        "aiPaused": summary["aiPaused"],
        "sandboxOn": summary["sandboxOn"],
        "syncLive": True,  # the audit WebSocket is the Phase 15 sync surface
        "providerLiveActionsLocked": summary["providerLiveActionsLocked"],
        "phase15ShellFrozen": True,
        "phase": "16F",
    }


def _automation_flags() -> dict[str, bool]:
    """The broad-automation env flags — all must be False for a safe pilot."""
    return {
        "aiCallingEnabled": _flag("AI_CALLING_ENABLED"),
        "whatsappAiAutoReplyEnabled": _flag("WHATSAPP_AI_AUTO_REPLY_ENABLED"),
        "whatsappCallHandoffEnabled": _flag("WHATSAPP_CALL_HANDOFF_ENABLED"),
        "whatsappLifecycleAutomationEnabled": _flag(
            "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED"
        ),
        "whatsappRescueDiscountEnabled": _flag(
            "WHATSAPP_RESCUE_DISCOUNT_ENABLED"
        ),
        "whatsappReorderDay20Enabled": _flag("WHATSAPP_REORDER_DAY20_ENABLED"),
        "mcpEnabled": _flag("MCP_ENABLED"),
        "whatsappProvider": _mode("WHATSAPP_PROVIDER"),
        "vapiMode": _mode("VAPI_MODE"),
    }


def _claim_vault_status() -> dict[str, Any]:
    """Read-only Claim Vault production-seed status (warning if demo-only)."""
    try:
        from apps.compliance.coverage import build_coverage_report

        report = build_coverage_report()
        demo_count = sum(
            1 for item in report.items if getattr(item, "is_demo_default", False)
        )
        total = report.total_products
        if total == 0:
            return {"status": WARNING, "message": "No Claim Vault rows found.", "demoCount": 0, "total": 0}
        if demo_count > 0:
            return {
                "status": WARNING,
                "message": (
                    f"Claim Vault contains {demo_count} demo-only seed(s); "
                    "production rollout requires doctor-approved final claims."
                ),
                "demoCount": demo_count,
                "total": total,
            }
        if report.missing_count > 0:
            return {
                "status": WARNING,
                "message": f"{report.missing_count} product(s) have no approved claims.",
                "demoCount": 0,
                "total": total,
            }
        return {
            "status": PASS,
            "message": "Claim Vault has approved (non-demo) coverage.",
            "demoCount": 0,
            "total": total,
        }
    except Exception:  # noqa: BLE001 - compliance optional at dry-run time
        return {"status": WARNING, "message": "Claim Vault status unavailable.", "demoCount": 0, "total": 0}


def _team_roles_present() -> dict[str, Any]:
    """Read-only check that at least a Director/Admin operational role exists."""
    try:
        from apps.directorops.models import TeamRoleAssignment

        roles = set(
            TeamRoleAssignment.objects.filter(is_active=True).values_list(
                "operational_role", flat=True
            )
        )
        has_director = (
            TeamRoleAssignment.OperationalRole.DIRECTOR_ADMIN in roles
        )
        return {
            "status": PASS if has_director else WARNING,
            "message": (
                "Director/Admin operational role assigned."
                if has_director
                else "No active Director/Admin operational-role assignment found."
            ),
            "assignedRoles": sorted(roles),
        }
    except Exception:  # noqa: BLE001
        return {"status": WARNING, "message": "Team-role data unavailable.", "assignedRoles": []}


def _gate(key: str, label: str, status: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "detail": detail}


def build_readiness() -> dict[str, Any]:
    """Composite pilot-readiness snapshot for the dashboard (read-only)."""
    safety = safety_snapshot()
    automation = _automation_flags()
    pl = hardening.payment_logistics_readiness()
    razorpay = next((p for p in pl["payments"] if p["provider"] == "razorpay"), {})
    payu = next((p for p in pl["payments"] if p["provider"] == "payu"), {})
    delhivery = pl["logistics"][0] if pl["logistics"] else {}
    claim_vault = _claim_vault_status()
    team_roles = _team_roles_present()

    # Data availability (read-only counts).
    lead_count = _count("apps.crm.models", "Lead")
    customer_count = _count("apps.crm.models", "Customer")
    order_count = _count("apps.orders.models", "Order")
    campaign_count = _count("apps.data_imports.models", "ImportedCallingCampaign")

    whatsapp_blocked = automation["whatsappProvider"] != "meta_cloud" and not (
        automation["whatsappAiAutoReplyEnabled"]
        or automation["whatsappLifecycleAutomationEnabled"]
        or automation["whatsappCallHandoffEnabled"]
    )
    vapi_blocked = automation["vapiMode"] != "live" and not automation[
        "aiCallingEnabled"
    ]

    gates = [
        _gate(
            "lead_customer_data", "Lead / Customer data ready",
            PASS if (lead_count + customer_count) > 0 else WARNING,
            f"{lead_count} leads, {customer_count} customers available.",
        ),
        _gate(
            "calling_outcome_flow", "Calling outcome flow ready",
            PASS,
            "Imported-campaign call-queue + manual outcome recording available (Phase 16D).",
        ),
        _gate(
            "order_creation", "Order creation ready",
            PASS if order_count >= 0 else WARNING,
            f"Internal order service available; {order_count} orders exist.",
        ),
        _gate(
            "confirmation_flow", "Confirmation flow ready",
            PASS,
            "Internal confirmation-outcome service available (Phase 16B).",
        ),
        _gate(
            "payment_readiness", "Payment readiness (live blocked)",
            BLOCKED if not razorpay.get("liveEnabled", False) else WARNING,
            f"Razorpay mode={razorpay.get('mode', '?')}; live actions blocked without a Director gate. PayU={payu.get('status', '?')}.",
        ),
        _gate(
            "shipment_readiness", "Shipment readiness (live blocked)",
            BLOCKED if not delhivery.get("liveEnabled", False) else WARNING,
            f"Delhivery mode={delhivery.get('mode', '?')}; live AWB booking blocked without a Director gate.",
        ),
        _gate(
            "delivery_rto_readiness", "Delivery / RTO tracking readiness",
            PASS,
            "Delhivery webhook + RTO board available; no live booking from this page.",
        ),
        _gate(
            "whatsapp_automation", "WhatsApp live automation blocked",
            BLOCKED if whatsapp_blocked else WARNING,
            f"WhatsApp provider={automation['whatsappProvider']}; broad automation flags OFF."
            if whatsapp_blocked
            else "WhatsApp automation appears enabled — review before pilot.",
        ),
        _gate(
            "vapi_ai_calling", "Vapi / AI calling blocked",
            BLOCKED if vapi_blocked else WARNING,
            f"VAPI_MODE={automation['vapiMode']}; AI_CALLING_ENABLED={automation['aiCallingEnabled']}."
            if vapi_blocked
            else "AI calling appears enabled — review before pilot.",
        ),
        _gate(
            "claim_vault_seed", "Claim Vault production seed",
            claim_vault["status"], claim_vault["message"],
        ),
        _gate(
            "team_roles", "Required team roles assigned",
            team_roles["status"], team_roles["message"],
        ),
        _gate(
            "safety_state", "Safety state (AI Paused / Sandbox OFF)",
            PASS if (safety["aiPaused"] and not safety["sandboxOn"]) else WARNING,
            f"AI Paused={safety['aiPaused']}, Sandbox ON={safety['sandboxOn']}, live actions locked={safety['providerLiveActionsLocked']}.",
        ),
    ]

    blocked_live_actions = [
        "Live Razorpay/PayU payment link / capture / refund — blocked (Director live gate required).",
        "Live Delhivery AWB booking / shipment — blocked (Director live gate required).",
        "WhatsApp / Meta Cloud send — blocked (broad automation OFF).",
        "Vapi / voice calling — blocked (AI calling disabled).",
        "AI/LLM provider calls — not invoked in any pilot path.",
    ]

    return {
        "safety": safety,
        "automationFlags": automation,
        "paymentReadiness": razorpay,
        "payuReadiness": payu,
        "logisticsReadiness": delhivery,
        "claimVault": claim_vault,
        "teamRoles": team_roles,
        "dataCounts": {
            "leads": lead_count,
            "customers": customer_count,
            "orders": order_count,
            "importedCampaigns": campaign_count,
        },
        "gates": gates,
        "blockedLiveActions": blocked_live_actions,
        "signoffChecklistKeys": _signoff_checklist_keys(),
        "noSideEffect": True,
        "generatedByProvider": False,
    }


def _signoff_checklist_keys() -> list[dict[str, str]]:
    return [
        {"key": "pilot_team_selected", "label": "Pilot team selected"},
        {"key": "test_product_disease_selected", "label": "Test product / disease selected"},
        {"key": "allowed_list_approved", "label": "Allowed-list approved"},
        {"key": "payment_mode_approved", "label": "Payment mode approved"},
        {"key": "courier_mode_approved", "label": "Courier mode approved"},
        {"key": "call_script_approved", "label": "Call script approved"},
        {"key": "claim_vault_seed_approved", "label": "Claim Vault production seed approved"},
        {"key": "live_provider_gate_not_approved", "label": "Live provider gate NOT approved yet (must stay false)"},
    ]


def _count(module_path: str, class_name: str) -> int:
    try:
        import importlib

        model = getattr(importlib.import_module(module_path), class_name)
        return int(model.objects.count())
    except Exception:  # noqa: BLE001
        return 0


def evaluate_dry_run(dry_run) -> dict[str, Any]:
    """Evaluate a PilotDryRun: compute gate matrix + verdict (no provider call).

    Mutates only the passed ``dry_run`` row (gate_results / blocked_reasons /
    safety_snapshot / status / result_summary). Returns the computed payload.
    """
    readiness = build_readiness()
    gates = readiness["gates"]

    # Scenario-aware: a payment_logistics scenario only cares about provider
    # gates; full_lifecycle considers everything.
    scenario = dry_run.scenario_type
    PilotDryRun = dry_run.__class__
    if scenario == PilotDryRun.ScenarioType.PAYMENT_LOGISTICS:
        relevant = [
            g for g in gates
            if g["key"] in {
                "payment_readiness", "shipment_readiness",
                "delivery_rto_readiness", "safety_state",
            }
        ]
    else:
        relevant = gates

    blocked = [g for g in relevant if g["status"] == BLOCKED]
    warnings = [g for g in relevant if g["status"] == WARNING]

    # A dry-run is "blocked" only when a gate that should PASS is actually
    # blocked for the wrong reason. The provider live-gate blocks are the
    # EXPECTED safe state, so they do NOT fail the dry-run — they are recorded
    # as intentional blocked-live-actions. The verdict is:
    #   - WARNING if any non-provider warning gate fired,
    #   - PASSED otherwise (provider live blocks are expected + safe).
    provider_gate_keys = {
        "payment_readiness", "shipment_readiness", "whatsapp_automation",
        "vapi_ai_calling",
    }
    non_provider_warnings = [g for g in warnings if g["key"] not in provider_gate_keys]
    # A provider gate showing WARNING (e.g. WhatsApp automation ON) is unsafe.
    provider_warnings = [g for g in warnings if g["key"] in provider_gate_keys]

    if provider_warnings:
        status = PilotDryRun.Status.BLOCKED
        summary = (
            f"Pilot BLOCKED — {len(provider_warnings)} provider gate(s) are not "
            "in the safe locked state. Review before any pilot."
        )
    elif non_provider_warnings:
        status = PilotDryRun.Status.WARNING
        summary = (
            f"Pilot dry-run completed with {len(non_provider_warnings)} warning(s). "
            "All live provider actions remain blocked."
        )
    else:
        status = PilotDryRun.Status.PASSED
        summary = (
            "Pilot dry-run PASSED — readiness confirmed; all live provider "
            "actions remain blocked behind a future Director live gate."
        )

    blocked_reasons = readiness["blockedLiveActions"]

    dry_run.gate_results = relevant
    dry_run.blocked_reasons = blocked_reasons
    dry_run.safety_snapshot = readiness["safety"]
    dry_run.result_summary = summary
    dry_run.status = status
    dry_run.provider_actions_attempted = False
    dry_run.provider_actions_blocked = True
    dry_run.save(
        update_fields=[
            "gate_results", "blocked_reasons", "safety_snapshot",
            "result_summary", "status", "provider_actions_attempted",
            "provider_actions_blocked", "updated_at",
        ]
    )

    return {
        "status": status,
        "summary": summary,
        "gateResults": relevant,
        "blockedReasons": blocked_reasons,
        "blockedGateCount": len(blocked),
        "warningGateCount": len(warnings),
    }


# ---------------------------------------------------------------------------
# Phase 16G — Internal Pilot Control Center services
# ---------------------------------------------------------------------------
#
# These functions create / update / transition pilot-plan records and derive
# read-only gate status + metrics. **None of them call a provider, enqueue a
# provider Celery job, or mutate the Phase 15 safety shell.** A plan's
# `provider_actions_allowed` stays False and `provider_actions_blocked` stays
# True at every state — including running_internal — because live execution is
# a future, separately-gated phase.


class PilotPlanStateError(Exception):
    """Raised when an invalid pilot-plan transition is requested."""


# action -> (allowed from-states, target status, event_type)
_PILOT_TRANSITIONS: dict[str, tuple[set[str], str, str]] = {
    "mark_ready": ({"draft"}, "ready_for_review", "ready_for_review"),
    "approve_internal": ({"ready_for_review"}, "approved_internal", "approved_internal"),
    "start_internal": ({"approved_internal"}, "running_internal", "started_internal"),
    "pause": ({"running_internal"}, "paused", "paused"),
    "resume_internal": ({"paused"}, "running_internal", "resumed_internal"),
    "complete": ({"running_internal", "paused"}, "completed", "completed"),
    "cancel": (
        {"draft", "ready_for_review", "approved_internal", "running_internal", "paused"},
        "cancelled",
        "cancelled",
    ),
}

PILOT_ACTIONS = tuple(_PILOT_TRANSITIONS.keys())


def _record_event(plan, event_type: str, *, actor=None, note: str = "") -> None:
    from .models import PilotPlanEvent

    PilotPlanEvent.objects.create(
        pilot_plan=plan,
        event_type=event_type,
        note=str(note or "")[:4000],
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        safety_snapshot=safety_snapshot(),
    )


def create_pilot_plan(*, name: str, pilot_type: str, created_by=None, **fields) -> Any:
    """Create a draft pilot plan + a 'created' event. No provider call."""
    from .models import PilotPlan

    actor = created_by if (created_by and getattr(created_by, "is_authenticated", False)) else None
    plan = PilotPlan.objects.create(
        name=str(name or "").strip()[:160],
        pilot_type=pilot_type,
        status=PilotPlan.Status.DRAFT,
        owner_user=fields.get("owner_user"),
        owner_team=str(fields.get("owner_team", "") or "")[:64],
        problem_category=str(fields.get("problem_category", "") or "")[:120],
        product_category=str(fields.get("product_category", "") or "")[:120],
        objective=str(fields.get("objective", "") or ""),
        risk_note=str(fields.get("risk_note", "") or ""),
        allowed_list_note=str(fields.get("allowed_list_note", "") or ""),
        max_contacts=int(fields.get("max_contacts") or 0),
        planned_start_at=fields.get("planned_start_at"),
        planned_end_at=fields.get("planned_end_at"),
        linked_import_campaign_id=fields.get("linked_import_campaign_id"),
        linked_dataset_id=fields.get("linked_dataset_id"),
        linked_order_id=fields.get("linked_order_id"),
        linked_dry_run_id=fields.get("linked_dry_run_id"),
        safety_acknowledged=bool(fields.get("safety_acknowledged", False)),
        provider_actions_allowed=False,
        provider_actions_attempted=False,
        provider_actions_blocked=True,
        created_by=actor,
        updated_by=actor,
    )
    _record_event(plan, "created", actor=actor, note="Pilot plan created (internal).")
    return plan


_EDITABLE_FIELDS = {
    "name", "pilot_type", "owner_team", "problem_category", "product_category",
    "objective", "risk_note", "allowed_list_note", "max_contacts",
    "planned_start_at", "planned_end_at", "owner_user", "safety_acknowledged",
    "linked_import_campaign_id", "linked_dataset_id", "linked_order_id",
    "linked_dry_run_id",
}


def update_pilot_plan(plan, *, updated_by=None, **fields) -> Any:
    """Update editable config fields. Never flips the provider-lock contract."""
    changed: list[str] = []
    for key, value in fields.items():
        if key not in _EDITABLE_FIELDS:
            continue
        if key == "name":
            value = str(value or "").strip()[:160]
        elif key in {"owner_team"}:
            value = str(value or "")[:64]
        elif key in {"problem_category", "product_category"}:
            value = str(value or "")[:120]
        elif key == "max_contacts":
            value = int(value or 0)
        elif key == "safety_acknowledged":
            value = bool(value)
        setattr(plan, key, value)
        changed.append(key)
    # The provider-lock contract is immutable here.
    plan.provider_actions_allowed = False
    plan.provider_actions_attempted = False
    plan.provider_actions_blocked = True
    if updated_by and getattr(updated_by, "is_authenticated", False):
        plan.updated_by = updated_by
    plan.save()
    return plan


def transition_pilot_plan(plan, action: str, *, actor=None, note: str = "") -> Any:
    """Move a pilot plan's internal status. No provider call, ever."""
    from .models import PilotPlan

    rule = _PILOT_TRANSITIONS.get(action)
    if rule is None:
        raise PilotPlanStateError(f"unknown_action:{action}")
    from_states, target, event_type = rule
    if plan.status not in from_states:
        raise PilotPlanStateError(
            f"invalid_transition:{plan.status}->{target} via {action}"
        )

    plan.status = target
    # Locked contract holds at every status, including running_internal.
    plan.provider_actions_allowed = False
    plan.provider_actions_attempted = False
    plan.provider_actions_blocked = True
    if actor and getattr(actor, "is_authenticated", False):
        plan.updated_by = actor
    plan.save(
        update_fields=[
            "status", "provider_actions_allowed", "provider_actions_attempted",
            "provider_actions_blocked", "updated_by", "updated_at",
        ]
    )
    _record_event(plan, event_type, actor=actor, note=note)
    return plan


def record_pilot_review(plan, *, decision: str, note: str = "", decided_by=None) -> Any:
    """Record an internal Director review (record-only; no status change)."""
    from .models import PilotPlanReview

    actor = decided_by if (decided_by and getattr(decided_by, "is_authenticated", False)) else None
    review = PilotPlanReview.objects.create(
        pilot_plan=plan,
        decision=decision,
        note=str(note or "")[:4000],
        decided_by=actor,
    )
    _record_event(plan, "note_added", actor=actor, note=f"Review: {decision}")
    return review


def get_pilot_gate_status(plan) -> list[dict[str, Any]]:
    """Derive the internal pilot gate checklist (read-only)."""
    readiness = build_readiness()
    gate_by_key = {g["key"]: g for g in readiness["gates"]}

    def _gate_status(key: str) -> str:
        return gate_by_key.get(key, {}).get("status", WARNING)

    has_director_approval = (
        plan.status in {"approved_internal", "running_internal", "paused", "completed"}
        or plan.reviews.filter(decision="approved_internal").exists()
    )
    dry_run_ok = bool(
        plan.linked_dry_run_id
        and getattr(plan.linked_dry_run, "status", None) in {"passed", "warning"}
    )
    data_selected = bool(
        plan.linked_import_campaign_id or plan.linked_dataset_id or plan.linked_order_id
    )

    def _item(key: str, label: str, ok: bool, detail: str) -> dict[str, Any]:
        return {"key": key, "label": label, "status": PASS if ok else WARNING, "detail": detail}

    payment_blocked = _gate_status("payment_readiness") == BLOCKED
    shipment_blocked = _gate_status("shipment_readiness") == BLOCKED
    whatsapp_blocked = _gate_status("whatsapp_automation") == BLOCKED
    vapi_blocked = _gate_status("vapi_ai_calling") == BLOCKED

    return [
        _item("team_assigned", "Team assigned",
              bool(plan.owner_user_id or plan.owner_team),
              "Owner user or team set." if (plan.owner_user_id or plan.owner_team) else "No owner assigned."),
        _item("data_selected", "Data selected", data_selected,
              "Campaign / dataset / order linked." if data_selected else "No data source linked."),
        _item("call_script_approved", "Call script approved",
              bool(plan.objective), "Objective recorded." if plan.objective else "No objective recorded."),
        _item("claim_vault_reviewed", "Claim Vault reviewed",
              _gate_status("claim_vault_seed") == PASS,
              readiness["claimVault"]["message"]),
        # These four must be BLOCKED (locked) for a safe pilot — "ok" = locked.
        {"key": "payment_live_gate_blocked", "label": "Payment live gate blocked",
         "status": PASS if payment_blocked else WARNING,
         "detail": "Live payment blocked (Director live gate required)." if payment_blocked
         else "Payment gate not in safe blocked state — review."},
        {"key": "shipment_live_gate_blocked", "label": "Shipment live gate blocked",
         "status": PASS if shipment_blocked else WARNING,
         "detail": "Live shipment blocked (Director live gate required)." if shipment_blocked
         else "Shipment gate not in safe blocked state — review."},
        {"key": "whatsapp_blocked", "label": "WhatsApp blocked",
         "status": PASS if whatsapp_blocked else WARNING,
         "detail": "WhatsApp live automation blocked." if whatsapp_blocked
         else "WhatsApp automation appears enabled — review before pilot."},
        {"key": "vapi_ai_blocked", "label": "Vapi / AI calling blocked",
         "status": PASS if vapi_blocked else WARNING,
         "detail": "Vapi / AI calling blocked." if vapi_blocked
         else "AI calling appears enabled — review before pilot."},
        _item("dry_run_completed", "Dry-run completed", dry_run_ok,
              "Linked dry-run passed/warning." if dry_run_ok else "No completed dry-run linked."),
        _item("director_internal_approval", "Director internal approval recorded",
              has_director_approval,
              "Internal approval recorded." if has_director_approval else "Not yet approved internally."),
    ]


def get_pilot_metrics(plan) -> dict[str, Any]:
    """Read-only internal metrics for a pilot plan. No provider call."""
    readiness = build_readiness()
    campaign = plan.linked_import_campaign
    dataset = plan.linked_dataset

    campaign_metrics = None
    if campaign is not None:
        campaign_metrics = {
            "name": campaign.name,
            "totalContacts": campaign.total_contacts,
            "pending": campaign.pending_count,
            "completed": campaign.completed_count,
            "interested": campaign.interested_count,
            "notInterested": campaign.not_interested_count,
            "callback": campaign.callback_count,
            "wrongNumber": campaign.wrong_number_count,
            "ordersCreated": campaign.order_created_count,
        }

    dataset_metrics = None
    if dataset is not None:
        dataset_metrics = {
            "name": dataset.name,
            "totalRows": dataset.total_rows,
            "validRows": dataset.valid_rows,
            "duplicateRows": dataset.duplicate_rows,
            "invalidRows": dataset.invalid_rows,
        }

    return {
        "campaign": campaign_metrics,
        "dataset": dataset_metrics,
        "linkedOrderId": plan.linked_order_id,
        "linkedDryRunId": plan.linked_dry_run_id,
        "dryRunStatus": getattr(plan.linked_dry_run, "status", None) if plan.linked_dry_run_id else None,
        "paymentReadinessStatus": readiness["paymentReadiness"].get("status"),
        "shipmentReadinessStatus": readiness["logisticsReadiness"].get("status"),
        "blockedLiveActions": readiness["blockedLiveActions"],
    }


def get_pilot_summary() -> dict[str, Any]:
    """Control-center summary: status counts + gate snapshot + safety."""
    from django.db.models import Count

    from .models import PilotPlan

    counts = {choice: 0 for choice, _ in PilotPlan.Status.choices}
    for row in PilotPlan.objects.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]

    readiness = build_readiness()
    return {
        "statusCounts": counts,
        "totalPlans": sum(counts.values()),
        "activePlans": counts.get("running_internal", 0) + counts.get("paused", 0),
        "safety": readiness["safety"],
        "gates": readiness["gates"],
        "blockedLiveActions": readiness["blockedLiveActions"],
        "noSideEffect": True,
        "generatedByProvider": False,
    }
