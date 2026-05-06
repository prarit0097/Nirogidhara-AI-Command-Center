"""Phase 6T - final Phase 6 audit-lock / decision gate.

Phase 6T composes the Phase 6N -> Phase 6S safety chain into a final
attestation record. It never executes a pilot, never calls Razorpay /
Meta Cloud / Delhivery, never sends or queues WhatsApp, never creates
shipment / AWB rows, and never mutates real business models.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import (
    RazorpayPaymentDispatchPilotPlan,
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpayPhase6FinalAuditLock,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)


PHASE_6T_WARNING = (
    "Phase 6T is final-audit-lock only. It NEVER executes a pilot, "
    "NEVER sends or queues WhatsApp, NEVER calls Meta Cloud, Delhivery, "
    "or Razorpay, NEVER creates shipment / AWB rows, and NEVER mutates "
    "real Order / Payment / Shipment / Customer / Lead state. CLI-only "
    "review may create or update RazorpayPhase6FinalAuditLock rows."
)

AUDIT_KIND_READINESS = "razorpay.phase6_final_audit.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.phase6_final_audit.previewed"
AUDIT_KIND_PREPARED = "razorpay.phase6_final_audit.prepared"
AUDIT_KIND_LOCKED = (
    "razorpay.phase6_final_audit.locked_for_future_controlled_pilot_review"
)
AUDIT_KIND_REJECTED = "razorpay.phase6_final_audit.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.phase6_final_audit.archived"
AUDIT_KIND_BLOCKED = "razorpay.phase6_final_audit.blocked"
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.phase6_final_audit.invariant_violation_blocked"
)

PHASE_6T_ALLOWED_EVENTS = {
    "payment.authorized",
    "payment.captured",
    "payment.failed",
    "order.paid",
    "refund.created",
    "refund.processed",
    "payment_link.paid",
    "payment_link.cancelled",
    "payment_link.expired",
}
PHASE_6T_MAX_AMOUNT_PAISE = 100
PHASE_6T_MAX_PILOT_ORDERS = 1


@dataclass(frozen=True)
class Phase6TEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    pilot_plan: RazorpayPaymentDispatchPilotPlan | None
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None
    ledger: RazorpaySandboxPaidStatusLedger | None
    review: RazorpaySandboxStatusReview | None
    event: RazorpayWebhookEvent | None


def _flag_enabled() -> bool:
    return bool(
        getattr(settings, "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED", False)
    )


def _safety_invariants() -> dict[str, bool | str | list[str]]:
    return {
        "phase": "6T",
        "finalAuditOnly": True,
        "futureExecutionAllowedByPhase6T": False,
        "controlledPilotExecutionAllowedInPhase6T": False,
        "pilotExecutionAllowed": False,
        "businessMutationAllowed": False,
        "customerNotificationAllowed": False,
        "providerCallAllowed": False,
        "whatsAppSendAllowed": False,
        "whatsAppQueueAllowed": False,
        "courierBookingAllowed": False,
        "shipmentCreationAllowed": False,
        "awbCreationAllowed": False,
        "frontendExecutionAllowed": False,
        "apiExecutionAllowed": False,
        "reviewStateChanges": "cli_only",
        "forbiddenModels": [
            "Order",
            "Payment",
            "Shipment",
            "DiscountOfferLog",
            "Customer",
            "Lead",
            "WhatsAppMessage",
            "WhatsAppLifecycleEvent",
        ],
    }


def _director_signoff_contract() -> dict[str, Any]:
    return {
        "required": True,
        "phase7AOnly": True,
        "requirements": [
            "explicit_director_written_signoff",
            "internal_staff_cohort_only",
            "max_pilot_orders_1",
            "max_amount_paise_100",
            "provider_flags_reviewed_before_future_phase",
            "no_real_customer_data_without_final_approval",
        ],
    }


def _kill_switch_contract() -> dict[str, Any]:
    return {
        "required": True,
        "requirements": [
            "global_ai_kill_switch_reviewed",
            "whatsapp_automation_flags_remain_false",
            "razorpay_mutation_flags_remain_false",
            "delhivery_live_or_test_not_enabled_by_phase6t",
            "mcp_write_and_provider_tools_remain_disabled",
        ],
    }


def _rollback_contract() -> dict[str, Any]:
    return {
        "required": True,
        "phase6TRollbackScope": "RazorpayPhase6FinalAuditLock_only",
        "futurePilotRollbackRequirements": [
            "abort_without_customer_notification",
            "no_courier_booking_without_final_approval",
            "no_payment_capture_or_refund_without_final_approval",
            "ledger_and_audit_review_before_any_future_execution",
        ],
    }


def _abort_criteria() -> list[dict[str, str]]:
    return [
        {"if": "any_provider_call_attempted", "then": "abort_and_audit"},
        {"if": "any_business_mutation_detected", "then": "abort_and_audit"},
        {"if": "any_whatsapp_send_or_queue_detected", "then": "abort_and_audit"},
        {"if": "any_shipment_or_awb_created", "then": "abort_and_audit"},
        {"if": "any_secret_or_full_pii_exposed", "then": "abort_and_audit"},
    ]


def _operator_checklist() -> list[dict[str, str]]:
    return [
        {"step": "inspect_final_audit_readiness", "surface": "read_only"},
        {"step": "preview_final_audit_lock", "surface": "read_only"},
        {"step": "prepare_final_audit_lock", "surface": "cli_only"},
        {"step": "lock_or_reject_final_audit", "surface": "cli_only"},
        {"step": "review_phase7a_design_only_after_director_approval", "surface": "future"},
    ]


def _final_attestation(full_chain_verified: bool = False) -> dict[str, Any]:
    return {
        "phase": "6T",
        "status": "final_audit_lock_only",
        "fullChainVerified": bool(full_chain_verified),
        "futureControlledPilotAllowedByPhase6T": False,
        "futureControlledPilotMayBeConsideredOnlyIf": [
            "phase6t_lock_status_locked_for_future_controlled_pilot_review",
            "director_signoff_present",
            "global_kill_switch_policy_reviewed",
            "rollback_plan_approved",
            "internal_staff_cohort_only",
            "max_pilot_orders_1",
            "max_amount_paise_100",
            "all_provider_flags_remain_false_until_future_phase",
            "no_real_customer_data",
            "no_live_whatsapp_without_final_approval",
            "no_courier_booking_without_final_approval",
        ],
        "absoluteBlocksStillInForce": [
            "no_live_execution_in_phase6t",
            "no_provider_call_in_phase6t",
            "no_business_mutation_in_phase6t",
        ],
    }


def build_phase6t_final_audit_contract() -> list[dict[str, Any]]:
    rows = [
        ("6N", "business_mutation_sandbox_plan_record_only"),
        ("6O", "approved_for_future_phase6p"),
        ("6P", "sandbox_ledger_only_attempt_executed_or_rolled_back"),
        ("6Q", "approved_for_future_phase6r"),
        ("6R", "approved_for_future_phase6s"),
        ("6S", "approved_for_future_phase6t"),
    ]
    return [
        {
            "phase": phase,
            "label": label,
            "requiredStatus": required,
            "actualStatus": "unknown_until_source_plan_selected",
            "verified": False,
            "mutationAllowedInPhase": False,
            "providerCallAllowedInPhase": False,
            "customerNotificationAllowedInPhase": False,
            "frontendExecutionAllowed": False,
            "apiExecutionAllowed": False,
            "cliOnlyReview": True,
            "requiredEvidence": [],
            "blockers": [],
            "warnings": [],
            "notes": ["Phase 6T final audit lock only"],
        }
        for phase, required in rows
        for label in [f"Phase {phase}"]
    ]


def _contract_with_actuals(
    eligibility: Phase6TEligibility | None = None,
) -> list[dict[str, Any]]:
    rows = build_phase6t_final_audit_contract()
    if eligibility is None:
        return rows
    actuals = {
        "6N": "record_only_webhook_event_present"
        if eligibility.event
        else "missing",
        "6O": eligibility.review.status if eligibility.review else "missing",
        "6P": eligibility.attempt.status if eligibility.attempt else "missing",
        "6Q": eligibility.workflow_gate.status
        if eligibility.workflow_gate
        else "missing",
        "6R": eligibility.readiness_gate.status
        if eligibility.readiness_gate
        else "missing",
        "6S": eligibility.pilot_plan.status
        if eligibility.pilot_plan
        else "missing",
    }
    verified = {
        "6N": eligibility.event is not None,
        "6O": bool(
            eligibility.review
            and eligibility.review.status
            == RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
        ),
        "6P": bool(
            eligibility.attempt
            and eligibility.attempt.status
            in (
                RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
                RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
            )
        ),
        "6Q": bool(
            eligibility.workflow_gate
            and eligibility.workflow_gate.status
            == RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
        ),
        "6R": bool(
            eligibility.readiness_gate
            and eligibility.readiness_gate.status
            == RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
        ),
        "6S": bool(
            eligibility.pilot_plan
            and eligibility.pilot_plan.status
            == RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
        ),
    }
    blockers = set(eligibility.blockers)
    for row in rows:
        phase = row["phase"]
        row["actualStatus"] = actuals[phase]
        row["verified"] = bool(verified[phase] and not blockers)
    return rows


def _snapshot_model(row: Any | None, fields: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        return {"exists": False}
    data = {"exists": True, "id": row.pk}
    for field in fields:
        data[field] = getattr(row, field, None)
    return data


def collect_phase6n_to_6s_audit_snapshot(
    eligibility: Phase6TEligibility | None = None,
) -> dict[str, Any]:
    event = eligibility.event if eligibility else None
    review = eligibility.review if eligibility else None
    ledger = eligibility.ledger if eligibility else None
    attempt = eligibility.attempt if eligibility else None
    workflow = eligibility.workflow_gate if eligibility else None
    readiness = eligibility.readiness_gate if eligibility else None
    plan = eligibility.pilot_plan if eligibility else None
    return {
        "phase6n": _snapshot_model(
            event,
            (
                "source_event_id",
                "event_name",
                "environment",
                "amount_paise",
                "currency",
                "signature_valid",
                "replay_window_valid",
                "idempotency_status",
                "business_mutation_was_made",
                "customer_notification_sent",
                "raw_secret_exposed",
                "full_pii_exposed",
            ),
        ),
        "phase6o": _snapshot_model(
            review,
            (
                "status",
                "synthetic_eligible",
                "business_mutation_was_made",
                "customer_notification_sent",
                "provider_call_attempted",
            ),
        ),
        "phase6p": {
            "ledger": _snapshot_model(
                ledger,
                (
                    "current_state",
                    "business_mutation_was_made",
                    "real_order_mutation_was_made",
                    "real_payment_mutation_was_made",
                    "customer_notification_sent",
                    "provider_call_attempted",
                    "rolled_back",
                ),
            ),
            "attempt": _snapshot_model(
                attempt,
                (
                    "status",
                    "business_mutation_was_made",
                    "real_order_mutation_was_made",
                    "real_payment_mutation_was_made",
                    "customer_notification_sent",
                    "provider_call_attempted",
                ),
            ),
        },
        "phase6q": _snapshot_model(
            workflow,
            (
                "status",
                "workflow_mutation_allowed_in_phase6q",
                "real_order_mutation_was_made",
                "real_payment_mutation_was_made",
                "shipment_mutation_was_made",
                "discount_mutation_was_made",
                "customer_notification_sent",
                "provider_call_attempted",
            ),
        ),
        "phase6r": _snapshot_model(
            readiness,
            (
                "status",
                "dispatch_readiness_allowed_in_phase6r",
                "real_order_mutation_was_made",
                "real_payment_mutation_was_made",
                "shipment_mutation_was_made",
                "shipment_created",
                "whatsapp_message_created",
                "whatsapp_message_queued",
                "customer_notification_sent",
                "meta_cloud_call_attempted",
                "delhivery_call_attempted",
                "provider_call_attempted",
            ),
        ),
        "phase6s": _snapshot_model(
            plan,
            (
                "status",
                "pilot_execution_allowed_in_phase6s",
                "live_send_allowed_in_phase6s",
                "courier_booking_allowed_in_phase6s",
                "provider_call_allowed_in_phase6s",
                "real_order_mutation_was_made",
                "real_payment_mutation_was_made",
                "shipment_mutation_was_made",
                "shipment_created",
                "awb_created",
                "whatsapp_message_created",
                "whatsapp_message_queued",
                "customer_notification_sent",
                "meta_cloud_call_attempted",
                "delhivery_call_attempted",
                "razorpay_call_attempted",
                "provider_call_attempted",
            ),
        ),
    }


def _load_pilot_plan(plan_id: int | None) -> RazorpayPaymentDispatchPilotPlan | None:
    qs = RazorpayPaymentDispatchPilotPlan.objects.select_related(
        "source_readiness_gate",
        "source_workflow_gate",
        "source_attempt",
        "source_ledger",
        "source_review",
        "razorpay_webhook_event",
    )
    if plan_id:
        return qs.filter(pk=plan_id).first()
    return (
        qs.filter(
            status=RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
        )
        .order_by("-created_at")
        .first()
    )


def _add_true_blocker(
    blockers: list[str], obj: Any | None, attr: str, label: str
) -> None:
    if obj is not None and bool(getattr(obj, attr, False)):
        blockers.append(f"{label}_{attr}")


def validate_phase6t_source_pilot_plan_eligibility(
    source_pilot_plan: RazorpayPaymentDispatchPilotPlan | int | None,
    *,
    require_env_flag: bool = False,
) -> Phase6TEligibility:
    blockers: list[str] = []
    warnings: list[str] = []
    if require_env_flag and not _flag_enabled():
        blockers.append("RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED_must_be_true")

    plan = (
        _load_pilot_plan(source_pilot_plan)
        if isinstance(source_pilot_plan, int) or source_pilot_plan is None
        else source_pilot_plan
    )
    if plan is None:
        blockers.append("approved_phase6s_pilot_plan_not_found")
        return Phase6TEligibility(
            False, tuple(blockers), tuple(warnings), None, None, None, None, None, None, None
        )

    readiness = plan.source_readiness_gate
    workflow = plan.source_workflow_gate
    attempt = plan.source_attempt
    ledger = plan.source_ledger
    review = plan.source_review
    event = plan.razorpay_webhook_event

    if plan.status != RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T:
        blockers.append(
            f"phase6s_pilot_plan_status_must_be_approved_for_future_phase6t_was_{plan.status}"
        )
    for attr in (
        "pilot_execution_allowed_in_phase6s",
        "live_send_allowed_in_phase6s",
        "courier_booking_allowed_in_phase6s",
        "provider_call_allowed_in_phase6s",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_mutation_was_made",
        "shipment_created",
        "awb_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "customer_notification_sent",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "razorpay_call_attempted",
        "provider_call_attempted",
    ):
        _add_true_blocker(blockers, plan, attr, "phase6s_pilot_plan")

    if readiness is None:
        blockers.append("linked_phase6r_readiness_gate_not_found")
    elif (
        readiness.status
        != RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
    ):
        blockers.append(
            f"phase6r_readiness_status_must_be_approved_for_future_phase6s_was_{readiness.status}"
        )
    for attr in (
        "dispatch_readiness_allowed_in_phase6r",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_mutation_was_made",
        "shipment_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "customer_notification_sent",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "razorpay_call_attempted",
        "provider_call_attempted",
    ):
        _add_true_blocker(blockers, readiness, attr, "phase6r_readiness")

    if workflow is None:
        blockers.append("linked_phase6q_workflow_gate_not_found")
    elif (
        workflow.status
        != RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
    ):
        blockers.append(
            f"phase6q_workflow_gate_status_must_be_approved_for_future_phase6r_was_{workflow.status}"
        )
    for attr in (
        "workflow_mutation_allowed_in_phase6q",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_mutation_was_made",
        "discount_mutation_was_made",
        "customer_notification_sent",
        "provider_call_attempted",
    ):
        _add_true_blocker(blockers, workflow, attr, "phase6q_workflow_gate")

    if attempt is None:
        blockers.append("linked_phase6p_attempt_not_found")
    elif attempt.status not in (
        RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
        RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
    ):
        blockers.append(f"phase6p_attempt_status_{attempt.status}_not_eligible")
    for attr in (
        "business_mutation_was_made",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "customer_notification_sent",
        "provider_call_attempted",
    ):
        _add_true_blocker(blockers, attempt, attr, "phase6p_attempt")

    if ledger is None:
        blockers.append("linked_phase6p_ledger_not_found")
    for attr in (
        "business_mutation_was_made",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "customer_notification_sent",
        "provider_call_attempted",
    ):
        _add_true_blocker(blockers, ledger, attr, "phase6p_ledger")

    if review is None:
        blockers.append("linked_phase6o_review_not_found")
    elif review.status != RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P:
        blockers.append(
            f"phase6o_review_status_must_be_approved_for_future_phase6p_was_{review.status}"
        )
    for attr in (
        "business_mutation_was_made",
        "customer_notification_sent",
        "provider_call_attempted",
    ):
        _add_true_blocker(blockers, review, attr, "phase6o_review")

    if event is None:
        blockers.append("linked_razorpay_webhook_event_not_found")
    else:
        if not event.signature_valid:
            blockers.append("source_event_signature_invalid")
        if not event.replay_window_valid:
            blockers.append("source_event_replay_window_invalid")
        if event.idempotency_status != RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN:
            blockers.append("source_event_idempotency_must_be_first_seen")
        if event.event_name not in PHASE_6T_ALLOWED_EVENTS:
            blockers.append(f"source_event_not_phase6t_allowlisted_{event.event_name}")
        if event.environment not in (
            RazorpayWebhookEvent.Environment.TEST,
            "sandbox",
        ):
            blockers.append(
                f"provider_environment_must_be_test_or_sandbox_was_{event.environment}"
            )
        if event.amount_paise is not None and event.amount_paise > PHASE_6T_MAX_AMOUNT_PAISE:
            blockers.append(f"amount_paise_must_be_<=_{PHASE_6T_MAX_AMOUNT_PAISE}")
        for attr in (
            "business_mutation_was_made",
            "customer_notification_sent",
            "raw_secret_exposed",
            "full_pii_exposed",
        ):
            _add_true_blocker(blockers, event, attr, "source_event")
        if event.scrubbed_keys:
            blockers.append("source_event_full_pii_must_be_absent")

    return Phase6TEligibility(
        not blockers,
        tuple(blockers),
        tuple(warnings),
        plan,
        readiness,
        workflow,
        attempt,
        ledger,
        review,
        event,
    )


def assert_phase6t_no_live_execution_or_provider_call(
    row: RazorpayPhase6FinalAuditLock | None = None,
) -> None:
    values = {
        "future_execution_allowed_by_phase6t": False,
        "controlled_pilot_execution_allowed_in_phase6t": False,
        "real_order_mutation_was_made": False,
        "real_payment_mutation_was_made": False,
        "shipment_mutation_was_made": False,
        "shipment_created": False,
        "awb_created": False,
        "whatsapp_message_created": False,
        "whatsapp_message_queued": False,
        "customer_notification_sent": False,
        "meta_cloud_call_attempted": False,
        "delhivery_call_attempted": False,
        "razorpay_call_attempted": False,
        "provider_call_attempted": False,
        "raw_secret_exposed": False,
        "full_pii_exposed": False,
    }
    if row is None:
        return
    violations = [
        key for key, expected in values.items() if getattr(row, key) != expected
    ]
    if violations:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text="Phase 6T invariant violation blocked",
            tone=AuditEvent.Tone.DANGER,
            payload={
                "phase": "6T",
                "audit_lock_id": row.pk,
                "status": row.status,
                "blockers": violations,
                **_audit_false_payload(),
            },
        )
        raise ValueError(f"Phase 6T invariant violation: {', '.join(violations)}")


def _audit_false_payload() -> dict[str, bool]:
    return {
        "future_execution_allowed_by_phase6t": False,
        "controlled_pilot_execution_allowed_in_phase6t": False,
        "real_order_mutation_was_made": False,
        "real_payment_mutation_was_made": False,
        "shipment_mutation_was_made": False,
        "shipment_created": False,
        "awb_created": False,
        "whatsapp_message_created": False,
        "whatsapp_message_queued": False,
        "customer_notification_sent": False,
        "meta_cloud_call_attempted": False,
        "delhivery_call_attempted": False,
        "razorpay_call_attempted": False,
        "provider_call_attempted": False,
    }


def _serialize_audit_lock(row: RazorpayPhase6FinalAuditLock) -> dict[str, Any]:
    return {
        "id": row.pk,
        "sourcePilotPlanId": row.source_pilot_plan_id,
        "sourceReadinessGateId": row.source_readiness_gate_id,
        "sourceWorkflowGateId": row.source_workflow_gate_id,
        "sourceAttemptId": row.source_attempt_id,
        "sourceLedgerId": row.source_ledger_id,
        "sourceReviewId": row.source_review_id,
        "sourceEventPk": row.source_event_id,
        "sourceEventId": row.source_event_id,
        "eventName": row.event_name,
        "providerEnvironment": row.provider_environment,
        "amountPaise": row.amount_paise,
        "currency": row.currency,
        "status": row.status,
        "phase6NVerified": row.phase6n_verified,
        "phase6OVerified": row.phase6o_verified,
        "phase6PVerified": row.phase6p_verified,
        "phase6QVerified": row.phase6q_verified,
        "phase6RVerified": row.phase6r_verified,
        "phase6SVerified": row.phase6s_verified,
        "fullChainVerified": row.full_chain_verified,
        "finalAuditPassed": row.final_audit_passed,
        "directorSignoffRequired": row.director_signoff_required,
        "killSwitchRequired": row.kill_switch_required,
        "rollbackRequired": row.rollback_required,
        "futureExecutionAllowedByPhase6T": row.future_execution_allowed_by_phase6t,
        "controlledPilotExecutionAllowedInPhase6T": (
            row.controlled_pilot_execution_allowed_in_phase6t
        ),
        "manualReviewRequired": row.manual_review_required,
        "internalOnly": row.internal_only,
        "maxPilotOrders": row.max_pilot_orders,
        "maxAmountPaise": row.max_amount_paise,
        "realOrderMutationWasMade": row.real_order_mutation_was_made,
        "realPaymentMutationWasMade": row.real_payment_mutation_was_made,
        "shipmentMutationWasMade": row.shipment_mutation_was_made,
        "shipmentCreated": row.shipment_created,
        "awbCreated": row.awb_created,
        "whatsAppMessageCreated": row.whatsapp_message_created,
        "whatsAppMessageQueued": row.whatsapp_message_queued,
        "customerNotificationSent": row.customer_notification_sent,
        "metaCloudCallAttempted": row.meta_cloud_call_attempted,
        "delhiveryCallAttempted": row.delhivery_call_attempted,
        "razorpayCallAttempted": row.razorpay_call_attempted,
        "providerCallAttempted": row.provider_call_attempted,
        "envFlagFlipDetected": row.env_flag_flip_detected,
        "rawSecretExposed": row.raw_secret_exposed,
        "fullPiiExposed": row.full_pii_exposed,
        "phase6NSnapshot": row.phase6n_snapshot,
        "phase6OSnapshot": row.phase6o_snapshot,
        "phase6PSnapshot": row.phase6p_snapshot,
        "phase6QSnapshot": row.phase6q_snapshot,
        "phase6RSnapshot": row.phase6r_snapshot,
        "phase6SSnapshot": row.phase6s_snapshot,
        "finalAttestation": row.final_attestation,
        "directorSignoffContract": row.director_signoff_contract,
        "killSwitchContract": row.kill_switch_contract,
        "rollbackContract": row.rollback_contract,
        "abortCriteria": list(row.abort_criteria or []),
        "operatorChecklist": list(row.operator_checklist or []),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "safetyInvariants": row.safety_invariants,
        "idempotencyKey": row.idempotency_key,
        "reviewedAt": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "archivedAt": row.archived_at.isoformat() if row.archived_at else None,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def _idempotency_key(plan: RazorpayPaymentDispatchPilotPlan) -> str:
    return f"phase6t::final_audit_lock::pilot_plan::{plan.pk}"


def preview_phase6t_final_audit_lock(plan_id: int | None = None) -> dict[str, Any]:
    eligibility = validate_phase6t_source_pilot_plan_eligibility(
        plan_id, require_env_flag=False
    )
    snapshot = collect_phase6n_to_6s_audit_snapshot(eligibility)
    contract = _contract_with_actuals(eligibility)
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 6T final audit preview plan_id={plan_id or ''}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6T",
            "source_phase6s_plan_id": (
                eligibility.pilot_plan.pk if eligibility.pilot_plan else None
            ),
            "source_phase6r_readiness_id": (
                eligibility.readiness_gate.pk if eligibility.readiness_gate else None
            ),
            "source_phase6q_gate_id": (
                eligibility.workflow_gate.pk if eligibility.workflow_gate else None
            ),
            "source_attempt_id": eligibility.attempt.pk if eligibility.attempt else None,
            "source_ledger_id": eligibility.ledger.pk if eligibility.ledger else None,
            "source_review_id": eligibility.review.pk if eligibility.review else None,
            "source_event_id": eligibility.event.source_event_id if eligibility.event else "",
            "status": "preview",
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings),
            **_audit_false_payload(),
        },
    )
    return {
        "phase": "6T",
        "status": "final_audit_lock_only",
        "found": eligibility.pilot_plan is not None,
        "eligible": eligibility.eligible,
        "sourcePilotPlanId": eligibility.pilot_plan.pk if eligibility.pilot_plan else None,
        "auditChain": contract,
        "snapshot": snapshot,
        "finalAttestation": _final_attestation(eligibility.eligible),
        "directorSignoffContract": _director_signoff_contract(),
        "killSwitchContract": _kill_switch_contract(),
        "rollbackContract": _rollback_contract(),
        "abortCriteria": _abort_criteria(),
        "operatorChecklist": _operator_checklist(),
        "safetyInvariants": _safety_invariants(),
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_6T_WARNING],
        "nextAction": (
            "enable_phase6t_flag_and_prepare_final_audit_lock"
            if eligibility.eligible
            else "fix_phase6t_source_chain_blockers"
        ),
    }


def prepare_phase6t_final_audit_lock(
    plan_id: int | None = None,
    *,
    requested_by=None,
) -> dict[str, Any]:
    eligibility = validate_phase6t_source_pilot_plan_eligibility(
        plan_id, require_env_flag=True
    )
    if not eligibility.eligible or eligibility.pilot_plan is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 6T prepare blocked plan_id={plan_id or ''}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "6T",
                "source_phase6s_plan_id": plan_id,
                "status": "blocked",
                "blockers": list(eligibility.blockers),
                "warnings": list(eligibility.warnings),
                **_audit_false_payload(),
            },
        )
        return {
            "phase": "6T",
            "created": False,
            "reused": False,
            "auditLock": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_6T_WARNING],
            "nextAction": "fix_phase6t_eligibility_blockers_or_enable_final_audit_lock_flag",
        }

    plan = eligibility.pilot_plan
    snapshot = collect_phase6n_to_6s_audit_snapshot(eligibility)
    contract = _contract_with_actuals(eligibility)
    idempotency = _idempotency_key(plan)
    with transaction.atomic():
        existing = (
            RazorpayPhase6FinalAuditLock.objects.filter(idempotency_key=idempotency)
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "6T",
                "created": False,
                "reused": True,
                "auditLock": _serialize_audit_lock(existing),
                "blockers": [],
                "warnings": [PHASE_6T_WARNING],
                "nextAction": "final_audit_lock_pending_manual_review",
            }
        row = RazorpayPhase6FinalAuditLock(
            source_pilot_plan=plan,
            source_readiness_gate=eligibility.readiness_gate,
            source_workflow_gate=eligibility.workflow_gate,
            source_attempt=eligibility.attempt,
            source_ledger=eligibility.ledger,
            source_review=eligibility.review,
            source_event_record=eligibility.event,
            source_event_id=eligibility.event.source_event_id if eligibility.event else "",
            event_name=eligibility.event.event_name if eligibility.event else plan.event_name,
            provider_environment=(
                eligibility.event.environment if eligibility.event else plan.provider_environment
            ),
            amount_paise=eligibility.event.amount_paise if eligibility.event else plan.amount_paise,
            currency=eligibility.event.currency if eligibility.event else plan.currency,
            status=RazorpayPhase6FinalAuditLock.Status.PENDING_MANUAL_REVIEW,
            phase6n_verified=True,
            phase6o_verified=True,
            phase6p_verified=True,
            phase6q_verified=True,
            phase6r_verified=True,
            phase6s_verified=True,
            full_chain_verified=True,
            final_audit_passed=True,
            future_execution_allowed_by_phase6t=False,
            controlled_pilot_execution_allowed_in_phase6t=False,
            max_pilot_orders=PHASE_6T_MAX_PILOT_ORDERS,
            max_amount_paise=PHASE_6T_MAX_AMOUNT_PAISE,
            phase6n_snapshot=snapshot["phase6n"],
            phase6o_snapshot=snapshot["phase6o"],
            phase6p_snapshot=snapshot["phase6p"],
            phase6q_snapshot=snapshot["phase6q"],
            phase6r_snapshot=snapshot["phase6r"],
            phase6s_snapshot=snapshot["phase6s"],
            final_attestation=_final_attestation(True),
            director_signoff_contract=_director_signoff_contract(),
            kill_switch_contract=_kill_switch_contract(),
            rollback_contract=_rollback_contract(),
            abort_criteria=_abort_criteria(),
            operator_checklist=_operator_checklist(),
            blockers=[],
            warnings=[PHASE_6T_WARNING],
            safety_invariants={**_safety_invariants(), "auditChain": contract},
            idempotency_key=idempotency,
        )
        assert_phase6t_no_live_execution_or_provider_call(row)
        try:
            row.save()
        except IntegrityError:
            row = RazorpayPhase6FinalAuditLock.objects.get(idempotency_key=idempotency)
            return {
                "phase": "6T",
                "created": False,
                "reused": True,
                "auditLock": _serialize_audit_lock(row),
                "blockers": [],
                "warnings": [PHASE_6T_WARNING],
                "nextAction": "final_audit_lock_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 6T final audit lock prepared audit_lock_id={row.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6T",
            "audit_lock_id": row.pk,
            "source_phase6s_plan_id": plan.pk,
            "source_phase6r_readiness_id": row.source_readiness_gate_id,
            "source_phase6q_gate_id": row.source_workflow_gate_id,
            "source_attempt_id": row.source_attempt_id,
            "source_ledger_id": row.source_ledger_id,
            "source_review_id": row.source_review_id,
            "source_event_id": row.source_event_id,
            "status": row.status,
            "blockers": [],
            "warnings": [PHASE_6T_WARNING],
            **_audit_false_payload(),
        },
    )
    return {
        "phase": "6T",
        "created": True,
        "reused": False,
        "auditLock": _serialize_audit_lock(row),
        "blockers": [],
        "warnings": [PHASE_6T_WARNING],
        "nextAction": "final_audit_lock_pending_manual_review",
    }


_TRANSITIONABLE_FROM = {
    RazorpayPhase6FinalAuditLock.Status.DRAFT,
    RazorpayPhase6FinalAuditLock.Status.PENDING_MANUAL_REVIEW,
}


def _transition(
    audit_lock_id: int,
    *,
    new_status: str,
    audit_kind: str,
    by_user=None,
    reason: str = "",
    archive: bool = False,
    require_reason: bool = False,
) -> dict[str, Any]:
    row = RazorpayPhase6FinalAuditLock.objects.filter(pk=audit_lock_id).first()
    if row is None:
        return {
            "phase": "6T",
            "ok": False,
            "auditLock": None,
            "blockers": ["final_audit_lock_not_found"],
            "warnings": [PHASE_6T_WARNING],
            "nextAction": "verify_audit_lock_id",
        }
    if not _flag_enabled():
        return {
            "phase": "6T",
            "ok": False,
            "auditLock": _serialize_audit_lock(row),
            "blockers": ["RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED_must_be_true"],
            "warnings": [PHASE_6T_WARNING],
            "nextAction": "enable_final_audit_lock_flag_before_cli_review",
        }
    if archive:
        if row.status == RazorpayPhase6FinalAuditLock.Status.ARCHIVED:
            return {
                "phase": "6T",
                "ok": False,
                "auditLock": _serialize_audit_lock(row),
                "blockers": ["final_audit_lock_already_archived"],
                "warnings": [PHASE_6T_WARNING],
                "nextAction": "verify_audit_lock_id",
            }
    elif row.status not in _TRANSITIONABLE_FROM:
        return {
            "phase": "6T",
            "ok": False,
            "auditLock": _serialize_audit_lock(row),
            "blockers": [f"final_audit_lock_status_{row.status}_not_transitionable"],
            "warnings": [PHASE_6T_WARNING],
            "nextAction": "verify_audit_lock_id",
        }
    if require_reason and not reason.strip():
        return {
            "phase": "6T",
            "ok": False,
            "auditLock": _serialize_audit_lock(row),
            "blockers": ["manual_review_reason_must_be_non_empty"],
            "warnings": [PHASE_6T_WARNING],
            "nextAction": "supply_manual_review_reason",
        }

    assert_phase6t_no_live_execution_or_provider_call(row)
    row.status = new_status
    if archive:
        row.archived_by = by_user
        row.archived_at = timezone.now()
        row.archive_reason = (reason or "")[:200]
    else:
        row.reviewed_by = by_user
        row.reviewed_at = timezone.now()
        row.review_reason = (reason or "")[:200]
    row.save()

    write_event(
        kind=audit_kind,
        text=f"Phase 6T final audit lock {new_status} audit_lock_id={row.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6T",
            "audit_lock_id": row.pk,
            "source_phase6s_plan_id": row.source_pilot_plan_id,
            "source_phase6r_readiness_id": row.source_readiness_gate_id,
            "source_phase6q_gate_id": row.source_workflow_gate_id,
            "source_attempt_id": row.source_attempt_id,
            "source_ledger_id": row.source_ledger_id,
            "source_review_id": row.source_review_id,
            "source_event_id": row.source_event_id,
            "status": row.status,
            "blockers": [],
            "warnings": [PHASE_6T_WARNING],
            **_audit_false_payload(),
        },
    )
    return {
        "phase": "6T",
        "ok": True,
        "auditLock": _serialize_audit_lock(row),
        "blockers": [],
        "warnings": [PHASE_6T_WARNING],
        "nextAction": "phase_6_final_audit_locked_for_future_review"
        if new_status
        == RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
        else "final_audit_lock_review_state_updated",
    }


def lock_phase6t_final_audit_record(
    audit_lock_id: int, *, reviewed_by=None, reason: str = ""
) -> dict[str, Any]:
    return _transition(
        audit_lock_id,
        new_status=RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW,
        audit_kind=AUDIT_KIND_LOCKED,
        by_user=reviewed_by,
        reason=reason,
        require_reason=True,
    )


def reject_phase6t_final_audit_lock(
    audit_lock_id: int, *, reviewed_by=None, reason: str = ""
) -> dict[str, Any]:
    return _transition(
        audit_lock_id,
        new_status=RazorpayPhase6FinalAuditLock.Status.REJECTED,
        audit_kind=AUDIT_KIND_REJECTED,
        by_user=reviewed_by,
        reason=reason,
    )


def archive_phase6t_final_audit_lock(
    audit_lock_id: int, *, archived_by=None, reason: str = ""
) -> dict[str, Any]:
    return _transition(
        audit_lock_id,
        new_status=RazorpayPhase6FinalAuditLock.Status.ARCHIVED,
        audit_kind=AUDIT_KIND_ARCHIVED,
        by_user=archived_by,
        reason=reason,
        archive=True,
    )


def summarize_phase6t_final_audit_locks(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayPhase6FinalAuditLock.objects.all().order_by("-created_at")
    Status = RazorpayPhase6FinalAuditLock.Status
    counts = {
        "draft": qs.filter(status=Status.DRAFT).count(),
        "pendingManualReview": qs.filter(status=Status.PENDING_MANUAL_REVIEW).count(),
        "lockedForFutureControlledPilotReview": qs.filter(
            status=Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
        ).count(),
        "rejected": qs.filter(status=Status.REJECTED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
        "futureExecutionAllowedByPhase6T": qs.filter(
            future_execution_allowed_by_phase6t=True
        ).count(),
        "controlledPilotExecutionAllowedInPhase6T": qs.filter(
            controlled_pilot_execution_allowed_in_phase6t=True
        ).count(),
        "realOrderMutationWasMade": qs.filter(real_order_mutation_was_made=True).count(),
        "realPaymentMutationWasMade": qs.filter(real_payment_mutation_was_made=True).count(),
        "shipmentMutationWasMade": qs.filter(shipment_mutation_was_made=True).count(),
        "shipmentCreated": qs.filter(shipment_created=True).count(),
        "awbCreated": qs.filter(awb_created=True).count(),
        "whatsAppMessageCreated": qs.filter(whatsapp_message_created=True).count(),
        "whatsAppMessageQueued": qs.filter(whatsapp_message_queued=True).count(),
        "customerNotificationSent": qs.filter(customer_notification_sent=True).count(),
        "metaCloudCallAttempted": qs.filter(meta_cloud_call_attempted=True).count(),
        "delhiveryCallAttempted": qs.filter(delhivery_call_attempted=True).count(),
        "razorpayCallAttempted": qs.filter(razorpay_call_attempted=True).count(),
        "providerCallAttempted": qs.filter(provider_call_attempted=True).count(),
    }
    return {
        "counts": counts,
        "items": [_serialize_audit_lock(row) for row in qs[: max(1, min(limit, 200))]],
    }


def inspect_phase6t_final_audit_lock_readiness() -> dict[str, Any]:
    summary = summarize_phase6t_final_audit_locks()
    counts = summary["counts"]
    blockers: list[str] = []
    warnings: list[str] = [PHASE_6T_WARNING]
    approved_phase6s_count = RazorpayPaymentDispatchPilotPlan.objects.filter(
        status=RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
    ).count()
    for key in (
        "futureExecutionAllowedByPhase6T",
        "controlledPilotExecutionAllowedInPhase6T",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "shipmentMutationWasMade",
        "shipmentCreated",
        "awbCreated",
        "whatsAppMessageCreated",
        "whatsAppMessageQueued",
        "customerNotificationSent",
        "metaCloudCallAttempted",
        "delhiveryCallAttempted",
        "razorpayCallAttempted",
        "providerCallAttempted",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(f"phase6t_final_audit_lock_{key}_observed_must_be_zero")
    locked_count = counts["lockedForFutureControlledPilotReview"]
    safe_to_consider_future_pilot = bool(not blockers and locked_count >= 1)
    if blockers:
        next_action = "fix_phase6t_safety_blockers"
    elif approved_phase6s_count == 0:
        next_action = "missing_approved_phase6s_pilot_plan_for_final_audit_lock"
    elif locked_count == 0:
        next_action = "prepare_and_cli_lock_phase6t_final_audit_record"
    else:
        next_action = "phase6_series_audit_locked_future_phase_requires_director_approval"
    return {
        "phase": "6T",
        "status": "final_audit_lock_only",
        "latestCompletedPreviousPhase": "6S",
        "nextPhase": "Phase 7A or future controlled-pilot execution decision after explicit Director approval",
        "razorpayPhase6FinalAuditLockEnabled": _flag_enabled(),
        "futureControlledPilotAllowedByPhase6T": False,
        "controlledPilotExecutionAllowedInPhase6T": False,
        "pilotExecutionAllowed": False,
        "realBusinessMutation": False,
        "realOrderMutation": False,
        "realPaymentMutation": False,
        "whatsAppSend": False,
        "whatsAppQueued": False,
        "metaCloudCall": False,
        "delhiveryCall": False,
        "razorpayCall": False,
        "shipmentCreated": False,
        "awbCreated": False,
        "customerNotification": False,
        "providerCall": False,
        "approvedPhase6SPilotPlanCount": approved_phase6s_count,
        "finalAuditLockCounts": counts,
        "auditChain": build_phase6t_final_audit_contract(),
        "finalAttestation": _final_attestation(safe_to_consider_future_pilot),
        "directorSignoffContract": _director_signoff_contract(),
        "killSwitchContract": _kill_switch_contract(),
        "rollbackContract": _rollback_contract(),
        "abortCriteria": _abort_criteria(),
        "operatorChecklist": _operator_checklist(),
        "safetyInvariants": _safety_invariants(),
        "safeToStartFutureControlledPilot": safe_to_consider_future_pilot,
        "safeToStartPhase7A": False,
        "executionPath": "cli_only_review",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentFinalAuditLocks": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("finalAuditLockCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 6T final audit lock readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6T",
            "status": report.get("status") or "",
            "audit_lock_id": None,
            "source_phase6s_plan_id": None,
            "locked_for_future_controlled_pilot_review": int(
                counts.get("lockedForFutureControlledPilotReview") or 0
            ),
            "blockers": list(report.get("blockers") or []),
            "warnings": list(report.get("warnings") or []),
            "future_execution_allowed_by_phase6t": False,
            "controlled_pilot_execution_allowed_in_phase6t": False,
            **_audit_false_payload(),
        },
    )


__all__ = (
    "PHASE_6T_WARNING",
    "PHASE_6T_ALLOWED_EVENTS",
    "PHASE_6T_MAX_AMOUNT_PAISE",
    "PHASE_6T_MAX_PILOT_ORDERS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_LOCKED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase6TEligibility",
    "inspect_phase6t_final_audit_lock_readiness",
    "build_phase6t_final_audit_contract",
    "collect_phase6n_to_6s_audit_snapshot",
    "validate_phase6t_source_pilot_plan_eligibility",
    "preview_phase6t_final_audit_lock",
    "prepare_phase6t_final_audit_lock",
    "lock_phase6t_final_audit_record",
    "reject_phase6t_final_audit_lock",
    "archive_phase6t_final_audit_lock",
    "summarize_phase6t_final_audit_locks",
    "assert_phase6t_no_live_execution_or_provider_call",
    "emit_readiness_inspected_audit",
    "_serialize_audit_lock",
)
