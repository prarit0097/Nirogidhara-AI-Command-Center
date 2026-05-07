"""Phase 7D - Razorpay-only one-shot internal TEST execution.

This service implements a *single* future Razorpay TEST-mode
``Orders.create()`` invocation derived from a fully-approved Phase 7B
:class:`RazorpayControlledPilotExecutionGate` row, against the existing
TEST key, at the 100-paise (Rs. 1.00) ceiling. Phase 7D **never** sends
WhatsApp, **never** queues an outbound, **never** calls Meta Cloud,
**never** calls Delhivery, **never** calls Vapi, **never** creates a
shipment / AWB, **never** creates a payment link, **never** captures,
**never** refunds, **never** mutates real ``Order`` / ``Payment`` /
``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead`` rows,
**never** sends a customer notification.

Phase 7D **never** edits any ``.env*`` file. The module does not
import ``dotenv``. Env flag flips are operator-controlled; this
service only *reads* the flags and records snapshots on every attempt
row at start and at end. Operators verify post-run that the three
Phase 7D window flags are ``False`` again.

Public surface:

- :func:`build_phase7d_controlled_pilot_execution_contract`
- :func:`inspect_phase7d_razorpay_test_execution_readiness`
- :func:`validate_phase7d_source_gate_eligibility`
- :func:`preview_phase7d_razorpay_test_execution_attempt`
- :func:`prepare_phase7d_razorpay_test_execution_attempt`
- :func:`approve_phase7d_razorpay_test_execution_attempt`
- :func:`execute_phase7d_razorpay_test_order` -- the only callable
  that may issue a Razorpay request, and only when every gate passes.
- :func:`rollback_phase7d_razorpay_test_execution_attempt`
- :func:`archive_phase7d_razorpay_test_execution_attempt`
- :func:`recover_phase7d_razorpay_test_execution_attempt`
- :func:`assert_phase7d_no_business_mutation`
- :func:`serialize_phase7d_attempt`
- :func:`summarize_phase7d_attempts`
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import (
    RazorpayControlledPilotExecutionAttempt,
    RazorpayControlledPilotExecutionGate,
    RazorpayControlledPilotExecutionRollback,
    RazorpayPaymentDispatchPilotPlan,
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpayPhase6FinalAuditLock,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)


PHASE_7D_WARNING = (
    "Phase 7D is the Razorpay-only one-shot internal TEST execution. "
    "It NEVER sends WhatsApp, NEVER queues an outbound, NEVER calls "
    "Meta Cloud / Delhivery / Vapi, NEVER creates a shipment / AWB, "
    "NEVER creates a payment link, NEVER captures, NEVER refunds, "
    "NEVER mutates real Order / Payment / Customer / Lead rows. The "
    "execute path is CLI-only and requires three Phase 7D env flags + "
    "non-empty Director sign-off + RAZORPAY_KEY_ID starting with "
    "'rzp_test_' + RuntimeKillSwitch enabled + source-chain green. "
    "The service NEVER edits any .env file."
)


# Audit kinds (every kind <= 64 chars).
AUDIT_KIND_READINESS = (
    "razorpay.controlled_pilot_execution.readiness_inspected"
)
AUDIT_KIND_PREVIEWED = "razorpay.controlled_pilot_execution.previewed"
AUDIT_KIND_PREPARED = (
    "razorpay.controlled_pilot_execution.attempt_prepared"
)
AUDIT_KIND_APPROVED_FOR_ONE_SHOT = (
    "razorpay.controlled_pilot_execution.approved_for_one_shot"
)
AUDIT_KIND_EXECUTED = "razorpay.controlled_pilot_execution.executed"
AUDIT_KIND_FAILED = "razorpay.controlled_pilot_execution.failed"
AUDIT_KIND_ROLLED_BACK = (
    "razorpay.controlled_pilot_execution.rolled_back"
)
AUDIT_KIND_ARCHIVED = "razorpay.controlled_pilot_execution.archived"
AUDIT_KIND_BLOCKED = "razorpay.controlled_pilot_execution.blocked"
AUDIT_KIND_KILL_SWITCH_BLOCKED = (
    "razorpay.controlled_pilot_execution.kill_switch_blocked"
)
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.controlled_pilot_execution.invariant_violation_blocked"
)
AUDIT_KIND_RECOVERY_RECONCILED = (
    "razorpay.controlled_pilot_execution.recovery_reconciled"
)


PHASE_7D_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "execute_pilot",
    "start_pilot",
    "run_pilot",
    "send_whatsapp_template",
    "queue_whatsapp_outbound",
    "create_whatsapp_message_outbound",
    "create_whatsapp_lifecycle_event",
    "call_meta_cloud_api",
    "call_delhivery_api",
    "create_shipment",
    "create_awb",
    "book_courier_pickup",
    "place_vapi_call",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "mutate_real_order_status",
    "mutate_real_payment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "send_customer_notification",
    "execute_via_frontend",
    "execute_via_api_endpoint",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "archive_via_api_endpoint",
    "edit_dotenv_production",
    "edit_dotenv_live",
    "edit_dotenv_any",
)


PHASE_7D_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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


PHASE_7D_MAX_AMOUNT_PAISE = 100
PHASE_7D_DEFAULT_CURRENCY = "INR"
RAZORPAY_TEST_KEY_PREFIX = "rzp_test_"
RAZORPAY_LIVE_KEY_PREFIX = "rzp_live_"


# ---------------------------------------------------------------------------
# Flag readers (read-only). NEVER edits .env files.
# ---------------------------------------------------------------------------


def _flag_execution_lifecycle_enabled() -> bool:
    return bool(
        getattr(settings, "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED", False)
    )


def _flag_director_one_shot_approved() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION",
            False,
        )
    )


def _flag_allow_razorpay_test_order() -> bool:
    return bool(
        getattr(settings, "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER", False)
    )


def _capture_env_flag_snapshot() -> dict[str, bool]:
    """Read-only snapshot of every Phase 7D / Phase 6T+ kill-switch
    flag's *boolean* presence. Never includes values of secret env
    vars; never opens any ``.env*`` file; never mutates settings.
    """
    return {
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED": _flag_execution_lifecycle_enabled(),
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION": _flag_director_one_shot_approved(),
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER": _flag_allow_razorpay_test_order(),
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED": bool(
            getattr(settings, "PHASE7_CONTROLLED_PILOT_GATE_ENABLED", False)
        ),
        "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED": bool(
            getattr(
                settings,
                "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED",
                False,
            )
        ),
        "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED": bool(
            getattr(
                settings,
                "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED",
                False,
            )
        ),
        "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED": bool(
            getattr(
                settings,
                "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED",
                False,
            )
        ),
        "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED": bool(
            getattr(
                settings,
                "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED",
                False,
            )
        ),
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED": bool(
            getattr(
                settings,
                "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
                False,
            )
        ),
        "WHATSAPP_AI_AUTO_REPLY_ENABLED": bool(
            getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
        ),
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": bool(
            getattr(
                settings,
                "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
                False,
            )
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


def _classify_razorpay_key(key_id: str) -> str:
    if not key_id:
        return "missing"
    if key_id.startswith(RAZORPAY_LIVE_KEY_PREFIX):
        return "live"
    if key_id.startswith(RAZORPAY_TEST_KEY_PREFIX):
        return "test"
    return "unknown"


def _mask_razorpay_key_id(key_id: str) -> str:
    if not key_id:
        return ""
    if len(key_id) <= 12:
        return key_id[:8] + "***"
    return f"{key_id[:9]}***{key_id[-4:]}"


def _razorpay_key_advisory() -> dict[str, Any]:
    """Read-only key advisory. NEVER returns the raw key.

    Reads from ``django.conf.settings.RAZORPAY_KEY_ID`` first (the
    canonical, override-settings-aware source) and falls back to
    ``os.environ`` so unit tests using ``override_settings`` work
    without env-var monkey patching.
    """
    key_id = (
        getattr(settings, "RAZORPAY_KEY_ID", None)
        or os.environ.get("RAZORPAY_KEY_ID")
        or ""
    )
    return {
        "razorpayKeyIdPresent": bool(key_id),
        "razorpayKeyIdMasked": _mask_razorpay_key_id(key_id),
        "razorpayKeyMode": _classify_razorpay_key(key_id),
        "isTestKey": _classify_razorpay_key(key_id) == "test",
    }


# ---------------------------------------------------------------------------
# Business-row count helpers (for before/after deltas).
# ---------------------------------------------------------------------------


def _business_row_counts() -> dict[str, int]:
    """Read-only count snapshot of every business model that Phase 7D
    must NEVER mutate. Used to assert before/after parity in tests +
    in :func:`assert_phase7d_no_business_mutation`.
    """
    from apps.crm.models import Customer, Lead
    from apps.orders.models import DiscountOfferLog, Order
    from apps.payments.models import Payment
    from apps.shipments.models import Shipment
    from apps.whatsapp.models import (
        WhatsAppHandoffToCall,
        WhatsAppLifecycleEvent,
        WhatsAppMessage,
    )

    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
    }


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "business_mutation_was_made",
    "payment_link_created",
    "payment_captured",
    "payment_refunded",
    "customer_notification_sent",
    "whatsapp_message_created",
    "whatsapp_message_queued",
    "whatsapp_lifecycle_event_created",
    "meta_cloud_call_attempted",
    "delhivery_call_attempted",
    "shipment_created",
    "awb_created",
    "real_order_mutation_was_made",
    "real_payment_mutation_was_made",
    "customer_mutation_was_made",
    "lead_mutation_was_made",
    "discount_offer_log_mutation_was_made",
    "mcp_tool_called",
    "kill_switch_disabled_during_attempt",
    "env_flag_flipped_outside_window",
    "raw_secret_exposed",
    "full_pii_exposed",
)


def assert_phase7d_no_business_mutation(
    attempt: RazorpayControlledPilotExecutionAttempt,
) -> None:
    """Refuse the operation if any locked-False boolean is True or any
    business-row count delta is non-zero. Emits an
    ``invariant_violation_blocked`` audit row and raises
    :class:`ValueError`.
    """
    flipped: list[str] = []
    for field in _LOCKED_FALSE_FIELDS:
        if getattr(attempt, field, False) is True:
            flipped.append(field)

    delta_keys: list[str] = []
    if attempt.before_counts and attempt.after_counts:
        for key, before in attempt.before_counts.items():
            after = attempt.after_counts.get(key, before)
            if after != before:
                delta_keys.append(
                    f"business_row_count_delta_{key}_{before}_to_{after}"
                )

    if not flipped and not delta_keys:
        return

    write_event(
        kind=AUDIT_KIND_INVARIANT_VIOLATION,
        text=(
            f"Phase 7D invariant violation blocked attempt_id={attempt.pk} "
            f"flipped={flipped} deltas={delta_keys}"
        ),
        tone=AuditEvent.Tone.DANGER,
        payload={
            "phase": "7D",
            "attempt_id": attempt.pk,
            "flipped_safety_booleans": flipped,
            "business_row_count_deltas": delta_keys,
            **_audit_locked_false_payload(),
        },
    )
    raise ValueError(
        f"Phase 7D safety invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


def _audit_locked_false_payload() -> dict[str, bool]:
    return {field: False for field in _LOCKED_FALSE_FIELDS}


# ---------------------------------------------------------------------------
# Contract + safety invariants
# ---------------------------------------------------------------------------


def _safety_invariants() -> dict[str, Any]:
    return {
        "phase": "7D",
        "razorpayTestExecutionOnly": True,
        "wpAtsAppSendAllowed": False,  # noqa: typo intentional sentinel
        "whatsappSendAllowed": False,
        "whatsappQueueAllowed": False,
        "metaCloudCallAllowed": False,
        "delhiveryCallAllowed": False,
        "vapiCallAllowed": False,
        "shipmentCreationAllowed": False,
        "awbCreationAllowed": False,
        "paymentLinkCreationAllowed": False,
        "paymentCaptureAllowed": False,
        "paymentRefundAllowed": False,
        "businessMutationAllowed": False,
        "customerNotificationAllowed": False,
        "frontendExecutionAllowed": False,
        "apiExecutionAllowed": False,
        "executeIsCliOnly": True,
        "envFileWriteAllowed": False,
        "razorpayKeyValidationAtRuntime": True,
        "razorpayKeyMustStartWithRzpTest": True,
        "phase7dRespectsKillSwitch": True,
        "phase7dApprovalApplyRealMutation": False,
        "envPosture": (
            "All execution / mutation / provider-enabling flags remain "
            "false outside the operator-controlled one-shot execution "
            "window. Provider modes remain safe/mock/test-only as "
            "applicable. DELHIVERY_MODE stays mock unless separately "
            "approved. WHATSAPP_LIVE_META_LIMITED_TEST_MODE may remain "
            "true as a safety allow-list guard, while WhatsApp send / "
            "automation flags remain false. MCP write / provider tools "
            "remain disabled. Phase 7D service NEVER edits any .env "
            "file."
        ),
    }


def build_phase7d_controlled_pilot_execution_contract() -> dict[str, Any]:
    return {
        "phase": "7D",
        "status": "razorpay_test_execution_only",
        "executionPath": "cli_only",
        "executeIsCliOnly": True,
        "providerCallAllowedDuringPlanning": False,
        "razorpayCreateOrderAllowedOnlyAt": (
            "execute_phase7d_razorpay_test_order_after_full_gate_chain"
        ),
        "phase7DSendsOrQueuesWhatsApp": False,
        "phase7DCallsMetaCloud": False,
        "phase7DCallsDelhivery": False,
        "phase7DCreatesShipmentOrAwb": False,
        "phase7DCreatesPaymentLink": False,
        "phase7DCapturesPayment": False,
        "phase7DRefundsPayment": False,
        "phase7DSendsCustomerNotification": False,
        "phase7DMutatesBusinessRow": False,
        "manualReviewRequired": True,
        "internalStaffOnly": True,
        "maxAmountPaise": PHASE_7D_MAX_AMOUNT_PAISE,
        "currency": PHASE_7D_DEFAULT_CURRENCY,
        "blockers": [
            "phase_7d_execute_requires_three_window_flags_plus_director_signoff",
            "phase_7d_execute_requires_rzp_test_key_prefix",
            "phase_7d_execute_requires_kill_switch_enabled",
            "phase_7d_execute_requires_source_chain_green",
        ],
        "notes": [
            "Phase 7D ships the gate-controlled execution lifecycle. "
            "The actual execute_* invocation requires a SECOND, "
            "separate, dated Director approval naming the exact gate "
            "id, attempt id, operator name, and UTC execution window."
        ],
    }


# ---------------------------------------------------------------------------
# Eligibility validator
# ---------------------------------------------------------------------------


@dataclass
class Phase7DEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    gate: RazorpayControlledPilotExecutionGate | None
    audit_lock: RazorpayPhase6FinalAuditLock | None
    pilot_plan: RazorpayPaymentDispatchPilotPlan | None
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None
    sandbox_attempt: RazorpaySandboxPaidStatusMutationAttempt | None
    sandbox_review: RazorpaySandboxStatusReview | None
    event_record: RazorpayWebhookEvent | None


def validate_phase7d_source_gate_eligibility(
    gate_id: int | None,
    *,
    require_env_flag: bool = True,
) -> Phase7DEligibility:
    """Validate that a Phase 7B gate is eligible for Phase 7D
    attempt-row creation.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    gate: RazorpayControlledPilotExecutionGate | None = None
    audit_lock: RazorpayPhase6FinalAuditLock | None = None
    pilot_plan: RazorpayPaymentDispatchPilotPlan | None = None
    readiness_gate: RazorpayPaymentDispatchReadinessGate | None = None
    workflow_gate: RazorpayPaymentOrderWorkflowGate | None = None
    sandbox_attempt: RazorpaySandboxPaidStatusMutationAttempt | None = None
    sandbox_review: RazorpaySandboxStatusReview | None = None
    event_record: RazorpayWebhookEvent | None = None

    if require_env_flag and not _flag_execution_lifecycle_enabled():
        blockers.append(
            "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED_must_be_true"
        )

    if gate_id:
        gate = (
            RazorpayControlledPilotExecutionGate.objects.filter(pk=gate_id)
            .select_related(
                "source_final_audit_lock",
                "source_pilot_plan",
                "source_readiness_gate",
                "source_workflow_gate",
                "source_attempt",
                "source_review",
                "source_event_record",
            )
            .first()
        )

    if gate is None:
        blockers.append("phase_7b_source_controlled_pilot_gate_not_found")
        return Phase7DEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            gate=None,
            audit_lock=None,
            pilot_plan=None,
            readiness_gate=None,
            workflow_gate=None,
            sandbox_attempt=None,
            sandbox_review=None,
            event_record=None,
        )

    if (
        gate.status
        != RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
    ):
        blockers.append(
            f"phase_7b_gate_status_must_be_approved_for_future_phase7c_was_{gate.status}"
        )
    if not gate.dry_run_passed:
        blockers.append("phase_7b_gate_dry_run_passed_must_be_true")
    if not gate.rollback_dry_run_passed:
        blockers.append(
            "phase_7b_gate_rollback_dry_run_passed_must_be_true"
        )
    for field in (
        "controlled_pilot_execution_allowed_in_phase7b",
        "live_execution_allowed_in_phase7b",
        "provider_call_allowed_in_phase7b",
        "business_mutation_allowed_in_phase7b",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_created",
        "awb_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "customer_notification_sent",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "razorpay_call_attempted",
        "provider_call_attempted",
        "raw_secret_exposed",
        "full_pii_exposed",
    ):
        if getattr(gate, field, False):
            blockers.append(
                f"phase_7b_gate_{field}_must_be_false"
            )

    audit_lock = gate.source_final_audit_lock
    pilot_plan = gate.source_pilot_plan
    readiness_gate = gate.source_readiness_gate
    workflow_gate = gate.source_workflow_gate
    sandbox_attempt = gate.source_attempt
    sandbox_review = gate.source_review
    event_record = gate.source_event_record

    if audit_lock is None:
        blockers.append("phase_6t_audit_lock_not_found_on_gate")
    else:
        if (
            audit_lock.status
            != RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
        ):
            blockers.append(
                f"phase_6t_lock_status_must_be_locked_for_future_controlled_pilot_review_was_{audit_lock.status}"
            )

    if pilot_plan is None:
        blockers.append("phase_6s_pilot_plan_not_found_on_gate")
    elif (
        pilot_plan.status
        != RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
    ):
        blockers.append(
            f"phase_6s_pilot_plan_status_must_be_approved_for_future_phase6t_was_{pilot_plan.status}"
        )

    if readiness_gate is None:
        blockers.append("phase_6r_readiness_gate_not_found_on_gate")
    elif (
        readiness_gate.status
        != RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
    ):
        blockers.append(
            "phase_6r_readiness_gate_status_must_be_approved_for_future_phase6s"
        )

    if workflow_gate is None:
        blockers.append("phase_6q_workflow_gate_not_found_on_gate")
    elif (
        workflow_gate.status
        != RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
    ):
        blockers.append(
            "phase_6q_workflow_gate_status_must_be_approved_for_future_phase6r"
        )

    if sandbox_attempt is None:
        blockers.append("phase_6p_sandbox_attempt_not_found_on_gate")
    elif sandbox_attempt.status not in (
        RazorpaySandboxPaidStatusMutationAttempt.Status.EXECUTED,
        RazorpaySandboxPaidStatusMutationAttempt.Status.ROLLED_BACK,
    ):
        blockers.append(
            f"phase_6p_sandbox_attempt_status_{sandbox_attempt.status}_not_eligible"
        )

    if sandbox_review is None:
        blockers.append("phase_6o_sandbox_review_not_found_on_gate")
    elif (
        sandbox_review.status
        != RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
    ):
        blockers.append(
            "phase_6o_sandbox_review_status_must_be_approved_for_future_phase6p"
        )

    if event_record is None:
        blockers.append("phase_6m_razorpay_webhook_event_not_found")
    else:
        if not event_record.signature_valid:
            blockers.append("phase_6m_event_signature_invalid")
        if not event_record.replay_window_valid:
            blockers.append("phase_6m_event_replay_window_invalid")
        if (
            event_record.idempotency_status
            != RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN
        ):
            blockers.append(
                "phase_6m_event_idempotency_must_be_first_seen"
            )
        if event_record.business_mutation_was_made:
            blockers.append("phase_6m_event_business_mutation_was_made")
        if event_record.customer_notification_sent:
            blockers.append("phase_6m_event_customer_notification_sent")
        if event_record.raw_secret_exposed:
            blockers.append("phase_6m_event_raw_secret_exposed")
        if event_record.full_pii_exposed or event_record.scrubbed_keys:
            blockers.append("phase_6m_event_full_pii_must_be_absent")
        if event_record.environment != RazorpayWebhookEvent.Environment.TEST:
            blockers.append(
                f"phase_6m_event_environment_must_be_test_was_{event_record.environment}"
            )
        if (
            event_record.amount_paise is not None
            and event_record.amount_paise > PHASE_7D_MAX_AMOUNT_PAISE
        ):
            blockers.append(
                f"amount_paise_must_be_<=_{PHASE_7D_MAX_AMOUNT_PAISE}"
            )

    return Phase7DEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        gate=gate,
        audit_lock=audit_lock,
        pilot_plan=pilot_plan,
        readiness_gate=readiness_gate,
        workflow_gate=workflow_gate,
        sandbox_attempt=sandbox_attempt,
        sandbox_review=sandbox_review,
        event_record=event_record,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_phase7d_attempt(
    row: RazorpayControlledPilotExecutionAttempt,
) -> dict[str, Any]:
    """Whitelisted serializer. NEVER returns raw key, raw secret, full
    phone / email / address / card / vpa / upi / bank_account /
    wallet, raw provider response, or the Director's full sign-off
    text.
    """
    signoff = row.director_signoff_text or ""
    signoff_present = bool(signoff.strip())
    return {
        "id": row.pk,
        "sourcePhase7BGateId": row.source_phase7b_gate_id,
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        "sourcePilotPlanId": row.source_pilot_plan_id,
        "sourceReadinessGateId": row.source_readiness_gate_id,
        "sourceWorkflowGateId": row.source_workflow_gate_id,
        "sourceSandboxAttemptId": row.source_sandbox_attempt_id,
        "sourceSandboxReviewId": row.source_sandbox_review_id,
        "sourceEventRecordId": row.source_event_record_id,
        "status": row.status,
        "providerEnvironment": row.provider_environment,
        "amountPaise": row.amount_paise,
        "currency": row.currency,
        "receipt": row.receipt,
        "idempotencyKey": row.idempotency_key,
        "safeRequestSummary": row.safe_request_summary or {},
        "safeResponseSummary": row.safe_response_summary or {},
        "providerObjectId": row.provider_object_id,
        "providerStatus": row.provider_status,
        "rollbackStatus": row.rollback_status,
        "rolledBackAt": (
            row.rolled_back_at.isoformat() if row.rolled_back_at else None
        ),
        "rollbackReasonPresent": bool((row.rollback_reason or "").strip()),
        "directorSignoffPresent": signoff_present,
        "killSwitchSnapshot": row.kill_switch_snapshot or {},
        "envFlagSnapshotAtStart": row.env_flag_snapshot_at_start or {},
        "envFlagSnapshotAtEnd": row.env_flag_snapshot_at_end or {},
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "safetyInvariants": row.safety_invariants or {},
        "businessMutationWasMade": row.business_mutation_was_made,
        "paymentLinkCreated": row.payment_link_created,
        "paymentCaptured": row.payment_captured,
        "paymentRefunded": row.payment_refunded,
        "customerNotificationSent": row.customer_notification_sent,
        "whatsAppMessageCreated": row.whatsapp_message_created,
        "whatsAppMessageQueued": row.whatsapp_message_queued,
        "whatsAppLifecycleEventCreated": (
            row.whatsapp_lifecycle_event_created
        ),
        "metaCloudCallAttempted": row.meta_cloud_call_attempted,
        "delhiveryCallAttempted": row.delhivery_call_attempted,
        "shipmentCreated": row.shipment_created,
        "awbCreated": row.awb_created,
        "realOrderMutationWasMade": row.real_order_mutation_was_made,
        "realPaymentMutationWasMade": row.real_payment_mutation_was_made,
        "customerMutationWasMade": row.customer_mutation_was_made,
        "leadMutationWasMade": row.lead_mutation_was_made,
        "discountOfferLogMutationWasMade": (
            row.discount_offer_log_mutation_was_made
        ),
        "mcpToolCalled": row.mcp_tool_called,
        "killSwitchDisabledDuringAttempt": (
            row.kill_switch_disabled_during_attempt
        ),
        "envFlagFlippedOutsideWindow": row.env_flag_flipped_outside_window,
        "rawSecretExposed": row.raw_secret_exposed,
        "fullPiiExposed": row.full_pii_exposed,
        "providerCallAttempted": row.provider_call_attempted,
        "razorpayCallAttempted": row.razorpay_call_attempted,
        "idempotencyLockAcquired": row.idempotency_lock_acquired,
        "rollbackRecorded": row.rollback_recorded,
        "directorSignoffPresentBoolean": row.director_signoff_present,
        "reviewedByUsername": (
            getattr(row.reviewed_by, "username", "") or ""
        ),
        "executedByUsername": (
            getattr(row.executed_by, "username", "") or ""
        ),
        "archivedByUsername": (
            getattr(row.archived_by, "username", "") or ""
        ),
        "reviewedAt": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "reviewReason": row.review_reason,
        "executedAt": (
            row.executed_at.isoformat() if row.executed_at else None
        ),
        "failedAt": row.failed_at.isoformat() if row.failed_at else None,
        "archivedAt": (
            row.archived_at.isoformat() if row.archived_at else None
        ),
        "archiveReason": row.archive_reason,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def serialize_phase7d_rollback(
    row: RazorpayControlledPilotExecutionRollback,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "attemptId": row.attempt_id,
        "verifiedAt": row.verified_at.isoformat(),
        "rollbackStatus": row.rollback_status,
        "rollbackReasonPresent": bool(
            (row.rollback_reason or "").strip()
        ),
        "envFlagPresenceAtRollback": (
            row.env_flag_presence_at_rollback or {}
        ),
        "evaluatedSafetyInvariants": (
            row.evaluated_safety_invariants or {}
        ),
        "providerObjectIdRecorded": row.provider_object_id_recorded,
        "idempotencyKey": row.idempotency_key,
        "createdAt": row.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Razorpay TEST create_order helpers (Phase 7D-scoped).
#
# The SDK is imported lazily and only inside the guarded execute path.
# Tests patch ``_create_order_via_sdk`` so the real network is never
# hit.
# ---------------------------------------------------------------------------


class Phase7DExecutionError(Exception):
    """Raised when execute_phase7d_razorpay_test_order refuses or the
    underlying SDK fails. Phase 7D never echoes the SDK error message
    verbatim because some SDK errors quote the request body.
    """


def _build_phase7d_test_order_payload(
    *,
    attempt_id: int,
    receipt: str,
) -> dict[str, Any]:
    """Construct the synthetic Phase 7D Razorpay TEST ``create_order``
    payload. Hard rules: amount=100 paise, currency=INR, no customer
    block, no notify, no callbacks, notes flagged internal-only.
    """
    return {
        "amount": 100,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "purpose": "phase7d_internal_test_mode_only",
            "external_customer": "false",
            "real_money": "false",
            "business_mutation": "false",
            "phase": "7D",
            "attempt_id": str(attempt_id),
        },
    }


def _summarize_razorpay_order_response(response: Any) -> dict[str, Any]:
    """Reduce the Razorpay response to a Phase 7D safe summary.

    Strips every key beyond the canonical ``id`` / ``status`` /
    ``amount`` / ``currency`` / ``receipt`` / ``created_at`` fields.
    NEVER stores raw provider response in DB.
    """
    if not isinstance(response, dict):
        return {
            "id": "",
            "status": "",
            "amount": 0,
            "currency": "INR",
            "receipt": "",
            "created_at": 0,
        }
    return {
        "id": str(response.get("id") or ""),
        "status": str(response.get("status") or ""),
        "amount": int(response.get("amount") or 0),
        "currency": str(response.get("currency") or "INR"),
        "receipt": str(response.get("receipt") or ""),
        "created_at": int(response.get("created_at") or 0),
    }


def _create_order_via_sdk(payload: dict[str, Any]) -> dict[str, Any]:
    """Call the Razorpay Orders API ``create`` endpoint via the SDK.

    NEVER logs the auth tuple. Raises :class:`Phase7DExecutionError`
    on missing dep, missing creds, or SDK failure. **Tests
    ``mock.patch`` this function so the real SDK is never invoked.**
    """
    try:
        import razorpay  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise Phase7DExecutionError(
            "razorpay SDK is not installed."
        ) from exc

    key_id = (
        getattr(settings, "RAZORPAY_KEY_ID", None)
        or os.environ.get("RAZORPAY_KEY_ID")
        or ""
    )
    key_secret = (
        getattr(settings, "RAZORPAY_KEY_SECRET", None)
        or os.environ.get("RAZORPAY_KEY_SECRET")
        or ""
    )
    if not key_id or not key_secret:
        raise Phase7DExecutionError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not configured."
        )
    if not key_id.startswith(RAZORPAY_TEST_KEY_PREFIX):
        raise Phase7DExecutionError(
            "RAZORPAY_KEY_ID must start with rzp_test_ for Phase 7D."
        )

    client = razorpay.Client(auth=(key_id, key_secret))
    try:
        return client.order.create(payload)
    except Exception as exc:  # pragma: no cover - real network only
        raise Phase7DExecutionError(
            f"Razorpay SDK error: {exc.__class__.__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7d_razorpay_test_execution_attempt(
    gate_id: int,
) -> dict[str, Any]:
    """Read-only preview. NEVER creates rows."""
    eligibility = validate_phase7d_source_gate_eligibility(
        gate_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7D preview source_gate_id={gate_id}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "7D",
            "phase7b_gate_id": gate_id,
            "phase6t_lock_id": (
                eligibility.audit_lock.pk
                if eligibility.audit_lock
                else None
            ),
            "phase6s_pilot_plan_id": (
                eligibility.pilot_plan.pk
                if eligibility.pilot_plan
                else None
            ),
            "phase6r_readiness_gate_id": (
                eligibility.readiness_gate.pk
                if eligibility.readiness_gate
                else None
            ),
            "phase6q_workflow_gate_id": (
                eligibility.workflow_gate.pk
                if eligibility.workflow_gate
                else None
            ),
            "phase6p_attempt_id": (
                eligibility.sandbox_attempt.pk
                if eligibility.sandbox_attempt
                else None
            ),
            "phase6o_review_id": (
                eligibility.sandbox_review.pk
                if eligibility.sandbox_review
                else None
            ),
            "phase6m_event_id": (
                eligibility.event_record.source_event_id
                if eligibility.event_record
                else ""
            ),
            "eligible": eligibility.eligible,
            "blockers": list(eligibility.blockers),
            "provider_call_attempted": False,
            "kill_switch_state_at_emit": _kill_switch_state(),
            **_audit_locked_false_payload(),
        },
    )
    return {
        "phase": "7D",
        "found": eligibility.gate is not None,
        "sourcePhase7BGateId": gate_id,
        "sourcePhase6TLockId": (
            eligibility.audit_lock.pk if eligibility.audit_lock else None
        ),
        "eligible": eligibility.eligible,
        "proposedContract": (
            build_phase7d_controlled_pilot_execution_contract()
        ),
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_7D_WARNING],
        "nextAction": (
            "ready_to_prepare_phase7d_execution_attempt"
            if eligibility.eligible
            and _flag_execution_lifecycle_enabled()
            else "fix_phase_7d_eligibility_blockers_or_enable_phase7d_lifecycle_flag"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(gate: RazorpayControlledPilotExecutionGate) -> str:
    return f"phase7d::execution::gate::{gate.pk}"


def _receipt(gate_id: int, attempt_id: int) -> str:
    return f"phase7d::ctrl_pilot::gate::{gate_id}::attempt::{attempt_id}"


def prepare_phase7d_razorpay_test_execution_attempt(
    gate_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Create / re-fetch a Phase 7D attempt row.

    Atomic. Idempotent on the source Phase 7B gate. NEVER calls a
    provider, NEVER mutates real business tables, NEVER edits any
    ``.env*`` file.
    """
    eligibility = validate_phase7d_source_gate_eligibility(
        gate_id, require_env_flag=True
    )
    if not eligibility.eligible or eligibility.gate is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7D prepare blocked source_gate_id={gate_id}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": "7D",
                "phase7b_gate_id": gate_id,
                "blockers": list(eligibility.blockers),
                "kill_switch_state_at_emit": _kill_switch_state(),
                **_audit_locked_false_payload(),
            },
        )
        return {
            "phase": "7D",
            "created": False,
            "reused": False,
            "attempt": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_7D_WARNING],
            "nextAction": (
                "fix_phase_7d_eligibility_blockers_or_enable_phase7d_lifecycle_flag"
            ),
        }

    gate = eligibility.gate
    idempotency = _idempotency_key(gate)
    before_counts = _business_row_counts()
    env_snapshot = _capture_env_flag_snapshot()
    kill_switch = _kill_switch_state()

    with transaction.atomic():
        existing = (
            RazorpayControlledPilotExecutionAttempt.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "7D",
                "created": False,
                "reused": True,
                "attempt": serialize_phase7d_attempt(existing),
                "blockers": [],
                "warnings": [PHASE_7D_WARNING],
                "nextAction": "phase7d_attempt_pending_director_signoff",
            }

        attempt = RazorpayControlledPilotExecutionAttempt(
            source_phase7b_gate=gate,
            source_phase6t_lock=eligibility.audit_lock,
            source_pilot_plan=eligibility.pilot_plan,
            source_readiness_gate=eligibility.readiness_gate,
            source_workflow_gate=eligibility.workflow_gate,
            source_sandbox_attempt=eligibility.sandbox_attempt,
            source_sandbox_review=eligibility.sandbox_review,
            source_event_record=eligibility.event_record,
            status=(
                RazorpayControlledPilotExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF
            ),
            provider_environment="test",
            amount_paise=PHASE_7D_MAX_AMOUNT_PAISE,
            currency=PHASE_7D_DEFAULT_CURRENCY,
            receipt="",  # set below from attempt pk
            idempotency_key=idempotency,
            safe_request_summary={
                "amount": PHASE_7D_MAX_AMOUNT_PAISE,
                "currency": PHASE_7D_DEFAULT_CURRENCY,
                "receipt_template": "phase7d::ctrl_pilot::gate::<G>::attempt::<A>",
            },
            safe_response_summary={},
            provider_object_id="",
            provider_status="",
            rollback_status=(
                RazorpayControlledPilotExecutionAttempt.RollbackStatus.PENDING
            ),
            rolled_back_at=None,
            rollback_reason="",
            director_signoff_text="",
            kill_switch_snapshot={"at_start": kill_switch},
            env_flag_snapshot_at_start=env_snapshot,
            env_flag_snapshot_at_end={},
            before_counts=before_counts,
            after_counts={},
            blockers=[],
            warnings=[PHASE_7D_WARNING],
            safety_invariants=_safety_invariants(),
            requested_by=requested_by,
        )
        assert_phase7d_no_business_mutation(attempt)
        try:
            attempt.save()
        except IntegrityError:
            attempt = RazorpayControlledPilotExecutionAttempt.objects.get(
                idempotency_key=idempotency
            )
            return {
                "phase": "7D",
                "created": False,
                "reused": True,
                "attempt": serialize_phase7d_attempt(attempt),
                "blockers": [],
                "warnings": [PHASE_7D_WARNING],
                "nextAction": "phase7d_attempt_pending_director_signoff",
            }

        # Now populate the receipt with the assigned pk.
        attempt.receipt = _receipt(gate.pk, attempt.pk)
        attempt.safe_request_summary = {
            "amount": PHASE_7D_MAX_AMOUNT_PAISE,
            "currency": PHASE_7D_DEFAULT_CURRENCY,
            "receipt": attempt.receipt,
        }
        attempt.save(update_fields=["receipt", "safe_request_summary"])

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 7D execution attempt prepared attempt_id={attempt.pk} "
            f"gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt, status_override=None),
    )

    return {
        "phase": "7D",
        "created": True,
        "reused": False,
        "attempt": serialize_phase7d_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7D_WARNING],
        "nextAction": "phase7d_attempt_pending_director_signoff",
    }


# ---------------------------------------------------------------------------
# Approve / reject (status-only)
# ---------------------------------------------------------------------------


def _audit_attempt_payload(
    attempt: RazorpayControlledPilotExecutionAttempt,
    *,
    status_override: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": "7D",
        "attempt_id": attempt.pk,
        "gate_id": attempt.source_phase7b_gate_id,
        "phase6t_lock_id": attempt.source_phase6t_lock_id,
        "phase6s_pilot_plan_id": attempt.source_pilot_plan_id,
        "phase6r_readiness_gate_id": attempt.source_readiness_gate_id,
        "phase6q_workflow_gate_id": attempt.source_workflow_gate_id,
        "phase6p_attempt_id": attempt.source_sandbox_attempt_id,
        "phase6o_review_id": attempt.source_sandbox_review_id,
        "phase6m_event_id": (
            attempt.source_event_record_id
            if attempt.source_event_record_id
            else None
        ),
        "status": status_override or attempt.status,
        "provider_call_attempted": attempt.provider_call_attempted,
        "razorpay_call_attempted": attempt.razorpay_call_attempted,
        "idempotency_key": attempt.idempotency_key,
        "kill_switch_state_at_emit": _kill_switch_state(),
        "before_counts_summary": attempt.before_counts or {},
        "after_counts_summary": attempt.after_counts or {},
        "provider_object_id_or_empty": attempt.provider_object_id or "",
        "safe_response_summary": attempt.safe_response_summary or {},
        **_audit_locked_false_payload(),
    }
    # Echo current values of locked-False booleans (defensive parity).
    for field in _LOCKED_FALSE_FIELDS:
        payload[field] = bool(getattr(attempt, field, False))
    if extra:
        payload.update(extra)
    return payload


def approve_phase7d_razorpay_test_execution_attempt(
    attempt_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the attempt approved for one-shot run. NEVER calls a
    provider; NEVER mutates real business tables. Manual review reason
    text required.
    """
    attempt = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7d_attempt_not_found"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if not _flag_execution_lifecycle_enabled():
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": [
                "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "enable_phase7d_lifecycle_flag",
        }
    if (
        attempt.status
        != RazorpayControlledPilotExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    ):
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": [
                f"phase7d_attempt_status_{attempt.status}_not_transitionable"
            ],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if not reason.strip():
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": ["manual_review_reason_must_be_non_empty"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "supply_manual_review_reason",
        }

    assert_phase7d_no_business_mutation(attempt)
    attempt.status = (
        RazorpayControlledPilotExecutionAttempt.Status.APPROVED_FOR_ONE_SHOT_RUN
    )
    attempt.reviewed_by = reviewed_by
    attempt.reviewed_at = timezone.now()
    attempt.review_reason = (reason or "")[:200]
    attempt.save()

    write_event(
        kind=AUDIT_KIND_APPROVED_FOR_ONE_SHOT,
        text=f"Phase 7D attempt approved attempt_id={attempt.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(
            attempt,
            extra={"reason_summary_present": bool(reason.strip())},
        ),
    )
    return {
        "phase": "7D",
        "ok": True,
        "attempt": serialize_phase7d_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7D_WARNING],
        "nextAction": (
            "approved_for_one_shot_run_execute_only_with_separate_director_window"
        ),
    }


# ---------------------------------------------------------------------------
# Execute (CLI-only; refuses unless every gate green)
# ---------------------------------------------------------------------------


def _director_signoff_mentions_gate(
    director_signoff: str, gate_id: int
) -> bool:
    if not director_signoff:
        return False
    needle = str(gate_id)
    return needle in director_signoff


def execute_phase7d_razorpay_test_order(
    attempt_id: int,
    *,
    confirmed_by=None,
    director_signoff: str = "",
) -> dict[str, Any]:
    """The ONLY callable that may issue a Razorpay request.

    Refuses unless EVERY pre-condition holds:

    1. ``PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED=True``
    2. ``PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION=True``
    3. ``PHASE7D_ALLOW_RAZORPAY_TEST_ORDER=True``
    4. attempt status == ``approved_for_one_shot_run``
    5. non-empty ``director_signoff`` mentioning the source gate id
    6. ``RAZORPAY_KEY_ID`` starts with ``rzp_test_``
    7. ``RuntimeKillSwitch.enabled`` true
    8. ``amount_paise == 100``
    9. source-chain still safe at runtime
    10. attempt has no prior provider call

    On success: ONE Razorpay TEST ``Orders.create()`` call. Records
    safe summary; flips status to ``executed``;
    ``provider_call_attempted=True`` and
    ``razorpay_call_attempted=True``. Refuses to retry. Calls
    ``assert_phase7d_no_business_mutation`` post-call. NEVER edits
    ``.env`` files. Persists ``env_flag_snapshot_at_start`` and
    ``env_flag_snapshot_at_end`` on the attempt row.
    """
    attempt = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7d_attempt_not_found"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }

    blockers: list[str] = []
    if not _flag_execution_lifecycle_enabled():
        blockers.append(
            "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED_must_be_true"
        )
    if not _flag_director_one_shot_approved():
        blockers.append(
            "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION_must_be_true"
        )
    if not _flag_allow_razorpay_test_order():
        blockers.append(
            "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER_must_be_true"
        )
    if (
        attempt.status
        != RazorpayControlledPilotExecutionAttempt.Status.APPROVED_FOR_ONE_SHOT_RUN
    ):
        blockers.append(
            f"phase7d_attempt_status_must_be_approved_for_one_shot_run_was_{attempt.status}"
        )
    if attempt.provider_call_attempted:
        blockers.append("phase7d_attempt_already_executed_idempotency_lock")
    if not director_signoff.strip():
        blockers.append("director_signoff_must_be_non_empty")
    elif not _director_signoff_mentions_gate(
        director_signoff, attempt.source_phase7b_gate_id or 0
    ):
        blockers.append("director_signoff_must_mention_phase7b_gate_id")

    key_advisory = _razorpay_key_advisory()
    if not key_advisory["razorpayKeyIdPresent"]:
        blockers.append("RAZORPAY_KEY_ID_must_be_present")
    elif key_advisory["razorpayKeyMode"] == "live":
        blockers.append(
            "RAZORPAY_KEY_ID_must_not_be_live_phase7d_refuses"
        )
    elif not key_advisory["isTestKey"]:
        blockers.append(
            "RAZORPAY_KEY_ID_must_start_with_rzp_test_for_phase7d"
        )

    kill_switch = _kill_switch_state()
    if not kill_switch.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    if attempt.amount_paise != PHASE_7D_MAX_AMOUNT_PAISE:
        blockers.append(
            f"phase7d_amount_paise_must_be_{PHASE_7D_MAX_AMOUNT_PAISE}"
        )

    eligibility = validate_phase7d_source_gate_eligibility(
        attempt.source_phase7b_gate_id, require_env_flag=False
    )
    if not eligibility.eligible:
        blockers.extend(eligibility.blockers)

    env_snapshot_start = _capture_env_flag_snapshot()
    attempt.env_flag_snapshot_at_start = env_snapshot_start
    attempt.kill_switch_snapshot = {
        **(attempt.kill_switch_snapshot or {}),
        "at_execute_start": kill_switch,
    }

    if blockers:
        attempt.blockers = list(blockers)
        attempt.status = RazorpayControlledPilotExecutionAttempt.Status.BLOCKED
        attempt.env_flag_snapshot_at_end = _capture_env_flag_snapshot()
        attempt.save(
            update_fields=[
                "blockers",
                "status",
                "env_flag_snapshot_at_start",
                "env_flag_snapshot_at_end",
                "kill_switch_snapshot",
                "updated_at",
            ]
        )
        write_event(
            kind=(
                AUDIT_KIND_KILL_SWITCH_BLOCKED
                if "runtime_kill_switch_disabled" in blockers
                else AUDIT_KIND_BLOCKED
            ),
            text=(
                f"Phase 7D execute blocked attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_attempt_payload(
                attempt,
                extra={"blockers": list(blockers)},
            ),
        )
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": list(blockers),
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "fix_phase7d_execute_blockers",
        }

    # All gates green. Acquire the idempotency lock.
    attempt.idempotency_lock_acquired = True
    attempt.director_signoff_text = (director_signoff or "")[:1000]
    attempt.director_signoff_present = True
    attempt.executed_by = confirmed_by
    attempt.save(
        update_fields=[
            "idempotency_lock_acquired",
            "director_signoff_text",
            "director_signoff_present",
            "executed_by",
            "env_flag_snapshot_at_start",
            "kill_switch_snapshot",
            "updated_at",
        ]
    )

    payload = _build_phase7d_test_order_payload(
        attempt_id=attempt.pk, receipt=attempt.receipt
    )
    summary: dict[str, Any] = {}
    sdk_error: str | None = None
    try:
        # Mark provider_call_attempted BEFORE the call so even an
        # exception preserves the audit trail.
        attempt.provider_call_attempted = True
        attempt.razorpay_call_attempted = True
        attempt.save(
            update_fields=[
                "provider_call_attempted",
                "razorpay_call_attempted",
                "updated_at",
            ]
        )
        response = _create_order_via_sdk(payload)
        summary = _summarize_razorpay_order_response(response)
    except Phase7DExecutionError as exc:
        sdk_error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        sdk_error = f"unexpected:{exc.__class__.__name__}"

    after_counts = _business_row_counts()
    env_snapshot_end = _capture_env_flag_snapshot()
    attempt.after_counts = after_counts
    attempt.env_flag_snapshot_at_end = env_snapshot_end
    attempt.kill_switch_snapshot = {
        **(attempt.kill_switch_snapshot or {}),
        "at_execute_end": _kill_switch_state(),
    }
    attempt.safe_request_summary = {
        "amount": PHASE_7D_MAX_AMOUNT_PAISE,
        "currency": PHASE_7D_DEFAULT_CURRENCY,
        "receipt": attempt.receipt,
    }

    if sdk_error or not summary.get("id"):
        attempt.status = RazorpayControlledPilotExecutionAttempt.Status.FAILED
        attempt.failed_at = timezone.now()
        attempt.warnings = list(attempt.warnings or []) + (
            [f"phase7d_execute_failed:{sdk_error}"] if sdk_error else []
        )
        attempt.save()
        # Defensive guard still runs.
        try:
            assert_phase7d_no_business_mutation(attempt)
        except ValueError:  # pragma: no cover - guard already audited
            pass
        write_event(
            kind=AUDIT_KIND_FAILED,
            text=(
                f"Phase 7D execute failed attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_attempt_payload(attempt),
        )
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": (
                [f"phase7d_execute_failed:{sdk_error}"]
                if sdk_error
                else ["phase7d_execute_succeeded_with_no_id"]
            ),
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "phase7d_execute_failed_review_attempt",
        }

    attempt.provider_object_id = summary["id"]
    attempt.provider_status = summary["status"] or "created"
    attempt.safe_response_summary = summary
    attempt.status = (
        RazorpayControlledPilotExecutionAttempt.Status.EXECUTED
    )
    attempt.executed_at = timezone.now()
    attempt.save()

    assert_phase7d_no_business_mutation(attempt)

    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=(
            f"Phase 7D execute succeeded attempt_id={attempt.pk} "
            f"provider_object_id={summary['id']}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7D",
        "ok": True,
        "attempt": serialize_phase7d_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7D_WARNING],
        "nextAction": (
            "phase7d_executed_record_rollback_when_director_directs"
        ),
    }


# ---------------------------------------------------------------------------
# Rollback (record-only; no provider call)
# ---------------------------------------------------------------------------


def rollback_phase7d_razorpay_test_execution_attempt(
    attempt_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Record-only rollback. NEVER calls Razorpay (TEST orders cannot
    be deleted). Sets ``rollback_status="completed"`` on success.
    """
    attempt = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7d_attempt_not_found"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status == (
        RazorpayControlledPilotExecutionAttempt.Status.ARCHIVED
    ):
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": ["phase7d_attempt_already_archived"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }

    timestamp = timezone.now().strftime("%Y%m%dT%H%M%S%f")
    record = RazorpayControlledPilotExecutionRollback.objects.create(
        attempt=attempt,
        verified_at=timezone.now(),
        rollback_status=(
            RazorpayControlledPilotExecutionRollback.DryRunStatus.COMPLETED
        ),
        rollback_reason=(reason or "")[:1000],
        env_flag_presence_at_rollback=_capture_env_flag_snapshot(),
        evaluated_safety_invariants=_safety_invariants(),
        provider_object_id_recorded=attempt.provider_object_id or "",
        recovery_notes="",
        idempotency_key=(
            f"phase7d::rollback::attempt::{attempt.pk}::run::{timestamp}"
        ),
    )

    attempt.rollback_status = (
        RazorpayControlledPilotExecutionAttempt.RollbackStatus.COMPLETED
    )
    attempt.rolled_back_at = timezone.now()
    attempt.rollback_reason = (reason or "")[:1000]
    attempt.rollback_recorded = True
    if attempt.status not in (
        RazorpayControlledPilotExecutionAttempt.Status.ARCHIVED,
        RazorpayControlledPilotExecutionAttempt.Status.ROLLED_BACK,
    ):
        attempt.status = (
            RazorpayControlledPilotExecutionAttempt.Status.ROLLED_BACK
        )
    attempt.save()

    assert_phase7d_no_business_mutation(attempt)

    write_event(
        kind=AUDIT_KIND_ROLLED_BACK,
        text=f"Phase 7D rollback recorded attempt_id={attempt.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(
            attempt,
            extra={"rollback_record_id": record.pk},
        ),
    )
    return {
        "phase": "7D",
        "ok": True,
        "attempt": serialize_phase7d_attempt(attempt),
        "rollback": serialize_phase7d_rollback(record),
        "blockers": [],
        "warnings": [PHASE_7D_WARNING],
        "nextAction": "phase7d_rollback_recorded",
    }


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def archive_phase7d_razorpay_test_execution_attempt(
    attempt_id: int,
    *,
    archived_by=None,
    reason: str = "",
) -> dict[str, Any]:
    attempt = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7d_attempt_not_found"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status == (
        RazorpayControlledPilotExecutionAttempt.Status.ARCHIVED
    ):
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": ["phase7d_attempt_already_archived"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_attempt_id",
        }
    assert_phase7d_no_business_mutation(attempt)
    attempt.status = (
        RazorpayControlledPilotExecutionAttempt.Status.ARCHIVED
    )
    attempt.archived_by = archived_by
    attempt.archived_at = timezone.now()
    attempt.archive_reason = (reason or "")[:200]
    attempt.save()
    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 7D attempt archived attempt_id={attempt.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7D",
        "ok": True,
        "attempt": serialize_phase7d_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7D_WARNING],
        "nextAction": "phase7d_attempt_archived",
    }


# ---------------------------------------------------------------------------
# Recovery (idempotency-key + provider-object-id reconciliation; no call)
# ---------------------------------------------------------------------------


def recover_phase7d_razorpay_test_execution_attempt(
    idempotency_key: str,
    provider_object_id: str,
) -> dict[str, Any]:
    """Reconcile by ``idempotency_key`` + ``provider_object_id`` only.
    NEVER calls Razorpay. Used when the provider call succeeded but
    the local DB write failed mid-call. Records the orphan
    ``provider_object_id`` on the attempt row and emits a recovery
    audit row.
    """
    if not idempotency_key.strip():
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["idempotency_key_required"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "supply_idempotency_key",
        }
    if not provider_object_id.strip():
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["provider_object_id_required"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "supply_provider_object_id",
        }
    attempt = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            idempotency_key=idempotency_key
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7D",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7d_attempt_not_found_for_idempotency_key"],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "verify_idempotency_key",
        }
    if (
        attempt.provider_object_id
        and attempt.provider_object_id != provider_object_id
    ):
        return {
            "phase": "7D",
            "ok": False,
            "attempt": serialize_phase7d_attempt(attempt),
            "blockers": [
                "phase7d_attempt_provider_object_id_mismatch_refusing"
            ],
            "warnings": [PHASE_7D_WARNING],
            "nextAction": "manual_director_review",
        }

    if not attempt.provider_object_id:
        attempt.provider_object_id = provider_object_id
        attempt.provider_status = (
            attempt.provider_status or "recovered_unknown_status"
        )
        attempt.safe_response_summary = {
            "id": provider_object_id,
            "status": attempt.provider_status,
            "amount": attempt.amount_paise,
            "currency": attempt.currency,
            "receipt": attempt.receipt,
            "created_at": 0,
        }
        attempt.provider_call_attempted = True
        attempt.razorpay_call_attempted = True
        if (
            attempt.status
            == RazorpayControlledPilotExecutionAttempt.Status.FAILED
        ):
            attempt.status = (
                RazorpayControlledPilotExecutionAttempt.Status.EXECUTED
            )
            attempt.executed_at = attempt.executed_at or timezone.now()
        attempt.save()

    assert_phase7d_no_business_mutation(attempt)

    write_event(
        kind=AUDIT_KIND_RECOVERY_RECONCILED,
        text=(
            f"Phase 7D recovery reconciled attempt_id={attempt.pk} "
            f"provider_object_id={provider_object_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7D",
        "ok": True,
        "attempt": serialize_phase7d_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7D_WARNING],
        "nextAction": "phase7d_recovery_reconciled",
    }


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase7d_attempts(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayControlledPilotExecutionAttempt.objects.all().order_by(
        "-created_at"
    )
    Status = RazorpayControlledPilotExecutionAttempt.Status
    counts = {
        "draft": qs.filter(status=Status.DRAFT).count(),
        "blocked": qs.filter(status=Status.BLOCKED).count(),
        "pendingDirectorSignoff": qs.filter(
            status=Status.PENDING_DIRECTOR_SIGNOFF
        ).count(),
        "approvedForOneShotRun": qs.filter(
            status=Status.APPROVED_FOR_ONE_SHOT_RUN
        ).count(),
        "executed": qs.filter(status=Status.EXECUTED).count(),
        "failed": qs.filter(status=Status.FAILED).count(),
        "rolledBack": qs.filter(status=Status.ROLLED_BACK).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "providerCallAttempted": qs.filter(
            provider_call_attempted=True
        ).count(),
        "businessMutationWasMade": qs.filter(
            business_mutation_was_made=True
        ).count(),
        "paymentLinkCreated": qs.filter(payment_link_created=True).count(),
        "paymentCaptured": qs.filter(payment_captured=True).count(),
        "paymentRefunded": qs.filter(payment_refunded=True).count(),
        "whatsAppMessageCreated": qs.filter(
            whatsapp_message_created=True
        ).count(),
        "whatsAppMessageQueued": qs.filter(
            whatsapp_message_queued=True
        ).count(),
        "shipmentCreated": qs.filter(shipment_created=True).count(),
        "awbCreated": qs.filter(awb_created=True).count(),
        "metaCloudCallAttempted": qs.filter(
            meta_cloud_call_attempted=True
        ).count(),
        "delhiveryCallAttempted": qs.filter(
            delhivery_call_attempted=True
        ).count(),
        "customerNotificationSent": qs.filter(
            customer_notification_sent=True
        ).count(),
    }
    sample = [
        serialize_phase7d_attempt(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"counts": counts, "items": sample}


def inspect_phase7d_razorpay_test_execution_readiness() -> dict[str, Any]:
    summary = summarize_phase7d_attempts()
    counts = summary["counts"]

    blockers: list[str] = []
    warnings: list[str] = [PHASE_7D_WARNING]

    for key in (
        "businessMutationWasMade",
        "paymentLinkCreated",
        "paymentCaptured",
        "paymentRefunded",
        "whatsAppMessageCreated",
        "whatsAppMessageQueued",
        "shipmentCreated",
        "awbCreated",
        "metaCloudCallAttempted",
        "delhiveryCallAttempted",
        "customerNotificationSent",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_7d_attempt_{key}_observed_must_be_zero"
            )

    approved_phase7b_gates = (
        RazorpayControlledPilotExecutionGate.objects.filter(
            status=RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
        ).count()
    )

    if blockers:
        next_action = "fix_phase_7d_safety_blockers"
    elif not _flag_execution_lifecycle_enabled():
        next_action = "enable_phase7d_lifecycle_flag_for_review_only"
    elif approved_phase7b_gates == 0:
        next_action = (
            "approve_at_least_one_phase_7b_gate_before_running_phase_7d"
        )
    elif counts["pendingDirectorSignoff"] == 0 and counts["approvedForOneShotRun"] == 0:
        next_action = "prepare_phase_7d_attempt_against_approved_phase7b_gate"
    elif counts["approvedForOneShotRun"] == 0:
        next_action = "approve_phase_7d_attempt_for_one_shot_run"
    else:
        next_action = (
            "phase7d_attempt_approved_for_one_shot_run_execute_only_with_separate_director_window"
        )

    safe_to_run = bool(
        not blockers
        and counts["approvedForOneShotRun"] >= 1
        and _flag_execution_lifecycle_enabled()
        and _flag_director_one_shot_approved()
        and _flag_allow_razorpay_test_order()
    )

    return {
        "phase": "7D",
        "status": "razorpay_test_execution_only",
        "latestCompletedPhase": "7B",
        "nextPhase": "7E_not_approved",
        "phase7DRazorpayTestExecutionEnabled": (
            _flag_execution_lifecycle_enabled()
        ),
        "phase7DDirectorApprovedOneShotExecution": (
            _flag_director_one_shot_approved()
        ),
        "phase7DAllowRazorpayTestOrder": (
            _flag_allow_razorpay_test_order()
        ),
        "phase7DSendsOrQueuesWhatsApp": False,
        "phase7DCreatesShipmentOrAwb": False,
        "phase7DMutatesBusinessRow": False,
        "phase7DCallsMetaCloud": False,
        "phase7DCallsDelhivery": False,
        "phase7DCreatesPaymentLink": False,
        "phase7DCapturesPayment": False,
        "phase7DRefundsPayment": False,
        "phase7DSendsCustomerNotification": False,
        "razorpayKeyAdvisory": _razorpay_key_advisory(),
        "killSwitch": _kill_switch_state(),
        "envFlagSnapshot": _capture_env_flag_snapshot(),
        "approvedPhase7BGateCount": approved_phase7b_gates,
        "attemptCounts": counts,
        "executionContract": (
            build_phase7d_controlled_pilot_execution_contract()
        ),
        "safetyInvariants": _safety_invariants(),
        "forbiddenActions": list(PHASE_7D_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "maxSafeAmountPaise": PHASE_7D_MAX_AMOUNT_PAISE,
        "currency": PHASE_7D_DEFAULT_CURRENCY,
        "envPosture": _safety_invariants()["envPosture"],
        "safeToRunPhase7DExecution": safe_to_run,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentAttempts": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("attemptCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7D Razorpay test execution readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": "7D",
            "phase7d_razorpay_test_execution_enabled": bool(
                report.get("phase7DRazorpayTestExecutionEnabled")
            ),
            "approved_phase7b_gate_count": int(
                report.get("approvedPhase7BGateCount") or 0
            ),
            "pending_director_signoff": int(
                counts.get("pendingDirectorSignoff") or 0
            ),
            "approved_for_one_shot_run": int(
                counts.get("approvedForOneShotRun") or 0
            ),
            "executed": int(counts.get("executed") or 0),
            "rolled_back": int(counts.get("rolledBack") or 0),
            "archived": int(counts.get("archived") or 0),
            "blockers": list(report.get("blockers") or []),
            "next_action": report.get("nextAction") or "",
            "kill_switch_state_at_emit": _kill_switch_state(),
            **_audit_locked_false_payload(),
        },
    )


__all__ = (
    "PHASE_7D_WARNING",
    "PHASE_7D_FORBIDDEN_ACTIONS",
    "PHASE_7D_FORBIDDEN_PAYLOAD_KEYS",
    "PHASE_7D_MAX_AMOUNT_PAISE",
    "RAZORPAY_TEST_KEY_PREFIX",
    "RAZORPAY_LIVE_KEY_PREFIX",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_APPROVED_FOR_ONE_SHOT",
    "AUDIT_KIND_EXECUTED",
    "AUDIT_KIND_FAILED",
    "AUDIT_KIND_ROLLED_BACK",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_KILL_SWITCH_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "AUDIT_KIND_RECOVERY_RECONCILED",
    "Phase7DEligibility",
    "Phase7DExecutionError",
    "build_phase7d_controlled_pilot_execution_contract",
    "validate_phase7d_source_gate_eligibility",
    "preview_phase7d_razorpay_test_execution_attempt",
    "prepare_phase7d_razorpay_test_execution_attempt",
    "approve_phase7d_razorpay_test_execution_attempt",
    "execute_phase7d_razorpay_test_order",
    "rollback_phase7d_razorpay_test_execution_attempt",
    "archive_phase7d_razorpay_test_execution_attempt",
    "recover_phase7d_razorpay_test_execution_attempt",
    "assert_phase7d_no_business_mutation",
    "serialize_phase7d_attempt",
    "serialize_phase7d_rollback",
    "summarize_phase7d_attempts",
    "inspect_phase7d_razorpay_test_execution_readiness",
    "emit_readiness_inspected_audit",
)
