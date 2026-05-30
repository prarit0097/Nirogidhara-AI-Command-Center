"""Phase 16F — dict serializers (camelCase out). No PII beyond safe display."""
from __future__ import annotations

from typing import Any

from .models import PilotDecision, PilotDryRun


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
