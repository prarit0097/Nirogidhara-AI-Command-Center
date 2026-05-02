"""Phase 6I single internal live-gate simulation service.

The simulation layer is intentionally built on top of the Phase 6H live
gate. It records an internal approval and run rehearsal without calling
providers or mutating business objects.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .context import get_default_organization
from .live_gate import (
    approve_live_execution_request,
    create_live_execution_request,
    evaluate_live_execution_gate,
    get_or_create_default_runtime_kill_switch,
    is_runtime_kill_switch_active,
    reject_live_execution_request,
)
from .live_gate_policy import get_live_gate_policy
from .models import (
    Branch,
    Organization,
    RuntimeLiveExecutionRequest,
    RuntimeLiveGateSimulation,
)


ALLOWED_SIMULATION_OPERATIONS = (
    "razorpay.create_order",
    "whatsapp.send_text",
    "ai.smoke_test",
)
DEFAULT_SIMULATION_OPERATION = "razorpay.create_order"
PHASE_6I_WARNING = (
    "Phase 6I simulation never calls providers or creates external side effects."
)


def _is_authenticated_user(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def _resolve_org_branch(
    *,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
) -> tuple[Optional[Organization], Optional[Branch]]:
    org = organization or get_default_organization()
    resolved_branch = branch
    if resolved_branch is None and org is not None:
        resolved_branch = Branch.objects.filter(
            organization=org,
            code="main",
        ).first()
    return org, resolved_branch


def _validate_operation(operation_type: str) -> str:
    op = (operation_type or DEFAULT_SIMULATION_OPERATION).strip()
    if op not in ALLOWED_SIMULATION_OPERATIONS:
        raise ValueError(
            "Unsupported Phase 6I simulation operation: "
            f"{op}. Allowed: {', '.join(ALLOWED_SIMULATION_OPERATIONS)}"
        )
    return op


def _default_payload(operation_type: str) -> dict[str, Any]:
    key = f"phase6i:{operation_type}:{uuid4()}"
    payload: dict[str, Any] = {
        "simulation": True,
        "internalOnly": True,
        "idempotencyKey": key,
        "phase": "6I",
        "noRealCustomerData": True,
    }
    if operation_type == "razorpay.create_order":
        payload.update(
            {
                "paymentApprovalRecorded": True,
                "webhookConfigured": True,
                "amountInPaise": 100,
                "currency": "INR",
            }
        )
    elif operation_type == "whatsapp.send_text":
        payload.update(
            {
                "consentVerified": False,
                "claimVaultValidated": False,
                "caioReviewed": False,
                "phone": "+91******0000",
                "message": "internal simulation placeholder",
            }
        )
    elif operation_type == "ai.smoke_test":
        payload.update({"prompt": "internal simulation placeholder"})
    return payload


def _coerce_payload(
    operation_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if payload is None:
        return _default_payload(operation_type)
    return {
        **_default_payload(operation_type),
        **payload,
        "simulation": True,
        "internalOnly": True,
        "noRealCustomerData": True,
    }


def _safe_identity(user) -> int | None:
    return user.id if _is_authenticated_user(user) else None


def _audit_simulation(
    *,
    kind: str,
    simulation: RuntimeLiveGateSimulation,
    user=None,
    text: str = "",
) -> AuditEvent:
    payload = {
        "simulation_id": simulation.id,
        "organization": (
            {
                "id": simulation.organization_id,
                "code": simulation.organization.code,
                "name": simulation.organization.name,
            }
            if simulation.organization_id and simulation.organization
            else None
        ),
        "operation_type": simulation.operation_type,
        "provider_type": simulation.provider_type,
        "status": simulation.status,
        "approval_status": simulation.approval_status,
        "dry_run": simulation.dry_run,
        "live_execution_allowed": simulation.live_execution_allowed,
        "external_call_will_be_made": simulation.external_call_will_be_made,
        "external_call_was_made": simulation.external_call_was_made,
        "provider_call_attempted": simulation.provider_call_attempted,
        "kill_switch_active": simulation.kill_switch_active,
        "gate_decision": simulation.gate_decision,
        "payload_hash": simulation.payload_hash,
        "safe_payload_summary": simulation.safe_payload_summary,
        "blockers": simulation.blockers,
        "warnings": simulation.warnings,
    }
    return write_event(
        kind=kind,
        text=text
        or f"Runtime live-gate simulation {kind.rsplit('.', 1)[-1]} for {simulation.operation_type}",
        tone=(
            AuditEvent.Tone.WARNING
            if simulation.status
            in {
                RuntimeLiveGateSimulation.Status.BLOCKED,
                RuntimeLiveGateSimulation.Status.REJECTED,
                RuntimeLiveGateSimulation.Status.FAILED,
            }
            else AuditEvent.Tone.INFO
        ),
        payload=payload,
        organization=simulation.organization,
        user=user if _is_authenticated_user(user) else None,
    )


def _apply_decision(
    simulation: RuntimeLiveGateSimulation,
    decision: dict[str, Any],
) -> RuntimeLiveGateSimulation:
    simulation.provider_type = decision.get(
        "providerType", simulation.provider_type
    )
    simulation.risk_level = decision.get("riskLevel", simulation.risk_level)
    simulation.payload_hash = decision.get(
        "payloadHash", simulation.payload_hash
    )
    simulation.safe_payload_summary = decision.get(
        "safePayloadSummary", simulation.safe_payload_summary
    )
    simulation.blockers = list(decision.get("blockers", []))
    simulation.warnings = list(decision.get("warnings", [])) + [
        PHASE_6I_WARNING
    ]
    simulation.gate_decision = decision.get(
        "gateDecision",
        RuntimeLiveExecutionRequest.GateDecision.BLOCKED_BY_DEFAULT,
    )
    simulation.kill_switch_active = bool(
        decision.get("killSwitchActive", True)
    )
    simulation.runtime_source = "env_config"
    simulation.per_org_runtime_enabled = False
    simulation.dry_run = True
    simulation.live_execution_allowed = False
    simulation.external_call_will_be_made = False
    simulation.external_call_was_made = False
    simulation.provider_call_attempted = False
    return simulation


def serialize_live_gate_simulation(
    simulation: RuntimeLiveGateSimulation,
) -> dict[str, Any]:
    return {
        "id": simulation.id,
        "organization": (
            {
                "id": simulation.organization_id,
                "code": simulation.organization.code,
                "name": simulation.organization.name,
            }
            if simulation.organization_id and simulation.organization
            else None
        ),
        "branch": (
            {
                "id": simulation.branch_id,
                "code": simulation.branch.code,
                "name": simulation.branch.name,
            }
            if simulation.branch_id and simulation.branch
            else None
        ),
        "liveExecutionRequestId": simulation.live_execution_request_id,
        "operationType": simulation.operation_type,
        "providerType": simulation.provider_type,
        "status": simulation.status,
        "approvalStatus": simulation.approval_status,
        "runtimeSource": simulation.runtime_source,
        "perOrgRuntimeEnabled": simulation.per_org_runtime_enabled,
        "dryRun": simulation.dry_run,
        "liveExecutionRequested": simulation.live_execution_requested,
        "liveExecutionAllowed": simulation.live_execution_allowed,
        "externalCallWillBeMade": simulation.external_call_will_be_made,
        "externalCallWasMade": simulation.external_call_was_made,
        "providerCallAttempted": simulation.provider_call_attempted,
        "killSwitchActive": simulation.kill_switch_active,
        "riskLevel": simulation.risk_level,
        "payloadHash": simulation.payload_hash,
        "safePayloadSummary": simulation.safe_payload_summary,
        "blockers": simulation.blockers,
        "warnings": simulation.warnings,
        "gateDecision": simulation.gate_decision,
        "idempotencyKey": simulation.idempotency_key,
        "simulationResult": simulation.simulation_result,
        "preparedBy": simulation.prepared_by_id,
        "approvalRequestedBy": simulation.approval_requested_by_id,
        "approvedBy": simulation.approved_by_id,
        "rejectedBy": simulation.rejected_by_id,
        "runBy": simulation.run_by_id,
        "rolledBackBy": simulation.rolled_back_by_id,
        "preparedAt": simulation.prepared_at.isoformat()
        if simulation.prepared_at
        else None,
        "approvalRequestedAt": (
            simulation.approval_requested_at.isoformat()
            if simulation.approval_requested_at
            else None
        ),
        "approvedAt": simulation.approved_at.isoformat()
        if simulation.approved_at
        else None,
        "rejectedAt": simulation.rejected_at.isoformat()
        if simulation.rejected_at
        else None,
        "runAt": simulation.run_at.isoformat()
        if simulation.run_at
        else None,
        "rolledBackAt": simulation.rolled_back_at.isoformat()
        if simulation.rolled_back_at
        else None,
        "metadata": simulation.metadata,
        "createdAt": simulation.created_at.isoformat(),
        "updatedAt": simulation.updated_at.isoformat(),
        "nextAction": _next_action(simulation),
    }


def _next_action(simulation: RuntimeLiveGateSimulation) -> str:
    if simulation.status == RuntimeLiveGateSimulation.Status.PREPARED:
        return "request_internal_approval_before_simulation_run"
    if simulation.status == RuntimeLiveGateSimulation.Status.APPROVAL_REQUESTED:
        return "approve_or_reject_internal_simulation"
    if simulation.status == RuntimeLiveGateSimulation.Status.APPROVED:
        return "run_internal_simulation_without_provider_calls"
    if simulation.status == RuntimeLiveGateSimulation.Status.SIMULATED:
        return "rollback_or_archive_phase_6i_simulation"
    if simulation.status == RuntimeLiveGateSimulation.Status.ROLLED_BACK:
        return "phase_6i_simulation_rolled_back_no_external_side_effects"
    if simulation.status == RuntimeLiveGateSimulation.Status.REJECTED:
        return "prepare_new_simulation_if_needed"
    return "keep_live_execution_blocked"


def prepare_single_internal_live_gate_simulation(
    *,
    operation_type: str = DEFAULT_SIMULATION_OPERATION,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    user=None,
    payload: Optional[dict[str, Any]] = None,
    reason: str = "",
) -> RuntimeLiveGateSimulation:
    operation = _validate_operation(operation_type)
    org, resolved_branch = _resolve_org_branch(
        organization=organization,
        branch=branch,
    )
    safe_payload = _coerce_payload(operation, payload)
    policy = get_live_gate_policy(operation)
    decision = evaluate_live_execution_gate(
        operation,
        organization=org,
        branch=resolved_branch,
        user=user,
        payload=safe_payload,
        live_requested=True,
        approval_status="pending",
    )
    get_or_create_default_runtime_kill_switch()
    simulation = RuntimeLiveGateSimulation(
        organization=org,
        branch=resolved_branch,
        operation_type=operation,
        provider_type=(policy.provider_type if policy else decision.get("providerType", "")),
        approval_status=RuntimeLiveExecutionRequest.ApprovalStatus.NOT_REQUIRED,
        prepared_by=user if _is_authenticated_user(user) else None,
        prepared_at=timezone.now(),
        idempotency_key=str(safe_payload.get("idempotencyKey", "")),
        metadata={
            "phase": "6I",
            "reason": reason,
            "allowedOperations": list(ALLOWED_SIMULATION_OPERATIONS),
            "defaultOperation": DEFAULT_SIMULATION_OPERATION,
            "noProviderCall": True,
            "preparedBy": _safe_identity(user),
        },
    )
    _apply_decision(simulation, decision)
    simulation.live_execution_requested = False
    simulation.save()
    event = _audit_simulation(
        kind="runtime.live_gate.simulation_prepared",
        simulation=simulation,
        user=user,
        text=f"Phase 6I simulation prepared for {operation}",
    )
    simulation.audit_event_id = event.id
    simulation.save(update_fields=["audit_event_id", "updated_at"])
    return simulation


def request_single_internal_live_gate_approval(
    simulation_id: int,
    *,
    user=None,
    reason: str = "",
) -> RuntimeLiveGateSimulation:
    simulation = RuntimeLiveGateSimulation.objects.get(id=simulation_id)
    payload = {
        **(simulation.safe_payload_summary or {}),
        "idempotencyKey": simulation.idempotency_key,
        "phase": "6I",
        "reason": reason,
    }
    request_row = create_live_execution_request(
        simulation.operation_type,
        organization=simulation.organization,
        branch=simulation.branch,
        user=user,
        payload=payload,
        live_requested=True,
    )
    simulation.live_execution_request = request_row
    simulation.status = RuntimeLiveGateSimulation.Status.APPROVAL_REQUESTED
    simulation.approval_status = request_row.approval_status
    simulation.approval_requested_by = (
        user if _is_authenticated_user(user) else None
    )
    simulation.approval_requested_at = timezone.now()
    simulation.live_execution_requested = True
    simulation.blockers = request_row.blockers
    simulation.warnings = list(request_row.warnings or []) + [
        PHASE_6I_WARNING
    ]
    simulation.gate_decision = request_row.gate_decision
    simulation.kill_switch_active = is_runtime_kill_switch_active(
        simulation.organization,
        simulation.provider_type,
        simulation.operation_type,
    )
    simulation.live_execution_allowed = False
    simulation.external_call_will_be_made = False
    simulation.external_call_was_made = False
    simulation.provider_call_attempted = False
    simulation.metadata = {
        **(simulation.metadata or {}),
        "approvalReason": reason,
        "requestedBy": _safe_identity(user),
    }
    simulation.save()
    event = _audit_simulation(
        kind="runtime.live_gate.simulation_approval_requested",
        simulation=simulation,
        user=user,
        text=f"Phase 6I simulation approval requested for {simulation.operation_type}",
    )
    simulation.audit_event_id = event.id
    simulation.save(update_fields=["audit_event_id", "updated_at"])
    return simulation


def approve_single_internal_live_gate_simulation(
    simulation_id: int,
    *,
    approver=None,
    reason: str = "",
) -> RuntimeLiveGateSimulation:
    simulation = RuntimeLiveGateSimulation.objects.get(id=simulation_id)
    if simulation.live_execution_request_id is None:
        simulation = request_single_internal_live_gate_approval(
            simulation.id,
            user=approver,
            reason=reason,
        )
    request_row = approve_live_execution_request(
        simulation.live_execution_request_id,
        approver,
        reason=reason,
    )
    simulation.status = RuntimeLiveGateSimulation.Status.APPROVED
    simulation.approval_status = request_row.approval_status
    simulation.approved_by = approver if _is_authenticated_user(approver) else None
    simulation.approved_at = timezone.now()
    simulation.blockers = request_row.blockers
    simulation.warnings = list(request_row.warnings or []) + [
        PHASE_6I_WARNING,
        "Approval does not execute external calls in Phase 6I.",
    ]
    simulation.gate_decision = request_row.gate_decision
    simulation.kill_switch_active = is_runtime_kill_switch_active(
        simulation.organization,
        simulation.provider_type,
        simulation.operation_type,
    )
    simulation.live_execution_allowed = False
    simulation.external_call_will_be_made = False
    simulation.external_call_was_made = False
    simulation.provider_call_attempted = False
    simulation.metadata = {
        **(simulation.metadata or {}),
        "approvalReason": reason,
        "approvedBy": _safe_identity(approver),
    }
    simulation.save()
    event = _audit_simulation(
        kind="runtime.live_gate.simulation_approved",
        simulation=simulation,
        user=approver,
        text=f"Phase 6I simulation approved for {simulation.operation_type}",
    )
    simulation.audit_event_id = event.id
    simulation.save(update_fields=["audit_event_id", "updated_at"])
    return simulation


def reject_single_internal_live_gate_simulation(
    simulation_id: int,
    *,
    rejector=None,
    reason: str = "",
) -> RuntimeLiveGateSimulation:
    simulation = RuntimeLiveGateSimulation.objects.get(id=simulation_id)
    if simulation.live_execution_request_id is not None:
        request_row = reject_live_execution_request(
            simulation.live_execution_request_id,
            rejector,
            reason=reason,
        )
        simulation.approval_status = request_row.approval_status
        simulation.blockers = request_row.blockers
        simulation.gate_decision = request_row.gate_decision
    else:
        simulation.approval_status = (
            RuntimeLiveExecutionRequest.ApprovalStatus.REJECTED
        )
        simulation.blockers = list(simulation.blockers or []) + [
            "simulation_rejected"
        ]
    simulation.status = RuntimeLiveGateSimulation.Status.REJECTED
    simulation.rejected_by = rejector if _is_authenticated_user(rejector) else None
    simulation.rejected_at = timezone.now()
    simulation.warnings = list(simulation.warnings or []) + [PHASE_6I_WARNING]
    simulation.live_execution_allowed = False
    simulation.external_call_will_be_made = False
    simulation.external_call_was_made = False
    simulation.provider_call_attempted = False
    simulation.metadata = {
        **(simulation.metadata or {}),
        "rejectionReason": reason,
        "rejectedBy": _safe_identity(rejector),
    }
    simulation.save()
    event = _audit_simulation(
        kind="runtime.live_gate.simulation_rejected",
        simulation=simulation,
        user=rejector,
        text=f"Phase 6I simulation rejected for {simulation.operation_type}",
    )
    simulation.audit_event_id = event.id
    simulation.save(update_fields=["audit_event_id", "updated_at"])
    return simulation


def run_single_internal_live_gate_simulation(
    simulation_id: int,
    *,
    user=None,
    reason: str = "",
) -> RuntimeLiveGateSimulation:
    simulation = RuntimeLiveGateSimulation.objects.get(id=simulation_id)
    if (
        simulation.approval_status
        != RuntimeLiveExecutionRequest.ApprovalStatus.APPROVED
    ):
        simulation.status = RuntimeLiveGateSimulation.Status.BLOCKED
        simulation.blockers = list(simulation.blockers or []) + [
            "approval_required_before_simulation_run"
        ]
        simulation.warnings = list(simulation.warnings or []) + [
            PHASE_6I_WARNING
        ]
        simulation.simulation_result = {
            "passed": False,
            "reason": "approval_required_before_simulation_run",
            "externalCallWasMade": False,
            "providerCallAttempted": False,
        }
        simulation.live_execution_allowed = False
        simulation.external_call_will_be_made = False
        simulation.external_call_was_made = False
        simulation.provider_call_attempted = False
        simulation.run_by = user if _is_authenticated_user(user) else None
        simulation.run_at = timezone.now()
        simulation.save()
        event = _audit_simulation(
            kind="runtime.live_gate.simulation_blocked",
            simulation=simulation,
            user=user,
            text=f"Phase 6I simulation blocked for {simulation.operation_type}",
        )
        simulation.audit_event_id = event.id
        simulation.save(update_fields=["audit_event_id", "updated_at"])
        return simulation

    decision = evaluate_live_execution_gate(
        simulation.operation_type,
        organization=simulation.organization,
        branch=simulation.branch,
        user=user,
        payload={
            **(simulation.safe_payload_summary or {}),
            "idempotencyKey": simulation.idempotency_key,
        },
        live_requested=True,
        approval_status="approved",
    )
    _apply_decision(simulation, decision)
    simulation.status = RuntimeLiveGateSimulation.Status.SIMULATED
    simulation.approval_status = (
        RuntimeLiveExecutionRequest.ApprovalStatus.APPROVED
    )
    simulation.run_by = user if _is_authenticated_user(user) else None
    simulation.run_at = timezone.now()
    simulation.simulation_result = {
        "passed": True,
        "phase": "6I",
        "operationType": simulation.operation_type,
        "dryRun": True,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "externalCallWasMade": False,
        "providerCallAttempted": False,
        "businessMutationWasMade": False,
        "reason": reason,
    }
    simulation.metadata = {
        **(simulation.metadata or {}),
        "runReason": reason,
        "runBy": _safe_identity(user),
    }
    simulation.save()
    event = _audit_simulation(
        kind="runtime.live_gate.simulation_ran",
        simulation=simulation,
        user=user,
        text=f"Phase 6I simulation ran without provider calls for {simulation.operation_type}",
    )
    simulation.audit_event_id = event.id
    simulation.save(update_fields=["audit_event_id", "updated_at"])
    return simulation


def rollback_single_internal_live_gate_simulation(
    simulation_id: int,
    *,
    user=None,
    reason: str = "",
) -> RuntimeLiveGateSimulation:
    simulation = RuntimeLiveGateSimulation.objects.get(id=simulation_id)
    simulation.status = RuntimeLiveGateSimulation.Status.ROLLED_BACK
    simulation.rolled_back_by = user if _is_authenticated_user(user) else None
    simulation.rolled_back_at = timezone.now()
    simulation.live_execution_allowed = False
    simulation.external_call_will_be_made = False
    simulation.external_call_was_made = False
    simulation.provider_call_attempted = False
    simulation.simulation_result = {
        **(simulation.simulation_result or {}),
        "rolledBack": True,
        "rollbackReason": reason,
        "externalCallWasMade": False,
        "providerCallAttempted": False,
    }
    simulation.metadata = {
        **(simulation.metadata or {}),
        "rollbackReason": reason,
        "rolledBackBy": _safe_identity(user),
    }
    simulation.save()
    event = _audit_simulation(
        kind="runtime.live_gate.simulation_rolled_back",
        simulation=simulation,
        user=user,
        text=f"Phase 6I simulation rolled back for {simulation.operation_type}",
    )
    simulation.audit_event_id = event.id
    simulation.save(update_fields=["audit_event_id", "updated_at"])
    return simulation


def list_live_gate_simulations(limit: int = 50) -> dict[str, Any]:
    rows = list(RuntimeLiveGateSimulation.objects.order_by("-created_at")[:limit])
    return {
        "count": len(rows),
        "simulations": [serialize_live_gate_simulation(row) for row in rows],
        "allowedOperations": list(ALLOWED_SIMULATION_OPERATIONS),
        "defaultOperation": DEFAULT_SIMULATION_OPERATION,
        "dryRun": True,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "externalCallWasMade": False,
        "providerCallAttempted": False,
        "killSwitchActive": get_or_create_default_runtime_kill_switch().enabled,
    }


def inspect_single_internal_live_gate_simulation(
    *,
    organization: Optional[Organization] = None,
) -> dict[str, Any]:
    org, _branch = _resolve_org_branch(organization=organization)
    switch = get_or_create_default_runtime_kill_switch()
    qs = RuntimeLiveGateSimulation.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    latest = qs.order_by("-created_at").first()
    pending_count = qs.filter(
        approval_status=RuntimeLiveExecutionRequest.ApprovalStatus.PENDING
    ).count()
    approved_count = qs.filter(
        approval_status=RuntimeLiveExecutionRequest.ApprovalStatus.APPROVED
    ).count()
    simulated_count = qs.filter(
        status=RuntimeLiveGateSimulation.Status.SIMULATED
    ).count()
    blockers: list[str] = []
    if not switch.enabled:
        blockers.append("global_runtime_kill_switch_should_remain_enabled")
    safe_to_prepare = switch.enabled
    return {
        "organization": (
            {"id": org.id, "code": org.code, "name": org.name}
            if org is not None
            else None
        ),
        "allowedOperations": list(ALLOWED_SIMULATION_OPERATIONS),
        "defaultOperation": DEFAULT_SIMULATION_OPERATION,
        "simulationCount": qs.count(),
        "approvalPendingCount": pending_count,
        "approvedCount": approved_count,
        "simulatedCount": simulated_count,
        "latestSimulation": (
            serialize_live_gate_simulation(latest) if latest is not None else None
        ),
        "dryRun": True,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "externalCallWasMade": False,
        "providerCallAttempted": False,
        "killSwitchActive": switch.enabled,
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "safeToPreparePhase6ISimulation": safe_to_prepare,
        "safeToRunInternalSimulation": safe_to_prepare,
        "blockers": blockers,
        "warnings": [
            PHASE_6I_WARNING,
            "Default operation is razorpay.create_order but no Razorpay API call is made.",
            "WhatsApp and AI smoke-test operations are simulation-only.",
        ],
        "nextAction": (
            "prepare_single_internal_live_gate_simulation"
            if latest is None
            else _next_action(latest)
        ),
    }


__all__ = (
    "ALLOWED_SIMULATION_OPERATIONS",
    "DEFAULT_SIMULATION_OPERATION",
    "serialize_live_gate_simulation",
    "prepare_single_internal_live_gate_simulation",
    "request_single_internal_live_gate_approval",
    "approve_single_internal_live_gate_simulation",
    "reject_single_internal_live_gate_simulation",
    "run_single_internal_live_gate_simulation",
    "rollback_single_internal_live_gate_simulation",
    "list_live_gate_simulations",
    "inspect_single_internal_live_gate_simulation",
)
