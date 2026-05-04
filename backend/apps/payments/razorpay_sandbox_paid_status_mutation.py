"""Phase 6P — Controlled Internal Paid-Status Mutation Test.

Sandbox-only mutation layer that converts an approved Phase 6O
:class:`RazorpaySandboxStatusReview` into a controlled
:class:`RazorpaySandboxPaidStatusLedger` state via a
:class:`RazorpaySandboxPaidStatusMutationAttempt` row.

**Phase 6P NEVER mutates real ``Order`` / ``Payment`` / ``Shipment`` /
``DiscountOfferLog`` / ``Customer`` / ``Lead`` / ``WhatsAppMessage``
/ ``WhatsAppConversation`` rows.** It NEVER calls Razorpay, NEVER
sends a customer notification, NEVER flips an env flag, NEVER
replays a webhook. It NEVER exposes API endpoints that execute
mutation — execution is exclusively CLI.

Public service surface:

- :func:`inspect_phase6p_paid_status_mutation_readiness`
- :func:`build_phase6p_paid_status_mapping`
- :func:`validate_phase6p_review_eligibility`
- :func:`preview_phase6p_paid_status_mutation`
- :func:`prepare_phase6p_paid_status_mutation_attempt`
- :func:`execute_phase6p_paid_status_mutation_attempt`
- :func:`rollback_phase6p_paid_status_mutation_attempt`
- :func:`archive_phase6p_paid_status_mutation_attempt`
- :func:`summarize_phase6p_paid_status_mutation_attempts`
- :func:`assert_phase6p_no_real_business_mutation`
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
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)
from .razorpay_sandbox_status_mapping import (
    PHASE_6O_MAX_SAFE_AMOUNT_PAISE,
    validate_phase6o_event_eligibility as _validate_phase6o_event_eligibility,
)


PHASE_6P_WARNING = (
    "Phase 6P is a controlled, sandbox-only paid-status mutation "
    "test. It NEVER mutates real Order / Payment / Shipment / "
    "DiscountOfferLog / Customer / Lead / WhatsAppMessage rows. "
    "It NEVER calls Razorpay, NEVER sends a customer notification, "
    "NEVER flips an env flag. Execution is CLI-only — no frontend "
    "or API endpoint can dispatch a Phase 6P mutation."
)


# Audit kinds Phase 6P emits. Payloads scrubbed by the helpers below.
AUDIT_KIND_READINESS = "razorpay.sandbox_paid_status.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.sandbox_paid_status.previewed"
AUDIT_KIND_ATTEMPT_PREPARED = (
    "razorpay.sandbox_paid_status.attempt_prepared"
)
AUDIT_KIND_EXECUTION_BLOCKED = (
    "razorpay.sandbox_paid_status.execution_blocked"
)
AUDIT_KIND_EXECUTED = "razorpay.sandbox_paid_status.executed"
AUDIT_KIND_ROLLED_BACK = "razorpay.sandbox_paid_status.rolled_back"
AUDIT_KIND_ARCHIVED = "razorpay.sandbox_paid_status.archived"
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.sandbox_paid_status.invariant_violation_blocked"
)


PHASE_6P_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "enable_customer_notification_env_flag",
    "execute_phase_6p_via_frontend",
    "execute_phase_6p_via_api_endpoint",
)


# ---------------------------------------------------------------------------
# Mapping (preserves the Phase 6O 9-event coverage)
# ---------------------------------------------------------------------------


_LEDGER_EFFECT_BY_EVENT: dict[str, dict[str, str]] = {
    "payment_link.paid": {
        "sandboxPaymentStatus": "paid",
        "sandboxOrderEffect": "advance_paid_candidate",
    },
    "payment.captured": {
        "sandboxPaymentStatus": "captured",
        "sandboxOrderEffect": "payment_verified_candidate",
    },
    "payment.failed": {
        "sandboxPaymentStatus": "failed",
        "sandboxOrderEffect": "payment_failed_candidate",
    },
    "payment.authorized": {
        "sandboxPaymentStatus": "authorized",
        "sandboxOrderEffect": "payment_authorized_candidate",
    },
    "order.paid": {
        "sandboxPaymentStatus": "paid",
        "sandboxOrderEffect": "paid_candidate",
    },
    "payment_link.cancelled": {
        "sandboxPaymentStatus": "cancelled",
        "sandboxOrderEffect": "payment_link_cancelled_candidate",
    },
    "payment_link.expired": {
        "sandboxPaymentStatus": "expired",
        "sandboxOrderEffect": "payment_link_expired_candidate",
    },
    "refund.created": {
        "sandboxPaymentStatus": "refund_pending",
        "sandboxOrderEffect": "refund_review_candidate",
    },
    "refund.processed": {
        "sandboxPaymentStatus": "refunded",
        "sandboxOrderEffect": "refund_processed_candidate",
    },
}


def build_phase6p_paid_status_mapping() -> list[dict[str, Any]]:
    """Return the canonical Phase 6P sandbox mapping plan.

    Every row carries `realOrderMutationAllowedInPhase6P=False`,
    `realPaymentMutationAllowedInPhase6P=False`,
    `customerNotificationAllowed=False`,
    `providerCallAllowed=False`. Phase 6P never writes to real
    business tables.
    """
    return [
        {
            "razorpayEventName": event_name,
            "sandboxPaymentStatus": effect["sandboxPaymentStatus"],
            "sandboxOrderEffect": effect["sandboxOrderEffect"],
            "realOrderMutationAllowedInPhase6P": False,
            "realPaymentMutationAllowedInPhase6P": False,
            "customerNotificationAllowed": False,
            "providerCallAllowed": False,
            "shipmentEffectAllowed": False,
            "discountEffectAllowed": False,
            "idempotencyRequired": True,
            "rollbackRequired": True,
            "executionPath": "cli_only",
            "blockers": [
                "phase_6p_sandbox_ledger_only",
                "phase_6q_must_supply_payment_to_order_workflow_safety_gate",
            ],
        }
        for event_name, effect in _LEDGER_EFFECT_BY_EVENT.items()
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
        "frontendCanExecutePhase6P": False,
        "apiEndpointCanExecutePhase6P": False,
        "phase6PRespectsKillSwitch": True,
        "phase6PApprovalApplyRealMutation": False,
    }


def assert_phase6p_no_real_business_mutation(
    row: RazorpaySandboxPaidStatusLedger
    | RazorpaySandboxPaidStatusMutationAttempt,
) -> None:
    """Defensive — refuse to save any Phase 6P row whose locked-False
    booleans have flipped True. Emits an audit row + raises.
    """
    bad: list[str] = []
    if getattr(row, "real_order_mutation_was_made", False):
        bad.append("real_order_mutation_was_made_flipped_true")
    if getattr(row, "real_payment_mutation_was_made", False):
        bad.append("real_payment_mutation_was_made_flipped_true")
    if getattr(row, "business_mutation_was_made", False):
        bad.append("business_mutation_was_made_flipped_true")
    if getattr(row, "customer_notification_sent", False):
        bad.append("customer_notification_sent_flipped_true")
    if getattr(row, "provider_call_attempted", False):
        bad.append("provider_call_attempted_flipped_true")
    if bad:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text=(
                f"Phase 6P invariant violation on "
                f"{row.__class__.__name__} {row.pk or 'unsaved'}: "
                f"{','.join(bad)}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload={
                "phase": "6P",
                "row_class": row.__class__.__name__,
                "row_id": row.pk,
                "violations": bad,
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
                "provider_call_attempted": False,
            },
        )
        raise ValueError(
            "Phase 6P invariant violation: " + ",".join(bad)
        )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase6PEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_phase6p_review_eligibility(
    review: RazorpaySandboxStatusReview,
    *,
    require_execute: bool = False,
    confirmed: bool = False,
    director_signoff_text: str = "",
) -> Phase6PEligibility:
    """Return whether the review can drive a Phase 6P sandbox attempt.

    ``require_execute`` toggles the strict execute-only checks
    (env flag, confirmation flag, sign-off text). The base review +
    source-event safety checks always apply.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    if (
        review.status
        != RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
    ):
        blockers.append(
            f"review_status_must_be_approved_for_future_phase6p_was_{review.status}"
        )
    if not review.synthetic_eligible:
        blockers.append("review_must_be_synthetic_eligible")
    if review.mutation_allowed_in_phase6o:
        blockers.append(
            "review_mutation_allowed_in_phase6o_must_remain_false"
        )
    if review.business_mutation_was_made:
        blockers.append("review_business_mutation_was_made_must_be_false")
    if review.customer_notification_sent:
        blockers.append(
            "review_customer_notification_sent_must_be_false"
        )
    if review.provider_call_attempted:
        blockers.append("review_provider_call_attempted_must_be_false")

    event = review.razorpay_webhook_event
    if event is None:
        blockers.append("review_missing_linked_razorpay_webhook_event")
    else:
        # Re-use the Phase 6O eligibility helper with the env-flag
        # check disabled — Phase 6P has its own env flag.
        underlying = _validate_phase6o_event_eligibility(
            event, require_env_flag=False
        )
        if not underlying.eligible:
            blockers.extend(
                f"phase_6m_event_blocker:{b}" for b in underlying.blockers
            )

        if event.event_name not in _LEDGER_EFFECT_BY_EVENT:
            blockers.append(
                f"event_name_not_phase6p_allowlisted_{event.event_name}"
            )
        if (
            event.amount_paise is not None
            and event.amount_paise > PHASE_6O_MAX_SAFE_AMOUNT_PAISE
        ):
            blockers.append(
                f"amount_paise_must_be_<=_{PHASE_6O_MAX_SAFE_AMOUNT_PAISE}"
            )

    if require_execute:
        if not bool(
            getattr(
                settings,
                "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED",
                False,
            )
        ):
            blockers.append(
                "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED_must_be_true"
            )
        if not confirmed:
            blockers.append("cli_confirmation_flag_must_be_provided")
        if not (director_signoff_text or "").strip():
            blockers.append("director_signoff_text_must_be_non_empty")

    return Phase6PEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Idempotency / serialization
# ---------------------------------------------------------------------------


def _idempotency_key_for_apply(review: RazorpaySandboxStatusReview) -> str:
    return (
        f"phase6p::apply::{review.source_event_id or review.pk}::"
        f"{review.proposed_review_action}"
    )


def _idempotency_key_for_rollback(
    attempt: RazorpaySandboxPaidStatusMutationAttempt,
) -> str:
    return (
        f"phase6p::rollback::{attempt.source_event_id or attempt.pk}::"
        f"{attempt.pk}"
    )


def _serialize_attempt(
    attempt: RazorpaySandboxPaidStatusMutationAttempt,
) -> dict[str, Any]:
    return {
        "id": attempt.pk,
        "reviewId": attempt.review_id,
        "ledgerId": attempt.ledger_id,
        "razorpayWebhookEventId": attempt.razorpay_webhook_event_id,
        "sourceEventId": attempt.source_event_id,
        "eventName": attempt.event_name,
        "status": attempt.status,
        "requestedAction": attempt.requested_action,
        "proposedPaymentStatus": attempt.proposed_payment_status,
        "proposedOrderEffect": attempt.proposed_order_effect,
        "beforeState": attempt.before_state or {},
        "afterState": attempt.after_state or {},
        "blockers": list(attempt.blockers or []),
        "warnings": list(attempt.warnings or []),
        "confirmationProvided": attempt.confirmation_provided,
        "directorSignoffText": attempt.director_signoff_text,
        "executedByUsername": (
            getattr(attempt.executed_by, "username", "") or ""
        ),
        "executedAt": (
            attempt.executed_at.isoformat() if attempt.executed_at else None
        ),
        "rolledBackByUsername": (
            getattr(attempt.rolled_back_by, "username", "") or ""
        ),
        "rolledBackAt": (
            attempt.rolled_back_at.isoformat()
            if attempt.rolled_back_at
            else None
        ),
        "archivedByUsername": (
            getattr(attempt.archived_by, "username", "") or ""
        ),
        "archivedAt": (
            attempt.archived_at.isoformat() if attempt.archived_at else None
        ),
        "idempotencyKey": attempt.idempotency_key,
        "businessMutationWasMade": attempt.business_mutation_was_made,
        "realOrderMutationWasMade": attempt.real_order_mutation_was_made,
        "realPaymentMutationWasMade": attempt.real_payment_mutation_was_made,
        "customerNotificationSent": attempt.customer_notification_sent,
        "providerCallAttempted": attempt.provider_call_attempted,
        "createdAt": attempt.created_at.isoformat(),
        "updatedAt": attempt.updated_at.isoformat(),
    }


def _serialize_ledger(
    ledger: RazorpaySandboxPaidStatusLedger,
) -> dict[str, Any]:
    return {
        "id": ledger.pk,
        "reviewId": ledger.review_id,
        "razorpayWebhookEventId": ledger.razorpay_webhook_event_id,
        "sourceEventId": ledger.source_event_id,
        "eventName": ledger.event_name,
        "providerEnvironment": ledger.provider_environment,
        "providerOrderId": ledger.provider_order_id,
        "providerPaymentId": ledger.provider_payment_id,
        "providerPaymentLinkId": ledger.provider_payment_link_id,
        "providerRefundId": ledger.provider_refund_id,
        "amountPaise": ledger.amount_paise,
        "currency": ledger.currency,
        "sandboxPaymentStatus": ledger.sandbox_payment_status,
        "sandboxOrderEffect": ledger.sandbox_order_effect,
        "currentState": ledger.current_state,
        "previousState": ledger.previous_state,
        "mutationCount": ledger.mutation_count,
        "lastAttemptId": ledger.last_attempt_id,
        "syntheticEligible": ledger.synthetic_eligible,
        "businessMutationWasMade": ledger.business_mutation_was_made,
        "realOrderMutationWasMade": ledger.real_order_mutation_was_made,
        "realPaymentMutationWasMade": ledger.real_payment_mutation_was_made,
        "customerNotificationSent": ledger.customer_notification_sent,
        "providerCallAttempted": ledger.provider_call_attempted,
        "rollbackRequired": ledger.rollback_required,
        "rolledBack": ledger.rolled_back,
        "rolledBackAt": (
            ledger.rolled_back_at.isoformat() if ledger.rolled_back_at else None
        ),
        "createdAt": ledger.created_at.isoformat(),
        "updatedAt": ledger.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _ledger_for_review(
    review: RazorpaySandboxStatusReview,
) -> RazorpaySandboxPaidStatusLedger | None:
    return getattr(review, "sandbox_paid_status_ledger", None)


def _proposed_for_review(
    review: RazorpaySandboxStatusReview,
) -> dict[str, str]:
    spec = _LEDGER_EFFECT_BY_EVENT.get(review.event_name)
    return {
        "sandboxPaymentStatus": (
            spec["sandboxPaymentStatus"] if spec else review.proposed_payment_status
        ),
        "sandboxOrderEffect": (
            spec["sandboxOrderEffect"] if spec else review.proposed_order_effect
        ),
    }


def preview_phase6p_paid_status_mutation(review_id: int) -> dict[str, Any]:
    """Read-only preview of a Phase 6P attempt for the given review.

    Never creates rows, never calls Razorpay, never mutates anything.
    """
    review = (
        RazorpaySandboxStatusReview.objects.filter(pk=review_id).first()
        if review_id
        else None
    )
    if review is None:
        return {
            "phase": "6P",
            "found": False,
            "reviewId": review_id,
            "blockers": ["razorpay_sandbox_status_review_not_found"],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "verify_review_id_or_complete_phase_6o_first",
        }

    eligibility = validate_phase6p_review_eligibility(
        review, require_execute=False
    )
    proposed = _proposed_for_review(review)
    ledger = _ledger_for_review(review)

    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 6P preview for review_id={review.pk}, "
            f"source_event_id={review.source_event_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6P",
            "review_id": review.pk,
            "source_event_id": review.source_event_id,
            "event_name": review.event_name,
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
        "phase": "6P",
        "found": True,
        "reviewId": review.pk,
        "eventName": review.event_name,
        "eligible": eligibility.eligible,
        "proposedSandboxPaymentStatus": proposed["sandboxPaymentStatus"],
        "proposedSandboxOrderEffect": proposed["sandboxOrderEffect"],
        "currentLedger": _serialize_ledger(ledger) if ledger else None,
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_6P_WARNING],
        "nextAction": (
            "ready_to_prepare_phase6p_attempt"
            if eligibility.eligible
            else "fix_phase_6p_eligibility_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase6p_paid_status_mutation_attempt(
    review_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create a ``prepared`` mutation attempt row.

    Idempotent on ``idempotency_key`` (one prepared attempt per
    review/action). Never mutates ledger state. Never calls
    Razorpay. Never sends a customer notification.
    """
    review = (
        RazorpaySandboxStatusReview.objects.filter(pk=review_id).first()
        if review_id
        else None
    )
    if review is None:
        return {
            "phase": "6P",
            "created": False,
            "reused": False,
            "attempt": None,
            "blockers": ["razorpay_sandbox_status_review_not_found"],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "verify_review_id_or_complete_phase_6o_first",
        }

    eligibility = validate_phase6p_review_eligibility(
        review, require_execute=False
    )
    proposed = _proposed_for_review(review)
    idempotency = _idempotency_key_for_apply(review)

    if not eligibility.eligible:
        # Defensively persist a BLOCKED attempt? No — we record the
        # block via audit only and refuse to write a row. This keeps
        # the attempts table truthful for the operator.
        write_event(
            kind=AUDIT_KIND_EXECUTION_BLOCKED,
            text=(
                f"Phase 6P prepare blocked for review_id={review.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "6P",
                "review_id": review.pk,
                "source_event_id": review.source_event_id,
                "event_name": review.event_name,
                "blockers": list(eligibility.blockers),
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
                "provider_call_attempted": False,
            },
        )
        return {
            "phase": "6P",
            "created": False,
            "reused": False,
            "attempt": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_6P_WARNING],
            "nextAction": "fix_phase_6p_eligibility_blockers",
        }

    with transaction.atomic():
        existing = (
            RazorpaySandboxPaidStatusMutationAttempt.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "6P",
                "created": False,
                "reused": True,
                "attempt": _serialize_attempt(existing),
                "blockers": [],
                "warnings": [PHASE_6P_WARNING],
                "nextAction": "attempt_already_prepared",
            }

        attempt = RazorpaySandboxPaidStatusMutationAttempt(
            review=review,
            razorpay_webhook_event=review.razorpay_webhook_event,
            source_event_id=review.source_event_id,
            event_name=review.event_name,
            status=RazorpaySandboxPaidStatusMutationAttempt.Status.PREPARED,
            requested_action=(
                RazorpaySandboxPaidStatusMutationAttempt.RequestedAction.APPLY_SANDBOX_STATUS
            ),
            proposed_payment_status=proposed["sandboxPaymentStatus"],
            proposed_order_effect=proposed["sandboxOrderEffect"],
            before_state={},
            after_state={},
            blockers=[],
            warnings=[PHASE_6P_WARNING],
            safety_invariants=_safety_invariants(),
            confirmation_provided=False,
            director_signoff_text="",
            requested_by=requested_by,
            idempotency_key=idempotency,
        )
        assert_phase6p_no_real_business_mutation(attempt)
        try:
            attempt.save()
        except IntegrityError:
            attempt = (
                RazorpaySandboxPaidStatusMutationAttempt.objects.get(
                    idempotency_key=idempotency
                )
            )
            return {
                "phase": "6P",
                "created": False,
                "reused": True,
                "attempt": _serialize_attempt(attempt),
                "blockers": [],
                "warnings": [PHASE_6P_WARNING],
                "nextAction": "attempt_already_prepared",
            }

    write_event(
        kind=AUDIT_KIND_ATTEMPT_PREPARED,
        text=(
            f"Phase 6P attempt prepared for review_id={review.pk}, "
            f"source_event_id={review.source_event_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6P",
            "attempt_id": attempt.pk,
            "review_id": review.pk,
            "source_event_id": review.source_event_id,
            "event_name": review.event_name,
            "status": attempt.status,
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6P",
        "created": True,
        "reused": False,
        "attempt": _serialize_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_6P_WARNING],
        "nextAction": "ready_for_cli_execute_with_confirmation_and_signoff",
    }


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def _ensure_ledger(
    review: RazorpaySandboxStatusReview,
    *,
    proposed: dict[str, str],
) -> RazorpaySandboxPaidStatusLedger:
    """Get-or-create the ledger row for the review."""
    ledger = _ledger_for_review(review)
    if ledger is not None:
        return ledger
    ledger = RazorpaySandboxPaidStatusLedger(
        review=review,
        razorpay_webhook_event=review.razorpay_webhook_event,
        source_event_id=review.source_event_id,
        event_name=review.event_name,
        provider_environment=review.provider_environment,
        provider_order_id=review.provider_order_id,
        provider_payment_id=review.provider_payment_id,
        provider_payment_link_id=review.provider_payment_link_id,
        provider_refund_id=review.provider_refund_id,
        amount_paise=review.amount_paise,
        currency=review.currency,
        sandbox_payment_status=proposed["sandboxPaymentStatus"],
        sandbox_order_effect=proposed["sandboxOrderEffect"],
        current_state="initial",
        previous_state="",
        mutation_count=0,
        synthetic_eligible=True,
        business_mutation_was_made=False,
        real_order_mutation_was_made=False,
        real_payment_mutation_was_made=False,
        customer_notification_sent=False,
        provider_call_attempted=False,
        rollback_required=True,
        rolled_back=False,
    )
    assert_phase6p_no_real_business_mutation(ledger)
    ledger.save()
    return ledger


def execute_phase6p_paid_status_mutation_attempt(
    review_id: int,
    *,
    confirmed: bool = False,
    director_signoff_text: str = "",
    executed_by=None,
) -> dict[str, Any]:
    """Execute the prepared apply-sandbox-status attempt for the given
    review. Mutates ONLY the Phase 6P ledger + attempt rows.

    Idempotent — re-running the same execute on the same review +
    same proposed status returns ``executed_again=True`` without
    flipping ``mutation_count`` past the first transition.
    """
    review = (
        RazorpaySandboxStatusReview.objects.filter(pk=review_id).first()
        if review_id
        else None
    )
    if review is None:
        return {
            "phase": "6P",
            "executed": False,
            "executedAgain": False,
            "attempt": None,
            "ledger": None,
            "blockers": ["razorpay_sandbox_status_review_not_found"],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "verify_review_id_or_complete_phase_6o_first",
        }

    eligibility = validate_phase6p_review_eligibility(
        review,
        require_execute=True,
        confirmed=confirmed,
        director_signoff_text=director_signoff_text,
    )

    if not eligibility.eligible:
        write_event(
            kind=AUDIT_KIND_EXECUTION_BLOCKED,
            text=(
                f"Phase 6P execute blocked for review_id={review.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "6P",
                "review_id": review.pk,
                "source_event_id": review.source_event_id,
                "event_name": review.event_name,
                "blockers": list(eligibility.blockers),
                "real_order_mutation_was_made": False,
                "real_payment_mutation_was_made": False,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
                "provider_call_attempted": False,
            },
        )
        return {
            "phase": "6P",
            "executed": False,
            "executedAgain": False,
            "attempt": None,
            "ledger": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_6P_WARNING],
            "nextAction": "fix_phase_6p_execute_blockers",
        }

    proposed = _proposed_for_review(review)
    idempotency = _idempotency_key_for_apply(review)
    target_state = proposed["sandboxPaymentStatus"]

    with transaction.atomic():
        ledger = _ensure_ledger(review, proposed=proposed)

        # Get-or-create the prepared attempt row.
        attempt, created = (
            RazorpaySandboxPaidStatusMutationAttempt.objects.select_for_update()
            .get_or_create(
                idempotency_key=idempotency,
                defaults=dict(
                    review=review,
                    razorpay_webhook_event=review.razorpay_webhook_event,
                    source_event_id=review.source_event_id,
                    event_name=review.event_name,
                    status=(
                        RazorpaySandboxPaidStatusMutationAttempt.Status.PREPARED
                    ),
                    requested_action=(
                        RazorpaySandboxPaidStatusMutationAttempt.RequestedAction.APPLY_SANDBOX_STATUS
                    ),
                    proposed_payment_status=proposed["sandboxPaymentStatus"],
                    proposed_order_effect=proposed["sandboxOrderEffect"],
                    before_state={},
                    after_state={},
                    blockers=[],
                    warnings=[PHASE_6P_WARNING],
                    safety_invariants=_safety_invariants(),
                    requested_by=executed_by,
                ),
            )
        )

        # Idempotent re-run guard.
        if (
            attempt.status
            == RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED
            and ledger.current_state == target_state
        ):
            attempt.confirmation_provided = True
            attempt.director_signoff_text = (
                director_signoff_text or attempt.director_signoff_text
            )[:200]
            assert_phase6p_no_real_business_mutation(attempt)
            attempt.save(
                update_fields=[
                    "confirmation_provided",
                    "director_signoff_text",
                    "updated_at",
                ]
            )
            return {
                "phase": "6P",
                "executed": False,
                "executedAgain": True,
                "attempt": _serialize_attempt(attempt),
                "ledger": _serialize_ledger(ledger),
                "blockers": [],
                "warnings": [PHASE_6P_WARNING],
                "nextAction": "attempt_already_executed_state_already_at_target",
            }

        before_state = {
            "currentState": ledger.current_state,
            "previousState": ledger.previous_state,
            "mutationCount": ledger.mutation_count,
            "rolledBack": ledger.rolled_back,
        }

        # Mutate ledger FIRST and persist all fields (no update_fields — we
        # are intentionally writing every column we just edited).
        ledger.previous_state = ledger.current_state
        ledger.current_state = target_state
        ledger.mutation_count += 1
        ledger.rolled_back = False
        ledger.rolled_back_at = None
        # Locked-False booleans must NEVER flip.
        ledger.business_mutation_was_made = False
        ledger.real_order_mutation_was_made = False
        ledger.real_payment_mutation_was_made = False
        ledger.customer_notification_sent = False
        ledger.provider_call_attempted = False
        assert_phase6p_no_real_business_mutation(ledger)
        ledger.save()

        attempt.status = (
            RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED
        )
        attempt.requested_action = (
            RazorpaySandboxPaidStatusMutationAttempt.RequestedAction.APPLY_SANDBOX_STATUS
        )
        attempt.ledger = ledger
        attempt.confirmation_provided = True
        attempt.director_signoff_text = (director_signoff_text or "")[:200]
        attempt.before_state = before_state
        attempt.after_state = {
            "currentState": ledger.current_state,
            "previousState": ledger.previous_state,
            "mutationCount": ledger.mutation_count,
            "rolledBack": ledger.rolled_back,
        }
        attempt.executed_by = executed_by
        attempt.executed_at = timezone.now()
        attempt.blockers = []
        attempt.warnings = [PHASE_6P_WARNING]
        attempt.safety_invariants = _safety_invariants()
        attempt.business_mutation_was_made = False
        attempt.real_order_mutation_was_made = False
        attempt.real_payment_mutation_was_made = False
        attempt.customer_notification_sent = False
        attempt.provider_call_attempted = False
        assert_phase6p_no_real_business_mutation(attempt)
        attempt.save()

        ledger.last_attempt = attempt
        ledger.save(update_fields=["last_attempt", "updated_at"])

    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=(
            f"Phase 6P attempt executed for review_id={review.pk}, "
            f"source_event_id={review.source_event_id} → "
            f"current_state={ledger.current_state}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6P",
            "attempt_id": attempt.pk,
            "ledger_id": ledger.pk,
            "review_id": review.pk,
            "source_event_id": review.source_event_id,
            "event_name": review.event_name,
            "status": attempt.status,
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6P",
        "executed": True,
        "executedAgain": False,
        "attempt": _serialize_attempt(attempt),
        "ledger": _serialize_ledger(ledger),
        "blockers": [],
        "warnings": [PHASE_6P_WARNING],
        "nextAction": "ready_to_rollback_or_archive_attempt",
    }


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback_phase6p_paid_status_mutation_attempt(
    attempt_id: int,
    *,
    confirmed: bool = False,
    reason: str = "",
    rolled_back_by=None,
) -> dict[str, Any]:
    """Roll back the sandbox ledger state recorded by the executed
    attempt. Mutates ONLY the Phase 6P ledger + attempt rows.
    Idempotent on rolled-back attempts.
    """
    attempt = (
        RazorpaySandboxPaidStatusMutationAttempt.objects.filter(
            pk=attempt_id
        )
        .select_related("review", "ledger")
        .first()
        if attempt_id
        else None
    )
    if attempt is None:
        return {
            "phase": "6P",
            "rolledBack": False,
            "rolledBackAgain": False,
            "attempt": None,
            "ledger": None,
            "blockers": ["razorpay_sandbox_paid_status_attempt_not_found"],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "verify_attempt_id",
        }

    if not confirmed:
        return {
            "phase": "6P",
            "rolledBack": False,
            "rolledBackAgain": False,
            "attempt": _serialize_attempt(attempt),
            "ledger": _serialize_ledger(attempt.ledger) if attempt.ledger else None,
            "blockers": ["cli_confirmation_flag_must_be_provided"],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "supply_confirm_sandbox_rollback_flag",
        }

    if attempt.status not in (
        RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
        RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
    ):
        return {
            "phase": "6P",
            "rolledBack": False,
            "rolledBackAgain": False,
            "attempt": _serialize_attempt(attempt),
            "ledger": _serialize_ledger(attempt.ledger) if attempt.ledger else None,
            "blockers": [
                f"attempt_status_{attempt.status}_not_rollbackable"
            ],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "execute_attempt_first_or_archive",
        }

    with transaction.atomic():
        ledger = (
            RazorpaySandboxPaidStatusLedger.objects.select_for_update()
            .filter(pk=attempt.ledger_id)
            .first()
            if attempt.ledger_id
            else None
        )

        if (
            attempt.status
            == RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK
        ):
            return {
                "phase": "6P",
                "rolledBack": False,
                "rolledBackAgain": True,
                "attempt": _serialize_attempt(attempt),
                "ledger": _serialize_ledger(ledger) if ledger else None,
                "blockers": [],
                "warnings": [PHASE_6P_WARNING],
                "nextAction": "attempt_already_rolled_back",
            }

        # Roll the ledger back to its before_state.
        if ledger is not None:
            before = attempt.before_state or {}
            ledger.previous_state = ledger.current_state
            ledger.current_state = (
                before.get("currentState") or "initial"
            )
            ledger.rolled_back = True
            ledger.rolled_back_at = timezone.now()
            ledger.business_mutation_was_made = False
            ledger.real_order_mutation_was_made = False
            ledger.real_payment_mutation_was_made = False
            ledger.customer_notification_sent = False
            ledger.provider_call_attempted = False
            assert_phase6p_no_real_business_mutation(ledger)
            ledger.save()

        attempt.status = (
            RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK
        )
        attempt.rolled_back_by = rolled_back_by
        attempt.rolled_back_at = timezone.now()
        attempt.warnings = list(attempt.warnings or []) + [
            (reason or "")[:200]
        ]
        attempt.business_mutation_was_made = False
        attempt.real_order_mutation_was_made = False
        attempt.real_payment_mutation_was_made = False
        attempt.customer_notification_sent = False
        attempt.provider_call_attempted = False
        assert_phase6p_no_real_business_mutation(attempt)
        attempt.save()

    write_event(
        kind=AUDIT_KIND_ROLLED_BACK,
        text=(
            f"Phase 6P attempt rolled back attempt_id={attempt.pk}"
            + (f" · {reason}" if reason else "")
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6P",
            "attempt_id": attempt.pk,
            "ledger_id": attempt.ledger_id,
            "review_id": attempt.review_id,
            "source_event_id": attempt.source_event_id,
            "event_name": attempt.event_name,
            "status": attempt.status,
            "reason": (reason or "")[:200],
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6P",
        "rolledBack": True,
        "rolledBackAgain": False,
        "attempt": _serialize_attempt(attempt),
        "ledger": _serialize_ledger(ledger) if ledger else None,
        "blockers": [],
        "warnings": [PHASE_6P_WARNING],
        "nextAction": "ready_to_archive_attempt",
    }


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def archive_phase6p_paid_status_mutation_attempt(
    attempt_id: int,
    *,
    reason: str = "",
    archived_by=None,
) -> dict[str, Any]:
    attempt = (
        RazorpaySandboxPaidStatusMutationAttempt.objects.filter(
            pk=attempt_id
        ).first()
        if attempt_id
        else None
    )
    if attempt is None:
        return {
            "phase": "6P",
            "archived": False,
            "attempt": None,
            "blockers": ["razorpay_sandbox_paid_status_attempt_not_found"],
            "warnings": [PHASE_6P_WARNING],
            "nextAction": "verify_attempt_id",
        }

    if (
        attempt.status
        == RazorpaySandboxPaidStatusMutationAttempt.Status.ARCHIVED
    ):
        return {
            "phase": "6P",
            "archived": True,
            "attempt": _serialize_attempt(attempt),
            "blockers": [],
            "warnings": [PHASE_6P_WARNING + " attempt_already_archived"],
            "nextAction": "attempt_already_archived",
        }

    attempt.status = (
        RazorpaySandboxPaidStatusMutationAttempt.Status.ARCHIVED
    )
    attempt.archived_by = archived_by
    attempt.archived_at = timezone.now()
    attempt.warnings = list(attempt.warnings or []) + [(reason or "")[:200]]
    attempt.business_mutation_was_made = False
    attempt.real_order_mutation_was_made = False
    attempt.real_payment_mutation_was_made = False
    attempt.customer_notification_sent = False
    attempt.provider_call_attempted = False
    assert_phase6p_no_real_business_mutation(attempt)
    attempt.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 6P attempt archived attempt_id={attempt.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6P",
            "attempt_id": attempt.pk,
            "review_id": attempt.review_id,
            "source_event_id": attempt.source_event_id,
            "event_name": attempt.event_name,
            "status": attempt.status,
            "reason": (reason or "")[:200],
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )

    return {
        "phase": "6P",
        "archived": True,
        "attempt": _serialize_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_6P_WARNING],
        "nextAction": "attempt_archived",
    }


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase6p_paid_status_mutation_attempts(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpaySandboxPaidStatusMutationAttempt.objects.all().order_by(
        "-created_at"
    )
    Status = RazorpaySandboxPaidStatusMutationAttempt.Status
    counts = {
        "prepared": qs.filter(status=Status.PREPARED).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
        "executed": qs.filter(status=Status.EXECUTED).count(),
        "rolledBack": qs.filter(status=Status.ROLLED_BACK).count(),
        "failed": qs.filter(status=Status.FAILED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        # Lifecycle counters — track every attempt that has ever been
        # executed / rolled back, regardless of current status. After a
        # rollback the row's `status` flips to `rolled_back`, so the
        # status-only `executed` count drops back to zero. These
        # timestamp-derived counters preserve the lifecycle history.
        "everExecuted": qs.filter(executed_at__isnull=False).count(),
        "everRolledBack": qs.filter(rolled_back_at__isnull=False).count(),
        "businessMutationWasMade": qs.filter(
            business_mutation_was_made=True
        ).count(),
        "realOrderMutationWasMade": qs.filter(
            real_order_mutation_was_made=True
        ).count(),
        "realPaymentMutationWasMade": qs.filter(
            real_payment_mutation_was_made=True
        ).count(),
        "customerNotificationSent": qs.filter(
            customer_notification_sent=True
        ).count(),
        "providerCallAttempted": qs.filter(provider_call_attempted=True).count(),
    }
    sample = [_serialize_attempt(row) for row in qs[: max(1, min(limit, 200))]]

    ledger_qs = RazorpaySandboxPaidStatusLedger.objects.all().order_by(
        "-created_at"
    )
    ledger_counts = {
        "totalLedgers": ledger_qs.count(),
        "rolledBackLedgers": ledger_qs.filter(rolled_back=True).count(),
        "businessMutationWasMade": ledger_qs.filter(
            business_mutation_was_made=True
        ).count(),
        "realOrderMutationWasMade": ledger_qs.filter(
            real_order_mutation_was_made=True
        ).count(),
        "realPaymentMutationWasMade": ledger_qs.filter(
            real_payment_mutation_was_made=True
        ).count(),
        "customerNotificationSent": ledger_qs.filter(
            customer_notification_sent=True
        ).count(),
        "providerCallAttempted": ledger_qs.filter(
            provider_call_attempted=True
        ).count(),
    }
    ledger_sample = [
        _serialize_ledger(row) for row in ledger_qs[: max(1, min(limit, 200))]
    ]

    return {
        "counts": counts,
        "items": sample,
        "ledgerCounts": ledger_counts,
        "ledgerItems": ledger_sample,
    }


def inspect_phase6p_paid_status_mutation_readiness() -> dict[str, Any]:
    """Read-only readiness composition. Never mutates anything."""
    flag_enabled = bool(
        getattr(
            settings, "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED", False
        )
    )
    summary = summarize_phase6p_paid_status_mutation_attempts()
    counts = summary["counts"]
    ledger_counts = summary["ledgerCounts"]

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6P_WARNING]

    for key in (
        "businessMutationWasMade",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "customerNotificationSent",
        "providerCallAttempted",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_6p_attempt_{key}_observed_must_be_zero"
            )
        if ledger_counts.get(key, 0) > 0:
            blockers.append(
                f"phase_6p_ledger_{key}_observed_must_be_zero"
            )

    approved_review_count = (
        RazorpaySandboxStatusReview.objects.filter(
            status=RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
        ).count()
    )

    safe_to_start_phase_6q = bool(
        not blockers
        and counts["everExecuted"] >= 1
        and counts["everRolledBack"] >= 1
    )

    if blockers:
        next_action = "fix_phase_6p_safety_blockers"
    elif approved_review_count == 0:
        next_action = (
            "approve_at_least_one_phase6o_review_before_running_phase_6p"
        )
    elif counts["everExecuted"] == 0:
        next_action = (
            "run_phase_6p_execute_via_cli_with_confirmation_and_signoff"
        )
    elif counts["everRolledBack"] == 0:
        next_action = (
            "rollback_at_least_one_executed_phase_6p_attempt_via_cli"
        )
    else:
        next_action = (
            "ready_for_phase_6q_payment_to_order_workflow_safety_gate"
        )

    return {
        "phase": "6P",
        "status": "sandbox_ledger_only",
        "latestCompletedPhase": "6O",
        "nextPhase": "6Q",
        "razorpaySandboxPaidStatusMutationEnabled": flag_enabled,
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "providerCallAttempted": False,
        "rawPayloadStorageEnabled": False,
        "approvedPhase6OReviewCount": approved_review_count,
        "attemptCounts": counts,
        "ledgerCounts": ledger_counts,
        "eventMappings": build_phase6p_paid_status_mapping(),
        "safetyInvariants": _safety_invariants(),
        "forbiddenActions": list(PHASE_6P_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "maxSafeAmountPaise": PHASE_6O_MAX_SAFE_AMOUNT_PAISE,
        "safeToStartPhase6Q": safe_to_start_phase_6q,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentAttempts": summary["items"][:10],
        "recentLedgers": summary["ledgerItems"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("attemptCounts") or {}
    ledger_counts = report.get("ledgerCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 6P sandbox paid-status mutation readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6P",
            "razorpay_sandbox_paid_status_mutation_enabled": bool(
                report.get("razorpaySandboxPaidStatusMutationEnabled")
            ),
            "approved_review_count": int(
                report.get("approvedPhase6OReviewCount") or 0
            ),
            "attempts_executed": int(counts.get("executed") or 0),
            "attempts_rolled_back": int(counts.get("rolledBack") or 0),
            "ledger_total": int(ledger_counts.get("totalLedgers") or 0),
            "safe_to_start_phase_6q": bool(report.get("safeToStartPhase6Q")),
            "real_order_mutation_was_made": False,
            "real_payment_mutation_was_made": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
            "provider_call_attempted": False,
        },
    )


__all__ = (
    "PHASE_6P_WARNING",
    "PHASE_6P_FORBIDDEN_ACTIONS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_ATTEMPT_PREPARED",
    "AUDIT_KIND_EXECUTION_BLOCKED",
    "AUDIT_KIND_EXECUTED",
    "AUDIT_KIND_ROLLED_BACK",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase6PEligibility",
    "build_phase6p_paid_status_mapping",
    "validate_phase6p_review_eligibility",
    "preview_phase6p_paid_status_mutation",
    "prepare_phase6p_paid_status_mutation_attempt",
    "execute_phase6p_paid_status_mutation_attempt",
    "rollback_phase6p_paid_status_mutation_attempt",
    "archive_phase6p_paid_status_mutation_attempt",
    "summarize_phase6p_paid_status_mutation_attempts",
    "inspect_phase6p_paid_status_mutation_readiness",
    "assert_phase6p_no_real_business_mutation",
    "emit_readiness_inspected_audit",
)
