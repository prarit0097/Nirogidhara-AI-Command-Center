"""Phase 7E - Controlled Internal WhatsApp Notification Readiness Gate.

This service is **gate-only** and **CLI-only** for review state
changes. It produces an audit-only readiness contract that turns an
executed-and-rolled-back Phase 7D Razorpay TEST attempt into a future
Phase 7F (or future Phase 7E-Live) candidacy contract - WITHOUT
sending a WhatsApp message, WITHOUT queuing an outbound, WITHOUT
calling Meta Cloud / Delhivery / Vapi, WITHOUT creating a shipment /
AWB / payment link, WITHOUT capturing or refunding, WITHOUT mutating
real ``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` /
``Customer`` / ``Lead`` rows, and WITHOUT editing any ``.env*`` file.

Phase 7E approval flips the gate status to
``approved_for_future_phase7f_or_7e_send_review`` only. Live customer
notification still requires Phase 7F or a future Phase 7E-Live with
a fresh Director directive AND Phase 7D-Hotfix-1 (structured UTC
window guard on execute commands) must already have shipped.

Hard scope rule: this module **never** imports
``apps.whatsapp.services.send_freeform_text_message``,
``apps.whatsapp.services.send_queued_message``,
``apps.whatsapp.services.queue_template_message``,
``apps.whatsapp.integrations.whatsapp.meta_cloud_client``, or
``dotenv``. Asserted by static-file scan tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.saas.utc_window import (
    parse_director_signoff_window,
    validate_review_window,
)

from .models import (
    Payment,
    RazorpayControlledPilotExecutionAttempt,
    RazorpayControlledPilotExecutionGate,
    RazorpayPhase6FinalAuditLock,
    RazorpayWhatsAppInternalNotificationDryRunRecord,
    RazorpayWhatsAppInternalNotificationGate,
)

# Read-only template registry helpers (NOT send helpers).
from apps.whatsapp.template_registry import (
    DEFAULT_CLAIM_VAULT_REQUIRED,
    DEFAULT_TEMPLATE_NAMES,
)
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from apps.shipments.models import Shipment


# ---------------------------------------------------------------------------
# Constants - safety contract, audit kinds, forbidden actions
# ---------------------------------------------------------------------------


PHASE_7E_WARNING = (
    "Phase 7E is a Controlled Internal WhatsApp Notification "
    "Readiness Gate. It NEVER sends a WhatsApp message, NEVER queues "
    "an outbound, NEVER calls Meta Cloud / Delhivery / Vapi, NEVER "
    "creates a shipment / AWB / payment link, NEVER captures, NEVER "
    "refunds, NEVER mutates real Order / Payment / Shipment / "
    "DiscountOfferLog / Customer / Lead, NEVER sends a customer "
    "notification, and NEVER edits any .env file. Approval flips "
    "status to approved_for_future_phase7f_or_7e_send_review only - "
    "it does NOT enable any send path."
)


AUDIT_KIND_READINESS = (
    "razorpay.whatsapp_internal_notification.readiness_inspected"
)
AUDIT_KIND_PREVIEWED = "razorpay.whatsapp_internal_notification.previewed"
AUDIT_KIND_PREPARED = "razorpay.whatsapp_internal_notification.prepared"
AUDIT_KIND_DRY_RUN_PASSED = (
    "razorpay.whatsapp_internal_notification.dry_run_passed"
)
AUDIT_KIND_DRY_RUN_FAILED = (
    "razorpay.whatsapp_internal_notification.dry_run_failed"
)
AUDIT_KIND_RB_DRY_RUN_PASSED = (
    "razorpay.whatsapp_internal_notification.rb_dry_run_passed"
)
AUDIT_KIND_RB_DRY_RUN_FAILED = (
    "razorpay.whatsapp_internal_notification.rb_dry_run_failed"
)
AUDIT_KIND_APPROVED_FUTURE_SEND = (
    "razorpay.whatsapp_internal_notification.approved_future_send"
)
AUDIT_KIND_REJECTED = "razorpay.whatsapp_internal_notification.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.whatsapp_internal_notification.archived"
AUDIT_KIND_BLOCKED = "razorpay.whatsapp_internal_notification.blocked"
AUDIT_KIND_KILL_SWITCH_BLOCKED = (
    "razorpay.whatsapp_internal_notification.kill_switch_blocked"
)
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.whatsapp_internal_notification.invariant_violation"
)
AUDIT_KIND_ACKED_LEGACY_SIGNOFF = (
    "razorpay.whatsapp_internal_notification.acked_legacy_signoff"
)


PHASE_7E_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "send_whatsapp_template",
    "send_whatsapp_freeform",
    "queue_whatsapp_outbound",
    "create_whatsapp_message_outbound",
    "create_whatsapp_lifecycle_event",
    "create_whatsapp_handoff_to_call",
    "call_meta_cloud_api",
    "call_meta_graph_api",
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
    "mutate_real_shipment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "send_customer_notification",
    "notify_staff_via_whatsapp",
    "execute_via_frontend",
    "execute_via_api_endpoint",
    "approve_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_7E_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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
    "META_WA_TOKEN",
    "META_WA_APP_SECRET",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "director_signoff_text",
)


PHASE_7E_PROPOSED_ACTION_KEYS: tuple[str, ...] = (
    "whatsapp.payment_reminder",
    "whatsapp.confirmation_reminder",
    "whatsapp.delivery_reminder",
)


PHASE_7E_PROPOSED_VARIABLE_KEYS: tuple[str, ...] = (
    "customer_first_name",
    "order_id_last4",
    "amount_inr",
    "expected_delivery_date",
)


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


def _flag_phase7e_gate_enabled() -> bool:
    return bool(
        getattr(
            settings, "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED",
            False,
        )
    )


def _capture_env_flag_snapshot() -> dict[str, bool]:
    return {
        "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED": (
            _flag_phase7e_gate_enabled()
        ),
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED": bool(
            getattr(
                settings, "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED",
                False,
            )
        ),
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION": bool(
            getattr(
                settings,
                "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION",
                False,
            )
        ),
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER": bool(
            getattr(settings, "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER", False)
        ),
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED": bool(
            getattr(
                settings, "PHASE7_CONTROLLED_PILOT_GATE_ENABLED", False
            )
        ),
        "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED": bool(
            getattr(
                settings, "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED",
                False,
            )
        ),
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED": bool(
            getattr(
                settings, "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
                False,
            )
        ),
        "WHATSAPP_AI_AUTO_REPLY_ENABLED": bool(
            getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
        ),
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": bool(
            getattr(
                settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False
            )
        ),
        "WHATSAPP_CALL_HANDOFF_ENABLED": bool(
            getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False)
        ),
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED": bool(
            getattr(
                settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False
            )
        ),
        "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED": bool(
            getattr(
                settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False
            )
        ),
        "WHATSAPP_REORDER_DAY20_ENABLED": bool(
            getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False)
        ),
        "WHATSAPP_PROVIDER": str(
            getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock"
        ),
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": bool(
            getattr(
                settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False
            )
        ),
        "DELHIVERY_MODE": str(
            getattr(settings, "DELHIVERY_MODE", "mock") or "mock"
        ),
        "MCP_ENABLED": bool(getattr(settings, "MCP_ENABLED", False)),
    }


def _kill_switch_state() -> dict[str, Any]:
    """Read-only kill-switch snapshot. NEVER mutates."""
    try:
        from apps.saas.models import RuntimeKillSwitch  # type: ignore[import-not-found]
    except Exception:
        return {"enabled": True, "model": "absent_treated_as_enabled"}
    try:
        kill = RuntimeKillSwitch.objects.filter(scope="global").first()
    except Exception:
        return {"enabled": True, "model": "lookup_failed_treated_as_enabled"}
    if kill is None:
        return {"enabled": True, "model": "no_row_treated_as_enabled"}
    return {
        "enabled": bool(kill.enabled),
        "model": "RuntimeKillSwitch",
        "id": kill.pk,
    }


# ---------------------------------------------------------------------------
# Business-row count helpers (defensive guard)
# ---------------------------------------------------------------------------


def _business_row_counts() -> dict[str, int]:
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": WhatsAppLifecycleEvent.objects.count(),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
    }


def _safety_invariants() -> dict[str, Any]:
    return {
        "whatsappSendAllowedInPhase7E": False,
        "whatsappQueueAllowedInPhase7E": False,
        "metaCloudCallAllowedInPhase7E": False,
        "businessMutationAllowedInPhase7E": False,
        "customerNotificationAllowedInPhase7E": False,
        "realCustomerAllowedInPhase7E": False,
        "providerCallAttempted": False,
        "whatsAppMessageCreated": False,
        "whatsAppMessageQueued": False,
        "whatsAppLifecycleEventCreated": False,
        "metaCloudCallAttempted": False,
        "customerNotificationSent": False,
        "realOrderMutationWasMade": False,
        "realPaymentMutationWasMade": False,
        "phase7EApprovalImpliesLiveSend": False,
        "phase7DSourceSignoffMayBeLegacyFreeTextWithAck": True,
        "phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand": True,
    }


def assert_phase7e_no_send_or_business_mutation(
    gate: RazorpayWhatsAppInternalNotificationGate,
    *,
    before_counts: Optional[dict[str, int]] = None,
) -> None:
    """Defensive guard.

    Raises ``ValueError`` and emits an invariant-violation audit row if
    any locked-False boolean has flipped or the business-row counts
    have moved between ``before_counts`` and the current snapshot.
    """
    invariants = _safety_invariants()
    snapshot = gate.safety_invariants_snapshot or {}
    flipped: list[str] = []
    for key, expected in invariants.items():
        observed = snapshot.get(key, expected)
        if isinstance(expected, bool) and observed != expected:
            flipped.append(key)

    delta_blockers: list[str] = []
    if before_counts is not None:
        current = _business_row_counts()
        for key, count_before in before_counts.items():
            count_after = current.get(key, count_before)
            if count_after != count_before:
                delta_blockers.append(
                    f"phase7e_business_row_count_changed_for_{key}"
                )

    if flipped or delta_blockers:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text=f"Phase 7E invariant violation gate_id={gate.pk}",
            tone=AuditEvent.Tone.DANGER,
            payload={
                "phase": "7E",
                "gate_id": gate.pk,
                "flipped_booleans": list(flipped),
                "row_count_blockers": list(delta_blockers),
                **{k: False for k in invariants if isinstance(invariants[k], bool) and not invariants[k]},
            },
        )
        raise ValueError(
            "Phase 7E invariant violation: "
            f"flipped={flipped} row_deltas={delta_blockers}"
        )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def build_phase7e_whatsapp_internal_notification_contract() -> dict[str, Any]:
    return {
        "phase": "7E",
        "status": "whatsapp_internal_notification_readiness_only",
        "executionPath": "cli_only",
        "executeIsCliOnly": True,
        "phase7ESendsWhatsApp": False,
        "phase7EQueuesWhatsApp": False,
        "phase7ECallsMetaCloud": False,
        "phase7ECallsDelhivery": False,
        "phase7ECreatesShipmentOrAwb": False,
        "phase7ECreatesPaymentLink": False,
        "phase7ECapturesPayment": False,
        "phase7ERefundsPayment": False,
        "phase7ESendsCustomerNotification": False,
        "phase7EMutatesBusinessRow": False,
        "phase7ECreatesWhatsAppMessageRow": False,
        "phase7ECreatesWhatsAppLifecycleEventRow": False,
        "phase7ECreatesWhatsAppHandoffRow": False,
        "phase7EWritesEnvFile": False,
        "phase7EImportsDotenv": False,
        "phase7ETouchesRealCustomerPhoneNumber": False,
        "phase7EApprovalImpliesLiveSend": False,
        "phase7DSourceSignoffMayBeLegacyFreeTextWithAck": True,
        "phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand": True,
        "phase7EMakesUtcWindowCheckMandatoryForFutureSend": True,
        "manualReviewRequired": True,
        "internalStaffOnly": True,
        "proposedTemplateActionKeys": list(PHASE_7E_PROPOSED_ACTION_KEYS),
        "proposedVariableKeys": list(PHASE_7E_PROPOSED_VARIABLE_KEYS),
        "nextPhaseForLiveSend": "phase_7f_or_7e_live_not_approved",
        "forbiddenActions": list(PHASE_7E_FORBIDDEN_ACTIONS),
        "forbiddenPayloadKeys": list(PHASE_7E_FORBIDDEN_PAYLOAD_KEYS),
    }


# ---------------------------------------------------------------------------
# Eligibility validator
# ---------------------------------------------------------------------------


@dataclass
class Phase7EEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    attempt: Optional[RazorpayControlledPilotExecutionAttempt]
    phase7b_gate: Optional[RazorpayControlledPilotExecutionGate]
    phase6t_lock: Optional[RazorpayPhase6FinalAuditLock]
    source_phase7d_signoff_window_validation_status: str


def _classify_source_phase7d_signoff_window_status(
    attempt: RazorpayControlledPilotExecutionAttempt,
) -> str:
    """Classify the source Phase 7D attempt's signoff window status.

    Pre-Phase 7D-Hotfix-1, no Phase 7D row carries structured window
    fields, so every existing attempt is treated as
    ``failed_or_legacy_free_text``. Post-Hotfix-1 those fields exist
    and we read them; this helper is forward-compatible.
    """
    if not attempt.director_signoff_text.strip():
        return "not_applicable"
    valid_attr = getattr(attempt, "recorded_signoff_window_valid", None)
    if valid_attr is True:
        return "valid_structured_window"
    return "failed_or_legacy_free_text"


def validate_phase7e_source_eligibility(
    attempt_id: Optional[int],
    *,
    require_env_flag: bool = True,
) -> Phase7EEligibility:
    blockers: list[str] = []
    warnings: list[str] = []
    attempt: Optional[RazorpayControlledPilotExecutionAttempt] = None
    phase7b_gate: Optional[RazorpayControlledPilotExecutionGate] = None
    phase6t_lock: Optional[RazorpayPhase6FinalAuditLock] = None
    signoff_status = "not_applicable"

    if require_env_flag and not _flag_phase7e_gate_enabled():
        blockers.append(
            "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED_must_be_true"
        )

    if attempt_id:
        attempt = (
            RazorpayControlledPilotExecutionAttempt.objects.filter(
                pk=attempt_id
            )
            .select_related("source_phase7b_gate", "source_phase6t_lock")
            .first()
        )
    if attempt is None:
        blockers.append("phase_7d_source_attempt_not_found")
        return Phase7EEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            attempt=None,
            phase7b_gate=None,
            phase6t_lock=None,
            source_phase7d_signoff_window_validation_status=(
                signoff_status
            ),
        )

    # Source-attempt invariants.
    if (
        attempt.status
        != RazorpayControlledPilotExecutionAttempt.Status.EXECUTED
    ):
        if (
            attempt.status
            != RazorpayControlledPilotExecutionAttempt.Status.ROLLED_BACK
        ):
            blockers.append(
                f"phase_7d_attempt_status_must_be_executed_or_rolled_back_was_{attempt.status}"
            )
    if (
        attempt.rollback_status
        != RazorpayControlledPilotExecutionAttempt.RollbackStatus.COMPLETED
    ):
        blockers.append(
            "phase_7d_attempt_rollback_status_must_be_completed"
        )
    if not attempt.provider_call_attempted:
        blockers.append("phase_7d_attempt_provider_call_attempted_must_be_true")
    for field in (
        "business_mutation_was_made",
        "payment_link_created",
        "payment_captured",
        "payment_refunded",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "whatsapp_lifecycle_event_created",
        "shipment_created",
        "awb_created",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "customer_notification_sent",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
    ):
        if getattr(attempt, field, False):
            blockers.append(f"phase_7d_attempt_{field}_must_be_false")

    signoff_status = _classify_source_phase7d_signoff_window_status(attempt)

    # Phase 7B gate chain.
    phase7b_gate = attempt.source_phase7b_gate
    if phase7b_gate is None:
        blockers.append("phase_7b_source_gate_not_found")
    else:
        if (
            phase7b_gate.status
            != RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
        ):
            blockers.append(
                "phase_7b_gate_must_be_approved_for_future_phase7c_review"
            )
        if not phase7b_gate.dry_run_passed:
            blockers.append("phase_7b_gate_dry_run_passed_must_be_true")
        if not phase7b_gate.rollback_dry_run_passed:
            blockers.append(
                "phase_7b_gate_rollback_dry_run_passed_must_be_true"
            )
        phase6t_lock = phase7b_gate.source_final_audit_lock

    if phase6t_lock is None and attempt.source_phase6t_lock_id:
        phase6t_lock = attempt.source_phase6t_lock
    if phase6t_lock is None:
        blockers.append("phase_6t_audit_lock_not_found")
    else:
        if (
            phase6t_lock.status
            != RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
        ):
            blockers.append(
                "phase_6t_audit_lock_must_be_locked_for_future_review"
            )

    # Kill switch.
    kill_switch = _kill_switch_state()
    if not kill_switch.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    # WhatsApp automation flags must all be off.
    snapshot = _capture_env_flag_snapshot()
    for flag in (
        "WHATSAPP_AI_AUTO_REPLY_ENABLED",
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
        "WHATSAPP_CALL_HANDOFF_ENABLED",
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
        "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED",
        "WHATSAPP_REORDER_DAY20_ENABLED",
    ):
        if snapshot.get(flag) is True:
            blockers.append(f"{flag}_must_be_false")

    # Provider must be mock OR limited-test-mode active.
    provider = snapshot.get("WHATSAPP_PROVIDER", "mock")
    if provider != "mock" and not snapshot.get(
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False
    ):
        blockers.append(
            "whatsapp_provider_must_be_mock_or_limited_test_mode_active"
        )

    # Delhivery must be in mock/test mode.
    if snapshot.get("DELHIVERY_MODE") not in {"mock", "test"}:
        blockers.append("DELHIVERY_MODE_must_be_mock_or_test")

    # Phase 7D / 6K execute env flags must all be false.
    for flag in (
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED",
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION",
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER",
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
    ):
        if snapshot.get(flag) is True:
            blockers.append(f"{flag}_must_be_false")

    if signoff_status == "failed_or_legacy_free_text":
        warnings.append(
            "phase_7d_source_signoff_is_legacy_free_text_acknowledgement_required_at_approve_time"
        )

    return Phase7EEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        attempt=attempt,
        phase7b_gate=phase7b_gate,
        phase6t_lock=phase6t_lock,
        source_phase7d_signoff_window_validation_status=signoff_status,
    )


# ---------------------------------------------------------------------------
# Claim Vault grounding
# ---------------------------------------------------------------------------


def _claim_vault_grounding_check() -> tuple[bool, list[str]]:
    """Verify proposed templates either need no claim variables OR
    have at least one approved Claim Vault row.

    Phase 7E uses a conservative check: all 3 proposed action keys
    are utility templates (not usage_explanation), so by default
    none currently require claim-vault grounding. We still scan the
    static `DEFAULT_CLAIM_VAULT_REQUIRED` set so future template
    additions auto-fail without code change.
    """
    blockers: list[str] = []
    for action in PHASE_7E_PROPOSED_ACTION_KEYS:
        if action in DEFAULT_CLAIM_VAULT_REQUIRED:
            # Lazy import: only when needed; never at module-load time
            # so tests that mock the orders / claim app boot stay fast.
            try:
                from apps.compliance.models import Claim
            except Exception:
                blockers.append(
                    f"phase7e_claim_vault_lookup_failed_for_{action}"
                )
                continue
            if not Claim.objects.filter(
                approved=True
            ).exists():
                blockers.append(
                    f"phase7e_claim_vault_no_approved_phrase_for_{action}"
                )
    return (not blockers, blockers)


# ---------------------------------------------------------------------------
# Serializers (whitelist only - never raw secrets / phone / signoff text)
# ---------------------------------------------------------------------------


def serialize_phase7e_gate(
    row: RazorpayWhatsAppInternalNotificationGate,
) -> dict[str, Any]:
    suffix = row.target_internal_cohort_phone_suffix_last4 or ""
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sourcePhase7BGateId": row.source_phase7b_gate_id,
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        "targetInternalCohortPhoneSuffixLast4": suffix,
        "proposedTemplateActionKeys": list(
            row.proposed_template_action_keys or []
        ),
        "proposedTemplateNamesResolved": list(
            row.proposed_template_names_resolved or []
        ),
        "proposedVariableKeys": list(row.proposed_variable_keys or []),
        "claimVaultGrounded": bool(row.claim_vault_grounded),
        "claimVaultBlockers": list(row.claim_vault_blockers or []),
        "dryRunPassed": bool(row.dry_run_passed),
        "dryRunFailedReasons": list(row.dry_run_failed_reasons or []),
        "rollbackDryRunPassed": bool(row.rollback_dry_run_passed),
        "rollbackDryRunFailedReasons": list(
            row.rollback_dry_run_failed_reasons or []
        ),
        "sourcePhase7DSignoffWindowValidationStatus": (
            row.source_phase7d_signoff_window_validation_status
        ),
        "sourcePhase7DWindowViolationAcknowledged": bool(
            row.source_phase7d_window_violation_acknowledged
        ),
        "sourcePhase7DWindowViolationAckAt": (
            row.source_phase7d_window_violation_ack_at.isoformat()
            if row.source_phase7d_window_violation_ack_at
            else None
        ),
        "phase7EFutureReviewSignoffWindowStartUtc": (
            row.phase7e_future_review_signoff_window_start_utc.isoformat()
            if row.phase7e_future_review_signoff_window_start_utc
            else None
        ),
        "phase7EFutureReviewSignoffWindowEndUtc": (
            row.phase7e_future_review_signoff_window_end_utc.isoformat()
            if row.phase7e_future_review_signoff_window_end_utc
            else None
        ),
        "phase7EFutureReviewSignoffWindowValid": bool(
            row.phase7e_future_review_signoff_window_valid
        ),
        # Locked-False booleans always returned for the section to render.
        "whatsappSendAllowedInPhase7E": False,
        "whatsappQueueAllowedInPhase7E": False,
        "metaCloudCallAllowedInPhase7E": False,
        "businessMutationAllowedInPhase7E": False,
        "customerNotificationAllowedInPhase7E": False,
        "realCustomerAllowedInPhase7E": False,
        "providerCallAttempted": False,
        "whatsAppMessageCreated": False,
        "whatsAppMessageQueued": False,
        "whatsAppLifecycleEventCreated": False,
        "metaCloudCallAttempted": False,
        "customerNotificationSent": False,
        "realOrderMutationWasMade": False,
        "realPaymentMutationWasMade": False,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action or "",
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "approvedAt": (
            row.approved_at.isoformat() if row.approved_at else None
        ),
        "rejectedAt": (
            row.rejected_at.isoformat() if row.rejected_at else None
        ),
        "archivedAt": (
            row.archived_at.isoformat() if row.archived_at else None
        ),
    }


def serialize_phase7e_dry_run_record(
    row: RazorpayWhatsAppInternalNotificationDryRunRecord,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "kind": row.kind,
        "status": row.status,
        "claimVaultGrounded": bool(row.claim_vault_grounded),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# Audit payload helper (always strips forbidden keys)
# ---------------------------------------------------------------------------


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"phase": "7E"}
    for key, value in extra.items():
        if key in PHASE_7E_FORBIDDEN_PAYLOAD_KEYS:
            continue
        safe[key] = value
    return safe


def _audit_gate_payload(
    gate: RazorpayWhatsAppInternalNotificationGate,
) -> dict[str, Any]:
    return _safe_audit_payload(
        {
            "gate_id": gate.pk,
            "status": gate.status,
            "phase7d_attempt_id": gate.source_phase7d_attempt_id,
            "phase7b_gate_id": gate.source_phase7b_gate_id,
            "phase6t_lock_id": gate.source_phase6t_lock_id,
            "claim_vault_grounded": bool(gate.claim_vault_grounded),
            "dry_run_passed": bool(gate.dry_run_passed),
            "rollback_dry_run_passed": bool(gate.rollback_dry_run_passed),
            "phase7e_future_review_signoff_window_valid": bool(
                gate.phase7e_future_review_signoff_window_valid
            ),
            "source_phase7d_signoff_window_validation_status": (
                gate.source_phase7d_signoff_window_validation_status
            ),
            "source_phase7d_window_violation_acknowledged": bool(
                gate.source_phase7d_window_violation_acknowledged
            ),
            "kill_switch_enabled": _kill_switch_state().get(
                "enabled", True
            ),
            "blockers": list(gate.blockers or []),
        }
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7e_gate(attempt_id: int) -> dict[str, Any]:
    """Read-only preview from a Phase 7D attempt. Never creates rows."""
    eligibility = validate_phase7e_source_eligibility(
        attempt_id, require_env_flag=False
    )
    proposed_names = [
        DEFAULT_TEMPLATE_NAMES.get(action, "")
        for action in PHASE_7E_PROPOSED_ACTION_KEYS
    ]
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7E preview attempt_id={attempt_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7d_attempt_id": attempt_id,
                "eligible": eligibility.eligible,
                "blockers": list(eligibility.blockers),
                "source_phase7d_signoff_window_validation_status": (
                    eligibility.source_phase7d_signoff_window_validation_status
                ),
            }
        ),
    )
    return {
        "phase": "7E",
        "found": eligibility.attempt is not None,
        "sourcePhase7DAttemptId": attempt_id,
        "sourcePhase7BGateId": (
            eligibility.phase7b_gate.pk
            if eligibility.phase7b_gate
            else None
        ),
        "sourcePhase6TLockId": (
            eligibility.phase6t_lock.pk
            if eligibility.phase6t_lock
            else None
        ),
        "sourcePhase7DSignoffWindowValidationStatus": (
            eligibility.source_phase7d_signoff_window_validation_status
        ),
        "eligible": eligibility.eligible,
        "proposedContract": (
            build_phase7e_whatsapp_internal_notification_contract()
        ),
        "proposedTemplateActionKeys": list(PHASE_7E_PROPOSED_ACTION_KEYS),
        "proposedTemplateNamesResolved": proposed_names,
        "proposedVariableKeys": list(PHASE_7E_PROPOSED_VARIABLE_KEYS),
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_7E_WARNING],
        "nextAction": (
            "ready_to_prepare_phase7e_gate"
            if eligibility.eligible and _flag_phase7e_gate_enabled()
            else "fix_phase_7e_eligibility_blockers_or_enable_phase7e_gate_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(
    attempt: RazorpayControlledPilotExecutionAttempt,
) -> str:
    return f"phase7e::wa_notify::attempt::{attempt.pk}"


def prepare_phase7e_gate(
    attempt_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Atomic, idempotent prepare. Creates one gate per Phase 7D attempt."""
    eligibility = validate_phase7e_source_eligibility(
        attempt_id, require_env_flag=True
    )
    if not eligibility.eligible or eligibility.attempt is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7E prepare blocked attempt_id={attempt_id}",
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7d_attempt_id": attempt_id,
                    "blockers": list(eligibility.blockers),
                }
            ),
        )
        return {
            "phase": "7E",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_7E_WARNING],
            "nextAction": (
                "fix_phase_7e_eligibility_blockers_or_enable_phase7e_gate_flag"
            ),
        }

    attempt = eligibility.attempt
    idem_key = _idempotency_key(attempt)
    before = _business_row_counts()
    snapshot = _capture_env_flag_snapshot()
    kill_state = _kill_switch_state()
    invariants = _safety_invariants()

    with transaction.atomic():
        existing = (
            RazorpayWhatsAppInternalNotificationGate.objects.filter(
                idempotency_key=idem_key
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            write_event(
                kind=AUDIT_KIND_PREPARED,
                text=f"Phase 7E prepare reused gate_id={existing.pk}",
                tone=AuditEvent.Tone.INFO,
                payload=_audit_gate_payload(existing),
            )
            return {
                "phase": "7E",
                "created": False,
                "reused": True,
                "gate": serialize_phase7e_gate(existing),
                "blockers": [],
                "warnings": list(eligibility.warnings) + [PHASE_7E_WARNING],
                "nextAction": "ready_for_phase7e_dry_run",
            }

        proposed_names = [
            DEFAULT_TEMPLATE_NAMES.get(action, "")
            for action in PHASE_7E_PROPOSED_ACTION_KEYS
        ]

        gate = RazorpayWhatsAppInternalNotificationGate.objects.create(
            source_phase7d_attempt=attempt,
            source_phase7b_gate=eligibility.phase7b_gate,
            source_phase6t_lock=eligibility.phase6t_lock,
            status=RazorpayWhatsAppInternalNotificationGate.Status.PENDING_MANUAL_REVIEW,
            target_internal_cohort_phone_suffix_last4="",
            target_internal_cohort_member_id="",
            proposed_template_action_keys=list(
                PHASE_7E_PROPOSED_ACTION_KEYS
            ),
            proposed_template_names_resolved=proposed_names,
            proposed_variable_keys=list(PHASE_7E_PROPOSED_VARIABLE_KEYS),
            source_phase7d_signoff_window_validation_status=(
                eligibility.source_phase7d_signoff_window_validation_status
            ),
            kill_switch_snapshot_at_each_step={"prepare": kill_state},
            env_flag_snapshot_at_each_step={"prepare": snapshot},
            safety_invariants_snapshot=invariants,
            before_counts=before,
            after_counts=before,
            idempotency_key=idem_key,
            blockers=[],
            warnings=list(eligibility.warnings),
            next_action="ready_for_phase7e_dry_run",
            requested_by=requested_by,
        )

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 7E prepare created gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7E",
        "created": True,
        "reused": False,
        "gate": serialize_phase7e_gate(gate),
        "blockers": [],
        "warnings": list(eligibility.warnings) + [PHASE_7E_WARNING],
        "nextAction": "ready_for_phase7e_dry_run",
    }


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def _dry_run_idempotency_key(gate_id: int) -> str:
    timestamp = timezone.now().strftime("%Y%m%dT%H%M%S%f")
    return f"phase7e::wa_notify::dry_run::gate::{gate_id}::run::{timestamp}"


def _rollback_dry_run_idempotency_key(gate_id: int) -> str:
    timestamp = timezone.now().strftime("%Y%m%dT%H%M%S%f")
    return (
        f"phase7e::wa_notify::rollback_dry_run::gate::{gate_id}"
        f"::run::{timestamp}"
    )


def dry_run_phase7e_gate(gate_id: int) -> dict[str, Any]:
    gate = (
        RazorpayWhatsAppInternalNotificationGate.objects.filter(pk=gate_id)
        .first()
    )
    if gate is None:
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_gate_not_found"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status != RazorpayWhatsAppInternalNotificationGate.Status.PENDING_MANUAL_REVIEW:
        return {
            "phase": "7E",
            "ok": False,
            "gate": serialize_phase7e_gate(gate),
            "blockers": [
                f"phase7e_gate_status_must_be_pending_manual_review_was_{gate.status}"
            ],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    grounded, claim_blockers = _claim_vault_grounding_check()

    # Defensive guard: nothing should have flipped on the gate row.
    assert_phase7e_no_send_or_business_mutation(gate, before_counts=before)

    after = _business_row_counts()
    record_blockers: list[str] = list(claim_blockers)
    if before != after:
        record_blockers.append(
            "phase7e_business_row_count_changed_during_dry_run"
        )
    passed = not record_blockers

    record = (
        RazorpayWhatsAppInternalNotificationDryRunRecord.objects.create(
            gate=gate,
            kind=RazorpayWhatsAppInternalNotificationDryRunRecord.Kind.DRY_RUN,
            status=(
                RazorpayWhatsAppInternalNotificationDryRunRecord.Status.PASSED
                if passed
                else RazorpayWhatsAppInternalNotificationDryRunRecord.Status.FAILED
            ),
            idempotency_key=_dry_run_idempotency_key(gate.pk),
            safety_invariants_snapshot=_safety_invariants(),
            before_counts=before,
            after_counts=after,
            claim_vault_grounded=grounded,
            blockers=record_blockers,
            warnings=[],
            reason="",
        )
    )

    gate.dry_run_passed = passed
    gate.dry_run_failed_reasons = record_blockers if not passed else []
    gate.claim_vault_grounded = grounded and passed
    gate.claim_vault_blockers = claim_blockers
    gate.kill_switch_snapshot_at_each_step = {
        **(gate.kill_switch_snapshot_at_each_step or {}),
        "dry_run": _kill_switch_state(),
    }
    gate.env_flag_snapshot_at_each_step = {
        **(gate.env_flag_snapshot_at_each_step or {}),
        "dry_run": _capture_env_flag_snapshot(),
    }
    gate.after_counts = after
    if not passed:
        gate.blockers = list(record_blockers)
    gate.next_action = (
        "ready_for_phase7e_rollback_dry_run"
        if passed
        else "fix_phase7e_dry_run_blockers"
    )
    gate.save()

    write_event(
        kind=(
            AUDIT_KIND_DRY_RUN_PASSED if passed else AUDIT_KIND_DRY_RUN_FAILED
        ),
        text=f"Phase 7E dry-run gate_id={gate.pk} passed={passed}",
        tone=AuditEvent.Tone.INFO if passed else AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7E",
        "ok": passed,
        "gate": serialize_phase7e_gate(gate),
        "record": serialize_phase7e_dry_run_record(record),
        "blockers": record_blockers,
        "warnings": [PHASE_7E_WARNING],
        "nextAction": gate.next_action,
    }


def rollback_dry_run_phase7e_gate(
    gate_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_rollback_dry_run_reason_required"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "supply_reason",
        }
    gate = (
        RazorpayWhatsAppInternalNotificationGate.objects.filter(pk=gate_id)
        .first()
    )
    if gate is None:
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_gate_not_found"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not gate.dry_run_passed:
        return {
            "phase": "7E",
            "ok": False,
            "gate": serialize_phase7e_gate(gate),
            "blockers": ["phase7e_dry_run_must_have_passed_first"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "run_phase7e_dry_run_first",
        }

    before = _business_row_counts()
    assert_phase7e_no_send_or_business_mutation(gate, before_counts=before)
    after = _business_row_counts()

    record_blockers: list[str] = []
    if before != after:
        record_blockers.append(
            "phase7e_business_row_count_changed_during_rollback_dry_run"
        )
    passed = not record_blockers

    record = (
        RazorpayWhatsAppInternalNotificationDryRunRecord.objects.create(
            gate=gate,
            kind=(
                RazorpayWhatsAppInternalNotificationDryRunRecord.Kind.ROLLBACK_DRY_RUN
            ),
            status=(
                RazorpayWhatsAppInternalNotificationDryRunRecord.Status.PASSED
                if passed
                else RazorpayWhatsAppInternalNotificationDryRunRecord.Status.FAILED
            ),
            idempotency_key=_rollback_dry_run_idempotency_key(gate.pk),
            safety_invariants_snapshot=_safety_invariants(),
            before_counts=before,
            after_counts=after,
            claim_vault_grounded=bool(gate.claim_vault_grounded),
            blockers=record_blockers,
            warnings=[],
            reason=reason[:1000],
        )
    )

    gate.rollback_dry_run_passed = passed
    gate.rollback_dry_run_failed_reasons = (
        record_blockers if not passed else []
    )
    gate.kill_switch_snapshot_at_each_step = {
        **(gate.kill_switch_snapshot_at_each_step or {}),
        "rollback_dry_run": _kill_switch_state(),
    }
    gate.env_flag_snapshot_at_each_step = {
        **(gate.env_flag_snapshot_at_each_step or {}),
        "rollback_dry_run": _capture_env_flag_snapshot(),
    }
    gate.next_action = (
        "ready_for_phase7e_approve"
        if passed
        else "fix_phase7e_rollback_dry_run_blockers"
    )
    gate.save()

    write_event(
        kind=(
            AUDIT_KIND_RB_DRY_RUN_PASSED
            if passed
            else AUDIT_KIND_RB_DRY_RUN_FAILED
        ),
        text=f"Phase 7E rollback-dry-run gate_id={gate.pk} passed={passed}",
        tone=AuditEvent.Tone.INFO if passed else AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7E",
        "ok": passed,
        "gate": serialize_phase7e_gate(gate),
        "record": serialize_phase7e_dry_run_record(record),
        "blockers": record_blockers,
        "warnings": [PHASE_7E_WARNING],
        "nextAction": gate.next_action,
    }


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


_ATTEMPT_ID_REFERENCE_TEMPLATE = (
    "phase7d_attempt_id_{attempt_id}"
)


def _signoff_references_attempt_id(
    signoff_text: str, attempt_id: int
) -> bool:
    """Approve requires the new sign-off body to literally reference
    the source Phase 7D attempt id."""
    if not signoff_text:
        return False
    needle = _ATTEMPT_ID_REFERENCE_TEMPLATE.format(attempt_id=attempt_id)
    return needle in signoff_text


def _ack_token(attempt_id: int) -> str:
    return (
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt_id}"
    )


def approve_phase7e_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
    director_signoff: str = "",
    acknowledge_source_phase7d_window_violation: bool = False,
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_approve_reason_required"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "supply_reason",
        }
    gate = (
        RazorpayWhatsAppInternalNotificationGate.objects.filter(pk=gate_id)
        .first()
    )
    if gate is None:
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_gate_not_found"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_id",
        }

    blockers: list[str] = []
    if (
        gate.status
        != RazorpayWhatsAppInternalNotificationGate.Status.PENDING_MANUAL_REVIEW
    ):
        blockers.append(
            f"phase7e_gate_status_must_be_pending_manual_review_was_{gate.status}"
        )
    if not gate.dry_run_passed:
        blockers.append("phase7e_dry_run_passed_must_be_true")
    if not gate.rollback_dry_run_passed:
        blockers.append("phase7e_rollback_dry_run_passed_must_be_true")
    if not gate.claim_vault_grounded:
        blockers.append("phase7e_claim_vault_grounded_must_be_true")

    parsed = parse_director_signoff_window(director_signoff)
    if parsed is None:
        blockers.append(
            "phase7e_director_signoff_missing_structured_utc_window"
        )
    else:
        validation = validate_review_window(parsed)
        if not validation.valid:
            for entry in validation.blockers:
                blockers.append(f"phase7e_review_window_{entry}")

    attempt_id = gate.source_phase7d_attempt_id
    if not _signoff_references_attempt_id(
        director_signoff, attempt_id
    ):
        blockers.append(
            "phase7e_director_signoff_must_reference_source_phase7d_attempt_id"
        )

    legacy = (
        gate.source_phase7d_signoff_window_validation_status
        == RazorpayWhatsAppInternalNotificationGate.SourcePhase7DSignoffWindowValidationStatus.FAILED_OR_LEGACY_FREE_TEXT
    )
    if legacy:
        if not acknowledge_source_phase7d_window_violation:
            blockers.append(
                "phase7e_acknowledge_source_phase7d_window_violation_required_for_legacy_signoff"
            )
        ack_needle = _ack_token(attempt_id)
        if ack_needle not in (reason or ""):
            blockers.append(
                "phase7e_reason_must_contain_acknowledgement_token_for_legacy_signoff"
            )

    if blockers:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7E approve blocked gate_id={gate.pk}",
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(gate)
            | {"approve_blockers": blockers},
        )
        return {
            "phase": "7E",
            "ok": False,
            "gate": serialize_phase7e_gate(gate),
            "blockers": blockers,
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "fix_phase7e_approve_blockers",
        }

    # Defensive guard before flipping status.
    before = _business_row_counts()
    assert_phase7e_no_send_or_business_mutation(gate, before_counts=before)

    gate.status = (
        RazorpayWhatsAppInternalNotificationGate.Status.APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW
    )
    gate.approved_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.director_signoff_text = (director_signoff or "")[:4000]
    gate.phase7e_future_review_signoff_window_start_utc = (
        parsed.window_start_utc if parsed else None
    )
    gate.phase7e_future_review_signoff_window_end_utc = (
        parsed.window_end_utc if parsed else None
    )
    gate.phase7e_future_review_signoff_window_valid = True
    if legacy:
        gate.source_phase7d_window_violation_acknowledged = True
        gate.source_phase7d_window_violation_ack_at = timezone.now()
    gate.kill_switch_snapshot_at_each_step = {
        **(gate.kill_switch_snapshot_at_each_step or {}),
        "approve": _kill_switch_state(),
    }
    gate.env_flag_snapshot_at_each_step = {
        **(gate.env_flag_snapshot_at_each_step or {}),
        "approve": _capture_env_flag_snapshot(),
    }
    gate.next_action = (
        "phase7e_gate_approved_for_future_phase7f_or_7e_send_review"
    )
    gate.save()

    if legacy:
        write_event(
            kind=AUDIT_KIND_ACKED_LEGACY_SIGNOFF,
            text=(
                f"Phase 7E acknowledged legacy free-text Phase 7D "
                f"signoff gate_id={gate.pk} attempt_id={attempt_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(gate)
            | {
                "acknowledged_at": gate.source_phase7d_window_violation_ack_at.isoformat(),
                "reason_text_includes_acknowledgement_token": True,
            },
        )

    write_event(
        kind=AUDIT_KIND_APPROVED_FUTURE_SEND,
        text=f"Phase 7E approved gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7E",
        "ok": True,
        "gate": serialize_phase7e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7E_WARNING],
        "nextAction": gate.next_action,
    }


# ---------------------------------------------------------------------------
# Reject / archive
# ---------------------------------------------------------------------------


def reject_phase7e_gate(
    gate_id: int,
    *,
    rejected_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_reject_reason_required"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "supply_reason",
        }
    gate = (
        RazorpayWhatsAppInternalNotificationGate.objects.filter(pk=gate_id)
        .first()
    )
    if gate is None:
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_gate_not_found"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayWhatsAppInternalNotificationGate.Status.DRAFT,
        RazorpayWhatsAppInternalNotificationGate.Status.PENDING_MANUAL_REVIEW,
    }:
        return {
            "phase": "7E",
            "ok": False,
            "gate": serialize_phase7e_gate(gate),
            "blockers": [
                f"phase7e_reject_refused_for_status_{gate.status}"
            ],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    assert_phase7e_no_send_or_business_mutation(gate, before_counts=before)

    gate.status = (
        RazorpayWhatsAppInternalNotificationGate.Status.REJECTED
    )
    gate.rejected_at = timezone.now()
    gate.rejected_by = rejected_by
    gate.reject_reason = (reason or "")[:1000]
    gate.next_action = "phase7e_gate_rejected"
    gate.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 7E rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7E",
        "ok": True,
        "gate": serialize_phase7e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7E_WARNING],
        "nextAction": gate.next_action,
    }


def archive_phase7e_gate(
    gate_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    gate = (
        RazorpayWhatsAppInternalNotificationGate.objects.filter(pk=gate_id)
        .first()
    )
    if gate is None:
        return {
            "phase": "7E",
            "ok": False,
            "gate": None,
            "blockers": ["phase7e_gate_not_found"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if (
        gate.status
        == RazorpayWhatsAppInternalNotificationGate.Status.ARCHIVED
    ):
        return {
            "phase": "7E",
            "ok": False,
            "gate": serialize_phase7e_gate(gate),
            "blockers": ["phase7e_gate_already_archived"],
            "warnings": [PHASE_7E_WARNING],
            "nextAction": "verify_gate_status",
        }
    before = _business_row_counts()
    assert_phase7e_no_send_or_business_mutation(gate, before_counts=before)

    gate.status = (
        RazorpayWhatsAppInternalNotificationGate.Status.ARCHIVED
    )
    gate.archived_at = timezone.now()
    gate.archived_by = archived_by
    gate.archive_reason = (reason or "")[:1000]
    gate.next_action = "phase7e_gate_archived"
    gate.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 7E archived gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7E",
        "ok": True,
        "gate": serialize_phase7e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7E_WARNING],
        "nextAction": gate.next_action,
    }


# ---------------------------------------------------------------------------
# Summarize / inspect-readiness
# ---------------------------------------------------------------------------


def summarize_phase7e_gates(limit: int = 25) -> dict[str, Any]:
    queryset = (
        RazorpayWhatsAppInternalNotificationGate.objects.order_by(
            "-created_at"
        )
    )
    statuses = [
        s.value
        for s in RazorpayWhatsAppInternalNotificationGate.Status
    ]
    counts = {
        s: queryset.filter(status=s).count() for s in statuses
    }
    items = [
        serialize_phase7e_gate(row) for row in queryset[: max(1, limit)]
    ]
    return {
        "phase": "7E",
        "limit": int(max(1, limit)),
        "counts": counts,
        "items": items,
    }


def inspect_phase7e_readiness() -> dict[str, Any]:
    snapshot = _capture_env_flag_snapshot()
    kill_state = _kill_switch_state()
    summary = summarize_phase7e_gates(limit=10)

    eligible_phase7d_count = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            status=RazorpayControlledPilotExecutionAttempt.Status.EXECUTED,
            rollback_status=RazorpayControlledPilotExecutionAttempt.RollbackStatus.COMPLETED,
            provider_call_attempted=True,
            business_mutation_was_made=False,
            payment_link_created=False,
            payment_captured=False,
            payment_refunded=False,
            whatsapp_message_created=False,
            whatsapp_message_queued=False,
            whatsapp_lifecycle_event_created=False,
            shipment_created=False,
            awb_created=False,
            customer_notification_sent=False,
        ).count()
    )
    rolled_back_count = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            status=RazorpayControlledPilotExecutionAttempt.Status.ROLLED_BACK,
            rollback_status=RazorpayControlledPilotExecutionAttempt.RollbackStatus.COMPLETED,
            provider_call_attempted=True,
        ).count()
    )

    blockers: list[str] = []
    if not _flag_phase7e_gate_enabled():
        blockers.append(
            "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED_must_be_true"
        )
    if not kill_state.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    for flag in (
        "WHATSAPP_AI_AUTO_REPLY_ENABLED",
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
        "WHATSAPP_CALL_HANDOFF_ENABLED",
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
        "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED",
        "WHATSAPP_REORDER_DAY20_ENABLED",
    ):
        if snapshot.get(flag) is True:
            blockers.append(f"{flag}_must_be_false")
    for flag in (
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED",
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION",
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER",
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
    ):
        if snapshot.get(flag) is True:
            blockers.append(f"{flag}_must_be_false")

    next_action = (
        "ready_to_prepare_phase7e_gate"
        if not blockers
        and eligible_phase7d_count > 0
        else "enable_phase7e_gate_flag_for_review_only"
        if not _flag_phase7e_gate_enabled()
        else "fix_phase7e_readiness_blockers"
    )

    return {
        "phase": "7E",
        "status": "whatsapp_internal_notification_readiness_only",
        "latestCompletedPhase": "7D",
        "nextPhase": "7F_or_7E_live_not_approved",
        "envFlags": {
            "phase7eGateEnabled": _flag_phase7e_gate_enabled(),
        },
        "envFlagSnapshot": snapshot,
        "killSwitch": kill_state,
        "phase7DRolledBackEligibleCount": rolled_back_count,
        "phase7DEligibleForPhase7ECount": eligible_phase7d_count,
        "gateCounts": summary["counts"],
        "items": summary["items"],
        "phase7DSourceSignoffMayBeLegacyFreeTextWithAck": True,
        "phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand": True,
        "phase7ESendsWhatsApp": False,
        "phase7EQueuesWhatsApp": False,
        "phase7ECallsMetaCloud": False,
        "phase7ECallsDelhivery": False,
        "phase7ECreatesShipmentOrAwb": False,
        "phase7ECreatesPaymentLink": False,
        "phase7ECapturesPayment": False,
        "phase7ERefundsPayment": False,
        "phase7ESendsCustomerNotification": False,
        "phase7EMutatesBusinessRow": False,
        "blockers": blockers,
        "warnings": [PHASE_7E_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_7E_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7E readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "next_action": report.get("nextAction"),
                "phase7e_gate_enabled": (
                    report.get("envFlags", {}).get(
                        "phase7eGateEnabled", False
                    )
                ),
                "phase7d_eligible_count": report.get(
                    "phase7DEligibleForPhase7ECount", 0
                ),
                "kill_switch_enabled": report.get(
                    "killSwitch", {}
                ).get("enabled", True),
            }
        ),
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


__all__ = (
    "PHASE_7E_WARNING",
    "PHASE_7E_FORBIDDEN_ACTIONS",
    "PHASE_7E_FORBIDDEN_PAYLOAD_KEYS",
    "PHASE_7E_PROPOSED_ACTION_KEYS",
    "PHASE_7E_PROPOSED_VARIABLE_KEYS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_DRY_RUN_PASSED",
    "AUDIT_KIND_DRY_RUN_FAILED",
    "AUDIT_KIND_RB_DRY_RUN_PASSED",
    "AUDIT_KIND_RB_DRY_RUN_FAILED",
    "AUDIT_KIND_APPROVED_FUTURE_SEND",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_KILL_SWITCH_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "AUDIT_KIND_ACKED_LEGACY_SIGNOFF",
    "Phase7EEligibility",
    "build_phase7e_whatsapp_internal_notification_contract",
    "validate_phase7e_source_eligibility",
    "preview_phase7e_gate",
    "prepare_phase7e_gate",
    "dry_run_phase7e_gate",
    "rollback_dry_run_phase7e_gate",
    "approve_phase7e_gate",
    "reject_phase7e_gate",
    "archive_phase7e_gate",
    "summarize_phase7e_gates",
    "inspect_phase7e_readiness",
    "emit_readiness_inspected_audit",
    "assert_phase7e_no_send_or_business_mutation",
    "serialize_phase7e_gate",
    "serialize_phase7e_dry_run_record",
)
