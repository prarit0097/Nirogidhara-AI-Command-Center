"""Phase 6S — Limited Internal Dispatch Pilot Plan (planning-only).

Planning-only layer that converts an approved Phase 6R
:class:`RazorpayPaymentDispatchReadinessGate` into a
:class:`RazorpayPaymentDispatchPilotPlan` review record. Phase 6S
**never** executes a pilot, **never** sends a WhatsApp message,
**never** queues an outbound, **never** calls Meta Cloud, **never**
calls Delhivery, **never** calls Razorpay, **never** creates a
shipment / AWB, **never** mutates real ``Order`` / ``Payment`` /
``Customer`` / ``Lead`` / ``WhatsAppMessage`` /
``WhatsAppLifecycleEvent`` rows. It NEVER flips an env flag.
Approving a pilot plan only flips ``status`` to
``approved_for_future_phase6t``.

Public surface:

- :func:`build_phase6s_payment_dispatch_pilot_contract`
- :func:`inspect_phase6s_payment_dispatch_pilot_plan_readiness`
- :func:`validate_phase6s_source_readiness_gate_eligibility`
- :func:`preview_phase6s_payment_dispatch_pilot_plan`
- :func:`prepare_phase6s_payment_dispatch_pilot_plan`
- :func:`approve_phase6s_payment_dispatch_pilot_plan`
- :func:`reject_phase6s_payment_dispatch_pilot_plan`
- :func:`archive_phase6s_payment_dispatch_pilot_plan`
- :func:`summarize_phase6s_payment_dispatch_pilot_plans`
- :func:`assert_phase6s_no_live_execution_or_provider_call`
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
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)


PHASE_6S_WARNING = (
    "Phase 6S is a planning-only Limited Internal Dispatch Pilot "
    "Plan. It NEVER executes a pilot, NEVER sends a WhatsApp message, "
    "NEVER queues an outbound, NEVER calls Meta Cloud, NEVER calls "
    "Delhivery, NEVER calls Razorpay, NEVER creates a shipment / AWB, "
    "NEVER mutates real Order / Payment / Customer / Lead / "
    "WhatsAppMessage / WhatsAppLifecycleEvent rows. It NEVER flips an "
    "env flag. Approving a pilot plan only marks it "
    "``approved_for_future_phase6t``. Review state changes are "
    "CLI-only — no API endpoint or frontend button dispatches Phase 6S "
    "approval."
)


# Audit kinds Phase 6S emits.
AUDIT_KIND_READINESS = (
    "razorpay.payment_dispatch_pilot_plan.readiness_inspected"
)
AUDIT_KIND_PREVIEWED = "razorpay.payment_dispatch_pilot_plan.previewed"
AUDIT_KIND_PREPARED = "razorpay.payment_dispatch_pilot_plan.prepared"
AUDIT_KIND_APPROVED = (
    "razorpay.payment_dispatch_pilot_plan.approved_for_future_phase6t"
)
AUDIT_KIND_REJECTED = "razorpay.payment_dispatch_pilot_plan.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.payment_dispatch_pilot_plan.archived"
AUDIT_KIND_BLOCKED = "razorpay.payment_dispatch_pilot_plan.blocked"
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.payment_dispatch_pilot_plan.invariant_violation_blocked"
)


PHASE_6S_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "approve_pilot_plan_via_api_endpoint",
)


PHASE_6S_MAX_SAFE_AMOUNT_PAISE = 100
PHASE_6S_DEFAULT_MAX_PILOT_ORDERS = 1


# ---------------------------------------------------------------------------
# Contract (9-event coverage)
# ---------------------------------------------------------------------------


_CONTRACT_BY_EVENT: dict[str, dict[str, str]] = {
    "payment_link.paid": {
        "futurePilotEligibility": (
            "eligible_for_internal_advance_paid_pilot_candidate"
        ),
        "futureWhatsAppPilotAction": (
            "internal_payment_received_template_candidate"
        ),
        "futureCourierPilotAction": "internal_courier_precheck_candidate",
        "futureDispatchPilotAction": (
            "internal_advance_paid_dispatch_precheck_candidate"
        ),
    },
    "payment.captured": {
        "futurePilotEligibility": (
            "eligible_for_internal_payment_captured_pilot_candidate"
        ),
        "futureWhatsAppPilotAction": (
            "internal_payment_captured_confirmation_candidate"
        ),
        "futureCourierPilotAction": (
            "internal_courier_handoff_precheck_candidate"
        ),
        "futureDispatchPilotAction": (
            "internal_payment_verified_dispatch_precheck_candidate"
        ),
    },
    "payment.failed": {
        "futurePilotEligibility": (
            "not_eligible_for_dispatch_pilot_payment_failed"
        ),
        "futureWhatsAppPilotAction": (
            "internal_payment_failed_followup_candidate"
        ),
        "futureCourierPilotAction": "courier_blocked_payment_failed",
        "futureDispatchPilotAction": "dispatch_blocked_payment_failed",
    },
    "payment.authorized": {
        "futurePilotEligibility": "review_only_authorized_payment_candidate",
        "futureWhatsAppPilotAction": (
            "internal_payment_authorized_review_candidate"
        ),
        "futureCourierPilotAction": (
            "courier_blocked_authorization_pending"
        ),
        "futureDispatchPilotAction": (
            "dispatch_blocked_authorization_pending"
        ),
    },
    "order.paid": {
        "futurePilotEligibility": (
            "eligible_for_internal_paid_order_pilot_candidate"
        ),
        "futureWhatsAppPilotAction": (
            "internal_paid_order_confirmation_candidate"
        ),
        "futureCourierPilotAction": (
            "internal_courier_ready_precheck_candidate"
        ),
        "futureDispatchPilotAction": (
            "internal_paid_order_dispatch_precheck_candidate"
        ),
    },
    "payment_link.cancelled": {
        "futurePilotEligibility": (
            "not_eligible_for_dispatch_pilot_payment_link_cancelled"
        ),
        "futureWhatsAppPilotAction": (
            "internal_payment_link_cancelled_followup_candidate"
        ),
        "futureCourierPilotAction": (
            "courier_blocked_payment_link_cancelled"
        ),
        "futureDispatchPilotAction": (
            "dispatch_blocked_payment_link_cancelled"
        ),
    },
    "payment_link.expired": {
        "futurePilotEligibility": (
            "not_eligible_for_dispatch_pilot_payment_link_expired"
        ),
        "futureWhatsAppPilotAction": (
            "internal_payment_link_expired_followup_candidate"
        ),
        "futureCourierPilotAction": (
            "courier_blocked_payment_link_expired"
        ),
        "futureDispatchPilotAction": (
            "dispatch_blocked_payment_link_expired"
        ),
    },
    "refund.created": {
        "futurePilotEligibility": (
            "not_eligible_for_dispatch_pilot_refund_review"
        ),
        "futureWhatsAppPilotAction": (
            "internal_refund_created_review_candidate"
        ),
        "futureCourierPilotAction": "courier_blocked_refund_review",
        "futureDispatchPilotAction": "dispatch_blocked_refund_review",
    },
    "refund.processed": {
        "futurePilotEligibility": (
            "not_eligible_for_dispatch_pilot_refunded"
        ),
        "futureWhatsAppPilotAction": (
            "internal_refund_processed_customer_info_candidate"
        ),
        "futureCourierPilotAction": "courier_blocked_refunded",
        "futureDispatchPilotAction": "dispatch_blocked_refunded",
    },
}


def _contract_row(event_name: str, spec: dict[str, str]) -> dict[str, Any]:
    return {
        "razorpayEventName": event_name,
        "futurePilotEligibility": spec["futurePilotEligibility"],
        "futureWhatsAppPilotAction": spec["futureWhatsAppPilotAction"],
        "futureCourierPilotAction": spec["futureCourierPilotAction"],
        "futureDispatchPilotAction": spec["futureDispatchPilotAction"],
        "pilotExecutionAllowedInPhase6S": False,
        "whatsappSendAllowedInPhase6S": False,
        "courierBookingAllowedInPhase6S": False,
        "providerCallAllowedInPhase6S": False,
        "mutationAllowedInFuturePhase6T": (
            "only_if_pilot_plan_approved_director_signed_off_kill_switch_policy_allows_and_internal_cohort_only"
        ),
        "manualReviewRequired": True,
        "internalStaffOnly": True,
        "maxPilotOrders": PHASE_6S_DEFAULT_MAX_PILOT_ORDERS,
        "maxAmountPaise": PHASE_6S_MAX_SAFE_AMOUNT_PAISE,
        "customerNotificationAllowed": False,
        "shipmentEffectAllowed": False,
        "discountEffectAllowed": False,
        "idempotencyRequired": True,
        "rollbackRequired": True,
        "abortCriteria": [
            "any_real_order_or_payment_mutation_observed",
            "any_whatsapp_send_or_queue_observed",
            "any_meta_cloud_or_delhivery_call_observed",
            "any_shipment_or_awb_creation_observed",
            "kill_switch_disabled",
        ],
        "blockers": [
            "phase_6s_pilot_planning_only_no_execution",
            "phase_6t_must_supply_director_signoff_kill_switch_check_and_internal_cohort",
        ],
        "notes": [
            "Phase 6S records the pilot planning contract; no production "
            "WhatsApp / courier / Razorpay / shipment / AWB action fires "
            "here.",
        ],
    }


def build_phase6s_payment_dispatch_pilot_contract() -> list[dict[str, Any]]:
    """Return the canonical 9-row Limited Internal Dispatch Pilot contract."""
    return [
        _contract_row(name, spec) for name, spec in _CONTRACT_BY_EVENT.items()
    ]


# ---------------------------------------------------------------------------
# Safety invariants + checklists
# ---------------------------------------------------------------------------


def _safety_invariants() -> dict[str, bool]:
    return {
        "pilotExecutionAllowed": False,
        "liveSendAllowed": False,
        "courierBookingAllowed": False,
        "providerCallAllowed": False,
        "realOrderMutationAllowed": False,
        "realPaymentMutationAllowed": False,
        "shipmentMutationAllowed": False,
        "shipmentCreationAllowed": False,
        "awbCreationAllowed": False,
        "discountOfferMutationAllowed": False,
        "customerMutationAllowed": False,
        "leadMutationAllowed": False,
        "whatsappMessageCreationAllowed": False,
        "whatsappQueueAllowed": False,
        "whatsappSendAllowed": False,
        "metaCloudCallAllowed": False,
        "delhiveryCallAllowed": False,
        "vapiCallAllowed": False,
        "razorpayApiInvocationAllowed": False,
        "envFlagFlipAllowed": False,
        "frontendCanExecutePhase6S": False,
        "apiEndpointCanExecutePhase6S": False,
        "apiEndpointCanApprovePhase6S": False,
        "phase6SRespectsKillSwitch": True,
        "phase6SApprovalApplyRealMutation": False,
    }


def _internal_staff_cohort_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyInternalStaffOnly",
            "description": (
                "Pilot cohort must be `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS` "
                "internal staff allow-list only — never a real customer "
                "phone."
            ),
            "automated": True,
        },
        {
            "key": "verifyMaxPilotOrders",
            "description": (
                "Pilot is bounded to a single order maximum "
                "(`max_pilot_orders=1`) for Phase 6T; subsequent runs "
                "require a fresh pilot plan."
            ),
            "automated": True,
        },
        {
            "key": "verifyMaxAmountPaise",
            "description": (
                "Pilot order amount must be <= 100 paise (₹1.00) and use "
                "the existing Razorpay TEST key only."
            ),
            "automated": True,
        },
        {
            "key": "verifyDirectorSignOff",
            "description": (
                "Manual reviewer sign-off (reason text) recorded on the "
                "pilot plan row before approval."
            ),
            "automated": False,
        },
    ]


def _whatsapp_pilot_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyApprovedClaimVaultCoverage",
            "description": (
                "Future WhatsApp template body must come only from "
                "approved Claim Vault rows."
            ),
            "automated": True,
        },
        {
            "key": "verifyConsentGranted",
            "description": (
                "Internal staff `WhatsAppConsent` row must be in "
                "``granted`` state with non-zero ``granted_at``."
            ),
            "automated": True,
        },
        {
            "key": "verifyApprovedTemplateActive",
            "description": (
                "Proposed template name must be APPROVED + active and "
                "within UTILITY/AUTHENTICATION tier."
            ),
            "automated": True,
        },
        {
            "key": "verifyLimitedTestModeOn",
            "description": (
                "`WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` and the "
                "final-send guard remains in force."
            ),
            "automated": True,
        },
    ]


def _courier_pilot_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyDelhiveryTestModeOrMock",
            "description": (
                "DELHIVERY_MODE must be 'mock' or 'test'; live courier "
                "calls forbidden in Phase 6S/6T pilot."
            ),
            "automated": True,
        },
        {
            "key": "verifyCourierServiceabilityForPincode",
            "description": (
                "Internal staff pincode (when present) must be marked "
                "serviceable in the courier service-area table."
            ),
            "automated": True,
        },
        {
            "key": "verifySyntheticOrderReference",
            "description": (
                "Order reference and AWB design remain synthetic for "
                "Phase 6S; no real Order row mutation, no real shipment "
                "row creation."
            ),
            "automated": True,
        },
    ]


def _dispatch_pilot_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyPhase6RReadinessApproved",
            "description": (
                "Source Phase 6R readiness gate is "
                "approved_for_future_phase6s with all safety booleans "
                "False."
            ),
            "automated": True,
        },
        {
            "key": "verifyPhase6QGateApproved",
            "description": (
                "Linked Phase 6Q workflow gate is "
                "approved_for_future_phase6r with all safety booleans "
                "False."
            ),
            "automated": True,
        },
        {
            "key": "verifyPhase6PSandboxProof",
            "description": (
                "Phase 6P attempt was executed + rolled back via CLI; "
                "ledger row exists and was restored."
            ),
            "automated": True,
        },
        {
            "key": "verifyPhase6SEnvFlagsAllOff",
            "description": (
                "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED, "
                "WHATSAPP_AI_AUTO_REPLY_ENABLED, "
                "WHATSAPP_CALL_HANDOFF_ENABLED, "
                "WHATSAPP_RESCUE_DISCOUNT_ENABLED, "
                "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED, "
                "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED, "
                "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED all "
                "remain false."
            ),
            "automated": True,
        },
        {
            "key": "verifyKillSwitchActive",
            "description": (
                "Phase 6H global kill switch remains enabled; no future "
                "runtime routing override is in effect."
            ),
            "automated": True,
        },
    ]


def _kill_switch_requirements() -> dict[str, Any]:
    return {
        "phase": "6S",
        "globalKillSwitchMustBeEnabled": True,
        "providerKillSwitchHonored": True,
        "rollbackOwnedByOperatorOnly": True,
        "phase6SCanExecuteRollback": False,
        "envFlagsThatMustRemainFalse": [
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED_default",
            "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED",
            "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED",
            "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED",
            "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED",
            "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED",
            "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED",
            "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD",
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
        "phase": "6S",
        "manualReviewReasonRequired": True,
        "directorSignOffRequired": True,
        "envFlagRequiredToPrepare": (
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED"
        ),
        "approvalOnlyMarksFutureCandidacy": True,
        "approvalDoesNotStartPilot": True,
        "approvalDoesNotSendWhatsApp": True,
        "approvalDoesNotCallProvider": True,
        "approvalDoesNotMutateRealBusinessRow": True,
    }


def _rollback_plan() -> dict[str, Any]:
    return {
        "phase": "6S",
        "rollbackTriggers": [
            "approval_observed_to_start_real_pilot",
            "approval_observed_to_send_real_whatsapp_message",
            "approval_observed_to_call_meta_cloud",
            "approval_observed_to_call_delhivery",
            "approval_observed_to_create_shipment_or_awb",
            "approval_observed_to_call_razorpay",
            "approval_observed_to_mutate_real_business_table",
        ],
        "rollbackSteps": [
            {
                "order": 1,
                "action": (
                    "set_RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED_to_false"
                ),
                "owner": "operator",
                "phase6SEnforced": True,
            },
            {
                "order": 2,
                "action": (
                    "archive_open_pilot_plans_via_archive_command"
                ),
                "owner": "operator",
                "phase6SEnforced": True,
            },
        ],
        "rollbackVerification": [
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED == false",
            "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED == false",
            "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED == false",
            "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED == false",
            "WHATSAPP_AI_AUTO_REPLY_ENABLED == false",
            "WHATSAPP_CALL_HANDOFF_ENABLED == false",
            "DELHIVERY_MODE == mock_or_test",
            "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED == false",
            "no_real_order_payment_shipment_customer_or_lead_mutation",
            "no_outbound_whatsapp_message_or_lifecycle_event_creation",
        ],
        "phase6SCanExecuteRollback": False,
        "rollbackOwnedByOperatorOnly": True,
        "rollbackNeverInvokesProviderApi": True,
    }


def _verification_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "noProviderCallObserved",
            "description": (
                "Phase 6S CLI/API path never calls Razorpay / Meta "
                "Cloud / Delhivery / Vapi (asserted with mock spies in "
                "tests)."
            ),
            "automated": True,
        },
        {
            "key": "noRealBusinessMutationObserved",
            "description": (
                "No Order / Payment / Shipment / DiscountOfferLog / "
                "Customer / Lead row created or updated by Phase 6S."
            ),
            "automated": True,
        },
        {
            "key": "noOutboundWhatsAppRowCreated",
            "description": (
                "No WhatsAppMessage / WhatsAppLifecycleEvent / "
                "WhatsAppHandoffToCall row created by Phase 6S."
            ),
            "automated": True,
        },
        {
            "key": "noRawSecretInOutput",
            "description": (
                "Command/API output never contains Razorpay key id, "
                "Razorpay key secret, Razorpay webhook secret, or any "
                "raw payload / signature."
            ),
            "automated": True,
        },
        {
            "key": "noPlantedPiiInOutput",
            "description": (
                "Command/API output never returns full phone, email, "
                "address, card, VPA, UPI, bank account, or wallet."
            ),
            "automated": True,
        },
    ]


def _abort_criteria() -> list[str]:
    return [
        "any_real_order_or_payment_mutation_observed",
        "any_whatsapp_send_or_queue_observed",
        "any_meta_cloud_or_delhivery_call_observed",
        "any_shipment_or_awb_creation_observed",
        "kill_switch_disabled",
        "raw_secret_or_full_pii_observed_in_output",
    ]


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


def assert_phase6s_no_live_execution_or_provider_call(
    plan: RazorpayPaymentDispatchPilotPlan,
) -> None:
    """Raise ``ValueError`` if any locked-False safety boolean is True.

    Phase 6S MUST never flip any of these to True. The defensive
    guard runs before persisting / serializing a plan row, emits an
    ``invariant_violation_blocked`` audit row, and refuses the
    operation.
    """
    flipped: list[str] = []
    for field in (
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
        if getattr(plan, field, False) is True:
            flipped.append(field)
    if not flipped:
        return

    write_event(
        kind=AUDIT_KIND_INVARIANT_VIOLATION,
        text=(
            f"Phase 6S invariant violation blocked plan_id={plan.pk} "
            f"flipped={flipped}"
        ),
        tone=AuditEvent.Tone.DANGER,
        payload={
            "phase": "6S",
            "plan_id": plan.pk,
            "flipped_safety_booleans": flipped,
            "pilot_execution_allowed_in_phase6s": False,
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
        },
    )
    raise ValueError(
        f"Phase 6S safety invariant violation: {flipped} must remain False."
    )


# ---------------------------------------------------------------------------
# Eligibility validator
# ---------------------------------------------------------------------------


@dataclass
class Phase6SEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None
    ledger: RazorpaySandboxPaidStatusLedger | None
    review: RazorpaySandboxStatusReview | None
    event: RazorpayWebhookEvent | None


def validate_phase6s_source_readiness_gate_eligibility(
    source_readiness_id: int | None,
    *,
    require_env_flag: bool = True,
) -> Phase6SEligibility:
    """Validate that a Phase 6R readiness gate is eligible for Phase 6S
    pilot plan creation.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None = None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None = None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None = None
    ledger: RazorpaySandboxPaidStatusLedger | None = None
    review: RazorpaySandboxStatusReview | None = None
    event: RazorpayWebhookEvent | None = None

    if require_env_flag and not bool(
        getattr(
            settings,
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
            False,
        )
    ):
        blockers.append(
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED_must_be_true"
        )

    if source_readiness_id:
        readiness_gate = (
            RazorpayPaymentDispatchReadinessGate.objects.filter(
                pk=source_readiness_id
            )
            .select_related(
                "source_workflow_gate",
                "source_attempt",
                "source_ledger",
                "source_review",
                "razorpay_webhook_event",
            )
            .first()
        )

    if readiness_gate is None:
        blockers.append("phase_6r_source_readiness_gate_not_found")
        return Phase6SEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            readiness_gate=None,
            workflow_gate=None,
            attempt=None,
            ledger=None,
            review=None,
            event=None,
        )

    # Phase 6R readiness gate eligibility.
    if (
        readiness_gate.status
        != RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
    ):
        blockers.append(
            f"phase_6r_readiness_gate_status_must_be_approved_for_future_phase6s_was_{readiness_gate.status}"
        )
    if readiness_gate.dispatch_readiness_allowed_in_phase6r:
        blockers.append(
            "phase_6r_readiness_gate_dispatch_readiness_allowed_must_be_false"
        )
    if readiness_gate.real_order_mutation_was_made:
        blockers.append(
            "phase_6r_readiness_gate_real_order_mutation_was_made"
        )
    if readiness_gate.real_payment_mutation_was_made:
        blockers.append(
            "phase_6r_readiness_gate_real_payment_mutation_was_made"
        )
    if readiness_gate.shipment_mutation_was_made:
        blockers.append(
            "phase_6r_readiness_gate_shipment_mutation_was_made"
        )
    if readiness_gate.shipment_created:
        blockers.append("phase_6r_readiness_gate_shipment_created")
    if readiness_gate.whatsapp_message_created:
        blockers.append(
            "phase_6r_readiness_gate_whatsapp_message_created"
        )
    if readiness_gate.whatsapp_message_queued:
        blockers.append(
            "phase_6r_readiness_gate_whatsapp_message_queued"
        )
    if readiness_gate.customer_notification_sent:
        blockers.append(
            "phase_6r_readiness_gate_customer_notification_sent"
        )
    if readiness_gate.meta_cloud_call_attempted:
        blockers.append(
            "phase_6r_readiness_gate_meta_cloud_call_attempted"
        )
    if readiness_gate.delhivery_call_attempted:
        blockers.append(
            "phase_6r_readiness_gate_delhivery_call_attempted"
        )
    if readiness_gate.provider_call_attempted:
        blockers.append(
            "phase_6r_readiness_gate_provider_call_attempted"
        )

    workflow_gate = readiness_gate.source_workflow_gate
    attempt = readiness_gate.source_attempt
    ledger = readiness_gate.source_ledger
    review = readiness_gate.source_review
    event = readiness_gate.razorpay_webhook_event

    # Phase 6Q gate eligibility.
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

    # Phase 6P attempt eligibility.
    if attempt is None:
        blockers.append("phase_6p_source_attempt_not_found")
    else:
        if attempt.status not in (
            RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
            RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
        ):
            blockers.append(
                f"phase6p_attempt_status_{attempt.status}_not_eligible"
            )
        if attempt.real_order_mutation_was_made:
            blockers.append(
                "phase6p_attempt_real_order_mutation_was_made"
            )
        if attempt.real_payment_mutation_was_made:
            blockers.append(
                "phase6p_attempt_real_payment_mutation_was_made"
            )
        if attempt.business_mutation_was_made:
            blockers.append("phase6p_attempt_business_mutation_was_made")
        if attempt.customer_notification_sent:
            blockers.append("phase6p_attempt_customer_notification_sent")
        if attempt.provider_call_attempted:
            blockers.append("phase6p_attempt_provider_call_attempted")

    # Phase 6O review eligibility.
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

    # Source RazorpayWebhookEvent.
    if event is None:
        blockers.append("razorpay_webhook_event_not_found")
    else:
        if not event.signature_valid:
            blockers.append("source_event_signature_invalid")
        if not event.replay_window_valid:
            blockers.append("source_event_replay_window_invalid")
        if (
            event.idempotency_status
            != RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN
        ):
            blockers.append("source_event_idempotency_must_be_first_seen")
        if event.business_mutation_was_made:
            blockers.append("source_event_business_mutation_was_made")
        if event.customer_notification_sent:
            blockers.append("source_event_customer_notification_sent")
        if event.raw_secret_exposed:
            blockers.append("source_event_raw_secret_exposed")
        if event.full_pii_exposed or event.scrubbed_keys:
            blockers.append("source_event_full_pii_must_be_absent")
        if event.environment != RazorpayWebhookEvent.Environment.TEST:
            blockers.append(
                f"source_event_environment_must_be_test_was_{event.environment}"
            )
        if event.event_name not in _CONTRACT_BY_EVENT:
            blockers.append(
                f"event_name_not_phase6s_allowlisted_{event.event_name}"
            )
        if (
            event.amount_paise is not None
            and event.amount_paise > PHASE_6S_MAX_SAFE_AMOUNT_PAISE
        ):
            blockers.append(
                f"amount_paise_must_be_<=_{PHASE_6S_MAX_SAFE_AMOUNT_PAISE}"
            )

    return Phase6SEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
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


def _serialize_pilot_plan(
    row: RazorpayPaymentDispatchPilotPlan,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "sourceReadinessGateId": row.source_readiness_gate_id,
        "sourceWorkflowGateId": row.source_workflow_gate_id,
        "sourceAttemptId": row.source_attempt_id,
        "sourceLedgerId": row.source_ledger_id,
        "sourceReviewId": row.source_review_id,
        "razorpayWebhookEventId": row.razorpay_webhook_event_id,
        "sourceEventId": row.source_event_id,
        "eventName": row.event_name,
        "providerEnvironment": row.provider_environment,
        "providerOrderId": row.provider_order_id,
        "providerPaymentId": row.provider_payment_id,
        "providerPaymentLinkId": row.provider_payment_link_id,
        "amountPaise": row.amount_paise,
        "currency": row.currency,
        "proposedPilotScope": row.proposed_pilot_scope,
        "proposedPaymentStatus": row.proposed_payment_status,
        "proposedOrderStatus": row.proposed_order_status,
        "proposedOrderEffect": row.proposed_order_effect,
        "proposedWhatsAppAction": row.proposed_whatsapp_action,
        "proposedCourierAction": row.proposed_courier_action,
        "proposedDispatchAction": row.proposed_dispatch_action,
        "pilotMode": row.pilot_mode,
        "status": row.status,
        "internalOnly": row.internal_only,
        "maxPilotOrders": row.max_pilot_orders,
        "maxAmountPaise": row.max_amount_paise,
        "allowedCustomerScope": row.allowed_customer_scope,
        "allowedStaffCohort": list(row.allowed_staff_cohort or []),
        "allowedEventNames": list(row.allowed_event_names or []),
        "manualReviewRequired": row.manual_review_required,
        "pilotExecutionAllowedInPhase6S": (
            row.pilot_execution_allowed_in_phase6s
        ),
        "liveSendAllowedInPhase6S": row.live_send_allowed_in_phase6s,
        "courierBookingAllowedInPhase6S": (
            row.courier_booking_allowed_in_phase6s
        ),
        "providerCallAllowedInPhase6S": (
            row.provider_call_allowed_in_phase6s
        ),
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
        "rollbackRequired": row.rollback_required,
        "idempotencyKey": row.idempotency_key,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
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


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase6s_payment_dispatch_pilot_plan(
    source_readiness_id: int,
) -> dict[str, Any]:
    """Read-only preview. Never creates rows, never mutates anything."""
    eligibility = validate_phase6s_source_readiness_gate_eligibility(
        source_readiness_id, require_env_flag=False
    )

    proposed = None
    if eligibility.event is not None:
        spec = _CONTRACT_BY_EVENT.get(eligibility.event.event_name)
        if spec is not None:
            proposed = _contract_row(eligibility.event.event_name, spec)

    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 6S preview source_readiness_id={source_readiness_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6S",
            "source_phase6r_readiness_id": source_readiness_id,
            "source_phase6q_gate_id": (
                eligibility.workflow_gate.pk
                if eligibility.workflow_gate
                else None
            ),
            "source_attempt_id": (
                eligibility.attempt.pk if eligibility.attempt else None
            ),
            "source_ledger_id": (
                eligibility.ledger.pk if eligibility.ledger else None
            ),
            "source_review_id": (
                eligibility.review.pk if eligibility.review else None
            ),
            "source_event_id": (
                eligibility.event.source_event_id if eligibility.event else ""
            ),
            "event_name": (
                eligibility.event.event_name if eligibility.event else ""
            ),
            "eligible": eligibility.eligible,
            "blockers": list(eligibility.blockers),
            "pilot_execution_allowed_in_phase6s": False,
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
        },
    )

    return {
        "phase": "6S",
        "found": eligibility.readiness_gate is not None,
        "sourcePhase6RReadinessId": source_readiness_id,
        "sourcePhase6QGateId": (
            eligibility.workflow_gate.pk
            if eligibility.workflow_gate
            else None
        ),
        "sourceAttemptId": (
            eligibility.attempt.pk if eligibility.attempt else None
        ),
        "sourceLedgerId": (
            eligibility.ledger.pk if eligibility.ledger else None
        ),
        "sourceReviewId": (
            eligibility.review.pk if eligibility.review else None
        ),
        "sourceEventId": (
            eligibility.event.source_event_id if eligibility.event else ""
        ),
        "eventName": (
            eligibility.event.event_name if eligibility.event else ""
        ),
        "eligible": eligibility.eligible,
        "proposedContract": proposed,
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_6S_WARNING],
        "nextAction": (
            "ready_to_prepare_phase6s_pilot_plan"
            if eligibility.eligible
            and bool(
                getattr(
                    settings,
                    "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
                    False,
                )
            )
            else "fix_phase_6s_eligibility_blockers_or_enable_pilot_plan_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(
    readiness_gate: RazorpayPaymentDispatchReadinessGate,
) -> str:
    return f"phase6s::pilot_plan::readiness_gate::{readiness_gate.pk}"


def prepare_phase6s_payment_dispatch_pilot_plan(
    source_readiness_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create / re-fetch a pilot plan row.

    Idempotent on the source Phase 6R readiness gate. NEVER mutates
    real business tables, NEVER sends WhatsApp, NEVER calls Meta
    Cloud, NEVER calls Delhivery, NEVER calls Razorpay, NEVER creates
    a shipment / AWB.
    """
    eligibility = validate_phase6s_source_readiness_gate_eligibility(
        source_readiness_id, require_env_flag=True
    )

    if not eligibility.eligible or eligibility.event is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 6S prepare blocked source_readiness_id={source_readiness_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "6S",
                "source_phase6r_readiness_id": source_readiness_id,
                "blockers": list(eligibility.blockers),
                "pilot_execution_allowed_in_phase6s": False,
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "shipment_created": False,
                "awb_created": False,
                "whatsapp_message_created": False,
                "whatsapp_message_queued": False,
                "customer_notification_sent": False,
                "meta_cloud_call_attempted": False,
                "delhivery_call_attempted": False,
                "razorpay_call_attempted": False,
                "provider_call_attempted": False,
            },
        )
        return {
            "phase": "6S",
            "created": False,
            "reused": False,
            "plan": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_6S_WARNING],
            "nextAction": (
                "fix_phase_6s_eligibility_blockers_or_enable_pilot_plan_flag"
            ),
        }

    spec = _CONTRACT_BY_EVENT.get(eligibility.event.event_name)
    if spec is None:
        return {
            "phase": "6S",
            "created": False,
            "reused": False,
            "plan": None,
            "blockers": [
                f"event_name_not_phase6s_allowlisted_{eligibility.event.event_name}"
            ],
            "warnings": [PHASE_6S_WARNING],
            "nextAction": "event_not_in_phase6s_allowlist",
        }

    contract = _contract_row(eligibility.event.event_name, spec)
    readiness_gate = eligibility.readiness_gate
    workflow_gate = eligibility.workflow_gate
    attempt = eligibility.attempt
    ledger = eligibility.ledger
    review = eligibility.review
    event = eligibility.event
    idempotency = _idempotency_key(readiness_gate)

    with transaction.atomic():
        existing = (
            RazorpayPaymentDispatchPilotPlan.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "6S",
                "created": False,
                "reused": True,
                "plan": _serialize_pilot_plan(existing),
                "blockers": [],
                "warnings": [PHASE_6S_WARNING],
                "nextAction": "pilot_plan_pending_manual_review",
            }

        plan = RazorpayPaymentDispatchPilotPlan(
            source_readiness_gate=readiness_gate,
            source_workflow_gate=workflow_gate,
            source_attempt=attempt,
            source_ledger=ledger,
            source_review=review,
            razorpay_webhook_event=event,
            source_event_id=event.source_event_id if event else "",
            event_name=event.event_name if event else "",
            provider_environment=(
                event.environment if event else "test"
            ),
            provider_order_id=(
                event.provider_order_id if event else ""
            ),
            provider_payment_id=(
                event.provider_payment_id if event else ""
            ),
            provider_payment_link_id="",
            amount_paise=(event.amount_paise if event else None),
            currency=(event.currency if event else ""),
            proposed_pilot_scope=spec["futurePilotEligibility"],
            proposed_payment_status=(
                readiness_gate.proposed_payment_status
                if readiness_gate
                else ""
            ),
            proposed_order_status=(
                readiness_gate.proposed_order_status
                if readiness_gate
                else ""
            ),
            proposed_order_effect=(
                readiness_gate.proposed_order_effect
                if readiness_gate
                else ""
            ),
            proposed_whatsapp_action=spec["futureWhatsAppPilotAction"],
            proposed_courier_action=spec["futureCourierPilotAction"],
            proposed_dispatch_action=spec["futureDispatchPilotAction"],
            pilot_mode=(
                RazorpayPaymentDispatchPilotPlan.PilotMode.PLANNING_ONLY
            ),
            status=(
                RazorpayPaymentDispatchPilotPlan.Status.PENDING_MANUAL_REVIEW
            ),
            internal_only=True,
            max_pilot_orders=PHASE_6S_DEFAULT_MAX_PILOT_ORDERS,
            max_amount_paise=PHASE_6S_MAX_SAFE_AMOUNT_PAISE,
            allowed_customer_scope="internal_staff_only",
            allowed_staff_cohort=[
                {
                    "key": "internal_staff_allow_list",
                    "description": (
                        "Pilot cohort sourced from "
                        "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS allow-list"
                    ),
                    "policy": "phone_last_4_only",
                },
            ],
            allowed_event_names=list(_CONTRACT_BY_EVENT.keys()),
            whatsapp_template_candidates=[
                {
                    "futureAction": spec["futureWhatsAppPilotAction"],
                    "templateTier": "UTILITY_OR_AUTHENTICATION",
                    "claimVaultRequired": True,
                    "approvedTemplateRequired": True,
                },
            ],
            courier_precheck_candidates=[
                {
                    "futureAction": spec["futureCourierPilotAction"],
                    "delhiveryMode": "mock_or_test",
                    "syntheticOrderReferenceRequired": True,
                },
            ],
            dispatch_precheck_candidates=[
                {
                    "futureAction": spec["futureDispatchPilotAction"],
                    "phase6RReadinessApprovalRequired": True,
                    "phase6QGateApprovalRequired": True,
                    "phase6PSandboxProofRequired": True,
                    "directorSignOffRequired": True,
                    "killSwitchActiveRequired": True,
                },
            ],
            kill_switch_requirements=_kill_switch_requirements(),
            approval_requirements=_approval_requirements(),
            rollback_plan=_rollback_plan(),
            abort_criteria=_abort_criteria(),
            verification_checklist=_verification_checklist(),
            manual_review_required=True,
            pilot_execution_allowed_in_phase6s=False,
            live_send_allowed_in_phase6s=False,
            courier_booking_allowed_in_phase6s=False,
            provider_call_allowed_in_phase6s=False,
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
            rollback_required=True,
            idempotency_key=idempotency,
            blockers=list(contract["blockers"]),
            warnings=[PHASE_6S_WARNING],
            safety_invariants=_safety_invariants(),
            requested_by=requested_by,
        )
        assert_phase6s_no_live_execution_or_provider_call(plan)
        try:
            plan.save()
        except IntegrityError:
            plan = RazorpayPaymentDispatchPilotPlan.objects.get(
                idempotency_key=idempotency
            )
            return {
                "phase": "6S",
                "created": False,
                "reused": True,
                "plan": _serialize_pilot_plan(plan),
                "blockers": [],
                "warnings": [PHASE_6S_WARNING],
                "nextAction": "pilot_plan_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 6S pilot plan prepared plan_id={plan.pk} "
            f"source_readiness_id={readiness_gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6S",
            "plan_id": plan.pk,
            "source_phase6r_readiness_id": readiness_gate.pk,
            "source_phase6q_gate_id": plan.source_workflow_gate_id,
            "source_attempt_id": plan.source_attempt_id,
            "source_ledger_id": plan.source_ledger_id,
            "source_review_id": plan.source_review_id,
            "source_event_id": plan.source_event_id,
            "event_name": plan.event_name,
            "status": plan.status,
            "pilot_execution_allowed_in_phase6s": False,
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
        },
    )

    return {
        "phase": "6S",
        "created": True,
        "reused": False,
        "plan": _serialize_pilot_plan(plan),
        "blockers": [],
        "warnings": [PHASE_6S_WARNING],
        "nextAction": "pilot_plan_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


_TRANSITIONABLE_FROM = {
    RazorpayPaymentDispatchPilotPlan.Status.DRAFT,
    RazorpayPaymentDispatchPilotPlan.Status.PENDING_MANUAL_REVIEW,
}


def _transition(
    plan_id: int,
    *,
    new_status: str,
    audit_kind: str,
    by_user=None,
    reason: str = "",
    archive: bool = False,
    require_reason: bool = False,
) -> dict[str, Any]:
    plan = (
        RazorpayPaymentDispatchPilotPlan.objects.filter(pk=plan_id).first()
        if plan_id
        else None
    )
    if plan is None:
        return {
            "phase": "6S",
            "ok": False,
            "plan": None,
            "blockers": ["pilot_plan_not_found"],
            "warnings": [PHASE_6S_WARNING],
            "nextAction": "verify_plan_id",
        }
    if not bool(
        getattr(
            settings,
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
            False,
        )
    ):
        return {
            "phase": "6S",
            "ok": False,
            "plan": _serialize_pilot_plan(plan),
            "blockers": [
                "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_6S_WARNING],
            "nextAction": (
                "enable_pilot_plan_flag_before_review_state_change"
            ),
        }
    if archive:
        if plan.status == RazorpayPaymentDispatchPilotPlan.Status.ARCHIVED:
            return {
                "phase": "6S",
                "ok": False,
                "plan": _serialize_pilot_plan(plan),
                "blockers": ["pilot_plan_already_archived"],
                "warnings": [PHASE_6S_WARNING],
                "nextAction": "verify_plan_id",
            }
    elif plan.status not in _TRANSITIONABLE_FROM:
        return {
            "phase": "6S",
            "ok": False,
            "plan": _serialize_pilot_plan(plan),
            "blockers": [f"pilot_plan_status_{plan.status}_not_transitionable"],
            "warnings": [PHASE_6S_WARNING],
            "nextAction": "verify_plan_id",
        }
    if require_reason and not reason.strip():
        return {
            "phase": "6S",
            "ok": False,
            "plan": _serialize_pilot_plan(plan),
            "blockers": ["manual_review_reason_must_be_non_empty"],
            "warnings": [PHASE_6S_WARNING],
            "nextAction": "supply_manual_review_reason",
        }

    assert_phase6s_no_live_execution_or_provider_call(plan)

    plan.status = new_status
    if archive:
        plan.archived_by = by_user
        plan.archived_at = timezone.now()
        plan.archive_reason = (reason or "")[:200]
    else:
        plan.reviewed_by = by_user
        plan.reviewed_at = timezone.now()
        plan.review_reason = (reason or "")[:200]
    plan.save()

    write_event(
        kind=audit_kind,
        text=(
            f"Phase 6S pilot plan {new_status} plan_id={plan.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6S",
            "plan_id": plan.pk,
            "source_phase6r_readiness_id": plan.source_readiness_gate_id,
            "source_phase6q_gate_id": plan.source_workflow_gate_id,
            "source_attempt_id": plan.source_attempt_id,
            "source_ledger_id": plan.source_ledger_id,
            "source_review_id": plan.source_review_id,
            "source_event_id": plan.source_event_id,
            "event_name": plan.event_name,
            "status": plan.status,
            "reason_summary_present": bool(reason.strip()),
            "pilot_execution_allowed_in_phase6s": False,
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
        },
    )

    return {
        "phase": "6S",
        "ok": True,
        "plan": _serialize_pilot_plan(plan),
        "blockers": [],
        "warnings": [PHASE_6S_WARNING],
        "nextAction": (
            "ready_for_phase_6t_planning_after_director_signoff"
            if new_status
            == RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
            else "pilot_plan_finalised"
        ),
    }


def approve_phase6s_payment_dispatch_pilot_plan(
    plan_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the pilot plan approved **for future Phase 6T only**. NEVER
    starts a pilot, NEVER sends WhatsApp, NEVER queues an outbound,
    NEVER calls Meta Cloud / Delhivery / Razorpay, NEVER creates a
    shipment / AWB, NEVER mutates real business tables. Manual review
    reason text required.
    """
    return _transition(
        plan_id,
        new_status=(
            RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
        ),
        audit_kind=AUDIT_KIND_APPROVED,
        by_user=reviewed_by,
        reason=reason,
        require_reason=True,
    )


def reject_phase6s_payment_dispatch_pilot_plan(
    plan_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        plan_id,
        new_status=RazorpayPaymentDispatchPilotPlan.Status.REJECTED,
        audit_kind=AUDIT_KIND_REJECTED,
        by_user=reviewed_by,
        reason=reason,
    )


def archive_phase6s_payment_dispatch_pilot_plan(
    plan_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        plan_id,
        new_status=RazorpayPaymentDispatchPilotPlan.Status.ARCHIVED,
        audit_kind=AUDIT_KIND_ARCHIVED,
        by_user=archived_by,
        reason=reason,
        archive=True,
    )


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase6s_payment_dispatch_pilot_plans(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpayPaymentDispatchPilotPlan.objects.all().order_by(
        "-created_at"
    )
    Status = RazorpayPaymentDispatchPilotPlan.Status
    counts = {
        "draft": qs.filter(status=Status.DRAFT).count(),
        "pendingManualReview": qs.filter(
            status=Status.PENDING_MANUAL_REVIEW
        ).count(),
        "approvedForFuturePhase6T": qs.filter(
            status=Status.APPROVED_FOR_FUTURE_PHASE6T
        ).count(),
        "rejected": qs.filter(status=Status.REJECTED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
        "pilotExecutionAllowedInPhase6S": qs.filter(
            pilot_execution_allowed_in_phase6s=True
        ).count(),
        "realOrderMutationWasMade": qs.filter(
            real_order_mutation_was_made=True
        ).count(),
        "realPaymentMutationWasMade": qs.filter(
            real_payment_mutation_was_made=True
        ).count(),
        "shipmentMutationWasMade": qs.filter(
            shipment_mutation_was_made=True
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
        "providerCallAttempted": qs.filter(
            provider_call_attempted=True
        ).count(),
    }
    sample = [
        _serialize_pilot_plan(row) for row in qs[: max(1, min(limit, 200))]
    ]
    return {"counts": counts, "items": sample}


def inspect_phase6s_payment_dispatch_pilot_plan_readiness() -> dict[str, Any]:
    flag_enabled = bool(
        getattr(
            settings,
            "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
            False,
        )
    )
    summary = summarize_phase6s_payment_dispatch_pilot_plans()
    counts = summary["counts"]

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6S_WARNING]

    for key in (
        "pilotExecutionAllowedInPhase6S",
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
        "providerCallAttempted",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_6s_pilot_plan_{key}_observed_must_be_zero"
            )

    # Phase 6R approved-readiness presence.
    phase6r_approved = (
        RazorpayPaymentDispatchReadinessGate.objects.filter(
            status=RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
        ).count()
    )

    safe_to_start_phase_6t = bool(
        not blockers and counts["approvedForFuturePhase6T"] >= 1
    )

    if blockers:
        next_action = "fix_phase_6s_safety_blockers"
    elif phase6r_approved == 0:
        next_action = (
            "approve_at_least_one_phase_6r_readiness_gate_before_running_phase_6s"
        )
    elif counts["approvedForFuturePhase6T"] == 0:
        next_action = (
            "approve_at_least_one_phase6s_pilot_plan_for_future_phase6t"
        )
    else:
        next_action = (
            "ready_for_phase_6t_final_phase6_audit_lock_or_controlled_pilot_execution_decision_gate"
        )

    return {
        "phase": "6S",
        "status": "pilot_planning_only",
        "latestCompletedPhase": "6R",
        "nextPhase": "6T",
        "razorpayPaymentDispatchPilotPlanEnabled": flag_enabled,
        "pilotExecutionEnabled": False,
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "providerCallAttempted": False,
        "rawPayloadStorageEnabled": False,
        "phase6RApprovedReadinessGateCount": phase6r_approved,
        "pilotPlanCounts": counts,
        "pilotContract": (
            build_phase6s_payment_dispatch_pilot_contract()
        ),
        "safetyInvariants": _safety_invariants(),
        "internalStaffCohortChecklist": (
            _internal_staff_cohort_checklist()
        ),
        "whatsAppPilotChecklist": _whatsapp_pilot_checklist(),
        "courierPilotChecklist": _courier_pilot_checklist(),
        "dispatchPilotChecklist": _dispatch_pilot_checklist(),
        "killSwitchRequirements": _kill_switch_requirements(),
        "approvalRequirements": _approval_requirements(),
        "rollbackPlan": _rollback_plan(),
        "abortCriteria": _abort_criteria(),
        "verificationChecklist": _verification_checklist(),
        "forbiddenActions": list(PHASE_6S_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "maxSafeAmountPaise": PHASE_6S_MAX_SAFE_AMOUNT_PAISE,
        "maxPilotOrders": PHASE_6S_DEFAULT_MAX_PILOT_ORDERS,
        "safeToStartPhase6T": safe_to_start_phase_6t,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentPilotPlans": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("pilotPlanCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 6S payment dispatch pilot plan readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6S",
            "razorpay_payment_dispatch_pilot_plan_enabled": bool(
                report.get("razorpayPaymentDispatchPilotPlanEnabled")
            ),
            "phase6r_approved_readiness_gate_count": int(
                report.get("phase6RApprovedReadinessGateCount") or 0
            ),
            "pending_manual_review": int(
                counts.get("pendingManualReview") or 0
            ),
            "approved_for_future_phase6t": int(
                counts.get("approvedForFuturePhase6T") or 0
            ),
            "rejected": int(counts.get("rejected") or 0),
            "archived": int(counts.get("archived") or 0),
            "blocked": int(counts.get("blocked") or 0),
            "safe_to_start_phase_6t": bool(
                report.get("safeToStartPhase6T")
            ),
            "blockers": list(report.get("blockers") or []),
            "next_action": report.get("nextAction") or "",
            "pilot_execution_allowed_in_phase6s": False,
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
        },
    )


__all__ = (
    "PHASE_6S_WARNING",
    "PHASE_6S_FORBIDDEN_ACTIONS",
    "PHASE_6S_MAX_SAFE_AMOUNT_PAISE",
    "PHASE_6S_DEFAULT_MAX_PILOT_ORDERS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase6SEligibility",
    "build_phase6s_payment_dispatch_pilot_contract",
    "validate_phase6s_source_readiness_gate_eligibility",
    "preview_phase6s_payment_dispatch_pilot_plan",
    "prepare_phase6s_payment_dispatch_pilot_plan",
    "approve_phase6s_payment_dispatch_pilot_plan",
    "reject_phase6s_payment_dispatch_pilot_plan",
    "archive_phase6s_payment_dispatch_pilot_plan",
    "summarize_phase6s_payment_dispatch_pilot_plans",
    "inspect_phase6s_payment_dispatch_pilot_plan_readiness",
    "emit_readiness_inspected_audit",
    "assert_phase6s_no_live_execution_or_provider_call",
)
