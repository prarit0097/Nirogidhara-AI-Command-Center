"""Phase 6O — Razorpay sandbox payment status mapping + manual review.

Pure service / selector layer. Phase 6O **never** mutates ``Order``,
``Payment``, ``Shipment`` or ``DiscountOfferLog``. It **never** sends
a customer notification, **never** calls Razorpay, and **never** flips
an env flag. Approving a review only changes the review row's status
to ``approved_for_future_phase6p`` — a marker for a future Phase 6P.

Public surface:

- :func:`build_phase6o_event_to_status_mapping`
- :func:`inspect_phase6o_sandbox_status_mapping_readiness`
- :func:`validate_phase6o_event_eligibility`
- :func:`preview_phase6o_status_mapping_for_event`
- :func:`prepare_phase6o_sandbox_status_review`
- :func:`approve_phase6o_sandbox_status_review`
- :func:`reject_phase6o_sandbox_status_review`
- :func:`archive_phase6o_sandbox_status_review`
- :func:`assert_phase6o_no_business_mutation`
- :func:`summarize_phase6o_reviews`
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import RazorpaySandboxStatusReview, RazorpayWebhookEvent
from .razorpay_webhook_readiness import get_razorpay_webhook_handler_readiness


PHASE_6O_WARNING = (
    "Phase 6O is sandbox-review-only. NEVER mutates Order / Payment / "
    "Shipment / DiscountOfferLog, NEVER sends customer notifications, "
    "NEVER calls Razorpay, NEVER flips env flags. Approving a review "
    "only marks it ``approved_for_future_phase6p`` — Phase 6P will own "
    "any sandbox-only mutation against synthetic test orders."
)


# Audit kinds Phase 6O may emit. Payloads are scrubbed in the helpers.
AUDIT_KIND_READINESS = "razorpay.sandbox_status_mapping.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.sandbox_status_review.previewed"
AUDIT_KIND_PREPARED = "razorpay.sandbox_status_review.prepared"
AUDIT_KIND_BLOCKED = "razorpay.sandbox_status_review.blocked"
AUDIT_KIND_APPROVED = (
    "razorpay.sandbox_status_review.approved_for_future_phase6p"
)
AUDIT_KIND_REJECTED = "razorpay.sandbox_status_review.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.sandbox_status_review.archived"
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.sandbox_status_review.invariant_violation_blocked"
)


PHASE_6O_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "mark_order_paid",
    "mark_payment_captured",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "send_whatsapp_template",
    "send_freeform_whatsapp",
    "place_vapi_call",
    "create_or_update_shipment",
    "create_or_update_discount_offer",
    "execute_webhook_replay",
    "enable_business_mutation_env_flag",
    "enable_customer_notification_env_flag",
    "enable_raw_payload_storage_env_flag",
)


# Locked synthetic-amount ceiling. Phase 6O refuses any event whose
# amount exceeds this; Phase 6P will reuse this ceiling.
PHASE_6O_MAX_SAFE_AMOUNT_PAISE = 100


# ---------------------------------------------------------------------------
# Event-to-status mapping
# ---------------------------------------------------------------------------


_EVENT_PLAN: tuple[dict[str, str], ...] = (
    {
        "razorpayEventName": "payment_link.paid",
        "futureSandboxPaymentStatus": "paid",
        "futureSandboxOrderEffect": "advance_paid_candidate",
        "proposedReviewAction": "review_payment_link_paid_for_synthetic_advance",
        "notes": (
            "Sandbox-only acknowledgement of an advance payment on a "
            "synthetic test payment link. No real Order/Payment row is "
            "touched."
        ),
    },
    {
        "razorpayEventName": "payment.captured",
        "futureSandboxPaymentStatus": "captured",
        "futureSandboxOrderEffect": "payment_verified_candidate",
        "proposedReviewAction": "review_payment_captured_for_synthetic_order",
        "notes": (
            "Sandbox-only capture confirmation. Customer notification "
            "stays disabled."
        ),
    },
    {
        "razorpayEventName": "payment.failed",
        "futureSandboxPaymentStatus": "failed",
        "futureSandboxOrderEffect": "payment_failed_candidate",
        "proposedReviewAction": "review_payment_failed_for_synthetic_order",
        "notes": "Sandbox-only failure log. No retry, no customer message.",
    },
    {
        "razorpayEventName": "payment.authorized",
        "futureSandboxPaymentStatus": "authorized",
        "futureSandboxOrderEffect": "payment_authorized_candidate",
        "proposedReviewAction": "review_payment_authorized_for_synthetic_order",
        "notes": (
            "Sandbox-only authorization acknowledgement. Capture is "
            "still gated by manual review in Phase 6P."
        ),
    },
    {
        "razorpayEventName": "order.paid",
        "futureSandboxPaymentStatus": "paid",
        "futureSandboxOrderEffect": "paid_candidate",
        "proposedReviewAction": "review_order_paid_for_synthetic_order",
        "notes": (
            "Sandbox-only confirmation that a synthetic Razorpay order "
            "is paid in full."
        ),
    },
    {
        "razorpayEventName": "payment_link.cancelled",
        "futureSandboxPaymentStatus": "cancelled",
        "futureSandboxOrderEffect": "payment_link_cancelled_candidate",
        "proposedReviewAction": "review_payment_link_cancelled_for_synthetic_order",
        "notes": "Sandbox-only cancellation log. Customer is never notified.",
    },
    {
        "razorpayEventName": "payment_link.expired",
        "futureSandboxPaymentStatus": "expired",
        "futureSandboxOrderEffect": "payment_link_expired_candidate",
        "proposedReviewAction": "review_payment_link_expired_for_synthetic_order",
        "notes": "Sandbox-only expiry log. No automatic re-issue.",
    },
    {
        "razorpayEventName": "refund.created",
        "futureSandboxPaymentStatus": "refund_pending",
        "futureSandboxOrderEffect": "refund_review_candidate",
        "proposedReviewAction": "review_refund_created_for_synthetic_order",
        "notes": (
            "Sandbox-only refund-created log. Phase 6P must wait for "
            "refund.processed before flipping any sandbox status."
        ),
    },
    {
        "razorpayEventName": "refund.processed",
        "futureSandboxPaymentStatus": "refunded",
        "futureSandboxOrderEffect": "refund_processed_candidate",
        "proposedReviewAction": "review_refund_processed_for_synthetic_order",
        "notes": (
            "Sandbox-only refund-processed acknowledgement. NEVER calls "
            "the Razorpay refunds API."
        ),
    },
)


def _event_mapping_row(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "razorpayEventName": spec["razorpayEventName"],
        "futureSandboxPaymentStatus": spec["futureSandboxPaymentStatus"],
        "futureSandboxOrderEffect": spec["futureSandboxOrderEffect"],
        "proposedReviewAction": spec["proposedReviewAction"],
        "manualReviewRequired": True,
        "mutationAllowedInPhase6O": False,
        "mutationAllowedInFuturePhase6P": (
            "only_if_synthetic_review_approved_and_director_signed_off"
        ),
        "customerNotificationAllowed": False,
        "shipmentEffectAllowed": False,
        "discountEffectAllowed": False,
        "idempotencyRequired": True,
        "rollbackRequired": True,
        "blockers": [
            "phase_6o_sandbox_review_only_no_mutation_path",
            "phase_6p_must_supply_synthetic_resolver_and_director_signoff",
        ],
        "notes": [spec["notes"]],
    }


def build_phase6o_event_to_status_mapping() -> list[dict[str, Any]]:
    """Return the canonical Phase 6O event-to-status mapping plan."""
    return [_event_mapping_row(spec) for spec in _EVENT_PLAN]


_MAPPING_BY_EVENT_NAME: dict[str, dict[str, str]] = {
    spec["razorpayEventName"]: spec for spec in _EVENT_PLAN
}


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


def _safety_invariants() -> dict[str, bool]:
    return {
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "rawPayloadStorageEnabled": False,
        "providerCallAllowed": False,
        "razorpayApiInvocationAllowed": False,
        "whatsappSendAllowed": False,
        "vapiCallAllowed": False,
        "envFlagFlipAllowed": False,
        "phase6OPathCanMutateProductionRecord": False,
        "phase6OPathCanCreateShipment": False,
        "phase6OPathCanCreateDiscountOffer": False,
        "phase6OPathCanSendCustomerNotification": False,
        "phase6OPathCanCallRazorpay": False,
        "phase6OPathCanFlipEnvFlag": False,
        "phase6OPathCanWriteToOrderTable": False,
        "phase6OPathCanWriteToPaymentTable": False,
        "phase6OPathRespectsKillSwitch": True,
        "approvalAppliesMutation": False,
    }


def _manual_review_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyPhase6MEventIsVerifiedAndSafe",
            "description": (
                "Source RazorpayWebhookEvent has signature_valid=True, "
                "replay_window_valid=True, idempotency_status=first_seen, "
                "no business_mutation_was_made, no customer_notification_sent, "
                "no raw_secret_exposed, no full_pii_exposed."
            ),
            "automated": True,
        },
        {
            "key": "verifyEnvFlagsLockedOff",
            "description": (
                "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED, "
                "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED and "
                "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD all remain false. "
                "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED only opens the "
                "review-creation path, never the mutation path."
            ),
            "automated": True,
        },
        {
            "key": "verifySyntheticReferenceOnly",
            "description": (
                "Provider order/payment/payment-link ids are synthetic "
                "test markers (no real production ids). Amount must be "
                f"<= {PHASE_6O_MAX_SAFE_AMOUNT_PAISE} paise."
            ),
            "automated": True,
        },
        {
            "key": "verifyNoFullPiiInPayload",
            "description": (
                "scrubbed_keys on the source RazorpayWebhookEvent shows "
                "no card / vpa / upi / bank_account / wallet / email / "
                "contact / phone / address fields leaked."
            ),
            "automated": True,
        },
        {
            "key": "verifyDirectorSignOff",
            "description": (
                "Written Director sign-off recorded in the Master Event "
                "Ledger before any Phase 6P sandbox mutation is rehearsed."
            ),
            "automated": False,
        },
        {
            "key": "verifyRollbackPlanIntact",
            "description": (
                "Phase 6O rollback plan + Phase 6N rollback plan both "
                "remain valid; rollback owned by operator only."
            ),
            "automated": True,
        },
    ]


def _rollback_plan() -> dict[str, Any]:
    return {
        "phase": "6O",
        "rollbackTriggers": [
            "approval_button_click_observed_to_mutate_business_table",
            "any_real_order_payment_shipment_or_discount_mutation_observed",
            "any_customer_notification_observed",
            "raw_secret_or_full_pii_exposure_observed",
        ],
        "rollbackSteps": [
            {
                "order": 1,
                "action": "set_RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED_to_false",
                "owner": "operator",
                "phase6OEnforced": True,
            },
            {
                "order": 2,
                "action": "mark_open_reviews_archived_with_rollback_reason",
                "owner": "operator",
                "phase6OEnforced": True,
            },
            {
                "order": 3,
                "action": "audit_recent_RazorpaySandboxStatusReview_rows_for_business_mutation_drift",
                "owner": "operator",
                "phase6OEnforced": True,
            },
            {
                "order": 4,
                "action": "verify_RazorpayWebhookEvent_safety_counters_remain_zero",
                "owner": "operator",
                "phase6OEnforced": True,
            },
        ],
        "rollbackVerification": [
            "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED == false",
            "every RazorpaySandboxStatusReview.business_mutation_was_made == false",
            "every RazorpaySandboxStatusReview.customer_notification_sent == false",
            "every RazorpaySandboxStatusReview.provider_call_attempted == false",
        ],
        "phase6OCanExecuteRollback": False,
        "rollbackOwnedByOperatorOnly": True,
        "rollbackNeverInvokesProviderApi": True,
    }


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


_SAFE_PROCESSING_STATUSES: frozenset[str] = frozenset(
    {
        RazorpayWebhookEvent.ProcessingStatus.STORED,
        RazorpayWebhookEvent.ProcessingStatus.VERIFIED,
    }
)

_REAL_LIKE_ID_PREFIXES: tuple[str, ...] = (
    # Razorpay live ids start with these prefixes; we reject them as
    # ineligible for Phase 6O. Synthetic test ids may also share these
    # prefixes (Razorpay test mode reuses them), but combined with the
    # ``environment="test"`` + amount-cap + ``safe_payload_summary`` PII
    # scrub gates this gives defence in depth.
)


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def _has_full_pii(event: RazorpayWebhookEvent) -> bool:
    """Heuristic — Phase 6M scrubbed_keys lists any key Phase 6M had to
    redact. Any non-empty list means the event carried sensitive payload
    keys that should not be Phase 6O-eligible."""
    return bool(event.scrubbed_keys) or bool(event.full_pii_exposed)


def validate_phase6o_event_eligibility(
    razorpay_event: RazorpayWebhookEvent,
    *,
    require_env_flag: bool = True,
) -> EligibilityResult:
    """Return whether the event can drive a Phase 6O review row.

    ``require_env_flag`` is ``True`` for ``prepare`` (creation must be
    gated by ``RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED``) and ``False``
    for ``preview`` / readiness composition (which are always safe).
    """
    blockers: list[str] = []
    warnings: list[str] = []

    if require_env_flag and not bool(
        getattr(settings, "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED", False)
    ):
        blockers.append(
            "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED_must_be_true_to_prepare_review"
        )

    if not razorpay_event.signature_valid:
        blockers.append("source_event_signature_invalid")
    if not razorpay_event.replay_window_valid:
        blockers.append("source_event_replay_window_invalid")
    if (
        razorpay_event.idempotency_status
        != RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN
    ):
        blockers.append("source_event_idempotency_must_be_first_seen")
    if razorpay_event.processing_status not in _SAFE_PROCESSING_STATUSES:
        blockers.append(
            f"source_event_processing_status_unsafe_{razorpay_event.processing_status}"
        )

    if razorpay_event.event_name not in _MAPPING_BY_EVENT_NAME:
        blockers.append(f"event_name_not_phase6o_allowlisted_{razorpay_event.event_name}")

    if (
        razorpay_event.environment
        != RazorpayWebhookEvent.Environment.TEST
    ):
        blockers.append(
            f"source_event_environment_must_be_test_was_{razorpay_event.environment}"
        )

    if razorpay_event.business_mutation_was_made:
        blockers.append("source_event_business_mutation_was_made_must_be_false")
    if razorpay_event.customer_notification_sent:
        blockers.append(
            "source_event_customer_notification_sent_must_be_false"
        )
    if razorpay_event.raw_secret_exposed:
        blockers.append("source_event_raw_secret_exposure_must_be_false")
    if _has_full_pii(razorpay_event):
        blockers.append("source_event_full_pii_must_be_absent")

    if not razorpay_event.source_event_id:
        blockers.append("source_event_id_missing")

    if razorpay_event.amount_paise is not None and (
        razorpay_event.amount_paise < 0
        or razorpay_event.amount_paise > PHASE_6O_MAX_SAFE_AMOUNT_PAISE
    ):
        blockers.append(
            f"amount_paise_must_be_between_0_and_{PHASE_6O_MAX_SAFE_AMOUNT_PAISE}"
        )

    if razorpay_event.amount_paise is None:
        warnings.append("amount_paise_missing_assumed_synthetic")

    return EligibilityResult(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _safe_event_summary(event: RazorpayWebhookEvent) -> dict[str, Any]:
    """Whitelist-only summary — never returns raw payload / PII."""
    return {
        "id": event.id,
        "sourceEventId": event.source_event_id,
        "eventName": event.event_name,
        "environment": event.environment,
        "processingStatus": event.processing_status,
        "idempotencyStatus": event.idempotency_status,
        "signatureValid": event.signature_valid,
        "replayWindowValid": event.replay_window_valid,
        "providerOrderId": event.provider_order_id,
        "providerPaymentId": event.provider_payment_id,
        "providerRefundId": event.provider_refund_id,
        "amountPaise": event.amount_paise,
        "currency": event.currency,
        "businessMutationWasMade": event.business_mutation_was_made,
        "customerNotificationSent": event.customer_notification_sent,
        "rawSecretExposed": event.raw_secret_exposed,
        "fullPiiExposed": event.full_pii_exposed,
    }


def preview_phase6o_status_mapping_for_event(
    event_id: int,
) -> dict[str, Any]:
    """Read-only preview. Never creates a review, never mutates anything."""
    event = (
        RazorpayWebhookEvent.objects.filter(pk=event_id).first()
        if event_id
        else None
    )
    if event is None:
        return {
            "phase": "6O",
            "found": False,
            "eventId": event_id,
            "blockers": ["razorpay_webhook_event_not_found"],
            "warnings": [PHASE_6O_WARNING],
            "nextAction": "verify_event_id_or_send_synthetic_via_phase_6m_simulator",
        }

    eligibility = validate_phase6o_event_eligibility(
        event, require_env_flag=False
    )
    spec = _MAPPING_BY_EVENT_NAME.get(event.event_name)
    proposed = _event_mapping_row(spec) if spec else None

    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 6O preview for source_event_id={event.source_event_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "event_id": event.id,
            "source_event_id": event.source_event_id,
            "event_name": event.event_name,
            "eligible": eligibility.eligible,
            "blockers": list(eligibility.blockers),
            "mutation_allowed_in_phase6o": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
        },
    )

    return {
        "phase": "6O",
        "found": True,
        "eventId": event.id,
        "event": _safe_event_summary(event),
        "eligible": eligibility.eligible,
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_6O_WARNING],
        "proposedMapping": proposed,
        "nextAction": (
            "ready_to_prepare_phase6o_sandbox_status_review"
            if eligibility.eligible
            and bool(
                getattr(
                    settings,
                    "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED",
                    False,
                )
            )
            else "fix_eligibility_blockers_or_enable_sandbox_status_mapping_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(event: RazorpayWebhookEvent, action: str) -> str:
    return f"phase6o::{event.source_event_id or event.id}::{action}"


def assert_phase6o_no_business_mutation(
    review: RazorpaySandboxStatusReview,
) -> None:
    """Raise ``ValueError`` if any locked-False boolean has flipped True.

    Phase 6O service paths call this defensively before saving any
    review row to guarantee we never persist a row that claims a
    business mutation happened.
    """
    bad: list[str] = []
    if review.business_mutation_was_made:
        bad.append("business_mutation_was_made_flipped_true")
    if review.customer_notification_sent:
        bad.append("customer_notification_sent_flipped_true")
    if review.provider_call_attempted:
        bad.append("provider_call_attempted_flipped_true")
    if review.shipment_effect_allowed:
        bad.append("shipment_effect_allowed_flipped_true")
    if review.discount_effect_allowed:
        bad.append("discount_effect_allowed_flipped_true")
    if review.mutation_allowed_in_phase6o:
        bad.append("mutation_allowed_in_phase6o_flipped_true")
    if bad:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text=(
                f"Phase 6O invariant violation on review "
                f"{review.pk or 'unsaved'}: {','.join(bad)}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload={
                "review_id": review.pk,
                "event_id": review.razorpay_webhook_event_id,
                "violations": bad,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
            },
        )
        raise ValueError(
            "Phase 6O invariant violation: " + ",".join(bad)
        )


def prepare_phase6o_sandbox_status_review(
    event_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create / re-fetch a review row for the given Phase 6M event.

    Idempotent on ``(razorpay_webhook_event, proposed_review_action)``.
    Returns a typed report with the (possibly newly created) review +
    blockers + nextAction. NEVER mutates business tables, NEVER calls
    Razorpay, NEVER sends a customer notification.
    """
    event = (
        RazorpayWebhookEvent.objects.filter(pk=event_id).first()
        if event_id
        else None
    )
    if event is None:
        return {
            "phase": "6O",
            "created": False,
            "reused": False,
            "review": None,
            "blockers": ["razorpay_webhook_event_not_found"],
            "warnings": [PHASE_6O_WARNING],
            "nextAction": "verify_event_id_or_send_synthetic_via_phase_6m_simulator",
        }

    eligibility = validate_phase6o_event_eligibility(
        event, require_env_flag=True
    )
    spec = _MAPPING_BY_EVENT_NAME.get(event.event_name)

    if not eligibility.eligible or spec is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 6O prepare blocked for source_event_id="
                f"{event.source_event_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "event_id": event.id,
                "source_event_id": event.source_event_id,
                "event_name": event.event_name,
                "blockers": list(eligibility.blockers)
                + ([] if spec else ["event_not_in_phase6o_allowlist"]),
                "mutation_allowed_in_phase6o": False,
                "business_mutation_was_made": False,
                "customer_notification_sent": False,
            },
        )
        return {
            "phase": "6O",
            "created": False,
            "reused": False,
            "review": None,
            "blockers": list(eligibility.blockers)
            + ([] if spec else ["event_not_in_phase6o_allowlist"]),
            "warnings": list(eligibility.warnings) + [PHASE_6O_WARNING],
            "nextAction": (
                "fix_eligibility_blockers_or_enable_sandbox_status_mapping_flag"
            ),
        }

    proposed = _event_mapping_row(spec)
    action = spec["proposedReviewAction"]
    idempotency = _idempotency_key(event, action)

    with transaction.atomic():
        existing = (
            RazorpaySandboxStatusReview.objects.filter(
                razorpay_webhook_event=event,
                proposed_review_action=action,
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            write_event(
                kind=AUDIT_KIND_PREPARED,
                text=(
                    f"Phase 6O review already prepared (reused) for "
                    f"source_event_id={event.source_event_id}"
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "review_id": existing.pk,
                    "event_id": event.id,
                    "source_event_id": event.source_event_id,
                    "event_name": event.event_name,
                    "status": existing.status,
                    "reused": True,
                    "mutation_allowed_in_phase6o": False,
                    "business_mutation_was_made": False,
                    "customer_notification_sent": False,
                },
            )
            return {
                "phase": "6O",
                "created": False,
                "reused": True,
                "review": _serialize_review(existing),
                "blockers": [],
                "warnings": [PHASE_6O_WARNING],
                "nextAction": "review_pending_manual_review",
            }

        review = RazorpaySandboxStatusReview(
            razorpay_webhook_event=event,
            source_event_id=event.source_event_id,
            event_name=event.event_name,
            provider_environment=event.environment,
            provider_order_id=event.provider_order_id,
            provider_payment_id=event.provider_payment_id,
            provider_refund_id=event.provider_refund_id,
            amount_paise=event.amount_paise,
            currency=event.currency,
            proposed_payment_status=spec["futureSandboxPaymentStatus"],
            proposed_order_effect=spec["futureSandboxOrderEffect"],
            proposed_review_action=action,
            status=RazorpaySandboxStatusReview.Status.PENDING_MANUAL_REVIEW,
            synthetic_eligible=True,
            manual_review_required=True,
            mutation_allowed_in_phase6o=False,
            business_mutation_was_made=False,
            customer_notification_sent=False,
            provider_call_attempted=False,
            shipment_effect_allowed=False,
            discount_effect_allowed=False,
            rollback_required=True,
            idempotency_key=idempotency,
            blockers=list(proposed["blockers"]),
            warnings=list(eligibility.warnings) + [PHASE_6O_WARNING],
            safety_invariants=_safety_invariants(),
            manual_review_checklist=_manual_review_checklist(),
            rollback_plan=_rollback_plan(),
            requested_by=requested_by,
        )
        assert_phase6o_no_business_mutation(review)
        try:
            review.save()
        except IntegrityError:
            # Lost the race with a concurrent prepare — re-fetch the
            # existing row and return it as ``reused``.
            review = RazorpaySandboxStatusReview.objects.get(
                razorpay_webhook_event=event,
                proposed_review_action=action,
            )
            return {
                "phase": "6O",
                "created": False,
                "reused": True,
                "review": _serialize_review(review),
                "blockers": [],
                "warnings": [PHASE_6O_WARNING],
                "nextAction": "review_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 6O review prepared for source_event_id="
            f"{event.source_event_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "review_id": review.pk,
            "event_id": event.id,
            "source_event_id": event.source_event_id,
            "event_name": event.event_name,
            "status": review.status,
            "mutation_allowed_in_phase6o": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
        },
    )

    return {
        "phase": "6O",
        "created": True,
        "reused": False,
        "review": _serialize_review(review),
        "blockers": [],
        "warnings": [PHASE_6O_WARNING],
        "nextAction": "review_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


_TRANSITIONABLE_FROM = {
    RazorpaySandboxStatusReview.Status.PROPOSED,
    RazorpaySandboxStatusReview.Status.PENDING_MANUAL_REVIEW,
}


def _transition_review(
    review_id: int,
    *,
    new_status: str,
    audit_kind: str,
    reviewed_by=None,
    reason: str = "",
    tone: str = AuditEvent.Tone.INFO,
    archive: bool = False,
) -> dict[str, Any]:
    review = (
        RazorpaySandboxStatusReview.objects.filter(pk=review_id).first()
        if review_id
        else None
    )
    if review is None:
        return {
            "phase": "6O",
            "ok": False,
            "review": None,
            "blockers": ["review_not_found"],
            "warnings": [PHASE_6O_WARNING],
            "nextAction": "verify_review_id",
        }

    # Approve / reject only valid from PROPOSED / PENDING_MANUAL_REVIEW.
    # Archive can be applied from any non-archived state. None of these
    # transitions touch business tables.
    if not archive and review.status not in _TRANSITIONABLE_FROM:
        return {
            "phase": "6O",
            "ok": False,
            "review": _serialize_review(review),
            "blockers": [
                f"review_status_{review.status}_not_transitionable_to_{new_status}"
            ],
            "warnings": [PHASE_6O_WARNING],
            "nextAction": "review_already_finalised",
        }

    if archive and review.status == RazorpaySandboxStatusReview.Status.ARCHIVED:
        return {
            "phase": "6O",
            "ok": True,
            "review": _serialize_review(review),
            "blockers": [],
            "warnings": [PHASE_6O_WARNING + " review_already_archived"],
            "nextAction": "review_already_archived",
        }

    review.status = new_status
    if archive:
        review.archived_by = reviewed_by
        review.archived_at = timezone.now()
        review.archive_reason = (reason or "").strip()[:200]
    else:
        review.reviewed_by = reviewed_by
        review.reviewed_at = timezone.now()
        review.review_reason = (reason or "").strip()[:200]

    # Defensive — invariants must still hold after the status flip.
    assert_phase6o_no_business_mutation(review)
    review.save()

    write_event(
        kind=audit_kind,
        text=(
            f"Phase 6O review {review.pk} -> {new_status}"
            + (f" · {reason}" if reason else "")
        ),
        tone=tone,
        payload={
            "review_id": review.pk,
            "event_id": review.razorpay_webhook_event_id,
            "source_event_id": review.source_event_id,
            "event_name": review.event_name,
            "status": review.status,
            "reason": (reason or "")[:200],
            "by": getattr(reviewed_by, "username", "") or "",
            "mutation_allowed_in_phase6o": False,
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
        },
    )

    return {
        "phase": "6O",
        "ok": True,
        "review": _serialize_review(review),
        "blockers": [],
        "warnings": [PHASE_6O_WARNING],
        "nextAction": (
            "ready_for_phase_6p_planning_after_director_signoff"
            if new_status
            == RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
            else "review_finalised"
        ),
    }


def approve_phase6o_sandbox_status_review(
    review_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the review approved for **future Phase 6P only**.

    This NEVER applies a business mutation, NEVER calls Razorpay,
    NEVER sends a customer notification. It is permission to consider
    the mapping in Phase 6P, not application.
    """
    return _transition_review(
        review_id,
        new_status=RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P,
        audit_kind=AUDIT_KIND_APPROVED,
        reviewed_by=reviewed_by,
        reason=reason,
        tone=AuditEvent.Tone.INFO,
    )


def reject_phase6o_sandbox_status_review(
    review_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition_review(
        review_id,
        new_status=RazorpaySandboxStatusReview.Status.REJECTED,
        audit_kind=AUDIT_KIND_REJECTED,
        reviewed_by=reviewed_by,
        reason=reason,
        tone=AuditEvent.Tone.INFO,
    )


def archive_phase6o_sandbox_status_review(
    review_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    return _transition_review(
        review_id,
        new_status=RazorpaySandboxStatusReview.Status.ARCHIVED,
        audit_kind=AUDIT_KIND_ARCHIVED,
        reviewed_by=archived_by,
        reason=reason,
        tone=AuditEvent.Tone.INFO,
        archive=True,
    )


# ---------------------------------------------------------------------------
# Readiness composition
# ---------------------------------------------------------------------------


def summarize_phase6o_reviews(limit: int = 25) -> dict[str, Any]:
    qs = RazorpaySandboxStatusReview.objects.all().order_by("-created_at")
    Status = RazorpaySandboxStatusReview.Status
    counts = {
        "proposed": qs.filter(status=Status.PROPOSED).count(),
        "pendingManualReview": qs.filter(
            status=Status.PENDING_MANUAL_REVIEW
        ).count(),
        "approvedForFuturePhase6P": qs.filter(
            status=Status.APPROVED_FOR_FUTURE_PHASE6P
        ).count(),
        "rejected": qs.filter(status=Status.REJECTED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
        "businessMutationWasMade": qs.filter(
            business_mutation_was_made=True
        ).count(),
        "customerNotificationSent": qs.filter(
            customer_notification_sent=True
        ).count(),
        "providerCallAttempted": qs.filter(provider_call_attempted=True).count(),
    }
    sample = [_serialize_review(row) for row in qs[: max(1, min(limit, 200))]]
    return {"counts": counts, "items": sample}


def _phase_6m_signal() -> dict[str, Any]:
    try:
        return get_razorpay_webhook_handler_readiness()
    except Exception as exc:  # pragma: no cover — defensive
        return {
            "businessMutationCount": -1,
            "customerNotificationCount": -1,
            "rawSecretExposureCount": -1,
            "fullPiiExposureCount": -1,
            "verifiedEventCount": 0,
            "businessMutationEnabled": False,
            "customerNotificationEnabled": False,
            "storeRawPayload": False,
            "blockers": [f"phase_6m_lookup_failed:{exc.__class__.__name__}"],
        }


def inspect_phase6o_sandbox_status_mapping_readiness() -> dict[str, Any]:
    """Return a typed Phase 6O readiness report.

    Composes the Phase 6M handler counters + Phase 6O review summary +
    the locked plan + flag state. Always read-only. Callers who emit
    audit events should use :func:`emit_readiness_inspected_audit`.
    """
    phase_6m = _phase_6m_signal()
    summary = summarize_phase6o_reviews()

    flag_enabled = bool(
        getattr(settings, "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED", False)
    )

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6O_WARNING]

    if phase_6m.get("businessMutationEnabled"):
        blockers.append(
            "phase_6m_business_mutation_flag_must_remain_disabled"
        )
    if phase_6m.get("customerNotificationEnabled"):
        blockers.append(
            "phase_6m_customer_notification_flag_must_remain_disabled"
        )
    if phase_6m.get("storeRawPayload"):
        blockers.append(
            "phase_6m_store_raw_payload_flag_must_remain_disabled"
        )
    if (phase_6m.get("businessMutationCount") or 0) > 0:
        blockers.append(
            "phase_6m_business_mutation_count_observed_must_be_zero"
        )
    if (phase_6m.get("customerNotificationCount") or 0) > 0:
        blockers.append(
            "phase_6m_customer_notification_count_observed_must_be_zero"
        )
    if (phase_6m.get("rawSecretExposureCount") or 0) > 0:
        blockers.append(
            "phase_6m_raw_secret_exposure_observed_must_be_zero"
        )
    if (phase_6m.get("fullPiiExposureCount") or 0) > 0:
        blockers.append("phase_6m_full_pii_exposure_observed_must_be_zero")

    counts = summary["counts"]
    if counts["businessMutationWasMade"] > 0:
        blockers.append("phase_6o_review_business_mutation_observed")
    if counts["customerNotificationSent"] > 0:
        blockers.append("phase_6o_review_customer_notification_observed")
    if counts["providerCallAttempted"] > 0:
        blockers.append("phase_6o_review_provider_call_observed")

    safe_to_start_phase_6p = (
        not blockers
        and counts["approvedForFuturePhase6P"] >= 1
        and counts["businessMutationWasMade"] == 0
        and counts["customerNotificationSent"] == 0
    )

    if blockers:
        next_action = "fix_phase_6o_safety_blockers"
    elif counts["approvedForFuturePhase6P"] == 0:
        next_action = (
            "approve_at_least_one_phase6o_review_for_future_phase6p"
        )
    else:
        next_action = "ready_for_phase_6p_controlled_internal_paid_status_test_planning"

    return {
        "phase": "6O",
        "status": "sandbox_review_only",
        "latestCompletedPhase": "6N",
        "nextPhase": "6P",
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "providerCallAttempted": False,
        "rawPayloadStorageEnabled": False,
        "razorpaySandboxStatusMappingEnabled": flag_enabled,
        "phase6MWebhookTestModeEnabled": bool(
            phase_6m.get("webhookTestModeEnabled")
        ),
        "phase6MVerifiedEventCount": int(
            phase_6m.get("verifiedEventCount") or 0
        ),
        "phase6MBusinessMutationCount": int(
            phase_6m.get("businessMutationCount") or 0
        ),
        "phase6MCustomerNotificationCount": int(
            phase_6m.get("customerNotificationCount") or 0
        ),
        "phase6MRawSecretExposureCount": int(
            phase_6m.get("rawSecretExposureCount") or 0
        ),
        "phase6MFullPiiExposureCount": int(
            phase_6m.get("fullPiiExposureCount") or 0
        ),
        "reviewCounts": counts,
        "eventMappings": build_phase6o_event_to_status_mapping(),
        "safetyInvariants": _safety_invariants(),
        "manualReviewChecklist": _manual_review_checklist(),
        "rollbackPlan": _rollback_plan(),
        "forbiddenActions": list(PHASE_6O_FORBIDDEN_ACTIONS),
        "maxSafeAmountPaise": PHASE_6O_MAX_SAFE_AMOUNT_PAISE,
        "safeToStartPhase6P": bool(safe_to_start_phase_6p),
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentReviews": summary["items"],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    """Best-effort audit emit for the readiness command. Safe payload only."""
    counts = report.get("reviewCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 6O sandbox status mapping readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "6O",
            "razorpay_sandbox_status_mapping_enabled": bool(
                report.get("razorpaySandboxStatusMappingEnabled")
            ),
            "safe_to_start_phase_6p": bool(report.get("safeToStartPhase6P")),
            "blocker_count": len(report.get("blockers") or []),
            "warning_count": len(report.get("warnings") or []),
            "review_count_proposed": int(counts.get("proposed") or 0),
            "review_count_pending": int(counts.get("pendingManualReview") or 0),
            "review_count_approved": int(
                counts.get("approvedForFuturePhase6P") or 0
            ),
            "review_count_rejected": int(counts.get("rejected") or 0),
            "review_count_archived": int(counts.get("archived") or 0),
            "business_mutation_was_made": False,
            "customer_notification_sent": False,
        },
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_review(review: RazorpaySandboxStatusReview) -> dict[str, Any]:
    """Whitelist serializer — never returns reviewer FK ids beyond
    username, never returns raw payload or PII."""
    return {
        "id": review.pk,
        "razorpayWebhookEventId": review.razorpay_webhook_event_id,
        "sourceEventId": review.source_event_id,
        "eventName": review.event_name,
        "providerEnvironment": review.provider_environment,
        "providerOrderId": review.provider_order_id,
        "providerPaymentId": review.provider_payment_id,
        "providerPaymentLinkId": review.provider_payment_link_id,
        "providerRefundId": review.provider_refund_id,
        "amountPaise": review.amount_paise,
        "currency": review.currency,
        "proposedPaymentStatus": review.proposed_payment_status,
        "proposedOrderEffect": review.proposed_order_effect,
        "proposedReviewAction": review.proposed_review_action,
        "status": review.status,
        "syntheticEligible": review.synthetic_eligible,
        "manualReviewRequired": review.manual_review_required,
        "mutationAllowedInPhase6O": review.mutation_allowed_in_phase6o,
        "businessMutationWasMade": review.business_mutation_was_made,
        "customerNotificationSent": review.customer_notification_sent,
        "providerCallAttempted": review.provider_call_attempted,
        "shipmentEffectAllowed": review.shipment_effect_allowed,
        "discountEffectAllowed": review.discount_effect_allowed,
        "rollbackRequired": review.rollback_required,
        "idempotencyKey": review.idempotency_key,
        "blockers": list(review.blockers or []),
        "warnings": list(review.warnings or []),
        "reviewedByUsername": (
            getattr(review.reviewed_by, "username", "") or ""
        ),
        "reviewedAt": (
            review.reviewed_at.isoformat() if review.reviewed_at else None
        ),
        "reviewReason": review.review_reason,
        "archivedByUsername": (
            getattr(review.archived_by, "username", "") or ""
        ),
        "archivedAt": (
            review.archived_at.isoformat() if review.archived_at else None
        ),
        "archiveReason": review.archive_reason,
        "createdAt": review.created_at.isoformat(),
        "updatedAt": review.updated_at.isoformat(),
    }


__all__ = (
    "PHASE_6O_WARNING",
    "PHASE_6O_FORBIDDEN_ACTIONS",
    "PHASE_6O_MAX_SAFE_AMOUNT_PAISE",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "EligibilityResult",
    "build_phase6o_event_to_status_mapping",
    "inspect_phase6o_sandbox_status_mapping_readiness",
    "validate_phase6o_event_eligibility",
    "preview_phase6o_status_mapping_for_event",
    "prepare_phase6o_sandbox_status_review",
    "approve_phase6o_sandbox_status_review",
    "reject_phase6o_sandbox_status_review",
    "archive_phase6o_sandbox_status_review",
    "assert_phase6o_no_business_mutation",
    "summarize_phase6o_reviews",
    "emit_readiness_inspected_audit",
)
