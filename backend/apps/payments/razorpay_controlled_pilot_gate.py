"""Phase 7B - Controlled Pilot Execution Gate (gate-only).

Gate-only layer that converts a locked Phase 6T
:class:`RazorpayPhase6FinalAuditLock` (status
``locked_for_future_controlled_pilot_review``) into a
:class:`RazorpayControlledPilotExecutionGate` review record. Phase 7B
**never** executes a pilot, **never** calls Razorpay / Meta Cloud /
Delhivery / Vapi, **never** sends or queues a WhatsApp message,
**never** creates a shipment / AWB, **never** mutates real ``Order``
/ ``Payment`` / ``Customer`` / ``Lead`` / ``WhatsAppMessage`` /
``WhatsAppLifecycleEvent`` rows. Approving a gate only flips
``status`` to ``approved_for_future_phase7c_execution_review``.

Public surface:

- :func:`build_phase7b_controlled_pilot_gate_contract`
- :func:`inspect_phase7b_controlled_pilot_gate_readiness`
- :func:`validate_phase7b_source_lock_eligibility`
- :func:`preview_phase7b_controlled_pilot_gate`
- :func:`prepare_phase7b_controlled_pilot_gate`
- :func:`dry_run_phase7b_controlled_pilot_gate`
- :func:`rollback_dry_run_phase7b_controlled_pilot_gate`
- :func:`approve_phase7b_controlled_pilot_gate`
- :func:`reject_phase7b_controlled_pilot_gate`
- :func:`archive_phase7b_controlled_pilot_gate`
- :func:`summarize_phase7b_controlled_pilot_gates`
- :func:`assert_phase7b_no_unauthorised_provider_call`
- :func:`serialize_phase7b_gate`
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
    RazorpayControlledPilotExecutionGate,
    RazorpayControlledPilotGateDryRunRecord,
    RazorpayControlledPilotGateRollbackDryRunRecord,
    RazorpayPaymentDispatchPilotPlan,
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpayPhase6FinalAuditLock,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)


PHASE_7B_WARNING = (
    "Phase 7B is the controlled pilot execution gate (gate-only). It "
    "NEVER executes a pilot, NEVER calls Razorpay / Meta Cloud / "
    "Delhivery / Vapi, NEVER sends or queues a WhatsApp message, "
    "NEVER creates a shipment / AWB, NEVER mutates real Order / "
    "Payment / Customer / Lead / WhatsAppMessage / "
    "WhatsAppLifecycleEvent rows. Approving a gate only marks it "
    "``approved_for_future_phase7c_execution_review``. Review state "
    "changes are CLI-only - no API endpoint or frontend button "
    "dispatches Phase 7B approval."
)


# Audit kinds Phase 7B emits. All <= 64 chars.
AUDIT_KIND_READINESS = "razorpay.controlled_pilot_gate.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.controlled_pilot_gate.previewed"
AUDIT_KIND_PREPARED = "razorpay.controlled_pilot_gate.prepared"
AUDIT_KIND_DRY_RUN_PASSED = "razorpay.controlled_pilot_gate.dry_run_passed"
AUDIT_KIND_DRY_RUN_FAILED = "razorpay.controlled_pilot_gate.dry_run_failed"
AUDIT_KIND_ROLLBACK_DRY_RUN_PASSED = (
    "razorpay.controlled_pilot_gate.rollback_dry_run_passed"
)
AUDIT_KIND_ROLLBACK_DRY_RUN_FAILED = (
    "razorpay.controlled_pilot_gate.rollback_dry_run_failed"
)
AUDIT_KIND_APPROVED_FOR_PHASE7C_REVIEW = (
    "razorpay.controlled_pilot_gate.approved_for_phase7c_review"
)
AUDIT_KIND_REJECTED = "razorpay.controlled_pilot_gate.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.controlled_pilot_gate.archived"
AUDIT_KIND_BLOCKED = "razorpay.controlled_pilot_gate.blocked"
AUDIT_KIND_KILL_SWITCH_DISABLED_BLOCKED = (
    "razorpay.controlled_pilot_gate.kill_switch_disabled_blocked"
)
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.controlled_pilot_gate.invariant_violation_blocked"
)


PHASE_7B_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "execute_pilot",
    "start_pilot",
    "run_pilot",
    "send_whatsapp_template",
    "send_freeform_whatsapp",
    "queue_whatsapp_outbound",
    "create_whatsapp_message_outbound",
    "create_whatsapp_lifecycle_event",
    "create_whatsapp_handoff_to_call",
    "call_meta_cloud_api",
    "call_delhivery_api",
    "create_shipment",
    "create_awb",
    "book_courier_pickup",
    "place_vapi_call",
    "call_razorpay_api",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "mutate_real_order_status",
    "mutate_real_payment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "execute_pilot_via_frontend",
    "execute_pilot_via_api_endpoint",
    "approve_pilot_via_api_endpoint",
)


PHASE_7B_MAX_SAFE_AMOUNT_PAISE = 100
PHASE_7B_DEFAULT_MAX_PILOT_ORDERS = 1


PHASE_7B_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "raw_payload",
    "raw_signature",
    "raw_secret",
    "phone",
    "email",
    "address",
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
    "verify_token",
    "app_secret",
    "access_token",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "META_WA_TOKEN",
    "META_WA_APP_SECRET",
)


def _flag_enabled() -> bool:
    return bool(
        getattr(settings, "PHASE7_CONTROLLED_PILOT_GATE_ENABLED", False)
    )


def _safety_invariants() -> dict[str, Any]:
    return {
        "phase": "7B",
        "controlledPilotGateOnly": True,
        "controlledPilotExecutionAllowedInPhase7B": False,
        "liveExecutionAllowedInPhase7B": False,
        "providerCallAllowedInPhase7B": False,
        "businessMutationAllowedInPhase7B": False,
        "customerNotificationAllowedInPhase7B": False,
        "whatsappSendAllowedInPhase7B": False,
        "whatsappQueueAllowedInPhase7B": False,
        "courierBookingAllowedInPhase7B": False,
        "shipmentCreationAllowedInPhase7B": False,
        "awbCreationAllowedInPhase7B": False,
        "frontendExecutionAllowedInPhase7B": False,
        "apiExecutionAllowedInPhase7B": False,
        "reviewStateChanges": "cli_only",
        "phase7bRespectsKillSwitch": True,
        "phase7bApprovalApplyRealMutation": False,
        "razorpayKeyValidationRequiredInPhase7B": False,
        "razorpayKeyValidationOwnedBy": "phase7c_or_later",
        "envPosture": (
            "All execution / mutation / provider-enabling flags remain "
            "false. Provider modes remain safe/mock/test-only as "
            "applicable. DELHIVERY_MODE stays mock unless separately "
            "approved. WHATSAPP_LIVE_META_LIMITED_TEST_MODE may remain "
            "true as a safety allow-list guard, while WhatsApp send / "
            "automation flags remain false. MCP write / provider tools "
            "remain disabled."
        ),
    }


def _internal_staff_cohort_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyInternalStaffOnly",
            "description": (
                "Future controlled pilot cohort, when designed by a "
                "later phase, must be the existing "
                "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS internal-staff "
                "allow-list only - never a real customer phone."
            ),
            "automated": True,
        },
        {
            "key": "verifyAmountCeiling",
            "description": (
                "Source chain amount must be <= 100 paise (Phase 6T "
                "ceiling honoured)."
            ),
            "automated": True,
        },
        {
            "key": "verifyDirectorSignOff",
            "description": (
                "Manual reviewer sign-off (reason text) recorded on "
                "the gate row before approval."
            ),
            "automated": False,
        },
    ]


def _kill_switch_requirements() -> dict[str, Any]:
    return {
        "phase": "7B",
        "globalKillSwitchMustBeEnabled": True,
        "providerKillSwitchHonored": True,
        "phase7bCanExecuteProviderCall": False,
        "envFlagsThatMustRemainFalse": [
            "PHASE7_CONTROLLED_PILOT_GATE_ENABLED_default",
            "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED",
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
            "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED",
            "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED",
            "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED",
            "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED",
            "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED",
            "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED",
            "WHATSAPP_AI_AUTO_REPLY_ENABLED",
            "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
            "WHATSAPP_CALL_HANDOFF_ENABLED",
            "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
            "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
            "MCP_ENABLED",
        ],
    }


def _approval_requirements() -> dict[str, Any]:
    return {
        "phase": "7B",
        "manualReviewReasonRequired": True,
        "directorSignOffRequired": True,
        "envFlagRequiredToPrepare": "PHASE7_CONTROLLED_PILOT_GATE_ENABLED",
        "approvalOnlyMarksFutureCandidacy": True,
        "approvalDoesNotStartPilot": True,
        "approvalDoesNotSendWhatsApp": True,
        "approvalDoesNotCallProvider": True,
        "approvalDoesNotMutateRealBusinessRow": True,
        "dryRunPassRequiredBeforeApproval": True,
        "rollbackDryRunPassRequiredBeforeApproval": True,
    }


def _rollback_rehearsal_steps() -> list[dict[str, Any]]:
    return [
        {
            "order": 1,
            "action": "snapshot_phase7b_env_flag_presence_only",
            "owner": "operator",
            "phase7bEnforced": True,
        },
        {
            "order": 2,
            "action": "verify_runtime_kill_switch_enabled_true",
            "owner": "operator",
            "phase7bEnforced": True,
        },
        {
            "order": 3,
            "action": "verify_no_provider_call_observed_in_window",
            "owner": "service",
            "phase7bEnforced": True,
        },
        {
            "order": 4,
            "action": "verify_no_business_row_mutation_in_window",
            "owner": "service",
            "phase7bEnforced": True,
        },
        {
            "order": 5,
            "action": (
                "record_synthetic_gate_state_revert_steps_for_phase7c"
            ),
            "owner": "service",
            "phase7bEnforced": True,
        },
    ]


def _abort_criteria() -> list[str]:
    return [
        "any_real_order_or_payment_mutation_observed",
        "any_whatsapp_send_or_queue_observed",
        "any_meta_cloud_or_delhivery_call_observed",
        "any_shipment_or_awb_creation_observed",
        "any_razorpay_provider_call_observed",
        "kill_switch_disabled",
        "raw_secret_or_full_pii_observed_in_output",
    ]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def build_phase7b_controlled_pilot_gate_contract() -> dict[str, Any]:
    """Return the canonical gate-only contract."""
    return {
        "phase": "7B",
        "status": "controlled_pilot_gate_only",
        "executionPath": "cli_only_review",
        "controlledPilotExecutionAllowedInPhase7B": False,
        "liveExecutionAllowedInPhase7B": False,
        "providerCallAllowedInPhase7B": False,
        "businessMutationAllowedInPhase7B": False,
        "customerNotificationAllowedInPhase7B": False,
        "whatsappSendAllowedInPhase7B": False,
        "whatsappQueueAllowedInPhase7B": False,
        "courierBookingAllowedInPhase7B": False,
        "shipmentCreationAllowedInPhase7B": False,
        "awbCreationAllowedInPhase7B": False,
        "frontendExecutionAllowedInPhase7B": False,
        "apiExecutionAllowedInPhase7B": False,
        "manualReviewRequired": True,
        "internalStaffOnly": True,
        "maxPilotOrders": PHASE_7B_DEFAULT_MAX_PILOT_ORDERS,
        "maxAmountPaise": PHASE_7B_MAX_SAFE_AMOUNT_PAISE,
        "approvalAdvancesToFuturePhase7CReviewOnly": True,
        "razorpayKeyValidationDeferredToPhase7COrLater": True,
        "blockers": [
            "phase_7b_controlled_pilot_gate_only_no_execution",
            "phase_7c_must_supply_director_signoff_kill_switch_check_and_internal_cohort",
        ],
        "notes": [
            "Phase 7B records the gate-only contract; no production "
            "WhatsApp / courier / Razorpay / shipment / AWB action "
            "fires here. Phase 7C is not approved.",
        ],
    }


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


_LOCKED_FALSE_GATE_FIELDS: tuple[str, ...] = (
    "controlled_pilot_execution_allowed_in_phase7b",
    "live_execution_allowed_in_phase7b",
    "provider_call_allowed_in_phase7b",
    "business_mutation_allowed_in_phase7b",
    "customer_notification_allowed_in_phase7b",
    "whatsapp_send_allowed_in_phase7b",
    "whatsapp_queue_allowed_in_phase7b",
    "courier_booking_allowed_in_phase7b",
    "shipment_creation_allowed_in_phase7b",
    "awb_creation_allowed_in_phase7b",
    "frontend_execution_allowed_in_phase7b",
    "api_execution_allowed_in_phase7b",
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
    "env_flag_flip_detected",
    "raw_secret_exposed",
    "full_pii_exposed",
)


def assert_phase7b_no_unauthorised_provider_call(
    gate: RazorpayControlledPilotExecutionGate,
) -> None:
    """Raise ``ValueError`` if any locked-False safety boolean is True.

    Phase 7B MUST never flip any of these to True. The defensive
    guard runs before persisting / serialising a gate row, emits an
    ``invariant_violation_blocked`` audit row, and refuses the
    operation.
    """
    flipped: list[str] = []
    for field in _LOCKED_FALSE_GATE_FIELDS:
        if getattr(gate, field, False) is True:
            flipped.append(field)
    if not flipped:
        return

    write_event(
        kind=AUDIT_KIND_INVARIANT_VIOLATION,
        text=(
            f"Phase 7B invariant violation blocked gate_id={gate.pk} "
            f"flipped={flipped}"
        ),
        tone=AuditEvent.Tone.DANGER,
        payload={
            "phase": "7B",
            "gate_id": gate.pk,
            "flipped_safety_booleans": flipped,
            **_audit_false_payload(),
        },
    )
    raise ValueError(
        f"Phase 7B safety invariant violation: {flipped} must remain False."
    )


def _audit_false_payload() -> dict[str, bool]:
    return {
        "controlled_pilot_execution_allowed_in_phase7b": False,
        "live_execution_allowed_in_phase7b": False,
        "provider_call_allowed_in_phase7b": False,
        "business_mutation_allowed_in_phase7b": False,
        "customer_notification_allowed_in_phase7b": False,
        "whatsapp_send_allowed_in_phase7b": False,
        "whatsapp_queue_allowed_in_phase7b": False,
        "courier_booking_allowed_in_phase7b": False,
        "shipment_creation_allowed_in_phase7b": False,
        "awb_creation_allowed_in_phase7b": False,
        "frontend_execution_allowed_in_phase7b": False,
        "api_execution_allowed_in_phase7b": False,
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
        "env_flag_flip_detected": False,
        "raw_secret_exposed": False,
        "full_pii_exposed": False,
    }


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass
class Phase7BEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    audit_lock: RazorpayPhase6FinalAuditLock | None
    pilot_plan: RazorpayPaymentDispatchPilotPlan | None
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None
    ledger: RazorpaySandboxPaidStatusLedger | None
    review: RazorpaySandboxStatusReview | None
    event: RazorpayWebhookEvent | None


def validate_phase7b_source_lock_eligibility(
    lock_id: int | None,
    *,
    require_env_flag: bool = True,
) -> Phase7BEligibility:
    """Validate that a Phase 6T lock chain is eligible for Phase 7B
    gate-row creation.

    Phase 7B does NOT validate the current ``RAZORPAY_KEY_ID``. The
    Razorpay key is read for masked display only; provider-execution
    key validation belongs to Phase 7C or later. Phase 7B eligibility
    relies on linked Phase 6M / 6T source-chain
    ``provider_environment=test/sandbox``.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    audit_lock: RazorpayPhase6FinalAuditLock | None = None
    pilot_plan: RazorpayPaymentDispatchPilotPlan | None = None
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None = None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None = None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None = None
    ledger: RazorpaySandboxPaidStatusLedger | None = None
    review: RazorpaySandboxStatusReview | None = None
    event: RazorpayWebhookEvent | None = None

    if require_env_flag and not _flag_enabled():
        blockers.append("PHASE7_CONTROLLED_PILOT_GATE_ENABLED_must_be_true")

    if lock_id:
        audit_lock = (
            RazorpayPhase6FinalAuditLock.objects.filter(pk=lock_id)
            .select_related(
                "source_pilot_plan",
                "source_readiness_gate",
                "source_workflow_gate",
                "source_attempt",
                "source_ledger",
                "source_review",
                "source_event_record",
            )
            .first()
        )

    if audit_lock is None:
        blockers.append("phase_6t_source_final_audit_lock_not_found")
        return Phase7BEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            audit_lock=None,
            pilot_plan=None,
            readiness_gate=None,
            workflow_gate=None,
            attempt=None,
            ledger=None,
            review=None,
            event=None,
        )

    # Phase 6T verification.
    if (
        audit_lock.status
        != RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
    ):
        blockers.append(
            f"phase_6t_lock_status_must_be_locked_for_future_controlled_pilot_review_was_{audit_lock.status}"
        )
    if not audit_lock.phase6n_verified:
        blockers.append("phase_6t_lock_phase6n_verified_must_be_true")
    if not audit_lock.phase6o_verified:
        blockers.append("phase_6t_lock_phase6o_verified_must_be_true")
    if not audit_lock.phase6p_verified:
        blockers.append("phase_6t_lock_phase6p_verified_must_be_true")
    if not audit_lock.phase6q_verified:
        blockers.append("phase_6t_lock_phase6q_verified_must_be_true")
    if not audit_lock.phase6r_verified:
        blockers.append("phase_6t_lock_phase6r_verified_must_be_true")
    if not audit_lock.phase6s_verified:
        blockers.append("phase_6t_lock_phase6s_verified_must_be_true")
    if not audit_lock.full_chain_verified:
        blockers.append("phase_6t_lock_full_chain_verified_must_be_true")
    if not audit_lock.final_audit_passed:
        blockers.append("phase_6t_lock_final_audit_passed_must_be_true")
    if audit_lock.future_execution_allowed_by_phase6t:
        blockers.append(
            "phase_6t_lock_future_execution_allowed_by_phase6t_must_be_false"
        )
    if audit_lock.controlled_pilot_execution_allowed_in_phase6t:
        blockers.append(
            "phase_6t_lock_controlled_pilot_execution_allowed_in_phase6t_must_be_false"
        )
    for field in (
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
        "env_flag_flip_detected",
        "raw_secret_exposed",
        "full_pii_exposed",
    ):
        if getattr(audit_lock, field, False):
            blockers.append(f"phase_6t_lock_{field}_must_be_false")

    pilot_plan = audit_lock.source_pilot_plan
    readiness_gate = audit_lock.source_readiness_gate
    workflow_gate = audit_lock.source_workflow_gate
    attempt = audit_lock.source_attempt
    ledger = audit_lock.source_ledger
    review = audit_lock.source_review
    event = audit_lock.source_event_record

    # Phase 6S verification.
    if pilot_plan is None:
        blockers.append("phase_6s_source_pilot_plan_not_found")
    else:
        if (
            pilot_plan.status
            != RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
        ):
            blockers.append(
                f"phase_6s_pilot_plan_status_must_be_approved_for_future_phase6t_was_{pilot_plan.status}"
            )

    # Phase 6R verification.
    if readiness_gate is None:
        blockers.append("phase_6r_source_readiness_gate_not_found")
    else:
        if (
            readiness_gate.status
            != RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
        ):
            blockers.append(
                f"phase_6r_readiness_gate_status_must_be_approved_for_future_phase6s_was_{readiness_gate.status}"
            )

    # Phase 6Q verification.
    if workflow_gate is None:
        blockers.append("phase_6q_source_workflow_gate_not_found")
    else:
        if (
            workflow_gate.status
            != RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
        ):
            blockers.append(
                f"phase_6q_workflow_gate_status_must_be_approved_for_future_phase6r_was_{workflow_gate.status}"
            )

    # Phase 6P attempt verification.
    if attempt is None:
        blockers.append("phase_6p_source_attempt_not_found")
    else:
        if attempt.status not in (
            RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
            RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
        ):
            blockers.append(
                f"phase_6p_attempt_status_{attempt.status}_not_eligible"
            )
        if attempt.real_order_mutation_was_made:
            blockers.append(
                "phase_6p_attempt_real_order_mutation_was_made"
            )
        if attempt.real_payment_mutation_was_made:
            blockers.append(
                "phase_6p_attempt_real_payment_mutation_was_made"
            )
        if attempt.business_mutation_was_made:
            blockers.append("phase_6p_attempt_business_mutation_was_made")
        if attempt.customer_notification_sent:
            blockers.append("phase_6p_attempt_customer_notification_sent")
        if attempt.provider_call_attempted:
            blockers.append("phase_6p_attempt_provider_call_attempted")

    # Phase 6O verification.
    if review is None:
        blockers.append("phase_6o_review_not_found")
    else:
        if (
            review.status
            != RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
        ):
            blockers.append(
                f"phase_6o_review_status_must_be_approved_for_future_phase6p_was_{review.status}"
            )
        if not review.synthetic_eligible:
            blockers.append("phase_6o_review_must_be_synthetic_eligible")

    # Phase 6M event verification.
    if event is None:
        blockers.append("phase_6m_razorpay_webhook_event_not_found")
    else:
        if not event.signature_valid:
            blockers.append("phase_6m_event_signature_invalid")
        if not event.replay_window_valid:
            blockers.append("phase_6m_event_replay_window_invalid")
        if (
            event.idempotency_status
            != RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN
        ):
            blockers.append(
                "phase_6m_event_idempotency_must_be_first_seen"
            )
        if event.business_mutation_was_made:
            blockers.append("phase_6m_event_business_mutation_was_made")
        if event.customer_notification_sent:
            blockers.append("phase_6m_event_customer_notification_sent")
        if event.raw_secret_exposed:
            blockers.append("phase_6m_event_raw_secret_exposed")
        if event.full_pii_exposed or event.scrubbed_keys:
            blockers.append("phase_6m_event_full_pii_must_be_absent")
        if event.environment != RazorpayWebhookEvent.Environment.TEST:
            blockers.append(
                f"phase_6m_event_environment_must_be_test_was_{event.environment}"
            )
        if (
            event.amount_paise is not None
            and event.amount_paise > PHASE_7B_MAX_SAFE_AMOUNT_PAISE
        ):
            blockers.append(
                f"amount_paise_must_be_<=_{PHASE_7B_MAX_SAFE_AMOUNT_PAISE}"
            )

    return Phase7BEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        audit_lock=audit_lock,
        pilot_plan=pilot_plan,
        readiness_gate=readiness_gate,
        workflow_gate=workflow_gate,
        attempt=attempt,
        ledger=ledger,
        review=review,
        event=event,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_phase7b_gate(
    row: RazorpayControlledPilotExecutionGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "sourceFinalAuditLockId": row.source_final_audit_lock_id,
        "sourcePilotPlanId": row.source_pilot_plan_id,
        "sourceReadinessGateId": row.source_readiness_gate_id,
        "sourceWorkflowGateId": row.source_workflow_gate_id,
        "sourceAttemptId": row.source_attempt_id,
        "sourceLedgerId": row.source_ledger_id,
        "sourceReviewId": row.source_review_id,
        "sourceEventRecordId": row.source_event_record_id,
        "sourceEventId": row.source_event_id,
        "eventName": row.event_name,
        "providerEnvironment": row.provider_environment,
        "amountPaise": row.amount_paise,
        "currency": row.currency,
        "status": row.status,
        "phase6TLockVerified": row.phase6t_lock_verified,
        "phase6SPilotPlanVerified": row.phase6s_pilot_plan_verified,
        "phase6RReadinessVerified": row.phase6r_readiness_verified,
        "phase6QWorkflowGateVerified": row.phase6q_workflow_gate_verified,
        "phase6PAttemptVerified": row.phase6p_attempt_verified,
        "phase6OReviewVerified": row.phase6o_review_verified,
        "phase6MEventVerified": row.phase6m_event_verified,
        "fullChainVerified": row.full_chain_verified,
        "dryRunPassed": row.dry_run_passed,
        "rollbackDryRunPassed": row.rollback_dry_run_passed,
        "manualReviewRequired": row.manual_review_required,
        "internalOnly": row.internal_only,
        "maxPilotOrders": row.max_pilot_orders,
        "maxAmountPaise": row.max_amount_paise,
        "controlledPilotExecutionAllowedInPhase7B": (
            row.controlled_pilot_execution_allowed_in_phase7b
        ),
        "liveExecutionAllowedInPhase7B": row.live_execution_allowed_in_phase7b,
        "providerCallAllowedInPhase7B": row.provider_call_allowed_in_phase7b,
        "businessMutationAllowedInPhase7B": (
            row.business_mutation_allowed_in_phase7b
        ),
        "customerNotificationAllowedInPhase7B": (
            row.customer_notification_allowed_in_phase7b
        ),
        "whatsAppSendAllowedInPhase7B": row.whatsapp_send_allowed_in_phase7b,
        "whatsAppQueueAllowedInPhase7B": (
            row.whatsapp_queue_allowed_in_phase7b
        ),
        "courierBookingAllowedInPhase7B": (
            row.courier_booking_allowed_in_phase7b
        ),
        "shipmentCreationAllowedInPhase7B": (
            row.shipment_creation_allowed_in_phase7b
        ),
        "awbCreationAllowedInPhase7B": row.awb_creation_allowed_in_phase7b,
        "frontendExecutionAllowedInPhase7B": (
            row.frontend_execution_allowed_in_phase7b
        ),
        "apiExecutionAllowedInPhase7B": row.api_execution_allowed_in_phase7b,
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
        "idempotencyKey": row.idempotency_key,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "safetyInvariants": row.safety_invariants,
        "reviewedByUsername": (
            getattr(row.reviewed_by, "username", "") or ""
        ),
        "reviewedAt": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "reviewReason": row.review_reason,
        "archivedByUsername": (
            getattr(row.archived_by, "username", "") or ""
        ),
        "archivedAt": (
            row.archived_at.isoformat() if row.archived_at else None
        ),
        "archiveReason": row.archive_reason,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def serialize_phase7b_dry_run_record(
    row: RazorpayControlledPilotGateDryRunRecord,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "verifiedAt": row.verified_at.isoformat(),
        "phase6TVerified": row.phase6t_verified,
        "phase6SVerified": row.phase6s_verified,
        "phase6RVerified": row.phase6r_verified,
        "phase6QVerified": row.phase6q_verified,
        "phase6PVerified": row.phase6p_verified,
        "phase6OVerified": row.phase6o_verified,
        "phase6MVerified": row.phase6m_verified,
        "chainPass": row.chain_pass,
        "evaluatedSafetyInvariants": row.evaluated_safety_invariants,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "idempotencyKey": row.idempotency_key,
        "createdAt": row.created_at.isoformat(),
    }


def serialize_phase7b_rollback_dry_run_record(
    row: RazorpayControlledPilotGateRollbackDryRunRecord,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "verifiedAt": row.verified_at.isoformat(),
        "dryRunStatus": row.dry_run_status,
        "rehearsalSteps": list(row.rehearsal_steps or []),
        "envFlagSnapshot": row.env_flag_snapshot,
        "evaluatedSafetyInvariants": row.evaluated_safety_invariants,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "idempotencyKey": row.idempotency_key,
        "createdAt": row.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7b_controlled_pilot_gate(lock_id: int) -> dict[str, Any]:
    """Read-only preview. Never creates rows."""
    eligibility = validate_phase7b_source_lock_eligibility(
        lock_id, require_env_flag=False
    )

    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7B preview source_lock_id={lock_id}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "7B",
            "source_phase6t_lock_id": lock_id,
            "source_phase6s_pilot_plan_id": (
                eligibility.pilot_plan.pk if eligibility.pilot_plan else None
            ),
            "source_phase6r_readiness_gate_id": (
                eligibility.readiness_gate.pk
                if eligibility.readiness_gate
                else None
            ),
            "source_phase6q_workflow_gate_id": (
                eligibility.workflow_gate.pk
                if eligibility.workflow_gate
                else None
            ),
            "source_phase6p_attempt_id": (
                eligibility.attempt.pk if eligibility.attempt else None
            ),
            "source_phase6o_review_id": (
                eligibility.review.pk if eligibility.review else None
            ),
            "source_phase6m_event_id": (
                eligibility.event.source_event_id if eligibility.event else ""
            ),
            "event_name": (
                eligibility.event.event_name if eligibility.event else ""
            ),
            "eligible": eligibility.eligible,
            "blockers": list(eligibility.blockers),
            **_audit_false_payload(),
        },
    )

    return {
        "phase": "7B",
        "found": eligibility.audit_lock is not None,
        "sourcePhase6TLockId": lock_id,
        "sourcePhase6SPilotPlanId": (
            eligibility.pilot_plan.pk if eligibility.pilot_plan else None
        ),
        "sourcePhase6RReadinessGateId": (
            eligibility.readiness_gate.pk
            if eligibility.readiness_gate
            else None
        ),
        "sourcePhase6QWorkflowGateId": (
            eligibility.workflow_gate.pk
            if eligibility.workflow_gate
            else None
        ),
        "sourcePhase6PAttemptId": (
            eligibility.attempt.pk if eligibility.attempt else None
        ),
        "sourcePhase6OReviewId": (
            eligibility.review.pk if eligibility.review else None
        ),
        "sourcePhase6MEventId": (
            eligibility.event.source_event_id if eligibility.event else ""
        ),
        "eventName": (
            eligibility.event.event_name if eligibility.event else ""
        ),
        "eligible": eligibility.eligible,
        "proposedContract": build_phase7b_controlled_pilot_gate_contract(),
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_7B_WARNING],
        "nextAction": (
            "ready_to_prepare_phase7b_controlled_pilot_gate"
            if eligibility.eligible and _flag_enabled()
            else "fix_phase_7b_eligibility_blockers_or_enable_pilot_gate_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(lock: RazorpayPhase6FinalAuditLock) -> str:
    return f"phase7b::pilot_execution_gate::lock::{lock.pk}"


def prepare_phase7b_controlled_pilot_gate(
    lock_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create / re-fetch a Phase 7B gate row.

    Idempotent on the source Phase 6T lock id. NEVER calls a provider,
    NEVER sends WhatsApp, NEVER calls Meta Cloud / Delhivery, NEVER
    creates a shipment / AWB, NEVER mutates real business tables.
    Phase 7B does NOT validate the live ``RAZORPAY_KEY_ID``.
    """
    eligibility = validate_phase7b_source_lock_eligibility(
        lock_id, require_env_flag=True
    )

    if not eligibility.eligible or eligibility.audit_lock is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7B prepare blocked source_lock_id={lock_id}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "7B",
                "source_phase6t_lock_id": lock_id,
                "blockers": list(eligibility.blockers),
                **_audit_false_payload(),
            },
        )
        return {
            "phase": "7B",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_7B_WARNING],
            "nextAction": (
                "fix_phase_7b_eligibility_blockers_or_enable_pilot_gate_flag"
            ),
        }

    audit_lock = eligibility.audit_lock
    pilot_plan = eligibility.pilot_plan
    readiness_gate = eligibility.readiness_gate
    workflow_gate = eligibility.workflow_gate
    attempt = eligibility.attempt
    ledger = eligibility.ledger
    review = eligibility.review
    event = eligibility.event
    idempotency = _idempotency_key(audit_lock)

    with transaction.atomic():
        existing = (
            RazorpayControlledPilotExecutionGate.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "7B",
                "created": False,
                "reused": True,
                "gate": serialize_phase7b_gate(existing),
                "blockers": [],
                "warnings": [PHASE_7B_WARNING],
                "nextAction": "controlled_pilot_gate_pending_manual_review",
            }

        gate = RazorpayControlledPilotExecutionGate(
            source_final_audit_lock=audit_lock,
            source_pilot_plan=pilot_plan,
            source_readiness_gate=readiness_gate,
            source_workflow_gate=workflow_gate,
            source_attempt=attempt,
            source_ledger=ledger,
            source_review=review,
            source_event_record=event,
            source_event_id=event.source_event_id if event else "",
            event_name=(
                event.event_name if event else audit_lock.event_name
            ),
            provider_environment=(
                event.environment
                if event
                else audit_lock.provider_environment
            ),
            amount_paise=(
                event.amount_paise if event else audit_lock.amount_paise
            ),
            currency=event.currency if event else audit_lock.currency,
            status=(
                RazorpayControlledPilotExecutionGate.Status.PENDING_MANUAL_REVIEW
            ),
            phase6t_lock_verified=True,
            phase6s_pilot_plan_verified=pilot_plan is not None,
            phase6r_readiness_verified=readiness_gate is not None,
            phase6q_workflow_gate_verified=workflow_gate is not None,
            phase6p_attempt_verified=attempt is not None,
            phase6o_review_verified=review is not None,
            phase6m_event_verified=event is not None,
            full_chain_verified=True,
            dry_run_passed=False,
            rollback_dry_run_passed=False,
            manual_review_required=True,
            internal_only=True,
            max_pilot_orders=PHASE_7B_DEFAULT_MAX_PILOT_ORDERS,
            max_amount_paise=PHASE_7B_MAX_SAFE_AMOUNT_PAISE,
            controlled_pilot_execution_allowed_in_phase7b=False,
            live_execution_allowed_in_phase7b=False,
            provider_call_allowed_in_phase7b=False,
            business_mutation_allowed_in_phase7b=False,
            customer_notification_allowed_in_phase7b=False,
            whatsapp_send_allowed_in_phase7b=False,
            whatsapp_queue_allowed_in_phase7b=False,
            courier_booking_allowed_in_phase7b=False,
            shipment_creation_allowed_in_phase7b=False,
            awb_creation_allowed_in_phase7b=False,
            frontend_execution_allowed_in_phase7b=False,
            api_execution_allowed_in_phase7b=False,
            real_order_mutation_was_made=False,
            real_payment_mutation_was_made=False,
            shipment_mutation_was_made=False,
            shipment_created=False,
            awb_created=False,
            whatsapp_message_created=False,
            whatsapp_message_queued=False,
            customer_notification_sent=False,
            meta_cloud_call_attempted=False,
            delhivery_call_attempted=False,
            razorpay_call_attempted=False,
            provider_call_attempted=False,
            env_flag_flip_detected=False,
            raw_secret_exposed=False,
            full_pii_exposed=False,
            idempotency_key=idempotency,
            blockers=[],
            warnings=[PHASE_7B_WARNING],
            safety_invariants={
                **_safety_invariants(),
                "auditChain": build_phase7b_controlled_pilot_gate_contract(),
                "internalStaffCohortChecklist": (
                    _internal_staff_cohort_checklist()
                ),
                "killSwitchRequirements": _kill_switch_requirements(),
                "approvalRequirements": _approval_requirements(),
                "abortCriteria": _abort_criteria(),
                "rollbackRehearsalSteps": _rollback_rehearsal_steps(),
            },
            requested_by=requested_by,
        )
        assert_phase7b_no_unauthorised_provider_call(gate)
        try:
            gate.save()
        except IntegrityError:
            gate = RazorpayControlledPilotExecutionGate.objects.get(
                idempotency_key=idempotency
            )
            return {
                "phase": "7B",
                "created": False,
                "reused": True,
                "gate": serialize_phase7b_gate(gate),
                "blockers": [],
                "warnings": [PHASE_7B_WARNING],
                "nextAction": "controlled_pilot_gate_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 7B controlled pilot gate prepared gate_id={gate.pk} "
            f"source_lock_id={audit_lock.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "7B",
            "gate_id": gate.pk,
            "phase6t_lock_id": audit_lock.pk,
            "phase6s_pilot_plan_id": gate.source_pilot_plan_id,
            "phase6r_readiness_gate_id": gate.source_readiness_gate_id,
            "phase6q_workflow_gate_id": gate.source_workflow_gate_id,
            "phase6p_attempt_id": gate.source_attempt_id,
            "phase6o_review_id": gate.source_review_id,
            "phase6m_event_id": gate.source_event_id,
            "event_name": gate.event_name,
            "status": gate.status,
            "dry_run_passed": False,
            "rollback_dry_run_passed": False,
            **_audit_false_payload(),
        },
    )

    return {
        "phase": "7B",
        "created": True,
        "reused": False,
        "gate": serialize_phase7b_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7B_WARNING],
        "nextAction": "controlled_pilot_gate_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def _dry_run_idempotency_key(gate_id: int) -> str:
    return (
        f"phase7b::dry_run::gate::{gate_id}::run::"
        f"{timezone.now().strftime('%Y%m%dT%H%M%S%f')}"
    )


def _rollback_dry_run_idempotency_key(gate_id: int) -> str:
    return (
        f"phase7b::rollback_dry_run::gate::{gate_id}::run::"
        f"{timezone.now().strftime('%Y%m%dT%H%M%S%f')}"
    )


def dry_run_phase7b_controlled_pilot_gate(
    gate_id: int,
    *,
    run_by=None,
) -> dict[str, Any]:
    gate = (
        RazorpayControlledPilotExecutionGate.objects.filter(pk=gate_id)
        .select_related("source_final_audit_lock")
        .first()
    )
    if gate is None:
        return {
            "phase": "7B",
            "ok": False,
            "record": None,
            "blockers": ["controlled_pilot_gate_not_found"],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not _flag_enabled():
        return {
            "phase": "7B",
            "ok": False,
            "record": None,
            "blockers": [
                "PHASE7_CONTROLLED_PILOT_GATE_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "enable_pilot_gate_flag_before_dry_run",
        }

    assert_phase7b_no_unauthorised_provider_call(gate)

    eligibility = validate_phase7b_source_lock_eligibility(
        gate.source_final_audit_lock_id, require_env_flag=False
    )
    chain_pass = eligibility.eligible and eligibility.audit_lock is not None

    record = RazorpayControlledPilotGateDryRunRecord(
        gate=gate,
        verified_at=timezone.now(),
        phase6t_verified=eligibility.audit_lock is not None
        and not any(
            blocker.startswith("phase_6t_") for blocker in eligibility.blockers
        ),
        phase6s_verified=eligibility.pilot_plan is not None
        and not any(
            blocker.startswith("phase_6s_") for blocker in eligibility.blockers
        ),
        phase6r_verified=eligibility.readiness_gate is not None
        and not any(
            blocker.startswith("phase_6r_") for blocker in eligibility.blockers
        ),
        phase6q_verified=eligibility.workflow_gate is not None
        and not any(
            blocker.startswith("phase_6q_") for blocker in eligibility.blockers
        ),
        phase6p_verified=eligibility.attempt is not None
        and not any(
            blocker.startswith("phase_6p_") for blocker in eligibility.blockers
        ),
        phase6o_verified=eligibility.review is not None
        and not any(
            blocker.startswith("phase_6o_") for blocker in eligibility.blockers
        ),
        phase6m_verified=eligibility.event is not None
        and not any(
            blocker.startswith("phase_6m_") for blocker in eligibility.blockers
        ),
        chain_pass=chain_pass,
        evaluated_safety_invariants=_safety_invariants(),
        blockers=list(eligibility.blockers),
        warnings=list(eligibility.warnings) + [PHASE_7B_WARNING],
        idempotency_key=_dry_run_idempotency_key(gate.pk),
    )
    record.save()

    if chain_pass:
        gate.dry_run_passed = True
        gate.save(update_fields=["dry_run_passed", "updated_at"])
        write_event(
            kind=AUDIT_KIND_DRY_RUN_PASSED,
            text=f"Phase 7B dry-run passed gate_id={gate.pk}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "phase": "7B",
                "gate_id": gate.pk,
                "dry_run_record_id": record.pk,
                "chain_pass": True,
                "dry_run_passed": True,
                "rollback_dry_run_passed": gate.rollback_dry_run_passed,
                **_audit_false_payload(),
            },
        )
        return {
            "phase": "7B",
            "ok": True,
            "record": serialize_phase7b_dry_run_record(record),
            "gate": serialize_phase7b_gate(gate),
            "blockers": [],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "ready_for_rollback_dry_run_or_approve",
        }

    if (
        gate.status
        not in (
            RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW,
            RazorpayControlledPilotExecutionGate.Status.REJECTED,
            RazorpayControlledPilotExecutionGate.Status.ARCHIVED,
        )
    ):
        gate.status = RazorpayControlledPilotExecutionGate.Status.BLOCKED
        gate.save(update_fields=["status", "updated_at"])

    write_event(
        kind=AUDIT_KIND_DRY_RUN_FAILED,
        text=f"Phase 7B dry-run failed gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": "7B",
            "gate_id": gate.pk,
            "dry_run_record_id": record.pk,
            "chain_pass": False,
            "dry_run_passed": False,
            "rollback_dry_run_passed": gate.rollback_dry_run_passed,
            "blockers": list(eligibility.blockers),
            **_audit_false_payload(),
        },
    )
    return {
        "phase": "7B",
        "ok": False,
        "record": serialize_phase7b_dry_run_record(record),
        "gate": serialize_phase7b_gate(gate),
        "blockers": list(eligibility.blockers),
        "warnings": [PHASE_7B_WARNING],
        "nextAction": "fix_phase_7b_dry_run_blockers",
    }


# ---------------------------------------------------------------------------
# Rollback dry-run
# ---------------------------------------------------------------------------


def _env_flag_presence_snapshot() -> dict[str, bool]:
    flags = (
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED",
        "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED",
        "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
        "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED",
        "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED",
        "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED",
        "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED",
        "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED",
        "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED",
        "WHATSAPP_AI_AUTO_REPLY_ENABLED",
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
        "WHATSAPP_CALL_HANDOFF_ENABLED",
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
        "MCP_ENABLED",
    )
    return {flag: bool(getattr(settings, flag, False)) for flag in flags}


def rollback_dry_run_phase7b_controlled_pilot_gate(
    gate_id: int,
    *,
    run_by=None,
    reason: str = "",
) -> dict[str, Any]:
    gate = (
        RazorpayControlledPilotExecutionGate.objects.filter(pk=gate_id).first()
    )
    if gate is None:
        return {
            "phase": "7B",
            "ok": False,
            "record": None,
            "blockers": ["controlled_pilot_gate_not_found"],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not _flag_enabled():
        return {
            "phase": "7B",
            "ok": False,
            "record": None,
            "blockers": [
                "PHASE7_CONTROLLED_PILOT_GATE_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "enable_pilot_gate_flag_before_rollback_dry_run",
        }

    assert_phase7b_no_unauthorised_provider_call(gate)

    env_snapshot = _env_flag_presence_snapshot()
    blockers: list[str] = []

    # Any non-Phase 7B execution flag flipped to true in the live
    # process is a kill-switch trigger for the rehearsal.
    for flag, value in env_snapshot.items():
        if flag == "PHASE7_CONTROLLED_PILOT_GATE_ENABLED":
            continue
        if value is True:
            blockers.append(
                f"phase_7b_rollback_dry_run_blocker_unexpected_flag_true_{flag}"
            )

    rehearsal_steps = _rollback_rehearsal_steps()
    chain_pass = not blockers

    record = RazorpayControlledPilotGateRollbackDryRunRecord(
        gate=gate,
        verified_at=timezone.now(),
        dry_run_status=(
            RazorpayControlledPilotGateRollbackDryRunRecord.DryRunStatus.PASSED
            if chain_pass
            else (
                RazorpayControlledPilotGateRollbackDryRunRecord.DryRunStatus.FAILED
            )
        ),
        rehearsal_steps=rehearsal_steps,
        env_flag_snapshot=env_snapshot,
        evaluated_safety_invariants=_safety_invariants(),
        blockers=blockers,
        warnings=[PHASE_7B_WARNING],
        idempotency_key=_rollback_dry_run_idempotency_key(gate.pk),
        notes=(reason or "")[:200],
    )
    record.save()

    if chain_pass:
        gate.rollback_dry_run_passed = True
        gate.save(update_fields=["rollback_dry_run_passed", "updated_at"])
        write_event(
            kind=AUDIT_KIND_ROLLBACK_DRY_RUN_PASSED,
            text=(
                f"Phase 7B rollback dry-run passed gate_id={gate.pk}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phase": "7B",
                "gate_id": gate.pk,
                "rollback_dry_run_record_id": record.pk,
                "dry_run_passed": gate.dry_run_passed,
                "rollback_dry_run_passed": True,
                **_audit_false_payload(),
            },
        )
        return {
            "phase": "7B",
            "ok": True,
            "record": serialize_phase7b_rollback_dry_run_record(record),
            "gate": serialize_phase7b_gate(gate),
            "blockers": [],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "ready_to_approve_for_future_phase7c_review",
        }

    if (
        gate.status
        not in (
            RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW,
            RazorpayControlledPilotExecutionGate.Status.REJECTED,
            RazorpayControlledPilotExecutionGate.Status.ARCHIVED,
        )
    ):
        gate.status = RazorpayControlledPilotExecutionGate.Status.BLOCKED
        gate.save(update_fields=["status", "updated_at"])

    write_event(
        kind=AUDIT_KIND_ROLLBACK_DRY_RUN_FAILED,
        text=f"Phase 7B rollback dry-run failed gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": "7B",
            "gate_id": gate.pk,
            "rollback_dry_run_record_id": record.pk,
            "dry_run_passed": gate.dry_run_passed,
            "rollback_dry_run_passed": False,
            "blockers": blockers,
            **_audit_false_payload(),
        },
    )
    return {
        "phase": "7B",
        "ok": False,
        "record": serialize_phase7b_rollback_dry_run_record(record),
        "gate": serialize_phase7b_gate(gate),
        "blockers": blockers,
        "warnings": [PHASE_7B_WARNING],
        "nextAction": "fix_phase_7b_rollback_dry_run_blockers",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


_TRANSITIONABLE_FROM = {
    RazorpayControlledPilotExecutionGate.Status.DRAFT,
    RazorpayControlledPilotExecutionGate.Status.PENDING_MANUAL_REVIEW,
    RazorpayControlledPilotExecutionGate.Status.BLOCKED,
}


def _transition(
    gate_id: int,
    *,
    new_status: str,
    audit_kind: str,
    by_user=None,
    reason: str = "",
    archive: bool = False,
    require_reason: bool = False,
    require_dry_run_passed: bool = False,
    require_rollback_dry_run_passed: bool = False,
) -> dict[str, Any]:
    gate = (
        RazorpayControlledPilotExecutionGate.objects.filter(pk=gate_id).first()
    )
    if gate is None:
        return {
            "phase": "7B",
            "ok": False,
            "gate": None,
            "blockers": ["controlled_pilot_gate_not_found"],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not _flag_enabled():
        return {
            "phase": "7B",
            "ok": False,
            "gate": serialize_phase7b_gate(gate),
            "blockers": [
                "PHASE7_CONTROLLED_PILOT_GATE_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "enable_pilot_gate_flag_before_review_state_change",
        }
    if archive:
        if (
            gate.status
            == RazorpayControlledPilotExecutionGate.Status.ARCHIVED
        ):
            return {
                "phase": "7B",
                "ok": False,
                "gate": serialize_phase7b_gate(gate),
                "blockers": ["controlled_pilot_gate_already_archived"],
                "warnings": [PHASE_7B_WARNING],
                "nextAction": "verify_gate_id",
            }
    elif gate.status not in _TRANSITIONABLE_FROM:
        return {
            "phase": "7B",
            "ok": False,
            "gate": serialize_phase7b_gate(gate),
            "blockers": [
                f"controlled_pilot_gate_status_{gate.status}_not_transitionable"
            ],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if require_reason and not reason.strip():
        return {
            "phase": "7B",
            "ok": False,
            "gate": serialize_phase7b_gate(gate),
            "blockers": ["manual_review_reason_must_be_non_empty"],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "supply_manual_review_reason",
        }
    if require_dry_run_passed and not gate.dry_run_passed:
        return {
            "phase": "7B",
            "ok": False,
            "gate": serialize_phase7b_gate(gate),
            "blockers": ["phase_7b_dry_run_required"],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "run_dry_run_before_approve",
        }
    if (
        require_rollback_dry_run_passed
        and not gate.rollback_dry_run_passed
    ):
        return {
            "phase": "7B",
            "ok": False,
            "gate": serialize_phase7b_gate(gate),
            "blockers": ["phase_7b_rollback_dry_run_required"],
            "warnings": [PHASE_7B_WARNING],
            "nextAction": "run_rollback_dry_run_before_approve",
        }

    assert_phase7b_no_unauthorised_provider_call(gate)
    gate.status = new_status
    if archive:
        gate.archived_by = by_user
        gate.archived_at = timezone.now()
        gate.archive_reason = (reason or "")[:200]
    else:
        gate.reviewed_by = by_user
        gate.reviewed_at = timezone.now()
        gate.review_reason = (reason or "")[:200]
    gate.save()

    write_event(
        kind=audit_kind,
        text=f"Phase 7B controlled pilot gate {new_status} gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "7B",
            "gate_id": gate.pk,
            "phase6t_lock_id": gate.source_final_audit_lock_id,
            "phase6s_pilot_plan_id": gate.source_pilot_plan_id,
            "phase6r_readiness_gate_id": gate.source_readiness_gate_id,
            "phase6q_workflow_gate_id": gate.source_workflow_gate_id,
            "phase6p_attempt_id": gate.source_attempt_id,
            "phase6o_review_id": gate.source_review_id,
            "phase6m_event_id": gate.source_event_id,
            "event_name": gate.event_name,
            "status": gate.status,
            "dry_run_passed": gate.dry_run_passed,
            "rollback_dry_run_passed": gate.rollback_dry_run_passed,
            "reason_summary_present": bool(reason.strip()),
            **_audit_false_payload(),
        },
    )

    return {
        "phase": "7B",
        "ok": True,
        "gate": serialize_phase7b_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7B_WARNING],
        "nextAction": (
            "approved_for_future_phase7c_execution_review_no_live_execution"
            if new_status
            == (
                RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
            )
            else "controlled_pilot_gate_finalised"
        ),
    }


def approve_phase7b_controlled_pilot_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the gate approved **for future Phase 7C review only**.
    NEVER calls a provider; NEVER sends WhatsApp; NEVER mutates real
    business tables.
    """
    return _transition(
        gate_id,
        new_status=(
            RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
        ),
        audit_kind=AUDIT_KIND_APPROVED_FOR_PHASE7C_REVIEW,
        by_user=reviewed_by,
        reason=reason,
        require_reason=True,
        require_dry_run_passed=True,
        require_rollback_dry_run_passed=True,
    )


def reject_phase7b_controlled_pilot_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        gate_id,
        new_status=RazorpayControlledPilotExecutionGate.Status.REJECTED,
        audit_kind=AUDIT_KIND_REJECTED,
        by_user=reviewed_by,
        reason=reason,
    )


def archive_phase7b_controlled_pilot_gate(
    gate_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        gate_id,
        new_status=RazorpayControlledPilotExecutionGate.Status.ARCHIVED,
        audit_kind=AUDIT_KIND_ARCHIVED,
        by_user=archived_by,
        reason=reason,
        archive=True,
    )


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase7b_controlled_pilot_gates(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpayControlledPilotExecutionGate.objects.all().order_by(
        "-created_at"
    )
    Status = RazorpayControlledPilotExecutionGate.Status
    counts = {
        "draft": qs.filter(status=Status.DRAFT).count(),
        "pendingManualReview": qs.filter(
            status=Status.PENDING_MANUAL_REVIEW
        ).count(),
        "approvedForFuturePhase7CExecutionReview": qs.filter(
            status=Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
        ).count(),
        "rejected": qs.filter(status=Status.REJECTED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
        "controlledPilotExecutionAllowedInPhase7B": qs.filter(
            controlled_pilot_execution_allowed_in_phase7b=True
        ).count(),
        "providerCallAttempted": qs.filter(
            provider_call_attempted=True
        ).count(),
        "realOrderMutationWasMade": qs.filter(
            real_order_mutation_was_made=True
        ).count(),
        "realPaymentMutationWasMade": qs.filter(
            real_payment_mutation_was_made=True
        ).count(),
        "shipmentCreated": qs.filter(shipment_created=True).count(),
        "awbCreated": qs.filter(awb_created=True).count(),
        "whatsAppMessageCreated": qs.filter(
            whatsapp_message_created=True
        ).count(),
        "whatsAppMessageQueued": qs.filter(
            whatsapp_message_queued=True
        ).count(),
        "customerNotificationSent": qs.filter(
            customer_notification_sent=True
        ).count(),
        "metaCloudCallAttempted": qs.filter(
            meta_cloud_call_attempted=True
        ).count(),
        "delhiveryCallAttempted": qs.filter(
            delhivery_call_attempted=True
        ).count(),
        "razorpayCallAttempted": qs.filter(
            razorpay_call_attempted=True
        ).count(),
    }
    sample = [
        serialize_phase7b_gate(row) for row in qs[: max(1, min(limit, 200))]
    ]
    return {"counts": counts, "items": sample}


def inspect_phase7b_controlled_pilot_gate_readiness() -> dict[str, Any]:
    flag_enabled = _flag_enabled()
    summary = summarize_phase7b_controlled_pilot_gates()
    counts = summary["counts"]

    blockers: list[str] = []
    warnings: list[str] = [PHASE_7B_WARNING]

    for key in (
        "controlledPilotExecutionAllowedInPhase7B",
        "providerCallAttempted",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "shipmentCreated",
        "awbCreated",
        "whatsAppMessageCreated",
        "whatsAppMessageQueued",
        "customerNotificationSent",
        "metaCloudCallAttempted",
        "delhiveryCallAttempted",
        "razorpayCallAttempted",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_7b_controlled_pilot_gate_{key}_observed_must_be_zero"
            )

    phase6t_locked = (
        RazorpayPhase6FinalAuditLock.objects.filter(
            status=RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
        ).count()
    )

    safe_to_start_phase_7c_execution_review_flow = bool(
        not blockers
        and counts["approvedForFuturePhase7CExecutionReview"] >= 1
    )

    if blockers:
        next_action = "fix_phase_7b_safety_blockers"
    elif phase6t_locked == 0:
        next_action = (
            "lock_at_least_one_phase_6t_final_audit_record_before_running_phase_7b"
        )
    elif counts["approvedForFuturePhase7CExecutionReview"] == 0:
        next_action = (
            "approve_at_least_one_phase7b_controlled_pilot_gate_for_future_phase7c_review"
        )
    else:
        next_action = (
            "ready_for_future_phase7c_execution_review_only_after_fresh_director_approval_no_live_execution"
        )

    return {
        "phase": "7B",
        "status": "controlled_pilot_gate_only",
        "latestCompletedPhase": "6T",
        "nextPhase": "7C_not_approved",
        "phase7ControlledPilotGateEnabled": flag_enabled,
        "phase7BMakesProviderCall": False,
        "phase7BSendsOrQueuesWhatsApp": False,
        "phase7BCreatesShipmentOrAwb": False,
        "phase7BMutatesBusinessRow": False,
        "phase7BSendsCustomerNotification": False,
        "phase7BCallsRazorpay": False,
        "phase7BValidatesLiveRazorpayKey": False,
        "phase7BRazorpayKeyDisplayPolicy": (
            "masked_advisory_only_if_displayed_at_all"
        ),
        "phase6TLockedForFutureControlledPilotReviewCount": phase6t_locked,
        "controlledPilotGateCounts": counts,
        "controlledPilotGateContract": (
            build_phase7b_controlled_pilot_gate_contract()
        ),
        "safetyInvariants": _safety_invariants(),
        "internalStaffCohortChecklist": (
            _internal_staff_cohort_checklist()
        ),
        "killSwitchRequirements": _kill_switch_requirements(),
        "approvalRequirements": _approval_requirements(),
        "rollbackRehearsalSteps": _rollback_rehearsal_steps(),
        "abortCriteria": _abort_criteria(),
        "forbiddenActions": list(PHASE_7B_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only_review",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "maxSafeAmountPaise": PHASE_7B_MAX_SAFE_AMOUNT_PAISE,
        "maxPilotOrders": PHASE_7B_DEFAULT_MAX_PILOT_ORDERS,
        "envPosture": _safety_invariants()["envPosture"],
        "razorpayKeyValidationOwnedBy": (
            _safety_invariants()["razorpayKeyValidationOwnedBy"]
        ),
        "safeToStartPhase7CExecutionReviewFlow": (
            safe_to_start_phase_7c_execution_review_flow
        ),
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentControlledPilotGates": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("controlledPilotGateCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7B controlled pilot gate readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "7B",
            "phase7_controlled_pilot_gate_enabled": bool(
                report.get("phase7ControlledPilotGateEnabled")
            ),
            "phase6t_locked_for_future_controlled_pilot_review_count": int(
                report.get(
                    "phase6TLockedForFutureControlledPilotReviewCount"
                )
                or 0
            ),
            "pending_manual_review": int(
                counts.get("pendingManualReview") or 0
            ),
            "approved_for_future_phase7c_execution_review": int(
                counts.get("approvedForFuturePhase7CExecutionReview") or 0
            ),
            "rejected": int(counts.get("rejected") or 0),
            "archived": int(counts.get("archived") or 0),
            "blocked": int(counts.get("blocked") or 0),
            "safe_to_start_phase_7c_execution_review_flow": bool(
                report.get("safeToStartPhase7CExecutionReviewFlow")
            ),
            "blockers": list(report.get("blockers") or []),
            "next_action": report.get("nextAction") or "",
            **_audit_false_payload(),
        },
    )


__all__ = (
    "PHASE_7B_WARNING",
    "PHASE_7B_FORBIDDEN_ACTIONS",
    "PHASE_7B_FORBIDDEN_PAYLOAD_KEYS",
    "PHASE_7B_MAX_SAFE_AMOUNT_PAISE",
    "PHASE_7B_DEFAULT_MAX_PILOT_ORDERS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_DRY_RUN_PASSED",
    "AUDIT_KIND_DRY_RUN_FAILED",
    "AUDIT_KIND_ROLLBACK_DRY_RUN_PASSED",
    "AUDIT_KIND_ROLLBACK_DRY_RUN_FAILED",
    "AUDIT_KIND_APPROVED_FOR_PHASE7C_REVIEW",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_KILL_SWITCH_DISABLED_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase7BEligibility",
    "build_phase7b_controlled_pilot_gate_contract",
    "validate_phase7b_source_lock_eligibility",
    "preview_phase7b_controlled_pilot_gate",
    "prepare_phase7b_controlled_pilot_gate",
    "dry_run_phase7b_controlled_pilot_gate",
    "rollback_dry_run_phase7b_controlled_pilot_gate",
    "approve_phase7b_controlled_pilot_gate",
    "reject_phase7b_controlled_pilot_gate",
    "archive_phase7b_controlled_pilot_gate",
    "summarize_phase7b_controlled_pilot_gates",
    "inspect_phase7b_controlled_pilot_gate_readiness",
    "emit_readiness_inspected_audit",
    "assert_phase7b_no_unauthorised_provider_call",
    "serialize_phase7b_gate",
    "serialize_phase7b_dry_run_record",
    "serialize_phase7b_rollback_dry_run_record",
)
