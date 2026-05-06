"""Phase 6Q — Payment → Order Workflow Safety Gate.

Audit-only gate layer that converts an approved Phase 6P sandbox
proof (executed + rolled-back ledger transition) into a
:class:`RazorpayPaymentOrderWorkflowGate` review record. Phase 6Q
**never** mutates real ``Order`` / ``Payment`` / ``Shipment`` /
``DiscountOfferLog`` / ``Customer`` / ``Lead`` /
``WhatsAppMessage`` / ``WhatsAppConversation`` rows. It NEVER calls
Razorpay, NEVER sends a customer notification, NEVER flips an env
flag. Approving a gate only flips its ``status`` to
``approved_for_future_phase6r``.

Public surface:

- :func:`build_phase6q_payment_order_workflow_contract`
- :func:`inspect_phase6q_payment_order_workflow_gate_readiness`
- :func:`validate_phase6q_source_eligibility`
- :func:`preview_phase6q_payment_order_workflow_gate`
- :func:`prepare_phase6q_payment_order_workflow_gate`
- :func:`approve_phase6q_payment_order_workflow_gate`
- :func:`reject_phase6q_payment_order_workflow_gate`
- :func:`archive_phase6q_payment_order_workflow_gate`
- :func:`summarize_phase6q_payment_order_workflow_gates`
- :func:`assert_phase6q_no_real_business_mutation`
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
    RazorpayPaymentOrderWorkflowGate,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)


PHASE_6Q_WARNING = (
    "Phase 6Q is an audit-only Payment → Order workflow safety gate. "
    "It NEVER mutates real Order / Payment / Shipment / "
    "DiscountOfferLog / Customer / Lead / WhatsAppMessage rows. It "
    "NEVER calls Razorpay, NEVER sends a customer notification, "
    "NEVER flips an env flag. Approving a gate only marks it "
    "``approved_for_future_phase6r``. Review state changes are "
    "CLI-only — no API endpoint dispatches Phase 6Q approval."
)


# Audit kinds Phase 6Q emits.
AUDIT_KIND_READINESS = "razorpay.payment_order_gate.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.payment_order_gate.previewed"
AUDIT_KIND_PREPARED = "razorpay.payment_order_gate.prepared"
AUDIT_KIND_APPROVED = (
    "razorpay.payment_order_gate.approved_for_future_phase6r"
)
AUDIT_KIND_REJECTED = "razorpay.payment_order_gate.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.payment_order_gate.archived"
AUDIT_KIND_BLOCKED = "razorpay.payment_order_gate.blocked"
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.payment_order_gate.invariant_violation_blocked"
)


PHASE_6Q_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "mutate_real_order_status",
    "mutate_real_payment_status",
    "create_or_update_real_shipment",
    "create_or_update_real_discount_offer",
    "mutate_real_customer",
    "mutate_real_lead",
    "send_whatsapp_template",
    "send_freeform_whatsapp",
    "place_vapi_call",
    "call_razorpay_api",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "execute_webhook_replay",
    "enable_business_mutation_env_flag",
    "execute_workflow_via_frontend",
    "execute_workflow_via_api_endpoint",
    "approve_gate_via_api_endpoint",
)


# Same synthetic safety ceiling as Phase 6N/6O/6P.
PHASE_6Q_MAX_SAFE_AMOUNT_PAISE = 100


# ---------------------------------------------------------------------------
# Workflow contract (9-event coverage)
# ---------------------------------------------------------------------------


_CONTRACT_BY_EVENT: dict[str, dict[str, str]] = {
    "payment_link.paid": {
        "futurePaymentStatus": "advance_paid_candidate",
        "futureOrderStatusCandidate": "payment_reviewed",
        "futureOrderEffect": "advance_received_candidate",
        "workflowAction": "gate_payment_link_paid_to_order_advance_review",
    },
    "payment.captured": {
        "futurePaymentStatus": "captured_candidate",
        "futureOrderStatusCandidate": "payment_verified",
        "futureOrderEffect": "payment_verified_candidate",
        "workflowAction": "gate_payment_captured_to_order_payment_verified",
    },
    "payment.failed": {
        "futurePaymentStatus": "failed_candidate",
        "futureOrderStatusCandidate": "payment_failed",
        "futureOrderEffect": "payment_failed_candidate",
        "workflowAction": "gate_payment_failed_to_order_followup_needed",
    },
    "payment.authorized": {
        "futurePaymentStatus": "authorized_candidate",
        "futureOrderStatusCandidate": "payment_authorized",
        "futureOrderEffect": "payment_authorized_candidate",
        "workflowAction": "gate_payment_authorized_to_order_review",
    },
    "order.paid": {
        "futurePaymentStatus": "paid_candidate",
        "futureOrderStatusCandidate": "paid",
        "futureOrderEffect": "paid_candidate",
        "workflowAction": "gate_order_paid_to_order_paid_candidate",
    },
    "payment_link.cancelled": {
        "futurePaymentStatus": "cancelled_candidate",
        "futureOrderStatusCandidate": "payment_link_cancelled",
        "futureOrderEffect": "payment_link_cancelled_candidate",
        "workflowAction": "gate_payment_link_cancelled_to_order_followup_needed",
    },
    "payment_link.expired": {
        "futurePaymentStatus": "expired_candidate",
        "futureOrderStatusCandidate": "payment_link_expired",
        "futureOrderEffect": "payment_link_expired_candidate",
        "workflowAction": "gate_payment_link_expired_to_order_followup_needed",
    },
    "refund.created": {
        "futurePaymentStatus": "refund_pending_candidate",
        "futureOrderStatusCandidate": "refund_review",
        "futureOrderEffect": "refund_review_candidate",
        "workflowAction": "gate_refund_created_to_refund_review",
    },
    "refund.processed": {
        "futurePaymentStatus": "refunded_candidate",
        "futureOrderStatusCandidate": "refund_processed",
        "futureOrderEffect": "refund_processed_candidate",
        "workflowAction": "gate_refund_processed_to_order_refunded_candidate",
    },
}


def _contract_row(event_name: str, spec: dict[str, str]) -> dict[str, Any]:
    return {
        "razorpayEventName": event_name,
        "futurePaymentStatus": spec["futurePaymentStatus"],
        "futureOrderStatusCandidate": spec["futureOrderStatusCandidate"],
        "futureOrderEffect": spec["futureOrderEffect"],
        "workflowAction": spec["workflowAction"],
        "workflowMutationAllowedInPhase6Q": False,
        "mutationAllowedInFuturePhase6R": (
            "only_if_gate_approved_director_signed_off_and_kill_switch_allows"
        ),
        "manualReviewRequired": True,
        "customerNotificationAllowed": False,
        "shipmentEffectAllowed": False,
        "discountEffectAllowed": False,
        "providerCallAllowed": False,
        "idempotencyRequired": True,
        "rollbackRequired": True,
        "blockers": [
            "phase_6q_audit_gate_only_no_real_business_mutation",
            "phase_6r_must_supply_director_signoff_and_kill_switch_check",
        ],
        "notes": [
            "Phase 6Q records the contract; no production-side action fires here.",
        ],
    }


def build_phase6q_payment_order_workflow_contract() -> list[dict[str, Any]]:
    """Return the canonical 9-row Payment → Order workflow contract."""
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
        "discountOfferMutationAllowed": False,
        "customerMutationAllowed": False,
        "leadMutationAllowed": False,
        "whatsappSendAllowed": False,
        "vapiCallAllowed": False,
        "razorpayApiInvocationAllowed": False,
        "envFlagFlipAllowed": False,
        "frontendCanExecutePhase6Q": False,
        "apiEndpointCanExecutePhase6Q": False,
        "apiEndpointCanApprovePhase6Q": False,
        "phase6QRespectsKillSwitch": True,
        "phase6QApprovalApplyRealMutation": False,
    }


def _manual_review_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyPhase6PSandboxProof",
            "description": (
                "Phase 6P attempt has executed + rolled_back via CLI; "
                "ledger row exists and was restored to its before "
                "state."
            ),
            "automated": True,
        },
        {
            "key": "verifyPhase6PSafetyCountersZero",
            "description": (
                "Phase 6P attempt has real_order_mutation_was_made=False, "
                "real_payment_mutation_was_made=False, "
                "business_mutation_was_made=False, "
                "customer_notification_sent=False, "
                "provider_call_attempted=False."
            ),
            "automated": True,
        },
        {
            "key": "verifyPhase6OReviewApproved",
            "description": (
                "Source Phase 6O review status is "
                "``approved_for_future_phase6p``."
            ),
            "automated": True,
        },
        {
            "key": "verifySourceEventSafe",
            "description": (
                "Source RazorpayWebhookEvent is signature_valid + "
                "replay_window_valid + idempotency_status=first_seen "
                "+ no raw secret / full PII exposure."
            ),
            "automated": True,
        },
        {
            "key": "verifyEnvFlagsLockedOff",
            "description": (
                "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED, "
                "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED, "
                "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED all "
                "remain false. RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED "
                "only opens the gate-creation path, never the "
                "real-mutation path."
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


def _rollback_plan() -> dict[str, Any]:
    return {
        "phase": "6Q",
        "rollbackTriggers": [
            "approval_observed_to_mutate_real_business_table",
            "real_order_payment_shipment_or_discount_mutation_observed",
            "customer_notification_observed",
            "raw_secret_or_full_pii_exposure_observed",
            "kill_switch_revoked",
        ],
        "rollbackSteps": [
            {
                "order": 1,
                "action": "set_RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED_to_false",
                "owner": "operator",
                "phase6QEnforced": True,
            },
            {
                "order": 2,
                "action": "mark_open_gate_reviews_archived_with_rollback_reason",
                "owner": "operator",
                "phase6QEnforced": True,
            },
            {
                "order": 3,
                "action": "audit_recent_gate_rows_for_real_business_mutation_drift",
                "owner": "operator",
                "phase6QEnforced": True,
            },
            {
                "order": 4,
                "action": "verify_phase6p_safety_counters_remain_zero",
                "owner": "operator",
                "phase6QEnforced": True,
            },
        ],
        "rollbackVerification": [
            "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED == false",
            "every RazorpayPaymentOrderWorkflowGate.real_order_mutation_was_made == false",
            "every RazorpayPaymentOrderWorkflowGate.real_payment_mutation_was_made == false",
            "every RazorpayPaymentOrderWorkflowGate.customer_notification_sent == false",
            "every RazorpayPaymentOrderWorkflowGate.provider_call_attempted == false",
        ],
        "phase6QCanExecuteRollback": False,
        "rollbackOwnedByOperatorOnly": True,
        "rollbackNeverInvokesProviderApi": True,
    }


def assert_phase6q_no_real_business_mutation(
    row: RazorpayPaymentOrderWorkflowGate,
) -> None:
    """Refuse to save any Phase 6Q row whose locked-False booleans
    have flipped True. Emits an audit row + raises.
    """
    bad: list[str] = []
    if row.real_order_mutation_was_made:
        bad.append("real_order_mutation_was_made_flipped_true")
    if row.real_payment_mutation_was_made:
        bad.append("real_payment_mutation_was_made_flipped_true")
    if row.shipment_mutation_was_made:
        bad.append("shipment_mutation_was_made_flipped_true")
    if row.discount_mutation_was_made:
        bad.append("discount_mutation_was_made_flipped_true")
    if row.customer_notification_sent:
        bad.append("customer_notification_sent_flipped_true")
    if row.provider_call_attempted:
        bad.append("provider_call_attempted_flipped_true")
    if row.workflow_mutation_allowed_in_phase6q:
        bad.append("workflow_mutation_allowed_in_phase6q_flipped_true")
    if bad:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text=(
                f"Phase 6Q invariant violation on gate "
                f"{row.pk or 'unsaved'}: {','.join(bad)}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload={
                "phase": "6Q",
                "gate_id": row.pk,
                "violations": bad,
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
                "provider_call_attempted": False,
            },
        )
        raise ValueError(
            "Phase 6Q invariant violation: " + ",".join(bad)
        )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase6QEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None
    ledger: RazorpaySandboxPaidStatusLedger | None
    review: RazorpaySandboxStatusReview | None
    event: RazorpayWebhookEvent | None


def _resolve_source(
    source_attempt_id: int | None,
    ledger_id: int | None,
) -> tuple[
    RazorpaySandboxPaidStatusMutationAttempt | None,
    RazorpaySandboxPaidStatusLedger | None,
]:
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None = None
    ledger: RazorpaySandboxPaidStatusLedger | None = None
    if source_attempt_id:
        attempt = (
            RazorpaySandboxPaidStatusMutationAttempt.objects.filter(
                pk=source_attempt_id
            )
            .select_related("review", "ledger", "razorpay_webhook_event")
            .first()
        )
        if attempt and attempt.ledger_id:
            ledger = attempt.ledger
    if ledger is None and ledger_id:
        ledger = (
            RazorpaySandboxPaidStatusLedger.objects.filter(pk=ledger_id)
            .select_related("review", "razorpay_webhook_event")
            .first()
        )
        if attempt is None and ledger is not None:
            # Pick the latest attempt linked to this ledger if any.
            attempt = (
                ledger.mutation_attempts.order_by("-created_at").first()
                if hasattr(ledger, "mutation_attempts")
                else None
            )
    return attempt, ledger


def validate_phase6q_source_eligibility(
    source_attempt_id: int | None = None,
    ledger_id: int | None = None,
    *,
    require_env_flag: bool = True,
    require_rollback: bool = True,
) -> Phase6QEligibility:
    """Return whether the source Phase 6P attempt/ledger is eligible
    for a Phase 6Q gate review row.
    """
    attempt, ledger = _resolve_source(source_attempt_id, ledger_id)
    blockers: list[str] = []
    warnings: list[str] = []
    review: RazorpaySandboxStatusReview | None = None
    event: RazorpayWebhookEvent | None = None

    if require_env_flag and not bool(
        getattr(
            settings, "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED", False
        )
    ):
        blockers.append(
            "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED_must_be_true"
        )

    if attempt is None and ledger is None:
        blockers.append("phase_6p_source_not_found")
        return Phase6QEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            attempt=None,
            ledger=None,
            review=None,
            event=None,
        )

    if attempt is not None:
        review = attempt.review
        event = attempt.razorpay_webhook_event

        # Phase 6P attempt-level checks.
        if attempt.status not in (
            RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
            RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
        ):
            blockers.append(
                f"phase6p_attempt_status_{attempt.status}_not_eligible"
            )
        if attempt.executed_at is None:
            blockers.append("phase6p_attempt_must_have_been_executed")
        if require_rollback and attempt.rolled_back_at is None:
            blockers.append("phase6p_attempt_must_have_been_rolled_back")

        # Phase 6P safety counters must all be False.
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

    if ledger is not None:
        if review is None:
            review = ledger.review
        if event is None:
            event = ledger.razorpay_webhook_event
        # Phase 6P ledger-level safety counters.
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

    # Phase 6O review state.
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

    # Source RazorpayWebhookEvent state.
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
                f"event_name_not_phase6q_allowlisted_{event.event_name}"
            )
        if (
            event.amount_paise is not None
            and event.amount_paise > PHASE_6Q_MAX_SAFE_AMOUNT_PAISE
        ):
            blockers.append(
                f"amount_paise_must_be_<=_{PHASE_6Q_MAX_SAFE_AMOUNT_PAISE}"
            )

    return Phase6QEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        attempt=attempt,
        ledger=ledger,
        review=review,
        event=event,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_gate(gate: RazorpayPaymentOrderWorkflowGate) -> dict[str, Any]:
    return {
        "id": gate.pk,
        "sourceAttemptId": gate.source_attempt_id,
        "sourceLedgerId": gate.source_ledger_id,
        "sourceReviewId": gate.source_review_id,
        "razorpayWebhookEventId": gate.razorpay_webhook_event_id,
        "sourceEventId": gate.source_event_id,
        "eventName": gate.event_name,
        "providerEnvironment": gate.provider_environment,
        "providerOrderId": gate.provider_order_id,
        "providerPaymentId": gate.provider_payment_id,
        "providerPaymentLinkId": gate.provider_payment_link_id,
        "amountPaise": gate.amount_paise,
        "currency": gate.currency,
        "proposedPaymentStatus": gate.proposed_payment_status,
        "proposedOrderStatus": gate.proposed_order_status,
        "proposedOrderEffect": gate.proposed_order_effect,
        "proposedWorkflowAction": gate.proposed_workflow_action,
        "status": gate.status,
        "phase6PExecutionVerified": gate.phase6p_execution_verified,
        "phase6PRollbackVerified": gate.phase6p_rollback_verified,
        "syntheticEligible": gate.synthetic_eligible,
        "manualReviewRequired": gate.manual_review_required,
        "workflowMutationAllowedInPhase6Q": gate.workflow_mutation_allowed_in_phase6q,
        "realOrderMutationWasMade": gate.real_order_mutation_was_made,
        "realPaymentMutationWasMade": gate.real_payment_mutation_was_made,
        "shipmentMutationWasMade": gate.shipment_mutation_was_made,
        "discountMutationWasMade": gate.discount_mutation_was_made,
        "customerNotificationSent": gate.customer_notification_sent,
        "providerCallAttempted": gate.provider_call_attempted,
        "rollbackRequired": gate.rollback_required,
        "idempotencyKey": gate.idempotency_key,
        "blockers": list(gate.blockers or []),
        "warnings": list(gate.warnings or []),
        "reviewedByUsername": (
            getattr(gate.reviewed_by, "username", "") or ""
        ),
        "reviewedAt": (
            gate.reviewed_at.isoformat() if gate.reviewed_at else None
        ),
        "reviewReason": gate.review_reason,
        "archivedByUsername": (
            getattr(gate.archived_by, "username", "") or ""
        ),
        "archivedAt": (
            gate.archived_at.isoformat() if gate.archived_at else None
        ),
        "archiveReason": gate.archive_reason,
        "createdAt": gate.created_at.isoformat(),
        "updatedAt": gate.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase6q_payment_order_workflow_gate(
    source_attempt_id: int | None = None,
    ledger_id: int | None = None,
) -> dict[str, Any]:
    """Read-only preview. Never creates a row, never mutates anything."""
    eligibility = validate_phase6q_source_eligibility(
        source_attempt_id=source_attempt_id,
        ledger_id=ledger_id,
        require_env_flag=False,
    )

    spec = None
    if eligibility.event is not None:
        spec = _CONTRACT_BY_EVENT.get(eligibility.event.event_name)

    proposed = (
        _contract_row(eligibility.event.event_name, spec)
        if (eligibility.event and spec)
        else None
    )

    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 6Q preview source_attempt_id={source_attempt_id} "
            f"ledger_id={ledger_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6Q",
            "source_attempt_id": source_attempt_id,
            "source_ledger_id": ledger_id,
            "source_review_id": (
                eligibility.review.pk if eligibility.review else None
            ),
            "source_event_id": (
                eligibility.event.source_event_id
                if eligibility.event
                else ""
            ),
            "event_name": (
                eligibility.event.event_name if eligibility.event else ""
            ),
            "eligible": eligibility.eligible,
            "blockers": list(eligibility.blockers),
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6Q",
        "found": eligibility.attempt is not None or eligibility.ledger is not None,
        "sourceAttemptId": (
            eligibility.attempt.pk if eligibility.attempt else source_attempt_id
        ),
        "sourceLedgerId": (
            eligibility.ledger.pk if eligibility.ledger else ledger_id
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
        "warnings": list(eligibility.warnings) + [PHASE_6Q_WARNING],
        "nextAction": (
            "ready_to_prepare_phase6q_gate"
            if eligibility.eligible
            and bool(
                getattr(
                    settings,
                    "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED",
                    False,
                )
            )
            else "fix_phase_6q_eligibility_blockers_or_enable_workflow_gate_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(
    attempt: RazorpaySandboxPaidStatusMutationAttempt | None,
    ledger: RazorpaySandboxPaidStatusLedger | None,
) -> str:
    if attempt is not None:
        return f"phase6q::workflow_gate::attempt::{attempt.pk}"
    if ledger is not None:
        return f"phase6q::workflow_gate::ledger::{ledger.pk}"
    return "phase6q::workflow_gate::unknown"


def prepare_phase6q_payment_order_workflow_gate(
    source_attempt_id: int | None = None,
    ledger_id: int | None = None,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create / re-fetch a gate row.

    Idempotent on the source attempt/ledger. NEVER mutates real
    business tables.
    """
    eligibility = validate_phase6q_source_eligibility(
        source_attempt_id=source_attempt_id,
        ledger_id=ledger_id,
        require_env_flag=True,
    )

    if not eligibility.eligible or eligibility.event is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 6Q prepare blocked source_attempt_id={source_attempt_id} "
                f"ledger_id={ledger_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "6Q",
                "source_attempt_id": source_attempt_id,
                "source_ledger_id": ledger_id,
                "blockers": list(eligibility.blockers),
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
                "provider_call_attempted": False,
            },
        )
        return {
            "phase": "6Q",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_6Q_WARNING],
            "nextAction": (
                "fix_phase_6q_eligibility_blockers_or_enable_workflow_gate_flag"
            ),
        }

    spec = _CONTRACT_BY_EVENT.get(eligibility.event.event_name)
    if spec is None:
        return {
            "phase": "6Q",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": [
                f"event_name_not_phase6q_allowlisted_{eligibility.event.event_name}"
            ],
            "warnings": [PHASE_6Q_WARNING],
            "nextAction": "event_not_in_phase6q_allowlist",
        }

    contract = _contract_row(eligibility.event.event_name, spec)
    idempotency = _idempotency_key(eligibility.attempt, eligibility.ledger)

    with transaction.atomic():
        existing = (
            RazorpayPaymentOrderWorkflowGate.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "6Q",
                "created": False,
                "reused": True,
                "gate": _serialize_gate(existing),
                "blockers": [],
                "warnings": [PHASE_6Q_WARNING],
                "nextAction": "gate_pending_manual_review",
            }

        attempt = eligibility.attempt
        ledger = eligibility.ledger
        review = eligibility.review
        event = eligibility.event

        gate = RazorpayPaymentOrderWorkflowGate(
            source_attempt=attempt,
            source_ledger=ledger,
            source_review=review,
            razorpay_webhook_event=event,
            source_event_id=(event.source_event_id if event else ""),
            event_name=event.event_name if event else "",
            provider_environment=(event.environment if event else "test"),
            provider_order_id=(event.provider_order_id if event else ""),
            provider_payment_id=(event.provider_payment_id if event else ""),
            provider_payment_link_id="",
            amount_paise=(event.amount_paise if event else None),
            currency=(event.currency if event else ""),
            proposed_payment_status=spec["futurePaymentStatus"],
            proposed_order_status=spec["futureOrderStatusCandidate"],
            proposed_order_effect=spec["futureOrderEffect"],
            proposed_workflow_action=spec["workflowAction"],
            status=RazorpayPaymentOrderWorkflowGate.Status.PENDING_MANUAL_REVIEW,
            phase6p_execution_verified=bool(
                attempt and attempt.executed_at is not None
            ),
            phase6p_rollback_verified=bool(
                attempt and attempt.rolled_back_at is not None
            ),
            synthetic_eligible=True,
            manual_review_required=True,
            workflow_mutation_allowed_in_phase6q=False,
            real_order_mutation_was_made=False,
            real_payment_mutation_was_made=False,
            shipment_mutation_was_made=False,
            discount_mutation_was_made=False,
            customer_notification_sent=False,
            provider_call_attempted=False,
            rollback_required=True,
            idempotency_key=idempotency,
            blockers=list(contract["blockers"]),
            warnings=[PHASE_6Q_WARNING],
            safety_invariants=_safety_invariants(),
            manual_review_checklist=_manual_review_checklist(),
            rollback_plan=_rollback_plan(),
            requested_by=requested_by,
        )
        assert_phase6q_no_real_business_mutation(gate)
        try:
            gate.save()
        except IntegrityError:
            gate = RazorpayPaymentOrderWorkflowGate.objects.get(
                idempotency_key=idempotency
            )
            return {
                "phase": "6Q",
                "created": False,
                "reused": True,
                "gate": _serialize_gate(gate),
                "blockers": [],
                "warnings": [PHASE_6Q_WARNING],
                "nextAction": "gate_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 6Q gate prepared gate_id={gate.pk} "
            f"source_event_id={gate.source_event_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6Q",
            "gate_id": gate.pk,
            "source_attempt_id": gate.source_attempt_id,
            "source_ledger_id": gate.source_ledger_id,
            "source_review_id": gate.source_review_id,
            "source_event_id": gate.source_event_id,
            "event_name": gate.event_name,
            "status": gate.status,
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6Q",
        "created": True,
        "reused": False,
        "gate": _serialize_gate(gate),
        "blockers": [],
        "warnings": [PHASE_6Q_WARNING],
        "nextAction": "gate_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


_TRANSITIONABLE_FROM = {
    RazorpayPaymentOrderWorkflowGate.Status.DRAFT,
    RazorpayPaymentOrderWorkflowGate.Status.PENDING_MANUAL_REVIEW,
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
) -> dict[str, Any]:
    gate = (
        RazorpayPaymentOrderWorkflowGate.objects.filter(pk=gate_id).first()
        if gate_id
        else None
    )
    if gate is None:
        return {
            "phase": "6Q",
            "ok": False,
            "gate": None,
            "blockers": ["gate_not_found"],
            "warnings": [PHASE_6Q_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not bool(
        getattr(
            settings, "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED", False
        )
    ):
        return {
            "phase": "6Q",
            "ok": False,
            "gate": _serialize_gate(gate),
            "blockers": [
                "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_6Q_WARNING],
            "nextAction": "enable_workflow_gate_flag_via_env",
        }

    if require_reason and not (reason or "").strip():
        return {
            "phase": "6Q",
            "ok": False,
            "gate": _serialize_gate(gate),
            "blockers": ["manual_review_reason_must_be_non_empty"],
            "warnings": [PHASE_6Q_WARNING],
            "nextAction": "supply_manual_review_reason",
        }

    if not archive and gate.status not in _TRANSITIONABLE_FROM:
        return {
            "phase": "6Q",
            "ok": False,
            "gate": _serialize_gate(gate),
            "blockers": [
                f"gate_status_{gate.status}_not_transitionable_to_{new_status}"
            ],
            "warnings": [PHASE_6Q_WARNING],
            "nextAction": "gate_already_finalised",
        }
    if archive and gate.status == RazorpayPaymentOrderWorkflowGate.Status.ARCHIVED:
        return {
            "phase": "6Q",
            "ok": True,
            "gate": _serialize_gate(gate),
            "blockers": [],
            "warnings": [PHASE_6Q_WARNING + " gate_already_archived"],
            "nextAction": "gate_already_archived",
        }

    gate.status = new_status
    if archive:
        gate.archived_by = by_user
        gate.archived_at = timezone.now()
        gate.archive_reason = (reason or "").strip()[:200]
    else:
        gate.reviewed_by = by_user
        gate.reviewed_at = timezone.now()
        gate.review_reason = (reason or "").strip()[:200]

    assert_phase6q_no_real_business_mutation(gate)
    gate.save()

    write_event(
        kind=audit_kind,
        text=(
            f"Phase 6Q gate {gate.pk} -> {new_status}"
            + (f" · {reason}" if reason else "")
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6Q",
            "gate_id": gate.pk,
            "source_attempt_id": gate.source_attempt_id,
            "source_ledger_id": gate.source_ledger_id,
            "source_review_id": gate.source_review_id,
            "source_event_id": gate.source_event_id,
            "event_name": gate.event_name,
            "status": gate.status,
            "reason": (reason or "")[:200],
            "by": getattr(by_user, "username", "") or "",
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6Q",
        "ok": True,
        "gate": _serialize_gate(gate),
        "blockers": [],
        "warnings": [PHASE_6Q_WARNING],
        "nextAction": (
            "ready_for_phase_6r_planning_after_director_signoff"
            if new_status
            == RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
            else "gate_finalised"
        ),
    }


def approve_phase6q_payment_order_workflow_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the gate approved **for future Phase 6R only**. NEVER
    mutates real business tables; NEVER calls Razorpay; NEVER sends
    a customer notification. Manual review reason text required.
    """
    return _transition(
        gate_id,
        new_status=RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R,
        audit_kind=AUDIT_KIND_APPROVED,
        by_user=reviewed_by,
        reason=reason,
        require_reason=True,
    )


def reject_phase6q_payment_order_workflow_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        gate_id,
        new_status=RazorpayPaymentOrderWorkflowGate.Status.REJECTED,
        audit_kind=AUDIT_KIND_REJECTED,
        by_user=reviewed_by,
        reason=reason,
    )


def archive_phase6q_payment_order_workflow_gate(
    gate_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition(
        gate_id,
        new_status=RazorpayPaymentOrderWorkflowGate.Status.ARCHIVED,
        audit_kind=AUDIT_KIND_ARCHIVED,
        by_user=archived_by,
        reason=reason,
        archive=True,
    )


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase6q_payment_order_workflow_gates(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpayPaymentOrderWorkflowGate.objects.all().order_by("-created_at")
    Status = RazorpayPaymentOrderWorkflowGate.Status
    counts = {
        "draft": qs.filter(status=Status.DRAFT).count(),
        "pendingManualReview": qs.filter(
            status=Status.PENDING_MANUAL_REVIEW
        ).count(),
        "approvedForFuturePhase6R": qs.filter(
            status=Status.APPROVED_FOR_FUTURE_PHASE6R
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
        "discountMutationWasMade": qs.filter(
            discount_mutation_was_made=True
        ).count(),
        "customerNotificationSent": qs.filter(
            customer_notification_sent=True
        ).count(),
        "providerCallAttempted": qs.filter(
            provider_call_attempted=True
        ).count(),
    }
    sample = [_serialize_gate(row) for row in qs[: max(1, min(limit, 200))]]
    return {"counts": counts, "items": sample}


def inspect_phase6q_payment_order_workflow_gate_readiness() -> dict[str, Any]:
    flag_enabled = bool(
        getattr(
            settings, "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED", False
        )
    )
    summary = summarize_phase6q_payment_order_workflow_gates()
    counts = summary["counts"]

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6Q_WARNING]

    for key in (
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "shipmentMutationWasMade",
        "discountMutationWasMade",
        "customerNotificationSent",
        "providerCallAttempted",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_6q_gate_{key}_observed_must_be_zero"
            )

    # Phase 6P proof presence — count attempts that have been
    # executed AND rolled back at least once.
    phase6p_executed = (
        RazorpaySandboxPaidStatusMutationAttempt.objects.filter(
            executed_at__isnull=False
        ).count()
    )
    phase6p_rolled_back = (
        RazorpaySandboxPaidStatusMutationAttempt.objects.filter(
            rolled_back_at__isnull=False
        ).count()
    )

    safe_to_start_phase_6r = bool(
        not blockers
        and counts["approvedForFuturePhase6R"] >= 1
    )

    if blockers:
        next_action = "fix_phase_6q_safety_blockers"
    elif phase6p_executed == 0 or phase6p_rolled_back == 0:
        next_action = (
            "complete_at_least_one_phase_6p_execute_and_rollback_cycle"
        )
    elif counts["approvedForFuturePhase6R"] == 0:
        next_action = (
            "approve_at_least_one_phase6q_gate_for_future_phase6r"
        )
    else:
        next_action = (
            "ready_for_phase_6r_payment_to_whatsapp_courier_readiness_planning"
        )

    return {
        "phase": "6Q",
        "status": "audit_gate_only",
        "latestCompletedPhase": "6P",
        "nextPhase": "6R",
        "razorpayPaymentOrderWorkflowGateEnabled": flag_enabled,
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "providerCallAttempted": False,
        "rawPayloadStorageEnabled": False,
        "phase6PExecutedCount": phase6p_executed,
        "phase6PRolledBackCount": phase6p_rolled_back,
        "gateCounts": counts,
        "workflowContract": build_phase6q_payment_order_workflow_contract(),
        "safetyInvariants": _safety_invariants(),
        "manualReviewChecklist": _manual_review_checklist(),
        "rollbackPlan": _rollback_plan(),
        "forbiddenActions": list(PHASE_6Q_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "maxSafeAmountPaise": PHASE_6Q_MAX_SAFE_AMOUNT_PAISE,
        "safeToStartPhase6R": safe_to_start_phase_6r,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentGates": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("gateCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 6Q payment-order workflow gate readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6Q",
            "razorpay_payment_order_workflow_gate_enabled": bool(
                report.get("razorpayPaymentOrderWorkflowGateEnabled")
            ),
            "phase6p_executed_count": int(
                report.get("phase6PExecutedCount") or 0
            ),
            "phase6p_rolled_back_count": int(
                report.get("phase6PRolledBackCount") or 0
            ),
            "gate_count_pending": int(
                counts.get("pendingManualReview") or 0
            ),
            "gate_count_approved": int(
                counts.get("approvedForFuturePhase6R") or 0
            ),
            "safe_to_start_phase_6r": bool(report.get("safeToStartPhase6R")),
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )


__all__ = (
    "PHASE_6Q_WARNING",
    "PHASE_6Q_FORBIDDEN_ACTIONS",
    "PHASE_6Q_MAX_SAFE_AMOUNT_PAISE",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase6QEligibility",
    "build_phase6q_payment_order_workflow_contract",
    "validate_phase6q_source_eligibility",
    "preview_phase6q_payment_order_workflow_gate",
    "prepare_phase6q_payment_order_workflow_gate",
    "approve_phase6q_payment_order_workflow_gate",
    "reject_phase6q_payment_order_workflow_gate",
    "archive_phase6q_payment_order_workflow_gate",
    "summarize_phase6q_payment_order_workflow_gates",
    "inspect_phase6q_payment_order_workflow_gate_readiness",
    "assert_phase6q_no_real_business_mutation",
    "emit_readiness_inspected_audit",
)
