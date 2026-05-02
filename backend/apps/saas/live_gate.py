"""Phase 6H controlled runtime live audit gate.

The service evaluates future live external side effects and records
operator approval state. Phase 6H never calls provider APIs and never
sets ``externalCallWillBeMade=True``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .context import (
    get_default_organization,
    get_user_active_branch,
    get_user_active_organization,
    resolve_request_branch,
    resolve_request_organization,
)
from .live_gate_policy import (
    POLICY_VERSION,
    LiveGateOperationPolicy,
    get_live_gate_policy,
    list_live_gate_policies,
)
from .models import (
    Branch,
    Organization,
    RuntimeKillSwitch,
    RuntimeLiveExecutionRequest,
    RuntimeLiveGatePolicySnapshot,
)


_SECRET_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "client_secret",
    "salt",
)
_PHONE_RE = re.compile(r"(\+?91[\s-]?)?([6-9]\d{9})")


class RuntimeLiveGateBlocked(RuntimeError):
    """Raised by ``assert_live_execution_allowed_or_block``."""


def _is_authenticated_user(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def _serialize_org(org: Optional[Organization]) -> dict[str, Any] | None:
    if org is None:
        return None
    return {"id": org.id, "code": org.code, "name": org.name}


def _serialize_branch(branch: Optional[Branch]) -> dict[str, Any] | None:
    if branch is None:
        return None
    return {"id": branch.id, "code": branch.code, "name": branch.name}


def _env_present(key: str) -> bool:
    return bool(os.environ.get(key) or getattr(settings, key, ""))


def _mask_phone_text(value: str) -> str:
    def repl(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        suffix = digits[-4:]
        return f"+91******{suffix}"

    return _PHONE_RE.sub(repl, value)


def _safe_summary(value: Any, *, key_name: str = "") -> Any:
    key_l = key_name.lower()
    if any(part in key_l for part in _SECRET_KEY_PARTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(key): _safe_summary(nested, key_name=str(key))
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_safe_summary(item, key_name=key_name) for item in value[:20]]
    if isinstance(value, tuple):
        return [_safe_summary(item, key_name=key_name) for item in value[:20]]
    if isinstance(value, str):
        if any(prefix in value for prefix in ("sk-", "ENV:", "VAULT:")):
            if value.startswith(("ENV:", "VAULT:")):
                scheme = value.split(":", 1)[0]
                return f"{scheme}:***"
            return "[redacted]"
        masked = _mask_phone_text(value)
        return masked[:240] + ("..." if len(masked) > 240 else "")
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:120]


def _hash_payload(payload: Optional[dict[str, Any]]) -> str:
    if not payload:
        return ""
    canonical = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(canonical).hexdigest()


def _resolve_org_branch(
    *,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    request=None,
    user=None,
) -> tuple[Optional[Organization], Optional[Branch]]:
    org = organization
    if org is None and request is not None:
        org = resolve_request_organization(request)
    if org is None and _is_authenticated_user(user):
        org = get_user_active_organization(user)
    if org is None:
        org = get_default_organization()

    resolved_branch = branch
    if resolved_branch is None and request is not None:
        resolved_branch = resolve_request_branch(request, organization=org)
    if resolved_branch is None and _is_authenticated_user(user):
        resolved_branch = get_user_active_branch(user, organization=org)
    return org, resolved_branch


def get_or_create_default_runtime_kill_switch() -> RuntimeKillSwitch:
    switch, _created = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        organization=None,
        provider_type="",
        operation_type="",
        defaults={
            "enabled": True,
            "reason": "Phase 6H default global live execution block.",
        },
    )
    return switch


def is_runtime_kill_switch_active(
    org: Optional[Organization] = None,
    provider_type: Optional[str] = None,
    operation_type: Optional[str] = None,
) -> bool:
    get_or_create_default_runtime_kill_switch()
    qs = RuntimeKillSwitch.objects.filter(enabled=True)
    candidates = [
        {"scope": RuntimeKillSwitch.Scope.GLOBAL},
    ]
    if org is not None:
        candidates.append(
            {"scope": RuntimeKillSwitch.Scope.ORGANIZATION, "organization": org}
        )
    if provider_type:
        candidates.append(
            {
                "scope": RuntimeKillSwitch.Scope.PROVIDER,
                "provider_type": provider_type,
            }
        )
    if operation_type:
        candidates.append(
            {
                "scope": RuntimeKillSwitch.Scope.OPERATION,
                "operation_type": operation_type,
            }
        )
    return any(qs.filter(**candidate).exists() for candidate in candidates)


def _kill_switch_snapshot(
    org: Optional[Organization],
    provider_type: str,
    operation_type: str,
) -> dict[str, Any]:
    global_switch = get_or_create_default_runtime_kill_switch()
    org_enabled = (
        RuntimeKillSwitch.objects.filter(
            enabled=True,
            scope=RuntimeKillSwitch.Scope.ORGANIZATION,
            organization=org,
        ).exists()
        if org is not None
        else False
    )
    provider_enabled = RuntimeKillSwitch.objects.filter(
        enabled=True,
        scope=RuntimeKillSwitch.Scope.PROVIDER,
        provider_type=provider_type,
    ).exists()
    operation_enabled = RuntimeKillSwitch.objects.filter(
        enabled=True,
        scope=RuntimeKillSwitch.Scope.OPERATION,
        operation_type=operation_type,
    ).exists()
    active = bool(
        global_switch.enabled
        or org_enabled
        or provider_enabled
        or operation_enabled
    )
    active_blockers = []
    if global_switch.enabled:
        active_blockers.append("global")
    if org_enabled:
        active_blockers.append("organization")
    if provider_enabled:
        active_blockers.append("provider")
    if operation_enabled:
        active_blockers.append("operation")
    return {
        "globalEnabled": bool(global_switch.enabled),
        "orgEnabled": org_enabled,
        "providerEnabled": provider_enabled,
        "operationEnabled": operation_enabled,
        "active": active,
        "activeBlockers": active_blockers,
    }


def build_live_gate_context(
    operation_type: str,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    request=None,
    user=None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    org, resolved_branch = _resolve_org_branch(
        organization=organization,
        branch=branch,
        request=request,
        user=user,
    )
    safe_payload = _safe_summary(payload or {})
    return {
        "operationType": operation_type,
        "organization": _serialize_org(org),
        "branch": _serialize_branch(resolved_branch),
        "payloadHash": _hash_payload(payload),
        "safePayloadSummary": safe_payload,
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "dryRun": True,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
    }


def _provider_env_blockers(policy: LiveGateOperationPolicy) -> list[str]:
    missing = [key for key in policy.required_env_keys if not _env_present(key)]
    if not missing:
        return []
    return [
        "missing_provider_env:"
        + ",".join(missing)
        + " (presence only; values never exposed)"
    ]


def _requirement_blockers(
    policy: LiveGateOperationPolicy,
    payload: dict[str, Any],
    *,
    approval_status: str = "",
) -> list[str]:
    blockers: list[str] = []
    if policy.provider_deferred:
        blockers.append(f"provider_deferred:{policy.provider_type}")
    blockers.extend(_provider_env_blockers(policy))
    if policy.idempotency_required and not (
        payload.get("idempotencyKey") or payload.get("idempotency_key")
    ):
        blockers.append("idempotency_key_required")
    if policy.consent_required and not payload.get("consentVerified"):
        blockers.append("consent_verified_required")
    if policy.claim_vault_required and not payload.get("claimVaultValidated"):
        blockers.append("claim_vault_validation_required")
    if policy.caio_review_required and not payload.get("caioReviewed"):
        blockers.append("caio_review_required")
    if policy.webhook_required and not payload.get("webhookConfigured"):
        blockers.append("webhook_required")
    if policy.template_approval_required and not payload.get(
        "templateApproved"
    ):
        blockers.append("template_approval_required")
    if policy.payment_approval_required and not payload.get(
        "paymentApprovalRecorded"
    ):
        blockers.append("payment_approval_required")
    if policy.customer_intent_required and not payload.get(
        "customerIntentConfirmed"
    ):
        blockers.append("customer_intent_required")
    if policy.address_validation_required and not payload.get(
        "addressValidated"
    ):
        blockers.append("address_validation_required")
    if policy.human_approval_required and approval_status != "approved":
        blockers.append("human_approval_required")
    return blockers


def _decision_for_blockers(
    policy: LiveGateOperationPolicy,
    blockers: list[str],
    *,
    kill_switch_active: bool,
    approval_status: str,
    live_requested: bool,
) -> str:
    if not live_requested:
        return RuntimeLiveExecutionRequest.GateDecision.DRY_RUN_ALLOWED
    if approval_status == "approved" and not kill_switch_active and not blockers:
        return RuntimeLiveExecutionRequest.GateDecision.LIVE_READY_BUT_NOT_EXECUTED
    if not policy.live_allowed_by_default or not policy.allowed_in_phase_6h:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_BY_DEFAULT
    if kill_switch_active:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_BY_KILL_SWITCH
    joined = " ".join(blockers)
    if "approval" in joined or "human_approval" in joined:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_MISSING_APPROVAL
    if "consent" in joined:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_MISSING_CONSENT
    if "caio" in joined:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_MISSING_CAIO_REVIEW
    if "claim_vault" in joined:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_MISSING_CLAIM_VAULT
    if "webhook" in joined:
        return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_MISSING_WEBHOOK
    return RuntimeLiveExecutionRequest.GateDecision.BLOCKED_MISSING_PROVIDER_CONFIG


def evaluate_live_execution_gate(
    operation_type: str,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    request=None,
    user=None,
    payload: Optional[dict[str, Any]] = None,
    live_requested: bool = False,
    approval_status: str = "",
    audit_preview: bool = False,
) -> dict[str, Any]:
    org, resolved_branch = _resolve_org_branch(
        organization=organization,
        branch=branch,
        request=request,
        user=user,
    )
    policy = get_live_gate_policy(operation_type)
    safe_payload = _safe_summary(payload or {})
    payload_hash = _hash_payload(payload)
    if policy is None:
        decision = {
            "operationType": operation_type,
            "providerType": "",
            "valid": False,
            "runtimeSource": "env_config",
            "perOrgRuntimeEnabled": False,
            "dryRun": True,
            "liveExecutionRequested": live_requested,
            "liveExecutionAllowed": False,
            "externalCallWillBeMade": False,
            "approvalRequired": True,
            "approvalStatus": approval_status or "blocked",
            "killSwitchActive": True,
            "gateDecision": RuntimeLiveExecutionRequest.GateDecision.BLOCKED_BY_DEFAULT,
            "blockers": [f"Unknown live gate operation: {operation_type}"],
            "warnings": [],
            "payloadHash": payload_hash,
            "safePayloadSummary": safe_payload,
            "organization": _serialize_org(org),
            "branch": _serialize_branch(resolved_branch),
            "nextAction": "fix_live_gate_operation_lookup",
        }
        return decision

    kill_switch = _kill_switch_snapshot(
        org, policy.provider_type, policy.operation_type
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if live_requested:
        if kill_switch["active"]:
            blockers.append(
                "runtime_kill_switch_active:"
                + ",".join(kill_switch["activeBlockers"])
            )
        if not policy.live_allowed_by_default:
            blockers.append("live_allowed_by_default_false")
        if not policy.allowed_in_phase_6h:
            blockers.append("phase_6h_live_execution_disabled")
        if policy.approval_required and approval_status != "approved":
            blockers.append("approval_required")
        blockers.extend(
            _requirement_blockers(
                policy, payload or {}, approval_status=approval_status
            )
        )
    else:
        warnings.append("dry_run_preview_only")

    gate_decision = _decision_for_blockers(
        policy,
        blockers,
        kill_switch_active=kill_switch["active"],
        approval_status=approval_status,
        live_requested=live_requested,
    )
    next_action = (
        "dry_run_preview_only"
        if not live_requested
        else "keep_live_execution_blocked"
        if gate_decision != RuntimeLiveExecutionRequest.GateDecision.LIVE_READY_BUT_NOT_EXECUTED
        else "ready_for_phase_6i_single_internal_live_gate_simulation"
    )
    decision = {
        "operationType": policy.operation_type,
        "providerType": policy.provider_type,
        "valid": True,
        "policy": policy.to_dict(),
        "organization": _serialize_org(org),
        "branch": _serialize_branch(resolved_branch),
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "dryRun": True,
        "liveExecutionRequested": live_requested,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "approvalRequired": policy.approval_required,
        "approvalStatus": approval_status
        or (
            "pending"
            if live_requested and policy.approval_required
            else "not_required"
        ),
        "killSwitchActive": kill_switch["active"],
        "killSwitch": kill_switch,
        "riskLevel": policy.risk_level,
        "payloadHash": payload_hash,
        "safePayloadSummary": safe_payload,
        "blockers": blockers,
        "warnings": warnings,
        "gateDecision": gate_decision,
        "nextAction": next_action,
    }
    if audit_preview:
        _write_live_gate_audit(
            kind="runtime.live_gate.previewed",
            decision=decision,
            organization=org,
            user=user,
        )
    return decision


def _create_policy_snapshot(
    policy: LiveGateOperationPolicy,
    org: Optional[Organization],
    branch: Optional[Branch],
) -> RuntimeLiveGatePolicySnapshot:
    return RuntimeLiveGatePolicySnapshot.objects.create(
        organization=org,
        branch=branch,
        operation_type=policy.operation_type,
        provider_type=policy.provider_type,
        risk_level=policy.risk_level,
        live_allowed_by_default=policy.live_allowed_by_default,
        approval_required=policy.approval_required,
        caio_review_required=policy.caio_review_required,
        consent_required=policy.consent_required,
        claim_vault_required=policy.claim_vault_required,
        webhook_required=policy.webhook_required,
        idempotency_required=policy.idempotency_required,
        kill_switch_can_block=policy.kill_switch_can_block,
        policy_version=POLICY_VERSION,
        metadata=policy.to_dict(),
    )


def _write_live_gate_audit(
    *,
    kind: str,
    decision: dict[str, Any],
    organization: Optional[Organization],
    user=None,
    text: str = "",
) -> AuditEvent:
    payload = {
        "organization": decision.get("organization"),
        "operation_type": decision.get("operationType"),
        "provider_type": decision.get("providerType"),
        "dry_run": decision.get("dryRun"),
        "live_execution_requested": decision.get(
            "liveExecutionRequested"
        ),
        "live_execution_allowed": decision.get("liveExecutionAllowed"),
        "external_call_will_be_made": decision.get(
            "externalCallWillBeMade"
        ),
        "gate_decision": decision.get("gateDecision"),
        "approval_status": decision.get("approvalStatus"),
        "blockers": decision.get("blockers", []),
        "warnings": decision.get("warnings", []),
        "payload_hash": decision.get("payloadHash", ""),
        "safe_payload_summary": decision.get("safePayloadSummary", {}),
    }
    return write_event(
        kind=kind,
        text=text
        or f"Runtime live gate {kind.rsplit('.', 1)[-1]} for {decision.get('operationType')}",
        tone=(
            AuditEvent.Tone.WARNING
            if "blocked" in str(decision.get("gateDecision", ""))
            or "rejected" in kind
            else AuditEvent.Tone.INFO
        ),
        payload=payload,
        organization=organization,
        user=user if _is_authenticated_user(user) else None,
    )


def _serialize_request(row: RuntimeLiveExecutionRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization": _serialize_org(row.organization),
        "branch": _serialize_branch(row.branch),
        "operationType": row.operation_type,
        "providerType": row.provider_type,
        "runtimeSource": row.runtime_source,
        "perOrgRuntimeEnabled": row.per_org_runtime_enabled,
        "dryRun": row.dry_run,
        "liveExecutionRequested": row.live_execution_requested,
        "liveExecutionAllowed": row.live_execution_allowed,
        "externalCallWillBeMade": row.external_call_will_be_made,
        "approvalRequired": row.approval_required,
        "approvalStatus": row.approval_status,
        "requestedBy": row.requested_by_id,
        "approvedBy": row.approved_by_id,
        "rejectedBy": row.rejected_by_id,
        "requestedAt": row.requested_at.isoformat()
        if row.requested_at
        else None,
        "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
        "rejectedAt": row.rejected_at.isoformat() if row.rejected_at else None,
        "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
        "riskLevel": row.risk_level,
        "payloadHash": row.payload_hash,
        "safePayloadSummary": row.safe_payload_summary,
        "blockers": row.blockers,
        "warnings": row.warnings,
        "gateDecision": row.gate_decision,
        "idempotencyKey": row.idempotency_key,
        "auditEventId": row.audit_event_id,
        "metadata": row.metadata,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "killSwitchActive": is_runtime_kill_switch_active(
            row.organization, row.provider_type, row.operation_type
        ),
        "nextAction": (
            "keep_live_execution_blocked"
            if row.gate_decision
            != RuntimeLiveExecutionRequest.GateDecision.LIVE_READY_BUT_NOT_EXECUTED
            else "ready_for_phase_6i_single_internal_live_gate_simulation"
        ),
    }


def create_live_execution_request(
    operation_type: str,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    request=None,
    user=None,
    payload: Optional[dict[str, Any]] = None,
    live_requested: bool = True,
) -> RuntimeLiveExecutionRequest:
    org, resolved_branch = _resolve_org_branch(
        organization=organization,
        branch=branch,
        request=request,
        user=user,
    )
    policy = get_live_gate_policy(operation_type)
    decision = evaluate_live_execution_gate(
        operation_type,
        organization=org,
        branch=resolved_branch,
        request=request,
        user=user,
        payload=payload,
        live_requested=live_requested,
        approval_status="pending",
    )
    if policy is not None:
        _create_policy_snapshot(policy, org, resolved_branch)
    status = (
        RuntimeLiveExecutionRequest.ApprovalStatus.PENDING
        if live_requested
        else RuntimeLiveExecutionRequest.ApprovalStatus.NOT_REQUIRED
    )
    row = RuntimeLiveExecutionRequest.objects.create(
        organization=org,
        branch=resolved_branch,
        operation_type=operation_type,
        provider_type=decision.get("providerType", ""),
        runtime_source="env_config",
        per_org_runtime_enabled=False,
        dry_run=True,
        live_execution_requested=live_requested,
        live_execution_allowed=False,
        external_call_will_be_made=False,
        approval_required=decision.get("approvalRequired", True),
        approval_status=status,
        requested_by=user if _is_authenticated_user(user) else None,
        requested_at=timezone.now(),
        risk_level=decision.get("riskLevel", "high"),
        payload_hash=decision.get("payloadHash", ""),
        safe_payload_summary=decision.get("safePayloadSummary", {}),
        blockers=decision.get("blockers", []),
        warnings=decision.get("warnings", []),
        gate_decision=decision.get(
            "gateDecision",
            RuntimeLiveExecutionRequest.GateDecision.BLOCKED_BY_DEFAULT,
        ),
        idempotency_key=str(
            (payload or {}).get("idempotencyKey")
            or (payload or {}).get("idempotency_key")
            or ""
        ),
        metadata={"phase": "6H", "no_provider_call": True},
    )
    event = _write_live_gate_audit(
        kind="runtime.live_gate.request_created",
        decision=decision,
        organization=org,
        user=user,
        text=f"Runtime live execution request created for {operation_type}",
    )
    row.audit_event_id = event.id
    row.save(update_fields=["audit_event_id", "updated_at"])
    return row


def approve_live_execution_request(
    request_id: int,
    approver,
    reason: Optional[str] = None,
) -> RuntimeLiveExecutionRequest:
    row = RuntimeLiveExecutionRequest.objects.get(id=request_id)
    row.approval_status = RuntimeLiveExecutionRequest.ApprovalStatus.APPROVED
    row.approved_by = approver if _is_authenticated_user(approver) else None
    row.approved_at = timezone.now()
    decision = evaluate_live_execution_gate(
        row.operation_type,
        organization=row.organization,
        branch=row.branch,
        user=approver,
        payload={
            **(row.safe_payload_summary or {}),
            "idempotencyKey": row.idempotency_key,
        },
        live_requested=row.live_execution_requested,
        approval_status="approved",
    )
    row.blockers = decision["blockers"]
    row.warnings = decision["warnings"] + [
        "Approving in Phase 6H does not execute external calls."
    ]
    row.gate_decision = decision["gateDecision"]
    row.live_execution_allowed = False
    row.external_call_will_be_made = False
    row.metadata = {
        **(row.metadata or {}),
        "approval_reason": reason or "",
        "phase6h_no_execution": True,
    }
    row.save()
    event = _write_live_gate_audit(
        kind="runtime.live_gate.request_approved",
        decision=decision,
        organization=row.organization,
        user=approver,
        text=f"Runtime live execution request approved for {row.operation_type}",
    )
    row.audit_event_id = event.id
    row.save(update_fields=["audit_event_id", "updated_at"])
    if (
        row.gate_decision
        == RuntimeLiveExecutionRequest.GateDecision.LIVE_READY_BUT_NOT_EXECUTED
    ):
        _write_live_gate_audit(
            kind="runtime.live_gate.ready_but_not_executed",
            decision=decision,
            organization=row.organization,
            user=approver,
            text=f"Runtime live gate ready but not executed for {row.operation_type}",
        )
    return row


def reject_live_execution_request(
    request_id: int,
    rejector,
    reason: Optional[str] = None,
) -> RuntimeLiveExecutionRequest:
    row = RuntimeLiveExecutionRequest.objects.get(id=request_id)
    row.approval_status = RuntimeLiveExecutionRequest.ApprovalStatus.REJECTED
    row.rejected_by = rejector if _is_authenticated_user(rejector) else None
    row.rejected_at = timezone.now()
    row.live_execution_allowed = False
    row.external_call_will_be_made = False
    row.blockers = list(row.blockers or []) + ["request_rejected"]
    row.metadata = {
        **(row.metadata or {}),
        "rejection_reason": reason or "",
        "phase6h_no_execution": True,
    }
    row.save()
    decision = _serialize_request(row)
    event = _write_live_gate_audit(
        kind="runtime.live_gate.request_rejected",
        decision=decision,
        organization=row.organization,
        user=rejector,
        text=f"Runtime live execution request rejected for {row.operation_type}",
    )
    row.audit_event_id = event.id
    row.save(update_fields=["audit_event_id", "updated_at"])
    return row


def summarize_live_gate_readiness(
    org: Optional[Organization] = None,
) -> dict[str, Any]:
    resolved_org = org or get_default_organization()
    get_or_create_default_runtime_kill_switch()
    policies = []
    blockers: list[str] = []
    warnings: list[str] = [
        "Default live execution remains blocked in Phase 6H.",
        "Approving in Phase 6H does not execute external calls.",
        "PayU deferred.",
        "Delhivery deferred.",
        "Vapi missing phone_number_id/webhook_secret until env is configured.",
        "WhatsApp auto-reply OFF; campaigns/broadcast locked.",
        "AI customer send requires Claim Vault + CAIO + approval.",
    ]
    for policy in list_live_gate_policies():
        decision = evaluate_live_execution_gate(
            policy.operation_type,
            organization=resolved_org,
            payload={},
            live_requested=True,
            approval_status="pending",
        )
        policies.append(
            {
                **policy.to_dict(),
                "currentGateDecision": decision["gateDecision"],
                "liveAllowedNow": False,
                "blockers": decision["blockers"],
                "warnings": decision["warnings"],
                "nextAction": decision["nextAction"],
            }
        )
    counts = {
        "approvalPendingCount": RuntimeLiveExecutionRequest.objects.filter(
            approval_status=RuntimeLiveExecutionRequest.ApprovalStatus.PENDING
        ).count(),
        "approvedButNotExecutedCount": RuntimeLiveExecutionRequest.objects.filter(
            approval_status=RuntimeLiveExecutionRequest.ApprovalStatus.APPROVED,
            external_call_will_be_made=False,
        ).count(),
        "blockedCount": RuntimeLiveExecutionRequest.objects.filter(
            gate_decision__startswith="blocked"
        ).count(),
        "rejectedCount": RuntimeLiveExecutionRequest.objects.filter(
            approval_status=RuntimeLiveExecutionRequest.ApprovalStatus.REJECTED
        ).count(),
    }
    recent_requests = [
        _serialize_request(row)
        for row in RuntimeLiveExecutionRequest.objects.order_by("-created_at")[
            :10
        ]
    ]
    audit_events = AuditEvent.objects.filter(
        kind__startswith="runtime."
    ).order_by("-occurred_at")[:12]
    recent_audit = [
        {
            "id": event.id,
            "kind": event.kind,
            "operationType": event.payload.get("operation_type", ""),
            "providerType": event.payload.get("provider_type", ""),
            "gateDecision": event.payload.get("gate_decision", ""),
            "actor": "",
            "createdAt": event.occurred_at.isoformat(),
            "text": event.text,
        }
        for event in audit_events
    ]
    kill_switch = _kill_switch_snapshot(resolved_org, "", "")
    safe_to_start_6i = bool(kill_switch["globalEnabled"]) and not blockers
    return {
        "organization": _serialize_org(resolved_org),
        "killSwitch": kill_switch,
        "operationPolicies": policies,
        "recentLiveExecutionRequests": recent_requests,
        "approvalQueue": counts,
        **counts,
        "recentGateAuditEvents": recent_audit,
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "runtimeUsesPerOrgSettings": False,
        "defaultDryRun": True,
        "defaultLiveExecutionAllowed": False,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "safeToStartPhase6I": safe_to_start_6i,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": (
            "ready_for_phase_6i_single_internal_live_gate_simulation"
            if safe_to_start_6i
            else "keep_live_execution_blocked"
        ),
    }


def assert_live_execution_allowed_or_block(
    operation_type: str,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    request=None,
    user=None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    decision = evaluate_live_execution_gate(
        operation_type,
        organization=organization,
        branch=branch,
        request=request,
        user=user,
        payload=payload,
        live_requested=True,
    )
    if not decision.get("liveExecutionAllowed"):
        raise RuntimeLiveGateBlocked(json.dumps(decision, default=str))
    return decision


def set_runtime_kill_switch(
    *,
    enabled: bool,
    scope: str = RuntimeKillSwitch.Scope.GLOBAL,
    reason: str = "",
    organization: Optional[Organization] = None,
    provider_type: str = "",
    operation_type: str = "",
    user=None,
) -> RuntimeKillSwitch:
    switch, _created = RuntimeKillSwitch.objects.get_or_create(
        scope=scope,
        organization=organization,
        provider_type=provider_type or "",
        operation_type=operation_type or "",
        defaults={"enabled": enabled, "reason": reason},
    )
    switch.enabled = enabled
    switch.reason = reason
    switch.changed_by = user if _is_authenticated_user(user) else None
    switch.save()
    decision = {
        "operationType": operation_type,
        "providerType": provider_type,
        "organization": _serialize_org(organization),
        "dryRun": True,
        "liveExecutionRequested": False,
        "liveExecutionAllowed": False,
        "externalCallWillBeMade": False,
        "gateDecision": (
            "blocked_by_kill_switch" if enabled else "kill_switch_disabled"
        ),
        "approvalStatus": "",
        "blockers": ["runtime_kill_switch_active"] if enabled else [],
        "warnings": ["Phase 6H still does not execute external calls."],
        "payloadHash": "",
        "safePayloadSummary": {"scope": scope, "reason": reason},
    }
    _write_live_gate_audit(
        kind=(
            "runtime.kill_switch.enabled"
            if enabled
            else "runtime.kill_switch.disabled"
        ),
        decision=decision,
        organization=organization,
        user=user,
        text=f"Runtime kill switch {'enabled' if enabled else 'disabled'} for {scope}",
    )
    return switch


__all__ = (
    "RuntimeLiveGateBlocked",
    "get_or_create_default_runtime_kill_switch",
    "is_runtime_kill_switch_active",
    "build_live_gate_context",
    "evaluate_live_execution_gate",
    "create_live_execution_request",
    "approve_live_execution_request",
    "reject_live_execution_request",
    "summarize_live_gate_readiness",
    "assert_live_execution_allowed_or_block",
    "set_runtime_kill_switch",
    "_serialize_request",
)
