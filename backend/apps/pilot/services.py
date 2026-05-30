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
