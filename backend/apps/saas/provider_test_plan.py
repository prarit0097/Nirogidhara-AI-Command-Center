"""Phase 6J — Single Internal Provider Test Plan service.

Plan-only service. Builds, validates, approves, rejects, archives,
and inspects :class:`RuntimeProviderTestPlan` rows. Phase 6J never
calls the provider, never mutates business records, and never
returns raw secrets.

Recommended target operation: ``razorpay.create_order`` in test mode
with a synthetic ₹1.00 (100 paise) payload. The plan is approved
"for future execution" only — actual execution is deferred to
**Phase 6K Single Internal Razorpay Test-Mode Execution Gate**.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional
from uuid import uuid4

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .context import get_default_organization
from .integration_runtime import (
    get_secret_ref_status,
)
from .live_gate import (
    get_or_create_default_runtime_kill_switch,
)
from .live_gate_policy import get_live_gate_policy
from .models import (
    Branch,
    Organization,
    RuntimeProviderTestPlan,
)
from .provider_test_plan_policy import (
    PHASE_6J_IMPLEMENTATION_TARGETS,
    POLICY_VERSION,
    ProviderTestPlanPolicy,
    get_provider_test_plan_policy,
    is_phase_6j_implementation_target,
    list_provider_test_plan_policies,
)


PHASE_6J_WARNING = (
    "Phase 6J never calls a provider, never mutates business records, "
    "and never exposes raw secrets."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_authenticated_user(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def _safe_identity(user) -> Optional[int]:
    return user.id if _is_authenticated_user(user) else None


def _resolve_org_branch(
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


def _new_plan_id() -> str:
    return f"ptp_{uuid4().hex[:24]}"


def _safe_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _env_present(key: str) -> bool:
    return bool(os.environ.get(key))


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------


def get_provider_test_plan_policy_payload(operation_type: str) -> dict[str, Any]:
    policy = get_provider_test_plan_policy(operation_type)
    if policy is None:
        return {
            "operationType": operation_type,
            "valid": False,
            "policyVersion": POLICY_VERSION,
            "blockers": [
                f"No provider test plan policy for: {operation_type}"
            ],
            "warnings": [],
            "nextAction": "fix_provider_test_plan_operation_lookup",
        }
    return {
        "valid": True,
        **policy.to_dict(),
        "phase6jImplementationTargets": list(
            PHASE_6J_IMPLEMENTATION_TARGETS
        ),
    }


# ---------------------------------------------------------------------------
# Synthetic payload + env readiness
# ---------------------------------------------------------------------------


def build_safe_synthetic_provider_payload(
    operation_type: str,
    organization: Optional[Organization] = None,
    plan_id: str = "",
) -> dict[str, Any]:
    """Construct a non-customer synthetic payload summary for the plan.

    NEVER includes real customer PII. NEVER includes raw secrets.
    """
    policy = get_provider_test_plan_policy(operation_type)
    suffix = (plan_id or "pending")
    if operation_type == "razorpay.create_order":
        amount = (
            policy.max_test_amount_paise if policy is not None else 100
        )
        return {
            "operationType": operation_type,
            "amount": amount,
            "currency": "INR",
            "receipt": f"phase6j_internal_test_plan_{suffix}",
            "notes": {
                "purpose": "internal_test_plan_only",
                "external_call": False,
                "real_customer_data": False,
                "phase": "6J",
            },
        }
    return {
        "operationType": operation_type,
        "purpose": "internal_test_plan_only",
        "external_call": False,
        "real_customer_data": False,
        "phase": "6J",
    }


def inspect_provider_env_readiness(provider_type: str) -> dict[str, Any]:
    """Return env-key + secret-ref readiness for the given provider.

    Reports presence (booleans only). Never returns env values.
    """
    if provider_type == "razorpay":
        env_status = {
            "RAZORPAY_KEY_ID": _env_present("RAZORPAY_KEY_ID"),
            "RAZORPAY_KEY_SECRET": _env_present("RAZORPAY_KEY_SECRET"),
            "RAZORPAY_WEBHOOK_SECRET": _env_present(
                "RAZORPAY_WEBHOOK_SECRET"
            ),
        }
        ref_status = {
            "key_id": get_secret_ref_status("ENV:RAZORPAY_KEY_ID"),
            "key_secret": get_secret_ref_status(
                "ENV:RAZORPAY_KEY_SECRET"
            ),
            "webhook_secret": get_secret_ref_status(
                "ENV:RAZORPAY_WEBHOOK_SECRET"
            ),
        }
        masked_refs = {
            key: value.get("maskedRef", "")
            for key, value in ref_status.items()
        }
        return {
            "providerType": provider_type,
            "envPresence": env_status,
            "secretRefStatus": ref_status,
            "maskedSecretRefs": masked_refs,
            "envReady": (
                env_status["RAZORPAY_KEY_ID"]
                and env_status["RAZORPAY_KEY_SECRET"]
            ),
            "webhookReady": env_status["RAZORPAY_WEBHOOK_SECRET"],
        }
    return {
        "providerType": provider_type,
        "envPresence": {},
        "secretRefStatus": {},
        "maskedSecretRefs": {},
        "envReady": False,
        "webhookReady": False,
    }


# ---------------------------------------------------------------------------
# Plan composition
# ---------------------------------------------------------------------------


def _gate_requirements_for(policy: ProviderTestPlanPolicy) -> dict[str, Any]:
    live_gate = get_live_gate_policy(policy.operation_type)
    return {
        "liveGateRequired": policy.live_gate_required,
        "killSwitchMustRemainEnabled": policy.kill_switch_must_remain_enabled,
        "approvalRequired": policy.approval_required,
        "idempotencyRequired": policy.idempotency_required,
        "webhookRequiredForFutureExecution": (
            policy.webhook_required_for_future_execution
        ),
        "providerCallAllowedInPhase6J": policy.provider_call_allowed,
        "externalProviderCallAllowedInPhase6J": (
            policy.external_provider_call_allowed_in_phase_6j
        ),
        "liveGatePolicyAttached": live_gate is not None,
        "liveGatePolicyVersion": (
            live_gate.metadata.get("policyVersion")
            if live_gate is not None
            else None
        ),
    }


def _approval_requirements_for(
    policy: ProviderTestPlanPolicy,
) -> dict[str, Any]:
    return {
        "approvalRequired": policy.approval_required,
        "approverRoles": ["admin", "director", "superuser"],
        "rejectionAllowed": True,
        "archiveAllowed": True,
        "approvalUnlocksLiveExecutionInPhase6J": False,
        "approvalUnlocksFutureExecutionInPhase6K": True,
    }


def _rollback_plan_for(
    policy: ProviderTestPlanPolicy,
    plan_id: str,
) -> dict[str, Any]:
    return {
        "rollbackRequired": policy.rollback_required,
        "noExternalRollbackInPhase6J": True,
        "rollbackSteps": [
            "Phase 6J never calls the provider — no provider-side "
            "state to rollback.",
            f"Archive plan {plan_id} via "
            "archive_single_provider_test_plan command or API.",
            "Audit trail is preserved in AuditEvent rows.",
        ],
        "executionPhaseRollback": (
            "Phase 6K execution gate will own provider-side rollback "
            "(refund / cancel order / void link) when it ships."
        ),
    }


def _abort_criteria_for(
    policy: ProviderTestPlanPolicy,
) -> list[str]:
    return [
        "any_raw_secret_exposure",
        "provider_call_attempted_true",
        "external_call_will_be_made_true",
        "live_execution_allowed_true",
        "real_customer_data_allowed_true",
        f"amount_paise_exceeds_max_{policy.max_test_amount_paise}",
        "missing_idempotency_key",
        "kill_switch_disabled_unexpectedly",
        "real_money_true",
    ]


def _verification_checklist_for(
    policy: ProviderTestPlanPolicy,
) -> list[dict[str, Any]]:
    return [
        {"key": "dryRun", "expected": True},
        {"key": "providerCallAllowed", "expected": False},
        {"key": "externalCallWillBeMade", "expected": False},
        {"key": "externalCallWasMade", "expected": False},
        {"key": "providerCallAttempted", "expected": False},
        {"key": "realMoney", "expected": False},
        {"key": "realCustomerDataAllowed", "expected": False},
        {"key": "amountPaiseAtMost", "expected": policy.max_test_amount_paise},
        {"key": "idempotencyKeyPresent", "expected": True},
        {"key": "payloadHashPresent", "expected": True},
        {"key": "killSwitchActive", "expected": True},
    ]


def _serialize_plan(plan: RuntimeProviderTestPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "planId": plan.plan_id,
        "organization": (
            {
                "id": plan.organization_id,
                "code": plan.organization.code,
                "name": plan.organization.name,
            }
            if plan.organization_id and plan.organization
            else None
        ),
        "branch": (
            {
                "id": plan.branch_id,
                "code": plan.branch.code,
                "name": plan.branch.name,
            }
            if plan.branch_id and plan.branch
            else None
        ),
        "providerType": plan.provider_type,
        "operationType": plan.operation_type,
        "providerEnvironment": plan.provider_environment,
        "status": plan.status,
        "runtimeSource": plan.runtime_source,
        "perOrgRuntimeEnabled": plan.per_org_runtime_enabled,
        "dryRun": plan.dry_run,
        "providerCallAllowed": plan.provider_call_allowed,
        "externalCallWillBeMade": plan.external_call_will_be_made,
        "externalCallWasMade": plan.external_call_was_made,
        "providerCallAttempted": plan.provider_call_attempted,
        "realCustomerDataAllowed": plan.real_customer_data_allowed,
        "realMoney": plan.real_money,
        "amountPaise": plan.amount_paise,
        "currency": plan.currency,
        "idempotencyKey": plan.idempotency_key,
        "payloadHash": plan.payload_hash,
        "safePayloadSummary": plan.safe_payload_summary,
        "envReadiness": plan.env_readiness,
        "secretRefReadiness": plan.secret_ref_readiness,
        "gateRequirements": plan.gate_requirements,
        "approvalRequirements": plan.approval_requirements,
        "rollbackPlan": plan.rollback_plan,
        "abortCriteria": plan.abort_criteria,
        "verificationChecklist": plan.verification_checklist,
        "blockers": plan.blockers,
        "warnings": plan.warnings,
        "nextPhase": plan.next_phase,
        "requestedBy": plan.requested_by_id,
        "approvedBy": plan.approved_by_id,
        "rejectedBy": plan.rejected_by_id,
        "archivedBy": plan.archived_by_id,
        "approvedAt": (
            plan.approved_at.isoformat() if plan.approved_at else None
        ),
        "rejectedAt": (
            plan.rejected_at.isoformat() if plan.rejected_at else None
        ),
        "archivedAt": (
            plan.archived_at.isoformat() if plan.archived_at else None
        ),
        "metadata": plan.metadata,
        "createdAt": plan.created_at.isoformat(),
        "updatedAt": plan.updated_at.isoformat(),
        "nextAction": _next_action(plan),
    }


def serialize_provider_test_plan(plan: RuntimeProviderTestPlan) -> dict[str, Any]:
    return _serialize_plan(plan)


def _next_action(plan: RuntimeProviderTestPlan) -> str:
    if plan.status == RuntimeProviderTestPlan.Status.DRAFT:
        return "validate_provider_test_plan"
    if plan.status == RuntimeProviderTestPlan.Status.PREPARED:
        return "validate_provider_test_plan"
    if plan.status == RuntimeProviderTestPlan.Status.VALIDATED:
        return "approve_provider_test_plan_for_future_execution"
    if plan.status == RuntimeProviderTestPlan.Status.APPROVAL_REQUIRED:
        return "approve_or_reject_provider_test_plan"
    if (
        plan.status
        == RuntimeProviderTestPlan.Status.APPROVED_FOR_FUTURE_EXECUTION
    ):
        return "ready_for_phase_6k_single_internal_razorpay_test_mode_execution_gate"
    if plan.status == RuntimeProviderTestPlan.Status.REJECTED:
        return "prepare_new_provider_test_plan_if_needed"
    if plan.status == RuntimeProviderTestPlan.Status.BLOCKED:
        return "fix_provider_test_plan_blockers"
    if plan.status == RuntimeProviderTestPlan.Status.ARCHIVED:
        return "keep_provider_execution_blocked"
    return "keep_provider_execution_blocked"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _audit_plan(
    *,
    kind: str,
    plan: RuntimeProviderTestPlan,
    user=None,
    text: str = "",
) -> AuditEvent:
    payload = {
        "plan_id": plan.plan_id,
        "provider_type": plan.provider_type,
        "operation_type": plan.operation_type,
        "provider_environment": plan.provider_environment,
        "organization": (
            {
                "id": plan.organization_id,
                "code": plan.organization.code,
                "name": plan.organization.name,
            }
            if plan.organization_id and plan.organization
            else None
        ),
        "status": plan.status,
        "dry_run": plan.dry_run,
        "provider_call_allowed": plan.provider_call_allowed,
        "external_call_will_be_made": plan.external_call_will_be_made,
        "external_call_was_made": plan.external_call_was_made,
        "provider_call_attempted": plan.provider_call_attempted,
        "amount_paise": plan.amount_paise,
        "currency": plan.currency,
        "blockers": plan.blockers,
        "warnings": plan.warnings,
    }
    return write_event(
        kind=kind,
        text=text or f"Provider test plan {plan.plan_id} {kind}",
        tone=(
            AuditEvent.Tone.WARNING
            if plan.status
            in {
                RuntimeProviderTestPlan.Status.BLOCKED,
                RuntimeProviderTestPlan.Status.REJECTED,
            }
            else AuditEvent.Tone.INFO
        ),
        payload=payload,
        organization=plan.organization,
        user=user if _is_authenticated_user(user) else None,
    )


# ---------------------------------------------------------------------------
# Invariant validator
# ---------------------------------------------------------------------------


def assert_provider_test_plan_has_no_side_effects(
    plan: RuntimeProviderTestPlan,
) -> bool:
    """True only when every Phase 6J invariant holds on this plan."""
    return (
        plan.dry_run is True
        and plan.provider_call_allowed is False
        and plan.external_call_will_be_made is False
        and plan.external_call_was_made is False
        and plan.provider_call_attempted is False
        and plan.real_money is False
        and plan.real_customer_data_allowed is False
        and plan.runtime_source == "env_config"
        and plan.per_org_runtime_enabled is False
    )


# ---------------------------------------------------------------------------
# Plan lifecycle
# ---------------------------------------------------------------------------


def prepare_single_provider_test_plan(
    *,
    operation_type: str = "razorpay.create_order",
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
    user=None,
    reason: str = "",
) -> RuntimeProviderTestPlan:
    """Create a new RuntimeProviderTestPlan in ``prepared`` status.

    Phase 6J only implements the ``razorpay.create_order`` target.
    Other operations are accepted by the policy registry but produce a
    ``blocked`` plan with a typed nextAction.
    """
    policy = get_provider_test_plan_policy(operation_type)
    org, resolved_branch = _resolve_org_branch(organization, branch)
    plan_id = _new_plan_id()

    if policy is None:
        plan = RuntimeProviderTestPlan(
            plan_id=plan_id,
            organization=org,
            branch=resolved_branch,
            provider_type="",
            operation_type=operation_type,
            provider_environment=(
                RuntimeProviderTestPlan.ProviderEnvironment.TEST
            ),
            status=RuntimeProviderTestPlan.Status.BLOCKED,
            requested_by=user if _is_authenticated_user(user) else None,
            blockers=[
                f"No provider test plan policy for: {operation_type}"
            ],
            warnings=[PHASE_6J_WARNING],
            metadata={
                "phase": "6J",
                "reason": reason,
                "preparedBy": _safe_identity(user),
            },
        )
        plan.save()
        event = _audit_plan(
            kind="runtime.provider_test_plan.blocked",
            plan=plan,
            user=user,
            text=(
                f"Provider test plan {plan_id} blocked — unsupported "
                f"operation {operation_type}."
            ),
        )
        plan.audit_event_id = event.id
        plan.save(update_fields=["audit_event_id", "updated_at"])
        return plan

    is_target = is_phase_6j_implementation_target(operation_type)
    payload = build_safe_synthetic_provider_payload(
        operation_type, organization=org, plan_id=plan_id
    )
    payload_hash = _safe_hash(payload)
    env_readiness = inspect_provider_env_readiness(policy.provider_type)
    ref_readiness = env_readiness.get("secretRefStatus", {})
    masked_refs = env_readiness.get("maskedSecretRefs", {})

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6J_WARNING]

    if not is_target:
        blockers.append(
            f"Phase 6J implementation target is razorpay.create_order; "
            f"{operation_type} is registered but not implemented in 6J."
        )

    if policy.provider_type == "razorpay":
        env = env_readiness.get("envPresence", {})
        if not env.get("RAZORPAY_KEY_ID"):
            blockers.append("RAZORPAY_KEY_ID env not set")
        if not env.get("RAZORPAY_KEY_SECRET"):
            blockers.append("RAZORPAY_KEY_SECRET env not set")
        if not env.get("RAZORPAY_WEBHOOK_SECRET"):
            warnings.append(
                "RAZORPAY_WEBHOOK_SECRET env not set — required for "
                "Phase 6K webhook handling but not blocking 6J."
            )

    amount_paise = (
        policy.max_test_amount_paise
        if operation_type == "razorpay.create_order"
        else None
    )
    if amount_paise is not None and amount_paise > policy.max_test_amount_paise:
        blockers.append(
            f"amount_paise {amount_paise} exceeds maxTestAmountPaise "
            f"{policy.max_test_amount_paise}"
        )

    kill_switch = get_or_create_default_runtime_kill_switch()
    if not kill_switch.enabled:
        blockers.append("global_runtime_kill_switch_should_remain_enabled")

    plan = RuntimeProviderTestPlan(
        plan_id=plan_id,
        organization=org,
        branch=resolved_branch,
        provider_type=policy.provider_type,
        operation_type=operation_type,
        provider_environment=policy.provider_environment,
        status=(
            RuntimeProviderTestPlan.Status.BLOCKED
            if blockers
            else RuntimeProviderTestPlan.Status.PREPARED
        ),
        runtime_source="env_config",
        per_org_runtime_enabled=False,
        dry_run=True,
        provider_call_allowed=False,
        external_call_will_be_made=False,
        external_call_was_made=False,
        provider_call_attempted=False,
        real_customer_data_allowed=False,
        real_money=False,
        amount_paise=amount_paise,
        currency=policy.currency or "INR",
        idempotency_key=str(payload.get("receipt", f"phase6j:{plan_id}")),
        payload_hash=payload_hash,
        safe_payload_summary=payload,
        env_readiness=env_readiness,
        secret_ref_readiness={
            "refs": ref_readiness,
            "maskedRefs": masked_refs,
        },
        gate_requirements=_gate_requirements_for(policy),
        approval_requirements=_approval_requirements_for(policy),
        rollback_plan=_rollback_plan_for(policy, plan_id),
        abort_criteria=_abort_criteria_for(policy),
        verification_checklist=_verification_checklist_for(policy),
        blockers=blockers,
        warnings=warnings,
        next_phase=policy.next_phase_for_execution,
        requested_by=user if _is_authenticated_user(user) else None,
        metadata={
            "phase": "6J",
            "reason": reason,
            "preparedBy": _safe_identity(user),
            "policyVersion": POLICY_VERSION,
            "implementationTargetInPhase6J": is_target,
        },
    )
    plan.save()

    kind = (
        "runtime.provider_test_plan.blocked"
        if blockers
        else "runtime.provider_test_plan.prepared"
    )
    event = _audit_plan(
        kind=kind,
        plan=plan,
        user=user,
        text=(
            f"Provider test plan {plan.plan_id} {kind.rsplit('.', 1)[-1]} "
            f"for {operation_type}"
        ),
    )
    plan.audit_event_id = event.id
    plan.save(update_fields=["audit_event_id", "updated_at"])
    return plan


def validate_single_provider_test_plan(
    plan_id: str,
    *,
    user=None,
) -> RuntimeProviderTestPlan:
    plan = RuntimeProviderTestPlan.objects.get(plan_id=plan_id)
    blockers: list[str] = []
    warnings: list[str] = list(plan.warnings or [])

    if not plan.payload_hash:
        blockers.append("payload_hash_missing")
    if not plan.idempotency_key:
        blockers.append("idempotency_key_missing")
    if not assert_provider_test_plan_has_no_side_effects(plan):
        blockers.append(
            "phase_6j_invariant_violation_detected_on_validate"
        )

    env = plan.env_readiness.get("envPresence", {}) if plan.env_readiness else {}
    if plan.provider_type == "razorpay":
        if not env.get("RAZORPAY_KEY_ID"):
            blockers.append("RAZORPAY_KEY_ID env not set")
        if not env.get("RAZORPAY_KEY_SECRET"):
            blockers.append("RAZORPAY_KEY_SECRET env not set")
        if not env.get("RAZORPAY_WEBHOOK_SECRET"):
            warnings.append(
                "RAZORPAY_WEBHOOK_SECRET env not set — required for "
                "Phase 6K webhook handling but not blocking 6J."
            )

    if blockers:
        plan.status = RuntimeProviderTestPlan.Status.BLOCKED
    else:
        plan.status = RuntimeProviderTestPlan.Status.VALIDATED
    plan.blockers = blockers
    plan.warnings = warnings
    plan.metadata = {
        **(plan.metadata or {}),
        "validatedBy": _safe_identity(user),
    }
    plan.save()

    kind = (
        "runtime.provider_test_plan.blocked"
        if blockers
        else "runtime.provider_test_plan.validated"
    )
    event = _audit_plan(
        kind=kind,
        plan=plan,
        user=user,
        text=(
            f"Provider test plan {plan.plan_id} "
            f"{kind.rsplit('.', 1)[-1]} for {plan.operation_type}"
        ),
    )
    plan.audit_event_id = event.id
    plan.save(update_fields=["audit_event_id", "updated_at"])
    return plan


def approve_single_provider_test_plan(
    plan_id: str,
    *,
    approver=None,
    reason: str = "",
) -> RuntimeProviderTestPlan:
    plan = RuntimeProviderTestPlan.objects.get(plan_id=plan_id)
    if plan.status not in {
        RuntimeProviderTestPlan.Status.VALIDATED,
        RuntimeProviderTestPlan.Status.APPROVAL_REQUIRED,
    }:
        plan.status = RuntimeProviderTestPlan.Status.BLOCKED
        plan.blockers = list(plan.blockers or []) + [
            f"approval_requires_validated_status_was_{plan.status}"
        ]
        plan.save()
        event = _audit_plan(
            kind="runtime.provider_test_plan.blocked",
            plan=plan,
            user=approver,
            text=(
                f"Provider test plan {plan.plan_id} approval blocked — "
                "must be validated first."
            ),
        )
        plan.audit_event_id = event.id
        plan.save(update_fields=["audit_event_id", "updated_at"])
        return plan

    if not assert_provider_test_plan_has_no_side_effects(plan):
        plan.status = RuntimeProviderTestPlan.Status.BLOCKED
        plan.blockers = list(plan.blockers or []) + [
            "phase_6j_invariant_violation_blocked_approval"
        ]
        plan.save()
        event = _audit_plan(
            kind="runtime.provider_test_plan.invariant_violation_blocked",
            plan=plan,
            user=approver,
            text=(
                f"Provider test plan {plan.plan_id} invariant violation "
                "blocked approval."
            ),
        )
        plan.audit_event_id = event.id
        plan.save(update_fields=["audit_event_id", "updated_at"])
        return plan

    plan.status = RuntimeProviderTestPlan.Status.APPROVED_FOR_FUTURE_EXECUTION
    plan.approved_by = approver if _is_authenticated_user(approver) else None
    plan.approved_at = timezone.now()
    plan.metadata = {
        **(plan.metadata or {}),
        "approvalReason": reason,
        "approvedBy": _safe_identity(approver),
    }
    plan.save()
    event = _audit_plan(
        kind="runtime.provider_test_plan.approved",
        plan=plan,
        user=approver,
        text=(
            f"Provider test plan {plan.plan_id} approved for future "
            f"execution ({plan.next_phase})."
        ),
    )
    plan.audit_event_id = event.id
    plan.save(update_fields=["audit_event_id", "updated_at"])
    return plan


def reject_single_provider_test_plan(
    plan_id: str,
    *,
    rejector=None,
    reason: str = "",
) -> RuntimeProviderTestPlan:
    plan = RuntimeProviderTestPlan.objects.get(plan_id=plan_id)
    plan.status = RuntimeProviderTestPlan.Status.REJECTED
    plan.rejected_by = rejector if _is_authenticated_user(rejector) else None
    plan.rejected_at = timezone.now()
    plan.metadata = {
        **(plan.metadata or {}),
        "rejectionReason": reason,
        "rejectedBy": _safe_identity(rejector),
    }
    plan.save()
    event = _audit_plan(
        kind="runtime.provider_test_plan.rejected",
        plan=plan,
        user=rejector,
        text=f"Provider test plan {plan.plan_id} rejected.",
    )
    plan.audit_event_id = event.id
    plan.save(update_fields=["audit_event_id", "updated_at"])
    return plan


def archive_single_provider_test_plan(
    plan_id: str,
    *,
    user=None,
    reason: str = "",
) -> RuntimeProviderTestPlan:
    plan = RuntimeProviderTestPlan.objects.get(plan_id=plan_id)
    plan.status = RuntimeProviderTestPlan.Status.ARCHIVED
    plan.archived_by = user if _is_authenticated_user(user) else None
    plan.archived_at = timezone.now()
    plan.metadata = {
        **(plan.metadata or {}),
        "archiveReason": reason,
        "archivedBy": _safe_identity(user),
    }
    plan.save()
    event = _audit_plan(
        kind="runtime.provider_test_plan.archived",
        plan=plan,
        user=user,
        text=f"Provider test plan {plan.plan_id} archived.",
    )
    plan.audit_event_id = event.id
    plan.save(update_fields=["audit_event_id", "updated_at"])
    return plan


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def inspect_single_provider_test_plan(
    *,
    plan_id: Optional[str] = None,
    organization: Optional[Organization] = None,
) -> dict[str, Any]:
    org, _branch = _resolve_org_branch(organization)
    qs = RuntimeProviderTestPlan.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    if plan_id:
        qs = qs.filter(plan_id=plan_id)
    plans = list(qs.order_by("-created_at"))
    latest = plans[0] if plans else None

    prepared = qs.filter(
        status=RuntimeProviderTestPlan.Status.PREPARED
    ).count()
    validated = qs.filter(
        status=RuntimeProviderTestPlan.Status.VALIDATED
    ).count()
    approved = qs.filter(
        status=RuntimeProviderTestPlan.Status.APPROVED_FOR_FUTURE_EXECUTION
    ).count()
    archived = qs.filter(
        status=RuntimeProviderTestPlan.Status.ARCHIVED
    ).count()
    blocked = qs.filter(
        status=RuntimeProviderTestPlan.Status.BLOCKED
    ).count()
    provider_call_attempted_count = qs.filter(
        provider_call_attempted=True
    ).count()
    external_call_made_count = qs.filter(
        external_call_was_made=True
    ).count()

    switch = get_or_create_default_runtime_kill_switch()
    blockers: list[str] = []
    if not switch.enabled:
        blockers.append("global_runtime_kill_switch_should_remain_enabled")
    if provider_call_attempted_count:
        blockers.append("provider_call_attempted_must_remain_zero_in_phase_6j")
    if external_call_made_count:
        blockers.append("external_call_made_must_remain_zero_in_phase_6j")

    safe_to_start_phase_6k = (
        not blockers
        and approved >= 1
        and provider_call_attempted_count == 0
        and external_call_made_count == 0
    )

    if not switch.enabled:
        next_action = "fix_provider_test_plan_blockers"
    elif provider_call_attempted_count or external_call_made_count:
        next_action = "fix_provider_test_plan_blockers"
    elif safe_to_start_phase_6k:
        next_action = (
            "ready_for_phase_6k_single_internal_razorpay_test_mode_execution_gate"
        )
    elif latest is None:
        next_action = "prepare_single_provider_test_plan"
    else:
        next_action = "keep_provider_execution_blocked"

    return {
        "organization": (
            {"id": org.id, "code": org.code, "name": org.name}
            if org is not None
            else None
        ),
        "policyVersion": POLICY_VERSION,
        "phase6jImplementationTargets": list(
            PHASE_6J_IMPLEMENTATION_TARGETS
        ),
        "policies": [
            policy.to_dict()
            for policy in list_provider_test_plan_policies()
        ],
        "planCount": qs.count(),
        "preparedCount": prepared,
        "validatedCount": validated,
        "approvedCount": approved,
        "archivedCount": archived,
        "blockedCount": blocked,
        "providerCallAttemptedCount": provider_call_attempted_count,
        "externalCallMadeCount": external_call_made_count,
        "latestPlan": _serialize_plan(latest) if latest else None,
        "plans": [_serialize_plan(p) for p in plans[:25]],
        "killSwitchActive": switch.enabled,
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "dryRun": True,
        "providerCallAllowed": False,
        "externalCallWillBeMade": False,
        "externalCallWasMade": False,
        "providerCallAttempted": False,
        "safeToStartPhase6K": safe_to_start_phase_6k,
        "blockers": blockers,
        "warnings": [
            PHASE_6J_WARNING,
            "Razorpay test-mode credentials must be present before "
            "Phase 6K can open.",
        ],
        "nextAction": next_action,
    }


__all__ = (
    "PHASE_6J_WARNING",
    "get_provider_test_plan_policy_payload",
    "build_safe_synthetic_provider_payload",
    "inspect_provider_env_readiness",
    "prepare_single_provider_test_plan",
    "validate_single_provider_test_plan",
    "approve_single_provider_test_plan",
    "reject_single_provider_test_plan",
    "archive_single_provider_test_plan",
    "inspect_single_provider_test_plan",
    "assert_provider_test_plan_has_no_side_effects",
    "serialize_provider_test_plan",
)
