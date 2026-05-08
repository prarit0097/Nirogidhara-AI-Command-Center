"""Phase 7F - Delhivery / Courier Controlled Readiness Gate.

Gate-only and CLI-only for review state changes. Phase 7F turns an
approved Phase 7E WhatsApp internal notification gate into an
audit-only readiness contract for a future Phase 7G courier
execution. Approval flips status to
``approved_for_future_phase7g_or_courier_execution_review`` only.

Hard scope rule (asserted by static-file scan tests): this module
**never** imports

* ``apps.shipments.integrations.delhivery_client.create_awb`` /
  ``_create_via_sdk``,
* ``apps.shipments.services.create_shipment`` /
  ``create_rescue_attempt`` / ``update_rescue_outcome``,
* ``apps.whatsapp.services.send_freeform_text_message`` /
  ``send_queued_message`` / ``queue_template_message``,
* ``apps.whatsapp.integrations.whatsapp.meta_cloud_client``,
* ``apps.payments.integrations.razorpay_client``,
* ``dotenv`` (any form).

Read-only count diagnostics on
``apps.shipments.models.{Shipment,WorkflowStep,RescueAttempt}`` and
``apps.whatsapp.models.{WhatsAppMessage,WhatsAppLifecycleEvent,
WhatsAppHandoffToCall}`` are allowed - never ``.create()`` /
``.update()`` / ``.save()``.

Phase 7F never calls Delhivery, never creates a ``Shipment`` /
``WorkflowStep`` / ``RescueAttempt`` row, never creates an AWB,
never books a pickup, never generates a courier label, never sends
or queues WhatsApp, never calls Meta Cloud / Razorpay / Vapi, never
sends a customer notification, never mutates real ``Order`` /
``Payment`` / ``Customer`` / ``Lead`` / ``DiscountOfferLog`` rows,
never edits any ``.env*`` file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)

from .models import (
    Payment,
    RazorpayControlledPilotExecutionAttempt,
    RazorpayControlledPilotExecutionGate,
    RazorpayCourierReadinessDryRunRecord,
    RazorpayCourierReadinessGate,
    RazorpayPhase6FinalAuditLock,
    RazorpayWhatsAppInternalNotificationGate,
)


# ---------------------------------------------------------------------------
# Constants - safety contract, audit kinds, forbidden actions
# ---------------------------------------------------------------------------


PHASE_7F_WARNING = (
    "Phase 7F is a Delhivery / Courier Controlled Readiness Gate. It "
    "NEVER calls the Delhivery API, NEVER creates a Shipment / "
    "WorkflowStep / RescueAttempt row, NEVER creates an AWB, NEVER "
    "books a pickup, NEVER generates a courier label, NEVER sends or "
    "queues WhatsApp, NEVER calls Meta Cloud / Razorpay / Vapi, NEVER "
    "sends a customer notification, NEVER mutates real Order / "
    "Payment / Customer / Lead rows, and NEVER edits any .env file. "
    "Approval flips status to "
    "approved_for_future_phase7g_or_courier_execution_review only - "
    "it does NOT enable any provider call."
)


AUDIT_KIND_READINESS = (
    "razorpay.courier_readiness.readiness_inspected"
)
AUDIT_KIND_PREVIEWED = "razorpay.courier_readiness.previewed"
AUDIT_KIND_PREPARED = "razorpay.courier_readiness.prepared"
AUDIT_KIND_DRY_RUN_PASSED = (
    "razorpay.courier_readiness.dry_run_passed"
)
AUDIT_KIND_DRY_RUN_FAILED = (
    "razorpay.courier_readiness.dry_run_failed"
)
AUDIT_KIND_RB_DRY_RUN_PASSED = (
    "razorpay.courier_readiness.rb_dry_run_passed"
)
AUDIT_KIND_RB_DRY_RUN_FAILED = (
    "razorpay.courier_readiness.rb_dry_run_failed"
)
AUDIT_KIND_APPROVED_FUTURE_COURIER = (
    "razorpay.courier_readiness.approved_future_courier"
)
AUDIT_KIND_REJECTED = "razorpay.courier_readiness.rejected"
AUDIT_KIND_ARCHIVED = "razorpay.courier_readiness.archived"
AUDIT_KIND_BLOCKED = "razorpay.courier_readiness.blocked"
AUDIT_KIND_KILL_SWITCH_BLOCKED = (
    "razorpay.courier_readiness.kill_switch_blocked"
)
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.courier_readiness.invariant_violation"
)


PHASE_7F_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "call_delhivery_api",
    "call_delhivery_create_awb",
    "call_delhivery_book_pickup",
    "call_delhivery_generate_label",
    "call_delhivery_track_awb",
    "call_delhivery_cancel_awb",
    "create_shipment_row",
    "create_workflow_step_row",
    "create_rescue_attempt_row",
    "create_awb",
    "book_courier_pickup",
    "generate_courier_label",
    "print_courier_label",
    "send_customer_notification",
    "send_whatsapp_template",
    "send_whatsapp_freeform",
    "queue_whatsapp_outbound",
    "call_meta_cloud_api",
    "call_razorpay_api",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "mutate_real_order_status",
    "mutate_real_payment_status",
    "mutate_real_shipment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "execute_via_frontend",
    "execute_via_api_endpoint",
    "approve_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_7F_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "token",
    "phone",
    "email",
    "address",
    "pincode",
    "pin_code",
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
    "DELHIVERY_API_TOKEN",
    "raw_payload",
    "raw_signature",
    "raw_secret",
)


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


def _flag_phase7f_gate_enabled() -> bool:
    return bool(
        getattr(
            settings, "PHASE7F_COURIER_READINESS_GATE_ENABLED", False
        )
    )


def _capture_env_flag_snapshot() -> dict[str, Any]:
    return {
        "PHASE7F_COURIER_READINESS_GATE_ENABLED": (
            _flag_phase7f_gate_enabled()
        ),
        "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED": bool(
            getattr(
                settings,
                "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED",
                False,
            )
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
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED": bool(
            getattr(
                settings, "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
                False,
            )
        ),
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED": bool(
            getattr(
                settings, "PHASE7_CONTROLLED_PILOT_GATE_ENABLED", False
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


def _delhivery_env_presence() -> dict[str, bool]:
    """Presence-only booleans on Delhivery env vars. NEVER values."""
    return {
        "DELHIVERY_API_TOKEN_present": bool(
            (getattr(settings, "DELHIVERY_API_TOKEN", "") or "").strip()
        ),
        "DELHIVERY_API_BASE_URL_present": bool(
            (
                getattr(settings, "DELHIVERY_API_BASE_URL", "") or ""
            ).strip()
        ),
        "DELHIVERY_PICKUP_LOCATION_present": bool(
            (
                getattr(settings, "DELHIVERY_PICKUP_LOCATION", "") or ""
            ).strip()
        ),
        "DELHIVERY_RETURN_ADDRESS_present": bool(
            (
                getattr(settings, "DELHIVERY_RETURN_ADDRESS", "") or ""
            ).strip()
        ),
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


def _phase7d_hotfix_1_present() -> bool:
    """Defence-in-depth: confirm the Hotfix-1 validator is importable."""
    try:
        from apps.saas.utc_window import (  # noqa: F401
            validate_within_director_window,
        )
    except Exception:
        return False
    return True


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
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }


def _safety_invariants() -> dict[str, Any]:
    return {
        "delhiveryCallAllowedInPhase7F": False,
        "courierBookingAllowedInPhase7F": False,
        "shipmentCreationAllowedInPhase7F": False,
        "awbCreationAllowedInPhase7F": False,
        "pickupBookingAllowedInPhase7F": False,
        "labelGenerationAllowedInPhase7F": False,
        "customerNotificationAllowedInPhase7F": False,
        "whatsappSendAllowedInPhase7F": False,
        "whatsappQueueAllowedInPhase7F": False,
        "metaCloudCallAllowedInPhase7F": False,
        "razorpayCallAllowedInPhase7F": False,
        "businessMutationAllowedInPhase7F": False,
        "realCustomerAllowedInPhase7F": False,
        "providerCallAttempted": False,
        "delhiveryCallAttempted": False,
        "shipmentCreated": False,
        "awbCreated": False,
        "pickupBooked": False,
        "labelGenerated": False,
        "customerNotificationSent": False,
        "realOrderMutationWasMade": False,
        "realPaymentMutationWasMade": False,
        "realShipmentMutationWasMade": False,
        "phase7FApprovalImpliesLiveCourier": False,
        "phase7FRequiresFutureExecuteWindowGuardForCourier": True,
    }


def assert_phase7f_no_courier_or_business_mutation(
    gate: RazorpayCourierReadinessGate,
    *,
    before_counts: Optional[dict[str, int]] = None,
) -> None:
    """Defensive guard.

    Raises ``ValueError`` and emits an invariant-violation audit row
    if any locked-False boolean has flipped or any of the 11 business
    table counts has moved between ``before_counts`` and the current
    snapshot.
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
                    f"phase7f_business_row_count_changed_for_{key}"
                )

    if flipped or delta_blockers:
        write_event(
            kind=AUDIT_KIND_INVARIANT_VIOLATION,
            text=f"Phase 7F invariant violation gate_id={gate.pk}",
            tone=AuditEvent.Tone.DANGER,
            payload={
                "phase": "7F",
                "gate_id": gate.pk,
                "flipped_booleans": list(flipped),
                "row_count_blockers": list(delta_blockers),
                **{
                    k: False
                    for k, v in invariants.items()
                    if isinstance(v, bool) and not v
                },
            },
        )
        raise ValueError(
            "Phase 7F invariant violation: "
            f"flipped={flipped} row_deltas={delta_blockers}"
        )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def build_phase7f_courier_readiness_contract() -> dict[str, Any]:
    return {
        "phase": "7F",
        "status": "courier_readiness_only",
        "executionPath": "cli_only",
        "executeIsCliOnly": True,
        "phase7FCallsDelhivery": False,
        "phase7FCreatesShipmentRow": False,
        "phase7FCreatesAwb": False,
        "phase7FBooksPickup": False,
        "phase7FGeneratesLabel": False,
        "phase7FSendsWhatsApp": False,
        "phase7FQueuesWhatsApp": False,
        "phase7FCallsMetaCloud": False,
        "phase7FCallsRazorpay": False,
        "phase7FSendsCustomerNotification": False,
        "phase7FMutatesBusinessRow": False,
        "phase7FTouchesRealCustomerPhoneNumber": False,
        "phase7FTouchesRealCustomerAddress": False,
        "phase7FWritesEnvFile": False,
        "phase7FImportsDotenv": False,
        "phase7FApprovalImpliesLiveCourier": False,
        "phase7DSourceSignoffMayBeLegacyFreeTextWithAck": True,
        "phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand": True,
        "phase7FRequiresFutureExecuteWindowGuardForCourier": True,
        "manualReviewRequired": True,
        "internalStaffOnly": True,
        "nextPhaseForLiveCourier": "phase_7g_or_courier_live_not_approved",
        "forbiddenActions": list(PHASE_7F_FORBIDDEN_ACTIONS),
        "forbiddenPayloadKeys": list(PHASE_7F_FORBIDDEN_PAYLOAD_KEYS),
    }


# ---------------------------------------------------------------------------
# Eligibility validator
# ---------------------------------------------------------------------------


@dataclass
class Phase7FEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    phase7e_gate: Optional[RazorpayWhatsAppInternalNotificationGate]
    phase7d_attempt: Optional[RazorpayControlledPilotExecutionAttempt]
    phase7b_gate: Optional[RazorpayControlledPilotExecutionGate]
    phase6t_lock: Optional[RazorpayPhase6FinalAuditLock]
    source_phase7d_signoff_window_validation_status: str
    phase7d_hotfix_1_present: bool


def _classify_source_phase7d_signoff_window_status(
    attempt: RazorpayControlledPilotExecutionAttempt,
) -> str:
    if not (attempt.director_signoff_text or "").strip():
        return "not_applicable"
    valid_attr = getattr(attempt, "recorded_signoff_window_valid", None)
    if valid_attr is True:
        return "valid_structured_window"
    return "failed_or_legacy_free_text"


def validate_phase7f_source_eligibility(
    phase7e_gate_id: Optional[int],
    *,
    require_env_flag: bool = True,
) -> Phase7FEligibility:
    blockers: list[str] = []
    warnings: list[str] = []
    phase7e_gate: Optional[RazorpayWhatsAppInternalNotificationGate] = None
    phase7d_attempt: Optional[RazorpayControlledPilotExecutionAttempt] = None
    phase7b_gate: Optional[RazorpayControlledPilotExecutionGate] = None
    phase6t_lock: Optional[RazorpayPhase6FinalAuditLock] = None
    signoff_status = "not_applicable"

    hotfix_present = _phase7d_hotfix_1_present()
    if not hotfix_present:
        blockers.append(
            "phase7d_hotfix_1_must_be_shipped_before_phase7f_review"
        )

    if require_env_flag and not _flag_phase7f_gate_enabled():
        blockers.append(
            "PHASE7F_COURIER_READINESS_GATE_ENABLED_must_be_true"
        )

    if phase7e_gate_id:
        phase7e_gate = (
            RazorpayWhatsAppInternalNotificationGate.objects.filter(
                pk=phase7e_gate_id
            )
            .select_related(
                "source_phase7d_attempt",
                "source_phase7b_gate",
                "source_phase6t_lock",
            )
            .first()
        )
    if phase7e_gate is None:
        blockers.append("phase_7e_source_gate_not_found")
        return Phase7FEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            phase7e_gate=None,
            phase7d_attempt=None,
            phase7b_gate=None,
            phase6t_lock=None,
            source_phase7d_signoff_window_validation_status=(
                signoff_status
            ),
            phase7d_hotfix_1_present=hotfix_present,
        )

    # Phase 7E gate must be approved.
    if (
        phase7e_gate.status
        != RazorpayWhatsAppInternalNotificationGate.Status.APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW
    ):
        blockers.append(
            f"phase_7e_gate_status_must_be_approved_was_{phase7e_gate.status}"
        )
    if not phase7e_gate.dry_run_passed:
        blockers.append("phase_7e_gate_dry_run_passed_must_be_true")
    if not phase7e_gate.rollback_dry_run_passed:
        blockers.append(
            "phase_7e_gate_rollback_dry_run_passed_must_be_true"
        )
    if not phase7e_gate.claim_vault_grounded:
        blockers.append("phase_7e_gate_claim_vault_grounded_must_be_true")
    if not phase7e_gate.phase7e_future_review_signoff_window_valid:
        blockers.append(
            "phase_7e_gate_future_review_signoff_window_must_be_valid"
        )

    phase7d_attempt = phase7e_gate.source_phase7d_attempt
    phase7b_gate = phase7e_gate.source_phase7b_gate
    phase6t_lock = phase7e_gate.source_phase6t_lock

    if phase7d_attempt is None:
        blockers.append("phase_7d_source_attempt_not_found")
    else:
        ok_status = {
            RazorpayControlledPilotExecutionAttempt.Status.EXECUTED,
            RazorpayControlledPilotExecutionAttempt.Status.ROLLED_BACK,
        }
        if phase7d_attempt.status not in ok_status:
            blockers.append(
                f"phase_7d_attempt_status_must_be_executed_or_rolled_back_was_{phase7d_attempt.status}"
            )
        if (
            phase7d_attempt.rollback_status
            != RazorpayControlledPilotExecutionAttempt.RollbackStatus.COMPLETED
        ):
            blockers.append(
                "phase_7d_attempt_rollback_status_must_be_completed"
            )
        if not phase7d_attempt.provider_call_attempted:
            blockers.append(
                "phase_7d_attempt_provider_call_attempted_must_be_true"
            )
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
        ):
            if getattr(phase7d_attempt, field, False):
                blockers.append(
                    f"phase_7d_attempt_{field}_must_be_false"
                )
        signoff_status = _classify_source_phase7d_signoff_window_status(
            phase7d_attempt
        )

    if phase7b_gate is not None:
        if (
            phase7b_gate.status
            != RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
        ):
            blockers.append(
                "phase_7b_gate_status_must_be_approved_for_future_phase7c_review"
            )
    else:
        blockers.append("phase_7b_source_gate_not_found")

    if phase6t_lock is None:
        blockers.append("phase_6t_audit_lock_not_found")
    elif (
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

    snapshot = _capture_env_flag_snapshot()
    # WhatsApp automation flags must be off.
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

    provider = snapshot.get("WHATSAPP_PROVIDER", "mock")
    if provider != "mock" and not snapshot.get(
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False
    ):
        blockers.append(
            "whatsapp_provider_must_be_mock_or_limited_test_mode_active"
        )

    # DELHIVERY_MODE must be mock or test (NEVER live).
    delhivery_mode = snapshot.get("DELHIVERY_MODE")
    if delhivery_mode not in {"mock", "test"}:
        blockers.append(
            f"DELHIVERY_MODE_must_be_mock_or_test_was_{delhivery_mode}"
        )

    # Phase 6K / 7D execute env flags must all be false.
    for flag in (
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED",
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION",
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER",
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
    ):
        if snapshot.get(flag) is True:
            blockers.append(f"{flag}_must_be_false")

    # Defence-in-depth: no Shipment row referencing the source attempt.
    if phase7d_attempt is not None:
        provider_object_id = (
            phase7d_attempt.provider_object_id or ""
        ).strip()
        if provider_object_id:
            leak = Shipment.objects.filter(
                awb=provider_object_id
            ).exists()
            if leak:
                blockers.append(
                    "phase_7f_unexpected_shipment_row_for_source_attempt_present"
                )

    if signoff_status == "failed_or_legacy_free_text":
        warnings.append(
            "phase_7d_source_signoff_was_legacy_free_text_phase_7e_already_acknowledged"
        )

    return Phase7FEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        phase7e_gate=phase7e_gate,
        phase7d_attempt=phase7d_attempt,
        phase7b_gate=phase7b_gate,
        phase6t_lock=phase6t_lock,
        source_phase7d_signoff_window_validation_status=signoff_status,
        phase7d_hotfix_1_present=hotfix_present,
    )


# ---------------------------------------------------------------------------
# Serializers (whitelist - never customer PII / signoff text / secrets)
# ---------------------------------------------------------------------------


def serialize_phase7f_gate(
    row: RazorpayCourierReadinessGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase7EGateId": row.source_phase7e_gate_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sourcePhase7BGateId": row.source_phase7b_gate_id,
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        "delhiveryModeAtPrepare": row.delhivery_mode_at_prepare,
        "delhiveryEnvTokenPresent": bool(row.delhivery_env_token_present),
        "delhiveryEnvBaseUrlPresent": bool(
            row.delhivery_env_base_url_present
        ),
        "delhiveryEnvPickupLocationPresent": bool(
            row.delhivery_env_pickup_location_present
        ),
        "delhiveryEnvReturnAddressPresent": bool(
            row.delhivery_env_return_address_present
        ),
        "sourcePhase7DSignoffWindowValidationStatus": (
            row.source_phase7d_signoff_window_validation_status
        ),
        "phase7DHotfix1Present": bool(row.phase7d_hotfix_1_present),
        "dryRunPassed": bool(row.dry_run_passed),
        "dryRunFailedReasons": list(row.dry_run_failed_reasons or []),
        "rollbackDryRunPassed": bool(row.rollback_dry_run_passed),
        "rollbackDryRunFailedReasons": list(
            row.rollback_dry_run_failed_reasons or []
        ),
        # Locked-False booleans always returned for the section to render.
        "delhiveryCallAllowedInPhase7F": False,
        "courierBookingAllowedInPhase7F": False,
        "shipmentCreationAllowedInPhase7F": False,
        "awbCreationAllowedInPhase7F": False,
        "pickupBookingAllowedInPhase7F": False,
        "labelGenerationAllowedInPhase7F": False,
        "customerNotificationAllowedInPhase7F": False,
        "whatsappSendAllowedInPhase7F": False,
        "whatsappQueueAllowedInPhase7F": False,
        "metaCloudCallAllowedInPhase7F": False,
        "razorpayCallAllowedInPhase7F": False,
        "businessMutationAllowedInPhase7F": False,
        "realCustomerAllowedInPhase7F": False,
        "providerCallAttempted": False,
        "delhiveryCallAttempted": False,
        "shipmentCreated": False,
        "awbCreated": False,
        "pickupBooked": False,
        "labelGenerated": False,
        "customerNotificationSent": False,
        "realOrderMutationWasMade": False,
        "realPaymentMutationWasMade": False,
        "realShipmentMutationWasMade": False,
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


def serialize_phase7f_dry_run_record(
    row: RazorpayCourierReadinessDryRunRecord,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "kind": row.kind,
        "status": row.status,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# Audit payload helper (always strips forbidden keys)
# ---------------------------------------------------------------------------


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"phase": "7F"}
    forbidden = set(PHASE_7F_FORBIDDEN_PAYLOAD_KEYS)
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


def _audit_gate_payload(
    gate: RazorpayCourierReadinessGate,
) -> dict[str, Any]:
    return _safe_audit_payload(
        {
            "gate_id": gate.pk,
            "status": gate.status,
            "phase7e_gate_id": gate.source_phase7e_gate_id,
            "phase7d_attempt_id": gate.source_phase7d_attempt_id,
            "phase7b_gate_id": gate.source_phase7b_gate_id,
            "phase6t_lock_id": gate.source_phase6t_lock_id,
            "delhivery_mode": gate.delhivery_mode_at_prepare,
            "phase7d_hotfix_1_present": bool(
                gate.phase7d_hotfix_1_present
            ),
            "source_phase7d_signoff_window_validation_status": (
                gate.source_phase7d_signoff_window_validation_status
            ),
            "dry_run_passed": bool(gate.dry_run_passed),
            "rollback_dry_run_passed": bool(gate.rollback_dry_run_passed),
            "kill_switch_enabled": _kill_switch_state().get(
                "enabled", True
            ),
            "blockers": list(gate.blockers or []),
        }
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7f_gate(phase7e_gate_id: int) -> dict[str, Any]:
    """Read-only preview from a Phase 7E approved gate. Never creates rows."""
    eligibility = validate_phase7f_source_eligibility(
        phase7e_gate_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7F preview phase7e_gate_id={phase7e_gate_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7e_gate_id": phase7e_gate_id,
                "eligible": eligibility.eligible,
                "blockers": list(eligibility.blockers),
                "phase7d_hotfix_1_present": (
                    eligibility.phase7d_hotfix_1_present
                ),
                "source_phase7d_signoff_window_validation_status": (
                    eligibility.source_phase7d_signoff_window_validation_status
                ),
            }
        ),
    )
    return {
        "phase": "7F",
        "found": eligibility.phase7e_gate is not None,
        "sourcePhase7EGateId": phase7e_gate_id,
        "sourcePhase7DAttemptId": (
            eligibility.phase7d_attempt.pk
            if eligibility.phase7d_attempt
            else None
        ),
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
        "phase7DHotfix1Present": eligibility.phase7d_hotfix_1_present,
        "delhiveryEnvPresence": _delhivery_env_presence(),
        "delhiveryModeAtPreview": _capture_env_flag_snapshot().get(
            "DELHIVERY_MODE", "mock"
        ),
        "eligible": eligibility.eligible,
        "proposedContract": (
            build_phase7f_courier_readiness_contract()
        ),
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_7F_WARNING],
        "nextAction": (
            "ready_to_prepare_phase7f_courier_readiness_gate"
            if eligibility.eligible and _flag_phase7f_gate_enabled()
            else (
                "fix_phase_7f_eligibility_blockers_or_enable_phase7f_gate_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(
    phase7e_gate: RazorpayWhatsAppInternalNotificationGate,
) -> str:
    return (
        f"phase7f::courier_readiness::phase7e_gate::{phase7e_gate.pk}"
    )


def prepare_phase7f_gate(
    phase7e_gate_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Atomic, idempotent prepare. One Phase 7F gate per Phase 7E gate."""
    eligibility = validate_phase7f_source_eligibility(
        phase7e_gate_id, require_env_flag=True
    )
    if (
        not eligibility.eligible
        or eligibility.phase7e_gate is None
        or eligibility.phase7d_attempt is None
        or eligibility.phase7b_gate is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7F prepare blocked phase7e_gate_id={phase7e_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7e_gate_id": phase7e_gate_id,
                    "blockers": list(eligibility.blockers),
                }
            ),
        )
        return {
            "phase": "7F",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_7F_WARNING],
            "nextAction": (
                "fix_phase_7f_eligibility_blockers_or_enable_phase7f_gate_flag"
            ),
        }

    phase7e_gate = eligibility.phase7e_gate
    idem_key = _idempotency_key(phase7e_gate)
    before = _business_row_counts()
    snapshot = _capture_env_flag_snapshot()
    kill_state = _kill_switch_state()
    invariants = _safety_invariants()
    delhivery_presence = _delhivery_env_presence()

    with transaction.atomic():
        existing = (
            RazorpayCourierReadinessGate.objects.filter(
                idempotency_key=idem_key
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            write_event(
                kind=AUDIT_KIND_PREPARED,
                text=f"Phase 7F prepare reused gate_id={existing.pk}",
                tone=AuditEvent.Tone.INFO,
                payload=_audit_gate_payload(existing),
            )
            return {
                "phase": "7F",
                "created": False,
                "reused": True,
                "gate": serialize_phase7f_gate(existing),
                "blockers": [],
                "warnings": list(eligibility.warnings) + [PHASE_7F_WARNING],
                "nextAction": "ready_for_phase7f_dry_run",
            }

        gate = RazorpayCourierReadinessGate.objects.create(
            source_phase7e_gate=phase7e_gate,
            source_phase7d_attempt=eligibility.phase7d_attempt,
            source_phase7b_gate=eligibility.phase7b_gate,
            source_phase6t_lock=eligibility.phase6t_lock,
            status=RazorpayCourierReadinessGate.Status.PENDING_MANUAL_REVIEW,
            delhivery_mode_at_prepare=str(
                snapshot.get("DELHIVERY_MODE", "mock")
            ),
            delhivery_env_token_present=delhivery_presence[
                "DELHIVERY_API_TOKEN_present"
            ],
            delhivery_env_base_url_present=delhivery_presence[
                "DELHIVERY_API_BASE_URL_present"
            ],
            delhivery_env_pickup_location_present=delhivery_presence[
                "DELHIVERY_PICKUP_LOCATION_present"
            ],
            delhivery_env_return_address_present=delhivery_presence[
                "DELHIVERY_RETURN_ADDRESS_present"
            ],
            source_phase7d_signoff_window_validation_status=(
                eligibility.source_phase7d_signoff_window_validation_status
            ),
            phase7d_hotfix_1_present=(
                eligibility.phase7d_hotfix_1_present
            ),
            kill_switch_snapshot_at_each_step={"prepare": kill_state},
            env_flag_snapshot_at_each_step={"prepare": snapshot},
            safety_invariants_snapshot=invariants,
            before_counts=before,
            after_counts=before,
            idempotency_key=idem_key,
            blockers=[],
            warnings=list(eligibility.warnings),
            next_action="ready_for_phase7f_dry_run",
            requested_by=requested_by,
        )

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 7F prepare created gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7F",
        "created": True,
        "reused": False,
        "gate": serialize_phase7f_gate(gate),
        "blockers": [],
        "warnings": list(eligibility.warnings) + [PHASE_7F_WARNING],
        "nextAction": "ready_for_phase7f_dry_run",
    }


# ---------------------------------------------------------------------------
# Dry run / rollback dry run
# ---------------------------------------------------------------------------


def _dry_run_idempotency_key(gate_id: int) -> str:
    timestamp = timezone.now().strftime("%Y%m%dT%H%M%S%f")
    return (
        f"phase7f::courier_readiness::dry_run::gate::{gate_id}"
        f"::run::{timestamp}"
    )


def _rollback_dry_run_idempotency_key(gate_id: int) -> str:
    timestamp = timezone.now().strftime("%Y%m%dT%H%M%S%f")
    return (
        f"phase7f::courier_readiness::rollback_dry_run::gate::{gate_id}"
        f"::run::{timestamp}"
    )


def _shipment_leak_check(
    gate: RazorpayCourierReadinessGate,
) -> list[str]:
    """Refuse the dry-run if a Shipment row references the source
    Phase 7D attempt's provider_object_id. Defence-in-depth.
    """
    blockers: list[str] = []
    attempt = gate.source_phase7d_attempt
    if attempt is None:
        return blockers
    provider_object_id = (attempt.provider_object_id or "").strip()
    if provider_object_id and Shipment.objects.filter(
        awb=provider_object_id
    ).exists():
        blockers.append(
            "phase7f_unexpected_shipment_row_for_source_attempt_present"
        )
    return blockers


def dry_run_phase7f_gate(gate_id: int) -> dict[str, Any]:
    gate = (
        RazorpayCourierReadinessGate.objects.filter(pk=gate_id).first()
    )
    if gate is None:
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_gate_not_found"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "verify_gate_id",
        }
    if (
        gate.status
        != RazorpayCourierReadinessGate.Status.PENDING_MANUAL_REVIEW
    ):
        return {
            "phase": "7F",
            "ok": False,
            "gate": serialize_phase7f_gate(gate),
            "blockers": [
                f"phase7f_gate_status_must_be_pending_manual_review_was_{gate.status}"
            ],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    leak = _shipment_leak_check(gate)
    assert_phase7f_no_courier_or_business_mutation(
        gate, before_counts=before
    )
    after = _business_row_counts()

    record_blockers: list[str] = list(leak)
    if before != after:
        record_blockers.append(
            "phase7f_business_row_count_changed_during_dry_run"
        )
    passed = not record_blockers

    record = (
        RazorpayCourierReadinessDryRunRecord.objects.create(
            gate=gate,
            kind=RazorpayCourierReadinessDryRunRecord.Kind.DRY_RUN,
            status=(
                RazorpayCourierReadinessDryRunRecord.Status.PASSED
                if passed
                else RazorpayCourierReadinessDryRunRecord.Status.FAILED
            ),
            idempotency_key=_dry_run_idempotency_key(gate.pk),
            safety_invariants_snapshot=_safety_invariants(),
            before_counts=before,
            after_counts=after,
            blockers=record_blockers,
            warnings=[],
            reason="",
        )
    )

    gate.dry_run_passed = passed
    gate.dry_run_failed_reasons = record_blockers if not passed else []
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
        "ready_for_phase7f_rollback_dry_run"
        if passed
        else "fix_phase7f_dry_run_blockers"
    )
    gate.save()

    write_event(
        kind=(
            AUDIT_KIND_DRY_RUN_PASSED
            if passed
            else AUDIT_KIND_DRY_RUN_FAILED
        ),
        text=f"Phase 7F dry-run gate_id={gate.pk} passed={passed}",
        tone=AuditEvent.Tone.INFO if passed else AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7F",
        "ok": passed,
        "gate": serialize_phase7f_gate(gate),
        "record": serialize_phase7f_dry_run_record(record),
        "blockers": record_blockers,
        "warnings": [PHASE_7F_WARNING],
        "nextAction": gate.next_action,
    }


def rollback_dry_run_phase7f_gate(
    gate_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_rollback_dry_run_reason_required"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "supply_reason",
        }
    gate = (
        RazorpayCourierReadinessGate.objects.filter(pk=gate_id).first()
    )
    if gate is None:
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_gate_not_found"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not gate.dry_run_passed:
        return {
            "phase": "7F",
            "ok": False,
            "gate": serialize_phase7f_gate(gate),
            "blockers": ["phase7f_dry_run_must_have_passed_first"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "run_phase7f_dry_run_first",
        }

    before = _business_row_counts()
    assert_phase7f_no_courier_or_business_mutation(
        gate, before_counts=before
    )
    after = _business_row_counts()

    record_blockers: list[str] = []
    if before != after:
        record_blockers.append(
            "phase7f_business_row_count_changed_during_rollback_dry_run"
        )
    passed = not record_blockers

    record = (
        RazorpayCourierReadinessDryRunRecord.objects.create(
            gate=gate,
            kind=(
                RazorpayCourierReadinessDryRunRecord.Kind.ROLLBACK_DRY_RUN
            ),
            status=(
                RazorpayCourierReadinessDryRunRecord.Status.PASSED
                if passed
                else RazorpayCourierReadinessDryRunRecord.Status.FAILED
            ),
            idempotency_key=_rollback_dry_run_idempotency_key(gate.pk),
            safety_invariants_snapshot=_safety_invariants(),
            before_counts=before,
            after_counts=after,
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
        "ready_for_phase7f_approve"
        if passed
        else "fix_phase7f_rollback_dry_run_blockers"
    )
    gate.save()

    write_event(
        kind=(
            AUDIT_KIND_RB_DRY_RUN_PASSED
            if passed
            else AUDIT_KIND_RB_DRY_RUN_FAILED
        ),
        text=(
            f"Phase 7F rollback-dry-run gate_id={gate.pk} passed={passed}"
        ),
        tone=AuditEvent.Tone.INFO if passed else AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "7F",
        "ok": passed,
        "gate": serialize_phase7f_gate(gate),
        "record": serialize_phase7f_dry_run_record(record),
        "blockers": record_blockers,
        "warnings": [PHASE_7F_WARNING],
        "nextAction": gate.next_action,
    }


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


def approve_phase7f_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Phase 7F approve takes ONLY a non-empty reason.

    No ``--director-signoff`` argument. Live courier dispatch
    requires Phase 7G + a future execute-window guard.
    """
    if not reason.strip():
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_approve_reason_required"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "supply_reason",
        }
    gate = (
        RazorpayCourierReadinessGate.objects.filter(pk=gate_id).first()
    )
    if gate is None:
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_gate_not_found"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "verify_gate_id",
        }

    blockers: list[str] = []
    if (
        gate.status
        != RazorpayCourierReadinessGate.Status.PENDING_MANUAL_REVIEW
    ):
        blockers.append(
            f"phase7f_gate_status_must_be_pending_manual_review_was_{gate.status}"
        )
    if not gate.dry_run_passed:
        blockers.append("phase7f_dry_run_passed_must_be_true")
    if not gate.rollback_dry_run_passed:
        blockers.append("phase7f_rollback_dry_run_passed_must_be_true")
    if not gate.phase7d_hotfix_1_present:
        blockers.append(
            "phase7d_hotfix_1_must_be_shipped_before_phase7f_approve"
        )
    if not _phase7d_hotfix_1_present():
        # Re-check at approve time in case the validator was removed
        # between prepare and approve.
        blockers.append(
            "phase7d_hotfix_1_validator_unimportable_at_approve_time"
        )

    if blockers:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7F approve blocked gate_id={gate.pk}",
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(gate)
            | {"approve_blockers": blockers},
        )
        return {
            "phase": "7F",
            "ok": False,
            "gate": serialize_phase7f_gate(gate),
            "blockers": blockers,
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "fix_phase7f_approve_blockers",
        }

    before = _business_row_counts()
    assert_phase7f_no_courier_or_business_mutation(
        gate, before_counts=before
    )

    gate.status = (
        RazorpayCourierReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE7G_OR_COURIER_EXECUTION_REVIEW
    )
    gate.approved_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.kill_switch_snapshot_at_each_step = {
        **(gate.kill_switch_snapshot_at_each_step or {}),
        "approve": _kill_switch_state(),
    }
    gate.env_flag_snapshot_at_each_step = {
        **(gate.env_flag_snapshot_at_each_step or {}),
        "approve": _capture_env_flag_snapshot(),
    }
    gate.next_action = (
        "phase7f_gate_approved_for_future_phase7g_or_courier_execution_review"
    )
    gate.save()

    write_event(
        kind=AUDIT_KIND_APPROVED_FUTURE_COURIER,
        text=f"Phase 7F approved gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate)
        | {"reason_excerpt": (reason or "")[:120]},
    )
    return {
        "phase": "7F",
        "ok": True,
        "gate": serialize_phase7f_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7F_WARNING],
        "nextAction": gate.next_action,
    }


def reject_phase7f_gate(
    gate_id: int,
    *,
    rejected_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_reject_reason_required"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "supply_reason",
        }
    gate = (
        RazorpayCourierReadinessGate.objects.filter(pk=gate_id).first()
    )
    if gate is None:
        return {
            "phase": "7F",
            "ok": False,
            "gate": None,
            "blockers": ["phase7f_gate_not_found"],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayCourierReadinessGate.Status.DRAFT,
        RazorpayCourierReadinessGate.Status.PENDING_MANUAL_REVIEW,
    }:
        return {
            "phase": "7F",
            "ok": False,
            "gate": serialize_phase7f_gate(gate),
            "blockers": [
                f"phase7f_reject_refused_for_status_{gate.status}"
            ],
            "warnings": [PHASE_7F_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    assert_phase7f_no_courier_or_business_mutation(
        gate, before_counts=before
    )

    gate.status = RazorpayCourierReadinessGate.Status.REJECTED
    gate.rejected_at = timezone.now()
    gate.rejected_by = rejected_by
    gate.reject_reason = (reason or "")[:1000]
    gate.next_action = "phase7f_gate_rejected"
    gate.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 7F rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(gate)
        | {"reason_excerpt": (reason or "")[:120]},
    )
    return {
        "phase": "7F",
        "ok": True,
        "gate": serialize_phase7f_gate(gate),
        "blockers": [],
        "warnings": [PHASE_7F_WARNING],
        "nextAction": gate.next_action,
    }


# ---------------------------------------------------------------------------
# Summarize / inspect-readiness
# ---------------------------------------------------------------------------


def summarize_phase7f_gates(limit: int = 25) -> dict[str, Any]:
    queryset = (
        RazorpayCourierReadinessGate.objects.order_by("-created_at")
    )
    statuses = [s.value for s in RazorpayCourierReadinessGate.Status]
    counts = {s: queryset.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase7f_gate(row) for row in queryset[: max(1, limit)]
    ]
    return {
        "phase": "7F",
        "limit": int(max(1, limit)),
        "counts": counts,
        "items": items,
    }


def inspect_phase7f_readiness() -> dict[str, Any]:
    snapshot = _capture_env_flag_snapshot()
    kill_state = _kill_switch_state()
    summary = summarize_phase7f_gates(limit=10)
    presence = _delhivery_env_presence()
    hotfix_present = _phase7d_hotfix_1_present()

    phase7e_approved_count = (
        RazorpayWhatsAppInternalNotificationGate.objects.filter(
            status=RazorpayWhatsAppInternalNotificationGate.Status.APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW
        ).count()
    )

    blockers: list[str] = []
    if not _flag_phase7f_gate_enabled():
        blockers.append(
            "PHASE7F_COURIER_READINESS_GATE_ENABLED_must_be_true"
        )
    if not kill_state.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if not hotfix_present:
        blockers.append(
            "phase7d_hotfix_1_must_be_shipped_before_phase7f_review"
        )
    if snapshot.get("DELHIVERY_MODE") not in {"mock", "test"}:
        blockers.append(
            "DELHIVERY_MODE_must_be_mock_or_test"
        )
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
        "ready_to_prepare_phase7f_courier_readiness_gate"
        if not blockers and phase7e_approved_count > 0
        else (
            "enable_phase7f_courier_readiness_gate_flag_for_review_only"
            if not _flag_phase7f_gate_enabled()
            else "fix_phase7f_readiness_blockers"
        )
    )

    return {
        "phase": "7F",
        "status": "courier_readiness_only",
        "latestCompletedPhase": "7E",
        "nextPhase": "7G_or_courier_live_not_approved",
        "envFlags": {
            "phase7fCourierReadinessGateEnabled": (
                _flag_phase7f_gate_enabled()
            ),
        },
        "envFlagSnapshot": snapshot,
        "delhiveryEnvPresence": presence,
        "killSwitch": kill_state,
        "phase7DHotfix1Present": hotfix_present,
        "phase7EApprovedGateCount": phase7e_approved_count,
        "phase7FGateCounts": summary["counts"],
        "items": summary["items"],
        "phase7DSourceSignoffMayBeLegacyFreeTextWithAck": True,
        "phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand": True,
        "phase7FRequiresFutureExecuteWindowGuardForCourier": True,
        "phase7FCallsDelhivery": False,
        "phase7FCreatesShipmentRow": False,
        "phase7FCreatesAwb": False,
        "phase7FBooksPickup": False,
        "phase7FGeneratesLabel": False,
        "phase7FSendsCustomerNotification": False,
        "phase7FMutatesBusinessRow": False,
        "phase7FCallsMetaCloud": False,
        "phase7FCallsRazorpay": False,
        "phase7FSendsWhatsApp": False,
        "phase7FQueuesWhatsApp": False,
        "blockers": blockers,
        "warnings": [PHASE_7F_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_7F_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7F courier readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "next_action": report.get("nextAction"),
                "phase7f_gate_enabled": (
                    report.get("envFlags", {}).get(
                        "phase7fCourierReadinessGateEnabled", False
                    )
                ),
                "phase7d_hotfix_1_present": report.get(
                    "phase7DHotfix1Present", False
                ),
                "phase7e_approved_gate_count": report.get(
                    "phase7EApprovedGateCount", 0
                ),
                "delhivery_mode": (
                    report.get("envFlagSnapshot", {}).get(
                        "DELHIVERY_MODE", "mock"
                    )
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
    "PHASE_7F_WARNING",
    "PHASE_7F_FORBIDDEN_ACTIONS",
    "PHASE_7F_FORBIDDEN_PAYLOAD_KEYS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_DRY_RUN_PASSED",
    "AUDIT_KIND_DRY_RUN_FAILED",
    "AUDIT_KIND_RB_DRY_RUN_PASSED",
    "AUDIT_KIND_RB_DRY_RUN_FAILED",
    "AUDIT_KIND_APPROVED_FUTURE_COURIER",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_KILL_SWITCH_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "Phase7FEligibility",
    "build_phase7f_courier_readiness_contract",
    "validate_phase7f_source_eligibility",
    "preview_phase7f_gate",
    "prepare_phase7f_gate",
    "dry_run_phase7f_gate",
    "rollback_dry_run_phase7f_gate",
    "approve_phase7f_gate",
    "reject_phase7f_gate",
    "summarize_phase7f_gates",
    "inspect_phase7f_readiness",
    "emit_readiness_inspected_audit",
    "assert_phase7f_no_courier_or_business_mutation",
    "serialize_phase7f_gate",
    "serialize_phase7f_dry_run_record",
)
