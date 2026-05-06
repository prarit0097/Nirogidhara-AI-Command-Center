"""Phase 6R — Payment → WhatsApp/Courier Dispatch Readiness.

Audit-only readiness layer that converts an approved Phase 6Q
:class:`RazorpayPaymentOrderWorkflowGate` into a
:class:`RazorpayPaymentDispatchReadinessGate` review record. Phase 6R
**never** sends a WhatsApp message, **never** queues an outbound,
**never** calls Meta Cloud, **never** calls Delhivery, **never**
creates a shipment, **never** mutates real ``Order`` / ``Payment`` /
``Customer`` / ``Lead`` / ``WhatsAppMessage`` /
``WhatsAppLifecycleEvent`` rows. It NEVER calls Razorpay, NEVER
flips an env flag. Approving a readiness gate only flips ``status``
to ``approved_for_future_phase6s``.

Public surface:

- :func:`build_phase6r_payment_dispatch_readiness_contract`
- :func:`inspect_phase6r_payment_dispatch_readiness`
- :func:`validate_phase6r_source_gate_eligibility`
- :func:`preview_phase6r_payment_dispatch_readiness_gate`
- :func:`prepare_phase6r_payment_dispatch_readiness_gate`
- :func:`approve_phase6r_payment_dispatch_readiness_gate`
- :func:`reject_phase6r_payment_dispatch_readiness_gate`
- :func:`archive_phase6r_payment_dispatch_readiness_gate`
- :func:`summarize_phase6r_payment_dispatch_readiness_gates`
- :func:`assert_phase6r_no_live_send_or_courier_mutation`
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
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)


PHASE_6R_WARNING = (
    "Phase 6R is an audit-only Payment → WhatsApp/Courier dispatch "
    "readiness gate. It NEVER sends a WhatsApp message, NEVER queues "
    "an outbound, NEVER calls Meta Cloud, NEVER calls Delhivery, "
    "NEVER creates a shipment, NEVER mutates real Order / Payment / "
    "Customer / Lead / WhatsAppMessage / WhatsAppLifecycleEvent rows. "
    "It NEVER calls Razorpay, NEVER flips an env flag. Approving a "
    "readiness gate only marks it ``approved_for_future_phase6s``. "
    "Review state changes are CLI-only — no API endpoint or frontend "
    "button dispatches Phase 6R approval."
)


# Audit kinds Phase 6R emits.
AUDIT_KIND_READINESS = "razorpay.payment_dispatch_readiness.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.payment_dispatch_readiness.previewed"
AUDIT_KIND_PREPARED = "razorpay.payment_dispatch_readiness.prepared"
AUDIT_KIND_APPROVED = (
    "razorpay.payment_dispatch_readiness.approved_for_future_phase6s"
)
AUDIT_KIND_REJECTED = "razorpay.payment_dispatch_readiness.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.payment_dispatch_readiness.archived"
AUDIT_KIND_BLOCKED = "razorpay.payment_dispatch_readiness.blocked"
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.payment_dispatch_readiness.invariant_violation_blocked"
)


PHASE_6R_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "execute_workflow_via_frontend",
    "execute_workflow_via_api_endpoint",
    "approve_readiness_via_api_endpoint",
)


PHASE_6R_MAX_SAFE_AMOUNT_PAISE = 100


# ---------------------------------------------------------------------------
# Contract (9-event coverage)
# ---------------------------------------------------------------------------


_CONTRACT_BY_EVENT: dict[str, dict[str, str]] = {
    "payment_link.paid": {
        "futureWhatsAppReadinessAction": (
            "ready_advance_payment_received_template_candidate"
        ),
        "futureCourierReadinessAction": "courier_precheck_candidate",
        "futureDispatchReadinessAction": (
            "advance_paid_dispatch_precheck_candidate"
        ),
    },
    "payment.captured": {
        "futureWhatsAppReadinessAction": (
            "ready_payment_captured_confirmation_candidate"
        ),
        "futureCourierReadinessAction": "courier_handoff_precheck_candidate",
        "futureDispatchReadinessAction": (
            "payment_verified_dispatch_precheck_candidate"
        ),
    },
    "payment.failed": {
        "futureWhatsAppReadinessAction": (
            "ready_payment_failed_followup_candidate"
        ),
        "futureCourierReadinessAction": "courier_blocked_payment_failed",
        "futureDispatchReadinessAction": "dispatch_blocked_payment_failed",
    },
    "payment.authorized": {
        "futureWhatsAppReadinessAction": (
            "ready_payment_authorized_review_candidate"
        ),
        "futureCourierReadinessAction": (
            "courier_blocked_authorization_pending"
        ),
        "futureDispatchReadinessAction": (
            "dispatch_blocked_authorization_pending"
        ),
    },
    "order.paid": {
        "futureWhatsAppReadinessAction": (
            "ready_paid_order_confirmation_candidate"
        ),
        "futureCourierReadinessAction": "courier_ready_precheck_candidate",
        "futureDispatchReadinessAction": (
            "paid_order_dispatch_precheck_candidate"
        ),
    },
    "payment_link.cancelled": {
        "futureWhatsAppReadinessAction": (
            "ready_payment_link_cancelled_followup_candidate"
        ),
        "futureCourierReadinessAction": (
            "courier_blocked_payment_link_cancelled"
        ),
        "futureDispatchReadinessAction": (
            "dispatch_blocked_payment_link_cancelled"
        ),
    },
    "payment_link.expired": {
        "futureWhatsAppReadinessAction": (
            "ready_payment_link_expired_followup_candidate"
        ),
        "futureCourierReadinessAction": (
            "courier_blocked_payment_link_expired"
        ),
        "futureDispatchReadinessAction": (
            "dispatch_blocked_payment_link_expired"
        ),
    },
    "refund.created": {
        "futureWhatsAppReadinessAction": (
            "ready_refund_created_review_candidate"
        ),
        "futureCourierReadinessAction": "courier_blocked_refund_review",
        "futureDispatchReadinessAction": "dispatch_blocked_refund_review",
    },
    "refund.processed": {
        "futureWhatsAppReadinessAction": (
            "ready_refund_processed_customer_info_candidate"
        ),
        "futureCourierReadinessAction": "courier_blocked_refunded",
        "futureDispatchReadinessAction": "dispatch_blocked_refunded",
    },
}


def _contract_row(event_name: str, spec: dict[str, str]) -> dict[str, Any]:
    return {
        "razorpayEventName": event_name,
        "futureWhatsAppReadinessAction": spec["futureWhatsAppReadinessAction"],
        "futureCourierReadinessAction": spec["futureCourierReadinessAction"],
        "futureDispatchReadinessAction": (
            spec["futureDispatchReadinessAction"]
        ),
        "whatsappSendAllowedInPhase6R": False,
        "courierBookingAllowedInPhase6R": False,
        "providerCallAllowedInPhase6R": False,
        "mutationAllowedInFuturePhase6S": (
            "only_if_readiness_gate_approved_director_signed_off_and_kill_switch_allows"
        ),
        "manualReviewRequired": True,
        "customerNotificationAllowed": False,
        "shipmentEffectAllowed": False,
        "discountEffectAllowed": False,
        "idempotencyRequired": True,
        "rollbackRequired": True,
        "blockers": [
            "phase_6r_readiness_only_no_live_send_or_courier_call",
            "phase_6s_must_supply_director_signoff_and_kill_switch_check",
        ],
        "notes": [
            "Phase 6R records the readiness contract; no production WhatsApp / courier / Razorpay action fires here.",
        ],
    }


def build_phase6r_payment_dispatch_readiness_contract() -> list[dict[str, Any]]:
    """Return the canonical 9-row Payment → WhatsApp/Courier readiness contract."""
    return [
        _contract_row(name, spec) for name, spec in _CONTRACT_BY_EVENT.items()
    ]


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


def _safety_invariants() -> dict[str, bool]:
    return {
        "realOrderMutationAllowed": False,
        "realPaymentMutationAllowed": False,
        "shipmentMutationAllowed": False,
        "shipmentCreationAllowed": False,
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
        "frontendCanExecutePhase6R": False,
        "apiEndpointCanExecutePhase6R": False,
        "apiEndpointCanApprovePhase6R": False,
        "phase6RRespectsKillSwitch": True,
        "phase6RApprovalApplyRealMutation": False,
    }


def _whatsapp_readiness_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyApprovedClaimVaultCoverage",
            "description": (
                "Future WhatsApp template body must come only from "
                "`apps.compliance.Claim` (Approved Claim Vault). No "
                "freeform medical claims."
            ),
            "automated": True,
        },
        {
            "key": "verifyConsentGranted",
            "description": (
                "Customer ``WhatsAppConsent`` row must be in "
                "``granted`` state with a non-zero ``granted_at``."
            ),
            "automated": True,
        },
        {
            "key": "verifyAllowListCohortMembership",
            "description": (
                "Customer phone last-4 must be present in the live "
                "allow-list (`WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`) "
                "while limited test mode is on."
            ),
            "automated": True,
        },
        {
            "key": "verifyApprovedTemplateActive",
            "description": (
                "The proposed template name must be APPROVED + active "
                "and within the UTILITY/AUTHENTICATION tier (not "
                "MARKETING)."
            ),
            "automated": True,
        },
        {
            "key": "verifyDirectorSignOff",
            "description": (
                "Manual reviewer sign-off (reason text) recorded on "
                "the readiness gate row before approval."
            ),
            "automated": False,
        },
    ]


def _courier_readiness_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyDelhiveryModeIsTestOrMock",
            "description": (
                "`DELHIVERY_MODE` must be `mock` or `test` for any "
                "future Phase 6S courier rehearsal — production "
                "deploys keep it `mock` until controlled rollout."
            ),
            "automated": True,
        },
        {
            "key": "verifyServiceAreaResolvable",
            "description": (
                "Customer pincode must resolve to a courier "
                "service-area in the future Phase 6S resolver "
                "(stub-only check in Phase 6R)."
            ),
            "automated": False,
        },
        {
            "key": "verifySyntheticOrderReference",
            "description": (
                "Source order id must be synthetic (Phase 6P/6Q "
                "prefixes) — production order ids must be refused "
                "by Phase 6S courier path."
            ),
            "automated": True,
        },
        {
            "key": "verifyAmountWithinSafeCeiling",
            "description": (
                f"Amount must be <= {PHASE_6R_MAX_SAFE_AMOUNT_PAISE} paise "
                "synthetic-test ceiling for any future courier "
                "rehearsal."
            ),
            "automated": True,
        },
    ]


def _dispatch_readiness_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyPhase6QGateApproved",
            "description": (
                "Source Phase 6Q workflow gate must be "
                "``approved_for_future_phase6r``."
            ),
            "automated": True,
        },
        {
            "key": "verifyPhase6PSandboxProof",
            "description": (
                "Phase 6P attempt has executed + rolled_back via CLI "
                "and the ledger row has zero real-mutation / "
                "notification / provider-call counters."
            ),
            "automated": True,
        },
        {
            "key": "verifyEnvFlagsLockedOff",
            "description": (
                "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED, "
                "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED, "
                "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED, "
                "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED all "
                "remain false. RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED "
                "only opens the readiness-creation path."
            ),
            "automated": True,
        },
        {
            "key": "verifyKillSwitchActive",
            "description": (
                "Global runtime kill switch must remain enabled "
                "(`RuntimeKillSwitch.enabled=True`) before any "
                "future Phase 6S send is even considered."
            ),
            "automated": False,
        },
    ]


def _rollback_plan() -> dict[str, Any]:
    return {
        "phase": "6R",
        "rollbackTriggers": [
            "approval_observed_to_send_real_whatsapp",
            "approval_observed_to_create_real_shipment",
            "approval_observed_to_call_meta_cloud",
            "approval_observed_to_call_delhivery",
            "real_order_payment_shipment_or_discount_mutation_observed",
            "kill_switch_revoked",
        ],
        "rollbackSteps": [
            {
                "order": 1,
                "action": "set_RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED_to_false",
                "owner": "operator",
                "phase6REnforced": True,
            },
            {
                "order": 2,
                "action": "mark_open_readiness_gates_archived_with_rollback_reason",
                "owner": "operator",
                "phase6REnforced": True,
            },
            {
                "order": 3,
                "action": "audit_recent_readiness_rows_for_real_send_or_courier_drift",
                "owner": "operator",
                "phase6REnforced": True,
            },
            {
                "order": 4,
                "action": "verify_phase6q_gate_safety_counters_remain_zero",
                "owner": "operator",
                "phase6REnforced": True,
            },
        ],
        "rollbackVerification": [
            "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED == false",
            "every RazorpayPaymentDispatchReadinessGate.real_order_mutation_was_made == false",
            "every RazorpayPaymentDispatchReadinessGate.real_payment_mutation_was_made == false",
            "every RazorpayPaymentDispatchReadinessGate.shipment_created == false",
            "every RazorpayPaymentDispatchReadinessGate.whatsapp_message_created == false",
            "every RazorpayPaymentDispatchReadinessGate.whatsapp_message_queued == false",
            "every RazorpayPaymentDispatchReadinessGate.customer_notification_sent == false",
            "every RazorpayPaymentDispatchReadinessGate.meta_cloud_call_attempted == false",
            "every RazorpayPaymentDispatchReadinessGate.delhivery_call_attempted == false",
            "every RazorpayPaymentDispatchReadinessGate.provider_call_attempted == false",
        ],
        "phase6RCanExecuteRollback": False,
        "rollbackOwnedByOperatorOnly": True,
        "rollbackNeverInvokesProviderApi": True,
    }


def assert_phase6r_no_live_send_or_courier_mutation(
    row: RazorpayPaymentDispatchReadinessGate,
) -> None:
    """Refuse to save any Phase 6R row whose locked-False booleans
    have flipped True. Emits an audit row + raises.
    """
    bad: list[str] = []
    if row.real_order_mutation_was_made:
        bad.append("real_order_mutation_was_made_flipped_true")
    if row.real_payment_mutation_was_made:
        bad.append("real_payment_mutation_was_made_flipped_true")
    if row.shipment_mutation_was_made:
        bad.append("shipment_mutation_was_made_flipped_true")
    if row.shipment_created:
        bad.append("shipment_created_flipped_true")
    if row.whatsapp_message_created:
        bad.append("whatsapp_message_created_flipped_true")
    if row.whatsapp_message_queued:
        bad.append("whatsapp_message_queued_flipped_true")
    if row.customer_notification_sent:
        bad.append("customer_notification_sent_flipped_true")
    if row.meta_cloud_call_attempted:
        bad.append("meta_cloud_call_attempted_flipped_true")
    if row.delhivery_call_attempted:
        bad.append("delhivery_call_attempted_flipped_true")
    if row.razorpay_call_attempted:
        bad.append("razorpay_call_attempted_flipped_true")
    if row.provider_call_attempted:
        bad.append("provider_call_attempted_flipped_true")
    if row.dispatch_readiness_allowed_in_phase6r:
        bad.append("dispatch_readiness_allowed_in_phase6r_flipped_true")
    if bad:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text=(
                f"Phase 6R invariant violation on readiness gate "
                f"{row.pk or 'unsaved'}: {','.join(bad)}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload={
                "phase": "6R",
                "readiness_id": row.pk,
                "violations": bad,
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "shipment_created": False,
                "whatsapp_message_created": False,
                "whatsapp_message_queued": False,
                "customer_notification_sent": False,
                "meta_cloud_call_attempted": False,
                "delhivery_call_attempted": False,
                "provider_call_attempted": False,
            },
        )
        raise ValueError(
            "Phase 6R invariant violation: " + ",".join(bad)
        )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase6REligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None
    ledger: RazorpaySandboxPaidStatusLedger | None
    review: RazorpaySandboxStatusReview | None
    event: RazorpayWebhookEvent | None


def validate_phase6r_source_gate_eligibility(
    source_gate_id: int | None,
    *,
    require_env_flag: bool = True,
) -> Phase6REligibility:
    """Return whether the source Phase 6Q gate is eligible for a
    Phase 6R readiness review row.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None = None
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None = None
    ledger: RazorpaySandboxPaidStatusLedger | None = None
    review: RazorpaySandboxStatusReview | None = None
    event: RazorpayWebhookEvent | None = None

    if require_env_flag and not bool(
        getattr(
            settings, "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED", False
        )
    ):
        blockers.append(
            "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED_must_be_true"
        )

    if source_gate_id:
        workflow_gate = (
            RazorpayPaymentOrderWorkflowGate.objects.filter(pk=source_gate_id)
            .select_related(
                "source_attempt",
                "source_ledger",
                "source_review",
                "razorpay_webhook_event",
            )
            .first()
        )

    if workflow_gate is None:
        blockers.append("phase_6q_source_workflow_gate_not_found")
        return Phase6REligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            workflow_gate=None,
            attempt=None,
            ledger=None,
            review=None,
            event=None,
        )

    # Phase 6Q gate eligibility.
    if (
        workflow_gate.status
        != RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
    ):
        blockers.append(
            f"phase_6q_gate_status_must_be_approved_for_future_phase6r_was_{workflow_gate.status}"
        )
    if workflow_gate.workflow_mutation_allowed_in_phase6q:
        blockers.append(
            "phase_6q_gate_workflow_mutation_allowed_must_be_false"
        )
    if workflow_gate.real_order_mutation_was_made:
        blockers.append("phase_6q_gate_real_order_mutation_was_made")
    if workflow_gate.real_payment_mutation_was_made:
        blockers.append("phase_6q_gate_real_payment_mutation_was_made")
    if workflow_gate.shipment_mutation_was_made:
        blockers.append("phase_6q_gate_shipment_mutation_was_made")
    if workflow_gate.discount_mutation_was_made:
        blockers.append("phase_6q_gate_discount_mutation_was_made")
    if workflow_gate.customer_notification_sent:
        blockers.append("phase_6q_gate_customer_notification_sent")
    if workflow_gate.provider_call_attempted:
        blockers.append("phase_6q_gate_provider_call_attempted")

    attempt = workflow_gate.source_attempt
    ledger = workflow_gate.source_ledger
    review = workflow_gate.source_review
    event = workflow_gate.razorpay_webhook_event

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
        if attempt.executed_at is None:
            blockers.append("phase6p_attempt_must_have_been_executed")
        if attempt.real_order_mutation_was_made:
            blockers.append("phase6p_attempt_real_order_mutation_was_made")
        if attempt.real_payment_mutation_was_made:
            blockers.append("phase6p_attempt_real_payment_mutation_was_made")
        if attempt.business_mutation_was_made:
            blockers.append("phase6p_attempt_business_mutation_was_made")
        if attempt.customer_notification_sent:
            blockers.append("phase6p_attempt_customer_notification_sent")
        if attempt.provider_call_attempted:
            blockers.append("phase6p_attempt_provider_call_attempted")

    # Phase 6P ledger eligibility (if linked).
    if ledger is not None:
        if ledger.real_order_mutation_was_made:
            blockers.append("phase6p_ledger_real_order_mutation_was_made")
        if ledger.real_payment_mutation_was_made:
            blockers.append("phase6p_ledger_real_payment_mutation_was_made")
        if ledger.business_mutation_was_made:
            blockers.append("phase6p_ledger_business_mutation_was_made")
        if ledger.customer_notification_sent:
            blockers.append("phase6p_ledger_customer_notification_sent")
        if ledger.provider_call_attempted:
            blockers.append("phase6p_ledger_provider_call_attempted")

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
                f"event_name_not_phase6r_allowlisted_{event.event_name}"
            )
        if (
            event.amount_paise is not None
            and event.amount_paise > PHASE_6R_MAX_SAFE_AMOUNT_PAISE
        ):
            blockers.append(
                f"amount_paise_must_be_<=_{PHASE_6R_MAX_SAFE_AMOUNT_PAISE}"
            )

    return Phase6REligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        workflow_gate=workflow_gate,
        attempt=attempt,
        ledger=ledger,
        review=review,
        event=event,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_readiness(
    row: RazorpayPaymentDispatchReadinessGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
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
        "proposedPaymentStatus": row.proposed_payment_status,
        "proposedOrderStatus": row.proposed_order_status,
        "proposedOrderEffect": row.proposed_order_effect,
        "proposedWhatsAppAction": row.proposed_whatsapp_action,
        "proposedCourierAction": row.proposed_courier_action,
        "proposedDispatchReadinessAction": (
            row.proposed_dispatch_readiness_action
        ),
        "status": row.status,
        "phase6QGateApproved": row.phase6q_gate_approved,
        "phase6PExecutionVerified": row.phase6p_execution_verified,
        "phase6PRollbackVerified": row.phase6p_rollback_verified,
        "syntheticEligible": row.synthetic_eligible,
        "manualReviewRequired": row.manual_review_required,
        "dispatchReadinessAllowedInPhase6R": (
            row.dispatch_readiness_allowed_in_phase6r
        ),
        "realOrderMutationWasMade": row.real_order_mutation_was_made,
        "realPaymentMutationWasMade": row.real_payment_mutation_was_made,
        "shipmentMutationWasMade": row.shipment_mutation_was_made,
        "shipmentCreated": row.shipment_created,
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


def preview_phase6r_payment_dispatch_readiness_gate(
    source_gate_id: int,
) -> dict[str, Any]:
    """Read-only preview. Never creates rows, never mutates anything."""
    eligibility = validate_phase6r_source_gate_eligibility(
        source_gate_id, require_env_flag=False
    )

    proposed = None
    if eligibility.event is not None:
        spec = _CONTRACT_BY_EVENT.get(eligibility.event.event_name)
        if spec is not None:
            proposed = _contract_row(eligibility.event.event_name, spec)

    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 6R preview source_workflow_gate_id={source_gate_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6R",
            "source_phase6q_gate_id": source_gate_id,
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
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "shipment_created": False,
            "whatsapp_message_created": False,
            "whatsapp_message_queued": False,
            "customer_notification_sent": False,
            "meta_cloud_call_attempted": False,
            "delhivery_call_attempted": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6R",
        "found": eligibility.workflow_gate is not None,
        "sourcePhase6QGateId": source_gate_id,
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
        "warnings": list(eligibility.warnings) + [PHASE_6R_WARNING],
        "nextAction": (
            "ready_to_prepare_phase6r_readiness_gate"
            if eligibility.eligible
            and bool(
                getattr(
                    settings,
                    "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED",
                    False,
                )
            )
            else "fix_phase_6r_eligibility_blockers_or_enable_dispatch_readiness_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(workflow_gate: RazorpayPaymentOrderWorkflowGate) -> str:
    return f"phase6r::dispatch_readiness::workflow_gate::{workflow_gate.pk}"


def prepare_phase6r_payment_dispatch_readiness_gate(
    source_gate_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create / re-fetch a readiness gate row.

    Idempotent on the source Phase 6Q gate. NEVER mutates real
    business tables, NEVER sends WhatsApp, NEVER calls Meta Cloud,
    NEVER calls Delhivery.
    """
    eligibility = validate_phase6r_source_gate_eligibility(
        source_gate_id, require_env_flag=True
    )

    if not eligibility.eligible or eligibility.event is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 6R prepare blocked source_workflow_gate_id={source_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "6R",
                "source_phase6q_gate_id": source_gate_id,
                "blockers": list(eligibility.blockers),
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "shipment_created": False,
                "whatsapp_message_created": False,
                "whatsapp_message_queued": False,
                "customer_notification_sent": False,
                "meta_cloud_call_attempted": False,
                "delhivery_call_attempted": False,
                "provider_call_attempted": False,
            },
        )
        return {
            "phase": "6R",
            "created": False,
            "reused": False,
            "readiness": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_6R_WARNING],
            "nextAction": (
                "fix_phase_6r_eligibility_blockers_or_enable_dispatch_readiness_flag"
            ),
        }

    spec = _CONTRACT_BY_EVENT.get(eligibility.event.event_name)
    if spec is None:
        return {
            "phase": "6R",
            "created": False,
            "reused": False,
            "readiness": None,
            "blockers": [
                f"event_name_not_phase6r_allowlisted_{eligibility.event.event_name}"
            ],
            "warnings": [PHASE_6R_WARNING],
            "nextAction": "event_not_in_phase6r_allowlist",
        }

    contract = _contract_row(eligibility.event.event_name, spec)
    workflow_gate = eligibility.workflow_gate
    attempt = eligibility.attempt
    ledger = eligibility.ledger
    review = eligibility.review
    event = eligibility.event
    idempotency = _idempotency_key(workflow_gate)

    with transaction.atomic():
        existing = (
            RazorpayPaymentDispatchReadinessGate.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "6R",
                "created": False,
                "reused": True,
                "readiness": _serialize_readiness(existing),
                "blockers": [],
                "warnings": [PHASE_6R_WARNING],
                "nextAction": "readiness_pending_manual_review",
            }

        readiness = RazorpayPaymentDispatchReadinessGate(
            source_workflow_gate=workflow_gate,
            source_attempt=attempt,
            source_ledger=ledger,
            source_review=review,
            razorpay_webhook_event=event,
            source_event_id=event.source_event_id if event else "",
            event_name=event.event_name if event else "",
            provider_environment=(event.environment if event else "test"),
            provider_order_id=(event.provider_order_id if event else ""),
            provider_payment_id=(event.provider_payment_id if event else ""),
            provider_payment_link_id="",
            amount_paise=(event.amount_paise if event else None),
            currency=(event.currency if event else ""),
            proposed_payment_status=(
                workflow_gate.proposed_payment_status
                if workflow_gate
                else ""
            ),
            proposed_order_status=(
                workflow_gate.proposed_order_status
                if workflow_gate
                else ""
            ),
            proposed_order_effect=(
                workflow_gate.proposed_order_effect
                if workflow_gate
                else ""
            ),
            proposed_whatsapp_action=spec["futureWhatsAppReadinessAction"],
            proposed_courier_action=spec["futureCourierReadinessAction"],
            proposed_dispatch_readiness_action=(
                spec["futureDispatchReadinessAction"]
            ),
            status=(
                RazorpayPaymentDispatchReadinessGate.Status.PENDING_MANUAL_REVIEW
            ),
            phase6q_gate_approved=True,
            phase6p_execution_verified=bool(
                attempt and attempt.executed_at is not None
            ),
            phase6p_rollback_verified=bool(
                attempt and attempt.rolled_back_at is not None
            ),
            synthetic_eligible=True,
            manual_review_required=True,
            dispatch_readiness_allowed_in_phase6r=False,
            real_order_mutation_was_made=False,
            real_payment_mutation_was_made=False,
            shipment_mutation_was_made=False,
            shipment_created=False,
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
            warnings=[PHASE_6R_WARNING],
            safety_invariants=_safety_invariants(),
            whatsapp_readiness_checklist=_whatsapp_readiness_checklist(),
            courier_readiness_checklist=_courier_readiness_checklist(),
            dispatch_readiness_checklist=_dispatch_readiness_checklist(),
            rollback_plan=_rollback_plan(),
            requested_by=requested_by,
        )
        assert_phase6r_no_live_send_or_courier_mutation(readiness)
        try:
            readiness.save()
        except IntegrityError:
            readiness = (
                RazorpayPaymentDispatchReadinessGate.objects.get(
                    idempotency_key=idempotency
                )
            )
            return {
                "phase": "6R",
                "created": False,
                "reused": True,
                "readiness": _serialize_readiness(readiness),
                "blockers": [],
                "warnings": [PHASE_6R_WARNING],
                "nextAction": "readiness_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 6R readiness gate prepared readiness_id={readiness.pk} "
            f"source_workflow_gate_id={workflow_gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6R",
            "readiness_id": readiness.pk,
            "source_phase6q_gate_id": workflow_gate.pk,
            "source_attempt_id": readiness.source_attempt_id,
            "source_ledger_id": readiness.source_ledger_id,
            "source_review_id": readiness.source_review_id,
            "source_event_id": readiness.source_event_id,
            "event_name": readiness.event_name,
            "status": readiness.status,
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "shipment_created": False,
            "whatsapp_message_created": False,
            "whatsapp_message_queued": False,
            "customer_notification_sent": False,
            "meta_cloud_call_attempted": False,
            "delhivery_call_attempted": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6R",
        "created": True,
        "reused": False,
        "readiness": _serialize_readiness(readiness),
        "blockers": [],
        "warnings": [PHASE_6R_WARNING],
        "nextAction": "readiness_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


_TRANSITIONABLE_FROM = {
    RazorpayPaymentDispatchReadinessGate.Status.DRAFT,
    RazorpayPaymentDispatchReadinessGate.Status.PENDING_MANUAL_REVIEW,
}


def _transition(
    readiness_id: int,
    *,
    new_status: str,
    audit_kind: str,
    by_user=None,
    reason: str = "",
    archive: bool = False,
    require_reason: bool = False,
) -> dict[str, Any]:
    readiness = (
        RazorpayPaymentDispatchReadinessGate.objects.filter(
            pk=readiness_id
        ).first()
        if readiness_id
        else None
    )
    if readiness is None:
        return {
            "phase": "6R",
            "ok": False,
            "readiness": None,
            "blockers": ["readiness_gate_not_found"],
            "warnings": [PHASE_6R_WARNING],
            "nextAction": "verify_readiness_id",
        }
    if not bool(
        getattr(
            settings, "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED", False
        )
    ):
        return {
            "phase": "6R",
            "ok": False,
            "readiness": _serialize_readiness(readiness),
            "blockers": [
                "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_6R_WARNING],
            "nextAction": "enable_dispatch_readiness_flag_via_env",
        }

    if require_reason and not (reason or "").strip():
        return {
            "phase": "6R",
            "ok": False,
            "readiness": _serialize_readiness(readiness),
            "blockers": ["manual_review_reason_must_be_non_empty"],
            "warnings": [PHASE_6R_WARNING],
            "nextAction": "supply_manual_review_reason",
        }

    if not archive and readiness.status not in _TRANSITIONABLE_FROM:
        return {
            "phase": "6R",
            "ok": False,
            "readiness": _serialize_readiness(readiness),
            "blockers": [
                f"readiness_status_{readiness.status}_not_transitionable_to_{new_status}"
            ],
            "warnings": [PHASE_6R_WARNING],
            "nextAction": "readiness_already_finalised",
        }
    if (
        archive
        and readiness.status
        == RazorpayPaymentDispatchReadinessGate.Status.ARCHIVED
    ):
        return {
            "phase": "6R",
            "ok": True,
            "readiness": _serialize_readiness(readiness),
            "blockers": [],
            "warnings": [PHASE_6R_WARNING + " readiness_already_archived"],
            "nextAction": "readiness_already_archived",
        }

    readiness.status = new_status
    if archive:
        readiness.archived_by = by_user
        readiness.archived_at = timezone.now()
        readiness.archive_reason = (reason or "").strip()[:200]
    else:
        readiness.reviewed_by = by_user
        readiness.reviewed_at = timezone.now()
        readiness.review_reason = (reason or "").strip()[:200]

    assert_phase6r_no_live_send_or_courier_mutation(readiness)
    readiness.save()

    write_event(
        kind=audit_kind,
        text=(
            f"Phase 6R readiness gate {readiness.pk} -> {new_status}"
            + (f" · {reason}" if reason else "")
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6R",
            "readiness_id": readiness.pk,
            "source_phase6q_gate_id": readiness.source_workflow_gate_id,
            "source_attempt_id": readiness.source_attempt_id,
            "source_ledger_id": readiness.source_ledger_id,
            "source_review_id": readiness.source_review_id,
            "source_event_id": readiness.source_event_id,
            "event_name": readiness.event_name,
            "status": readiness.status,
            "reason": (reason or "")[:200],
            "by": getattr(by_user, "username", "") or "",
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "shipment_created": False,
            "whatsapp_message_created": False,
            "whatsapp_message_queued": False,
            "customer_notification_sent": False,
            "meta_cloud_call_attempted": False,
            "delhivery_call_attempted": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6R",
        "ok": True,
        "readiness": _serialize_readiness(readiness),
        "blockers": [],
        "warnings": [PHASE_6R_WARNING],
        "nextAction": (
            "ready_for_phase_6s_planning_after_director_signoff"
            if new_status
            == RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
            else "readiness_finalised"
        ),
    }


def approve_phase6r_payment_dispatch_readiness_gate(
    readiness_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the readiness gate approved **for future Phase 6S only**.
    NEVER sends WhatsApp; NEVER queues an outbound; NEVER calls Meta
    Cloud / Delhivery; NEVER mutates real business tables. Manual
    review reason text required.
    """
    return _transition(
        readiness_id,
        new_status=RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S,
        audit_kind=AUDIT_KIND_APPROVED,
        by_user=reviewed_by,
        reason=reason,
        require_reason=True,
    )


def reject_phase6r_payment_dispatch_readiness_gate(
    readiness_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        readiness_id,
        new_status=RazorpayPaymentDispatchReadinessGate.Status.REJECTED,
        audit_kind=AUDIT_KIND_REJECTED,
        by_user=reviewed_by,
        reason=reason,
    )


def archive_phase6r_payment_dispatch_readiness_gate(
    readiness_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        readiness_id,
        new_status=RazorpayPaymentDispatchReadinessGate.Status.ARCHIVED,
        audit_kind=AUDIT_KIND_ARCHIVED,
        by_user=archived_by,
        reason=reason,
        archive=True,
    )


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase6r_payment_dispatch_readiness_gates(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpayPaymentDispatchReadinessGate.objects.all().order_by(
        "-created_at"
    )
    Status = RazorpayPaymentDispatchReadinessGate.Status
    counts = {
        "draft": qs.filter(status=Status.DRAFT).count(),
        "pendingManualReview": qs.filter(
            status=Status.PENDING_MANUAL_REVIEW
        ).count(),
        "approvedForFuturePhase6S": qs.filter(
            status=Status.APPROVED_FOR_FUTURE_PHASE6S
        ).count(),
        "rejected": qs.filter(status=Status.REJECTED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
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
        _serialize_readiness(row) for row in qs[: max(1, min(limit, 200))]
    ]
    return {"counts": counts, "items": sample}


def inspect_phase6r_payment_dispatch_readiness() -> dict[str, Any]:
    flag_enabled = bool(
        getattr(
            settings, "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED", False
        )
    )
    summary = summarize_phase6r_payment_dispatch_readiness_gates()
    counts = summary["counts"]

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6R_WARNING]

    for key in (
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "shipmentMutationWasMade",
        "shipmentCreated",
        "whatsAppMessageCreated",
        "whatsAppMessageQueued",
        "customerNotificationSent",
        "metaCloudCallAttempted",
        "delhiveryCallAttempted",
        "providerCallAttempted",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_6r_readiness_{key}_observed_must_be_zero"
            )

    # Phase 6Q proof presence — count gates that have been approved
    # for future Phase 6R.
    phase6q_approved = (
        RazorpayPaymentOrderWorkflowGate.objects.filter(
            status=RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
        ).count()
    )

    safe_to_start_phase_6s = bool(
        not blockers
        and counts["approvedForFuturePhase6S"] >= 1
    )

    if blockers:
        next_action = "fix_phase_6r_safety_blockers"
    elif phase6q_approved == 0:
        next_action = (
            "approve_at_least_one_phase_6q_gate_before_running_phase_6r"
        )
    elif counts["approvedForFuturePhase6S"] == 0:
        next_action = (
            "approve_at_least_one_phase6r_readiness_gate_for_future_phase6s"
        )
    else:
        next_action = (
            "ready_for_phase_6s_limited_internal_live_payment_workflow_pilot_planning"
        )

    return {
        "phase": "6R",
        "status": "dispatch_readiness_only",
        "latestCompletedPhase": "6Q",
        "nextPhase": "6S",
        "razorpayPaymentDispatchReadinessEnabled": flag_enabled,
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "providerCallAttempted": False,
        "rawPayloadStorageEnabled": False,
        "phase6QApprovedGateCount": phase6q_approved,
        "readinessCounts": counts,
        "readinessContract": (
            build_phase6r_payment_dispatch_readiness_contract()
        ),
        "safetyInvariants": _safety_invariants(),
        "whatsAppReadinessChecklist": _whatsapp_readiness_checklist(),
        "courierReadinessChecklist": _courier_readiness_checklist(),
        "dispatchReadinessChecklist": _dispatch_readiness_checklist(),
        "rollbackPlan": _rollback_plan(),
        "forbiddenActions": list(PHASE_6R_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "maxSafeAmountPaise": PHASE_6R_MAX_SAFE_AMOUNT_PAISE,
        "safeToStartPhase6S": safe_to_start_phase_6s,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentReadinessGates": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("readinessCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 6R payment dispatch readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6R",
            "razorpay_payment_dispatch_readiness_enabled": bool(
                report.get("razorpayPaymentDispatchReadinessEnabled")
            ),
            "phase6q_approved_gate_count": int(
                report.get("phase6QApprovedGateCount") or 0
            ),
            "readiness_count_pending": int(
                counts.get("pendingManualReview") or 0
            ),
            "readiness_count_approved": int(
                counts.get("approvedForFuturePhase6S") or 0
            ),
            "safe_to_start_phase_6s": bool(report.get("safeToStartPhase6S")),
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "shipment_created": False,
            "whatsapp_message_created": False,
            "whatsapp_message_queued": False,
            "customer_notification_sent": False,
            "meta_cloud_call_attempted": False,
            "delhivery_call_attempted": False,
            "provider_call_attempted": False,
        },
    )


__all__ = (
    "PHASE_6R_WARNING",
    "PHASE_6R_FORBIDDEN_ACTIONS",
    "PHASE_6R_MAX_SAFE_AMOUNT_PAISE",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase6REligibility",
    "build_phase6r_payment_dispatch_readiness_contract",
    "validate_phase6r_source_gate_eligibility",
    "preview_phase6r_payment_dispatch_readiness_gate",
    "prepare_phase6r_payment_dispatch_readiness_gate",
    "approve_phase6r_payment_dispatch_readiness_gate",
    "reject_phase6r_payment_dispatch_readiness_gate",
    "archive_phase6r_payment_dispatch_readiness_gate",
    "summarize_phase6r_payment_dispatch_readiness_gates",
    "inspect_phase6r_payment_dispatch_readiness",
    "assert_phase6r_no_live_send_or_courier_mutation",
    "emit_readiness_inspected_audit",
)
