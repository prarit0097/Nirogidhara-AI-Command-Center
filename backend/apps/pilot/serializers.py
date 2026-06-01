"""Phase 16F — dict serializers (camelCase out). No PII beyond safe display."""
from __future__ import annotations

from typing import Any

from .models import (
    PilotDecision,
    PilotDryRun,
    PilotPlan,
    PilotPlanEvent,
    PilotPlanReview,
)


def serialize_dry_run(d: PilotDryRun, *, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": d.pk,
        "name": d.name,
        "scenarioType": d.scenario_type,
        "status": d.status,
        "resultSummary": d.result_summary,
        "selectedLeadId": d.selected_lead_id,
        "selectedCustomerId": d.selected_customer_id,
        "selectedOrderId": d.selected_order_id,
        "selectedImportCampaignId": d.selected_import_campaign_id,
        "selectedQueueItemId": d.selected_queue_item_id,
        "createdBy": d.created_by.username if d.created_by_id else None,
        "providerActionsAttempted": d.provider_actions_attempted,
        "providerActionsBlocked": d.provider_actions_blocked,
        "createdAt": d.created_at,
        "updatedAt": d.updated_at,
    }
    if detail:
        out["gateResults"] = list(d.gate_results or [])
        out["blockedReasons"] = list(d.blocked_reasons or [])
        out["safetySnapshot"] = dict(d.safety_snapshot or {})
        out["decisions"] = [
            serialize_decision(dec) for dec in d.decisions.all().order_by("-created_at")
        ]
    return out


def serialize_decision(dec: PilotDecision) -> dict[str, Any]:
    return {
        "id": dec.pk,
        "dryRunId": dec.dry_run_id,
        "decision": dec.decision,
        "note": dec.note,
        "signoffChecklist": dict(dec.signoff_checklist or {}),
        "decidedBy": dec.decided_by.username if dec.decided_by_id else None,
        "createdAt": dec.created_at,
    }


# ---------------------------------------------------------------------------
# Phase 16G — Internal Pilot Control Center serializers (camelCase, no PII)
# ---------------------------------------------------------------------------


def serialize_pilot_plan(p: PilotPlan, *, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": p.pk,
        "name": p.name,
        "pilotType": p.pilot_type,
        "status": p.status,
        "ownerUser": p.owner_user.username if p.owner_user_id else None,
        "ownerTeam": p.owner_team,
        "problemCategory": p.problem_category,
        "productCategory": p.product_category,
        "objective": p.objective,
        "riskNote": p.risk_note,
        "allowedListNote": p.allowed_list_note,
        "maxContacts": p.max_contacts,
        "plannedStartAt": p.planned_start_at,
        "plannedEndAt": p.planned_end_at,
        "linkedImportCampaignId": p.linked_import_campaign_id,
        "linkedDatasetId": p.linked_dataset_id,
        "linkedOrderId": p.linked_order_id,
        "linkedDryRunId": p.linked_dry_run_id,
        "safetyAcknowledged": p.safety_acknowledged,
        "providerActionsAllowed": p.provider_actions_allowed,
        "providerActionsAttempted": p.provider_actions_attempted,
        "providerActionsBlocked": p.provider_actions_blocked,
        "createdBy": p.created_by.username if p.created_by_id else None,
        "updatedBy": p.updated_by.username if p.updated_by_id else None,
        "createdAt": p.created_at,
        "updatedAt": p.updated_at,
    }
    if detail:
        out["events"] = [
            serialize_pilot_event(e)
            for e in p.events.all().order_by("-created_at")[:50]
        ]
        out["reviews"] = [
            serialize_pilot_plan_review(r)
            for r in p.reviews.all().order_by("-created_at")[:50]
        ]
    return out


def serialize_pilot_event(e: PilotPlanEvent) -> dict[str, Any]:
    return {
        "id": e.pk,
        "pilotPlanId": e.pilot_plan_id,
        "eventType": e.event_type,
        "note": e.note,
        "actor": e.actor.username if e.actor_id else None,
        "createdAt": e.created_at,
    }


def serialize_pilot_plan_review(r: PilotPlanReview) -> dict[str, Any]:
    return {
        "id": r.pk,
        "pilotPlanId": r.pilot_plan_id,
        "decision": r.decision,
        "note": r.note,
        "decidedBy": r.decided_by.username if r.decided_by_id else None,
        "createdAt": r.created_at,
    }
