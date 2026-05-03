"""Phase 6K — Single Internal Razorpay Test-Mode Execution service.

Service layer that prepares, executes (CLI-only), rolls back, and
archives a :class:`RuntimeProviderExecutionAttempt` against an
APPROVED :class:`RuntimeProviderTestPlan` (Phase 6J output).

LOCKED rules:

- Only ``razorpay.create_order`` against a Razorpay TEST key.
- Only ONE successful execution per approved plan.
- ``business_mutation_was_made`` / ``payment_link_created`` /
  ``payment_captured`` / ``customer_notification_sent`` are asserted
  ``False`` at every save site (see
  :func:`assert_execution_invariants`).
- Raw secrets NEVER leave the backend.
- Provider response is reduced to a safe summary before persistence.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .context import get_default_organization
from .live_gate import get_or_create_default_runtime_kill_switch
from .models import (
    Branch,
    Organization,
    RuntimeProviderExecutionAttempt,
    RuntimeProviderTestPlan,
)
from .provider_execution_policy import (
    PHASE_6K_ALLOWED_OPERATION,
    PHASE_6K_ENV_FLAG,
    POLICY_VERSION,
    ProviderExecutionPolicy,
    get_provider_execution_policy,
)
from .razorpay_test_execution import (
    RazorpayTestExecutionError,
    assert_no_business_mutation_from_execution,
    execute_razorpay_test_create_order,
    inspect_razorpay_test_env,
)


PHASE_6K_WARNING = (
    "Phase 6K runs at most ONE Razorpay test create_order per approved "
    "plan. No customer data, no payment link, no capture, no business "
    "mutation."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_authenticated_user(actor) -> bool:
    return bool(actor is not None and getattr(actor, "is_authenticated", False))


def _safe_identity(actor) -> Optional[int]:
    return actor.id if _is_authenticated_user(actor) else None


def _new_execution_id() -> str:
    return f"pex_{uuid4().hex[:24]}"


def _safe_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _resolve_org_branch(
    plan: RuntimeProviderTestPlan,
    organization: Optional[Organization] = None,
    branch: Optional[Branch] = None,
) -> tuple[Optional[Organization], Optional[Branch]]:
    org = organization or plan.organization or get_default_organization()
    resolved_branch = branch or plan.branch
    if resolved_branch is None and org is not None:
        resolved_branch = Branch.objects.filter(
            organization=org,
            code="main",
        ).first()
    return org, resolved_branch


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def assert_execution_invariants(
    attempt: RuntimeProviderExecutionAttempt,
) -> bool:
    """True only when every Phase 6K invariant holds on the attempt."""
    return (
        attempt.test_mode is True
        and attempt.real_money is False
        and attempt.real_customer_data_allowed is False
        and attempt.business_mutation_was_made is False
        and attempt.payment_link_created is False
        and attempt.payment_captured is False
        and attempt.customer_notification_sent is False
        and attempt.runtime_source == "env_config"
        and attempt.per_org_runtime_enabled is False
        and assert_no_business_mutation_from_execution(attempt)
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _audit_attempt(
    *,
    kind: str,
    attempt: RuntimeProviderExecutionAttempt,
    actor=None,
    text: str = "",
) -> AuditEvent:
    payload = {
        "execution_id": attempt.execution_id,
        "plan_id": attempt.plan.plan_id if attempt.plan_id else "",
        "provider_type": attempt.provider_type,
        "operation_type": attempt.operation_type,
        "provider_environment": attempt.provider_environment,
        "organization": (
            {
                "id": attempt.organization_id,
                "code": attempt.organization.code,
                "name": attempt.organization.name,
            }
            if attempt.organization_id and attempt.organization
            else None
        ),
        "amount_paise": attempt.amount_paise,
        "currency": attempt.currency,
        "status": attempt.status,
        "test_mode": attempt.test_mode,
        "provider_call_allowed": attempt.provider_call_allowed,
        "external_call_will_be_made": attempt.external_call_will_be_made,
        "external_call_was_made": attempt.external_call_was_made,
        "provider_call_attempted": attempt.provider_call_attempted,
        "business_mutation_was_made": attempt.business_mutation_was_made,
        "payment_link_created": attempt.payment_link_created,
        "payment_captured": attempt.payment_captured,
        "customer_notification_sent": attempt.customer_notification_sent,
        "provider_object_id": attempt.provider_object_id,
        "blockers": attempt.blockers,
        "warnings": attempt.warnings,
    }
    return write_event(
        kind=kind,
        text=text or f"Provider execution {attempt.execution_id} {kind}",
        tone=(
            AuditEvent.Tone.WARNING
            if attempt.status
            in {
                RuntimeProviderExecutionAttempt.Status.BLOCKED,
                RuntimeProviderExecutionAttempt.Status.FAILED,
                RuntimeProviderExecutionAttempt.Status.ROLLED_BACK,
            }
            else AuditEvent.Tone.SUCCESS
            if attempt.status
            == RuntimeProviderExecutionAttempt.Status.SUCCEEDED
            else AuditEvent.Tone.INFO
        ),
        payload=payload,
        organization=attempt.organization,
        user=actor if _is_authenticated_user(actor) else None,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialize_execution_attempt(
    attempt: RuntimeProviderExecutionAttempt,
) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "executionId": attempt.execution_id,
        "planId": attempt.plan.plan_id if attempt.plan_id else "",
        "organization": (
            {
                "id": attempt.organization_id,
                "code": attempt.organization.code,
                "name": attempt.organization.name,
            }
            if attempt.organization_id and attempt.organization
            else None
        ),
        "branch": (
            {
                "id": attempt.branch_id,
                "code": attempt.branch.code,
                "name": attempt.branch.name,
            }
            if attempt.branch_id and attempt.branch
            else None
        ),
        "providerType": attempt.provider_type,
        "operationType": attempt.operation_type,
        "providerEnvironment": attempt.provider_environment,
        "status": attempt.status,
        "runtimeSource": attempt.runtime_source,
        "perOrgRuntimeEnabled": attempt.per_org_runtime_enabled,
        "dryRun": attempt.dry_run,
        "testMode": attempt.test_mode,
        "realMoney": attempt.real_money,
        "realCustomerDataAllowed": attempt.real_customer_data_allowed,
        "amountPaise": attempt.amount_paise,
        "currency": attempt.currency,
        "providerCallAllowed": attempt.provider_call_allowed,
        "externalCallWillBeMade": attempt.external_call_will_be_made,
        "externalCallWasMade": attempt.external_call_was_made,
        "providerCallAttempted": attempt.provider_call_attempted,
        "businessMutationWasMade": attempt.business_mutation_was_made,
        "paymentLinkCreated": attempt.payment_link_created,
        "paymentCaptured": attempt.payment_captured,
        "customerNotificationSent": attempt.customer_notification_sent,
        "idempotencyKey": attempt.idempotency_key,
        "receipt": attempt.receipt,
        "requestPayloadHash": attempt.request_payload_hash,
        "safeRequestSummary": attempt.safe_request_summary,
        "safeResponseSummary": attempt.safe_response_summary,
        "providerObjectId": attempt.provider_object_id,
        "providerStatus": attempt.provider_status,
        "envReadiness": attempt.env_readiness,
        "gateDecision": attempt.gate_decision,
        "blockers": attempt.blockers,
        "warnings": attempt.warnings,
        "rollbackPlan": attempt.rollback_plan,
        "rollbackStatus": attempt.rollback_status,
        "requestedBy": attempt.requested_by_id,
        "executedBy": attempt.executed_by_id,
        "rolledBackBy": attempt.rolled_back_by_id,
        "archivedBy": attempt.archived_by_id,
        "executedAt": (
            attempt.executed_at.isoformat() if attempt.executed_at else None
        ),
        "rolledBackAt": (
            attempt.rolled_back_at.isoformat()
            if attempt.rolled_back_at
            else None
        ),
        "archivedAt": (
            attempt.archived_at.isoformat() if attempt.archived_at else None
        ),
        "metadata": attempt.metadata,
        "createdAt": attempt.created_at.isoformat(),
        "updatedAt": attempt.updated_at.isoformat(),
        "nextAction": _next_action(attempt),
    }


def _next_action(attempt: RuntimeProviderExecutionAttempt) -> str:
    Status = RuntimeProviderExecutionAttempt.Status
    if attempt.status == Status.PREPARED:
        return "execute_single_razorpay_test_order_via_cli"
    if attempt.status == Status.READY:
        return "execute_single_razorpay_test_order_via_cli"
    if attempt.status == Status.EXECUTING:
        return "wait_for_execution_to_complete"
    if attempt.status == Status.SUCCEEDED:
        return "rollback_or_archive_phase_6k_execution_attempt"
    if attempt.status == Status.FAILED:
        return "inspect_failure_then_archive"
    if attempt.status == Status.ROLLED_BACK:
        return (
            "phase_6k_execution_rolled_back_no_external_side_effects"
        )
    if attempt.status == Status.BLOCKED:
        return "fix_provider_execution_blockers"
    if attempt.status == Status.ARCHIVED:
        return "ready_for_phase_6l_audit_review_and_webhook_readiness"
    return "keep_provider_execution_blocked"


# ---------------------------------------------------------------------------
# Plan + env precondition checks
# ---------------------------------------------------------------------------


_PLAN_APPROVED = (
    RuntimeProviderTestPlan.Status.APPROVED_FOR_FUTURE_EXECUTION
)

_CUSTOMER_PII_KEYS = (
    "phone",
    "phone_number",
    "mobile",
    "email",
    "address",
    "customer",
    "customer_name",
    "customer_phone",
    "customer_email",
)


def _payload_contains_customer_data(payload: dict[str, Any]) -> bool:
    """Cheap structural check — refuses any obvious customer PII keys."""
    if not isinstance(payload, dict):
        return False
    for key, value in payload.items():
        if str(key).lower() in _CUSTOMER_PII_KEYS:
            return True
        if isinstance(value, dict):
            if _payload_contains_customer_data(value):
                return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _payload_contains_customer_data(
                    item
                ):
                    return True
    return False


def _check_preconditions(
    plan: RuntimeProviderTestPlan,
    *,
    confirm: bool,
    env: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    policy = get_provider_execution_policy(plan.operation_type)
    if policy is None or not policy.allowed_in_phase_6k:
        blockers.append(
            f"operation_not_allowed_in_phase_6k: {plan.operation_type}"
        )
    if plan.operation_type != PHASE_6K_ALLOWED_OPERATION:
        blockers.append(
            f"only_razorpay_create_order_allowed_in_phase_6k_got_{plan.operation_type}"
        )
    if plan.status != _PLAN_APPROVED:
        blockers.append(
            f"plan_status_must_be_approved_for_future_execution_was_{plan.status}"
        )
    if plan.amount_paise != 100:
        blockers.append(
            f"plan_amount_paise_must_be_100_was_{plan.amount_paise}"
        )
    if plan.real_money:
        blockers.append("plan_real_money_must_be_false")
    if plan.real_customer_data_allowed:
        blockers.append("plan_real_customer_data_must_be_false")
    if plan.provider_call_attempted:
        blockers.append("plan_provider_call_attempted_already_true")
    if plan.external_call_was_made:
        blockers.append("plan_external_call_was_made_already_true")
    if _payload_contains_customer_data(plan.safe_payload_summary or {}):
        blockers.append("plan_payload_contains_customer_data")
    if not env["envFlagEnabled"]:
        blockers.append(f"env_flag_{PHASE_6K_ENV_FLAG}_must_be_true")
    if not env["razorpayKeyIdPresent"]:
        blockers.append("RAZORPAY_KEY_ID env not set")
    if not env["razorpayKeySecretPresent"]:
        blockers.append("RAZORPAY_KEY_SECRET env not set")
    if env["isLiveKey"]:
        blockers.append("razorpay_key_id_is_live_key_refusing")
    if env["razorpayKeyIdPresent"] and not env["isTestKey"]:
        blockers.append("razorpay_key_id_must_start_with_rzp_test")
    if not confirm:
        blockers.append("explicit_cli_confirmation_required")
    kill_switch = get_or_create_default_runtime_kill_switch()
    if not kill_switch.enabled:
        blockers.append("global_runtime_kill_switch_should_remain_enabled")

    # Per-plan dedup: refuse if a successful execution already exists.
    if RuntimeProviderExecutionAttempt.objects.filter(
        plan=plan,
        status=RuntimeProviderExecutionAttempt.Status.SUCCEEDED,
    ).exists():
        blockers.append("plan_already_has_successful_execution")
    return blockers


# ---------------------------------------------------------------------------
# Plan helpers exposed for tests / commands
# ---------------------------------------------------------------------------


def _build_attempt_seed(
    plan: RuntimeProviderTestPlan,
    *,
    actor=None,
) -> dict[str, Any]:
    execution_id = _new_execution_id()
    receipt = f"phase6k_{execution_id}"
    safe_request = {
        "operationType": plan.operation_type,
        "amount": 100,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "purpose": "phase6k_internal_test_mode_only",
            "external_customer": "false",
            "real_money": "false",
            "business_mutation": "false",
            "phase": "6K",
        },
    }
    rollback_plan = {
        "rollbackRequired": True,
        "noExternalRollbackInPhase6K": True,
        "rollbackSteps": [
            (
                "Razorpay test order remains in the test dashboard "
                "indefinitely — no real money / customer impact."
            ),
            "Mark execution attempt rollback_status=completed.",
            "Archive the attempt to keep the registry clean.",
            "No payment / order / shipment row is mutated.",
        ],
        "executionPhaseRollback": (
            "Phase 6L will own audit review + webhook readiness; no "
            "provider-side cancel is required for an unpaid test order."
        ),
    }
    return {
        "execution_id": execution_id,
        "receipt": receipt,
        "safe_request": safe_request,
        "rollback_plan": rollback_plan,
        "metadata": {
            "phase": "6K",
            "policyVersion": POLICY_VERSION,
            "preparedBy": _safe_identity(actor),
        },
    }


# ---------------------------------------------------------------------------
# Lifecycle: prepare / execute / rollback / archive / inspect
# ---------------------------------------------------------------------------


def prepare_single_provider_execution_attempt(
    plan_id: str,
    *,
    actor=None,
) -> RuntimeProviderExecutionAttempt:
    """Create a ``RuntimeProviderExecutionAttempt`` row in PREPARED.

    Phase 6K never makes a provider call here. The row only declares
    intent and snapshots env / blockers; the actual Razorpay call
    happens in :func:`execute_single_razorpay_test_order` and only via
    the dedicated CLI command with ``--confirm-test-execution``.
    """
    plan = RuntimeProviderTestPlan.objects.get(plan_id=plan_id)
    org, branch = _resolve_org_branch(plan)
    env = inspect_razorpay_test_env()
    seed = _build_attempt_seed(plan, actor=actor)
    blockers = _check_preconditions(plan, confirm=True, env=env)
    # During PREPARE we don't require the CLI confirm flag — that's an
    # execute-time gate. Strip it from the prep blockers so the row
    # only captures real configuration issues.
    blockers = [
        b
        for b in blockers
        if b
        not in {
            "explicit_cli_confirmation_required",
            "plan_already_has_successful_execution",
        }
    ]
    attempt = RuntimeProviderExecutionAttempt(
        execution_id=seed["execution_id"],
        plan=plan,
        organization=org,
        branch=branch,
        provider_type=plan.provider_type,
        operation_type=plan.operation_type,
        provider_environment=plan.provider_environment,
        status=(
            RuntimeProviderExecutionAttempt.Status.BLOCKED
            if blockers
            else RuntimeProviderExecutionAttempt.Status.PREPARED
        ),
        runtime_source="env_config",
        per_org_runtime_enabled=False,
        dry_run=False,
        test_mode=True,
        real_money=False,
        real_customer_data_allowed=False,
        amount_paise=100,
        currency="INR",
        provider_call_allowed=False,
        external_call_will_be_made=False,
        external_call_was_made=False,
        provider_call_attempted=False,
        business_mutation_was_made=False,
        payment_link_created=False,
        payment_captured=False,
        customer_notification_sent=False,
        idempotency_key=seed["receipt"],
        receipt=seed["receipt"],
        request_payload_hash=_safe_hash(seed["safe_request"]),
        safe_request_summary=seed["safe_request"],
        safe_response_summary={},
        provider_object_id="",
        provider_status="",
        env_readiness=env,
        gate_decision="prepared",
        blockers=blockers,
        warnings=[PHASE_6K_WARNING],
        rollback_plan=seed["rollback_plan"],
        rollback_status=(
            RuntimeProviderExecutionAttempt.RollbackStatus.NOT_REQUIRED
        ),
        requested_by=actor if _is_authenticated_user(actor) else None,
        metadata=seed["metadata"],
    )
    attempt.save()

    kind = (
        "runtime.provider_execution.blocked"
        if blockers
        else "runtime.provider_execution.prepared"
    )
    event = _audit_attempt(kind=kind, attempt=attempt, actor=actor)
    attempt.audit_event_id = event.id
    attempt.save(update_fields=["audit_event_id", "updated_at"])
    return attempt


def execute_single_razorpay_test_order(
    plan_id: str,
    *,
    actor=None,
    confirm: bool = False,
) -> RuntimeProviderExecutionAttempt:
    """Issue ONE Razorpay test-mode ``create_order`` against the plan.

    This is the ONLY function in the Phase 6K codebase that may
    contact Razorpay. The CLI command is the only sanctioned caller
    in Phase 6K (no API endpoint).
    """
    plan = RuntimeProviderTestPlan.objects.get(plan_id=plan_id)
    env = inspect_razorpay_test_env()
    blockers = _check_preconditions(plan, confirm=confirm, env=env)

    seed = _build_attempt_seed(plan, actor=actor)
    attempt = RuntimeProviderExecutionAttempt(
        execution_id=seed["execution_id"],
        plan=plan,
        organization=plan.organization or get_default_organization(),
        branch=plan.branch,
        provider_type=plan.provider_type,
        operation_type=plan.operation_type,
        provider_environment=plan.provider_environment,
        runtime_source="env_config",
        per_org_runtime_enabled=False,
        dry_run=False,
        test_mode=True,
        real_money=False,
        real_customer_data_allowed=False,
        amount_paise=100,
        currency="INR",
        provider_call_allowed=False,
        external_call_will_be_made=False,
        external_call_was_made=False,
        provider_call_attempted=False,
        business_mutation_was_made=False,
        payment_link_created=False,
        payment_captured=False,
        customer_notification_sent=False,
        idempotency_key=seed["receipt"],
        receipt=seed["receipt"],
        request_payload_hash=_safe_hash(seed["safe_request"]),
        safe_request_summary=seed["safe_request"],
        safe_response_summary={},
        provider_object_id="",
        provider_status="",
        env_readiness=env,
        gate_decision="executing" if not blockers else "blocked",
        blockers=blockers,
        warnings=[PHASE_6K_WARNING],
        rollback_plan=seed["rollback_plan"],
        rollback_status=(
            RuntimeProviderExecutionAttempt.RollbackStatus.NOT_REQUIRED
        ),
        requested_by=actor if _is_authenticated_user(actor) else None,
        metadata=seed["metadata"],
    )

    if blockers:
        attempt.status = RuntimeProviderExecutionAttempt.Status.BLOCKED
        attempt.save()
        event = _audit_attempt(
            kind="runtime.provider_execution.blocked",
            attempt=attempt,
            actor=actor,
            text=(
                f"Phase 6K execution blocked for plan {plan.plan_id}: "
                + ", ".join(blockers[:3])
            ),
        )
        attempt.audit_event_id = event.id
        attempt.save(update_fields=["audit_event_id", "updated_at"])
        return attempt

    # All gates passed → flip the live-call flags + persist EXECUTING.
    attempt.provider_call_allowed = True
    attempt.external_call_will_be_made = True
    attempt.status = RuntimeProviderExecutionAttempt.Status.EXECUTING
    attempt.executed_by = actor if _is_authenticated_user(actor) else None
    attempt.save()
    started_event = _audit_attempt(
        kind="runtime.provider_execution.started",
        attempt=attempt,
        actor=actor,
        text=(
            f"Phase 6K execution started for plan {plan.plan_id} "
            "(razorpay test create_order)."
        ),
    )
    attempt.audit_event_id = started_event.id
    attempt.save(update_fields=["audit_event_id", "updated_at"])

    # Provider call.
    try:
        result = execute_razorpay_test_create_order(
            execution_id=attempt.execution_id,
            amount_paise=100,
            currency="INR",
            confirm=True,
        )
    except RazorpayTestExecutionError as exc:
        attempt.provider_call_attempted = True
        # Whether the SDK reached the network is unknowable from the
        # exception alone; default to True so we never under-report.
        attempt.external_call_was_made = True
        attempt.status = RuntimeProviderExecutionAttempt.Status.FAILED
        attempt.executed_at = timezone.now()
        attempt.safe_response_summary = {
            "error": "razorpay_test_execution_error",
            "errorClass": exc.__class__.__name__,
        }
        attempt.warnings = list(attempt.warnings or []) + [str(exc)]
        attempt.save()
        event = _audit_attempt(
            kind="runtime.provider_execution.failed",
            attempt=attempt,
            actor=actor,
            text=(
                f"Phase 6K execution failed for plan {plan.plan_id}: "
                f"{exc.__class__.__name__}"
            ),
        )
        attempt.audit_event_id = event.id
        attempt.save(update_fields=["audit_event_id", "updated_at"])
        return attempt

    attempt.provider_call_attempted = True
    attempt.external_call_was_made = True
    attempt.provider_object_id = result.provider_object_id
    attempt.provider_status = result.status
    attempt.safe_response_summary = result.safe_response_summary
    attempt.status = RuntimeProviderExecutionAttempt.Status.SUCCEEDED
    attempt.executed_at = timezone.now()
    attempt.warnings = list(attempt.warnings or []) + list(result.warnings)

    if not assert_execution_invariants(attempt):
        attempt.status = RuntimeProviderExecutionAttempt.Status.BLOCKED
        attempt.blockers = list(attempt.blockers or []) + [
            "phase_6k_invariant_violation_detected_post_execution"
        ]
        attempt.save()
        event = _audit_attempt(
            kind="runtime.provider_execution.invariant_violation_blocked",
            attempt=attempt,
            actor=actor,
        )
        attempt.audit_event_id = event.id
        attempt.save(update_fields=["audit_event_id", "updated_at"])
        return attempt

    # Mark the plan as "executed once in 6K" via metadata; never flip
    # the plan side-effect flags (those are Phase 6J invariants).
    with transaction.atomic():
        attempt.save()
        plan.metadata = {
            **(plan.metadata or {}),
            "phase6kExecutionId": attempt.execution_id,
            "phase6kExecutedAt": attempt.executed_at.isoformat(),
            "phase6kProviderObjectId": attempt.provider_object_id,
        }
        plan.save(update_fields=["metadata", "updated_at"])
    event = _audit_attempt(
        kind="runtime.provider_execution.succeeded",
        attempt=attempt,
        actor=actor,
        text=(
            f"Phase 6K Razorpay test order created (id={attempt.provider_object_id}) "
            f"for plan {plan.plan_id}."
        ),
    )
    attempt.audit_event_id = event.id
    attempt.save(update_fields=["audit_event_id", "updated_at"])
    return attempt


def rollback_single_provider_execution_attempt(
    execution_id: str,
    *,
    actor=None,
    reason: str = "",
) -> RuntimeProviderExecutionAttempt:
    """Mark the attempt as rolled back. Phase 6K never calls Razorpay
    cancel/refund — the test order is unpaid and stays in the
    Razorpay test dashboard with no real-money / customer impact."""
    attempt = RuntimeProviderExecutionAttempt.objects.get(
        execution_id=execution_id
    )
    attempt.status = RuntimeProviderExecutionAttempt.Status.ROLLED_BACK
    attempt.rollback_status = (
        RuntimeProviderExecutionAttempt.RollbackStatus.COMPLETED
    )
    attempt.rolled_back_by = actor if _is_authenticated_user(actor) else None
    attempt.rolled_back_at = timezone.now()
    # Hard re-assert: rollback NEVER unsets safety to "true".
    attempt.business_mutation_was_made = False
    attempt.payment_link_created = False
    attempt.payment_captured = False
    attempt.customer_notification_sent = False
    attempt.metadata = {
        **(attempt.metadata or {}),
        "rollbackReason": reason,
        "rolledBackBy": _safe_identity(actor),
    }
    attempt.save()
    event = _audit_attempt(
        kind="runtime.provider_execution.rolled_back",
        attempt=attempt,
        actor=actor,
        text=f"Phase 6K execution {attempt.execution_id} rolled back.",
    )
    attempt.audit_event_id = event.id
    attempt.save(update_fields=["audit_event_id", "updated_at"])
    return attempt


def archive_single_provider_execution_attempt(
    execution_id: str,
    *,
    actor=None,
    reason: str = "",
) -> RuntimeProviderExecutionAttempt:
    attempt = RuntimeProviderExecutionAttempt.objects.get(
        execution_id=execution_id
    )
    attempt.status = RuntimeProviderExecutionAttempt.Status.ARCHIVED
    attempt.archived_by = actor if _is_authenticated_user(actor) else None
    attempt.archived_at = timezone.now()
    attempt.metadata = {
        **(attempt.metadata or {}),
        "archiveReason": reason,
        "archivedBy": _safe_identity(actor),
    }
    attempt.save()
    event = _audit_attempt(
        kind="runtime.provider_execution.archived",
        attempt=attempt,
        actor=actor,
        text=f"Phase 6K execution {attempt.execution_id} archived.",
    )
    attempt.audit_event_id = event.id
    attempt.save(update_fields=["audit_event_id", "updated_at"])
    return attempt


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------


def inspect_single_provider_execution_attempt(
    *,
    execution_id: Optional[str] = None,
    organization: Optional[Organization] = None,
) -> dict[str, Any]:
    org = organization or get_default_organization()
    qs = RuntimeProviderExecutionAttempt.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    if execution_id:
        qs = qs.filter(execution_id=execution_id)

    Status = RuntimeProviderExecutionAttempt.Status
    PlanStatus = RuntimeProviderTestPlan.Status

    latest_plan = (
        RuntimeProviderTestPlan.objects.filter(
            organization=org if org is not None else None,
            status=PlanStatus.APPROVED_FOR_FUTURE_EXECUTION,
        ).order_by("-approved_at", "-created_at").first()
        if org is not None
        else RuntimeProviderTestPlan.objects.filter(
            status=PlanStatus.APPROVED_FOR_FUTURE_EXECUTION
        ).order_by("-approved_at", "-created_at").first()
    )

    attempts = list(qs.order_by("-created_at"))
    latest = attempts[0] if attempts else None

    successful = qs.filter(status=Status.SUCCEEDED).count()
    failed = qs.filter(status=Status.FAILED).count()
    blocked = qs.filter(status=Status.BLOCKED).count()
    rolled_back = qs.filter(status=Status.ROLLED_BACK).count()
    archived = qs.filter(status=Status.ARCHIVED).count()
    provider_call_attempted_count = qs.filter(
        provider_call_attempted=True
    ).count()
    external_call_made_count = qs.filter(external_call_was_made=True).count()
    business_mutation_count = qs.filter(business_mutation_was_made=True).count()

    env = inspect_razorpay_test_env()
    kill_switch = get_or_create_default_runtime_kill_switch()

    blockers: list[str] = []
    if latest_plan is None:
        blockers.append("no_approved_provider_test_plan_available")
    if not env["envFlagEnabled"]:
        blockers.append(f"env_flag_{PHASE_6K_ENV_FLAG}_must_be_true")
    if not env["razorpayKeyIdPresent"]:
        blockers.append("RAZORPAY_KEY_ID env not set")
    if not env["razorpayKeySecretPresent"]:
        blockers.append("RAZORPAY_KEY_SECRET env not set")
    if env["isLiveKey"]:
        blockers.append("razorpay_key_id_is_live_key_refusing")
    if env["razorpayKeyIdPresent"] and not env["isTestKey"]:
        blockers.append("razorpay_key_id_must_start_with_rzp_test")
    if business_mutation_count:
        blockers.append("phase_6k_business_mutation_must_remain_zero")
    if not kill_switch.enabled:
        blockers.append("global_runtime_kill_switch_should_remain_enabled")
    if successful and latest and latest.status == Status.SUCCEEDED:
        # Already executed — operator should rollback / archive next.
        pass

    if blockers:
        next_action = "fix_provider_execution_blockers"
        safe_to_run = False
    elif latest_plan is None:
        next_action = "approve_provider_test_plan_in_phase_6j_first"
        safe_to_run = False
    elif successful >= 1:
        next_action = "rollback_or_archive_phase_6k_execution_attempt"
        safe_to_run = False
    else:
        next_action = (
            "ready_to_execute_single_razorpay_test_order_via_cli"
        )
        safe_to_run = True

    return {
        "organization": (
            {"id": org.id, "code": org.code, "name": org.name}
            if org is not None
            else None
        ),
        "policyVersion": POLICY_VERSION,
        "envReadiness": env,
        "killSwitchActive": kill_switch.enabled,
        "latestApprovedPlan": (
            {
                "planId": latest_plan.plan_id,
                "providerType": latest_plan.provider_type,
                "operationType": latest_plan.operation_type,
                "providerEnvironment": latest_plan.provider_environment,
                "amountPaise": latest_plan.amount_paise,
                "currency": latest_plan.currency,
                "status": latest_plan.status,
                "approvedAt": (
                    latest_plan.approved_at.isoformat()
                    if latest_plan.approved_at
                    else None
                ),
            }
            if latest_plan is not None
            else None
        ),
        "executionAttemptCount": qs.count(),
        "successfulExecutionCount": successful,
        "failedExecutionCount": failed,
        "blockedExecutionCount": blocked,
        "rolledBackExecutionCount": rolled_back,
        "archivedExecutionCount": archived,
        "providerCallAttemptedCount": provider_call_attempted_count,
        "externalCallMadeCount": external_call_made_count,
        "businessMutationCount": business_mutation_count,
        "latestAttempt": (
            serialize_execution_attempt(latest) if latest else None
        ),
        "attempts": [
            serialize_execution_attempt(a) for a in attempts[:25]
        ],
        "policy": (
            get_provider_execution_policy(
                PHASE_6K_ALLOWED_OPERATION
            ).to_dict()
            if get_provider_execution_policy(PHASE_6K_ALLOWED_OPERATION)
            else None
        ),
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "safeToRunPhase6KExecution": safe_to_run,
        "blockers": blockers,
        "warnings": [
            PHASE_6K_WARNING,
            "Razorpay test order remains in the test dashboard; no real money / customer impact.",
        ],
        "nextAction": next_action,
    }


__all__ = (
    "PHASE_6K_WARNING",
    "assert_execution_invariants",
    "serialize_execution_attempt",
    "prepare_single_provider_execution_attempt",
    "execute_single_razorpay_test_order",
    "rollback_single_provider_execution_attempt",
    "archive_single_provider_execution_attempt",
    "inspect_single_provider_execution_attempt",
)
