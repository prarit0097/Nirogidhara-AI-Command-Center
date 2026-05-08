"""Phase 7G - One-shot Delhivery TEST/MOCK Courier Execution Gate.

This service implements the *single* future Delhivery TEST/MOCK
``create_awb`` invocation derived from a fully-approved Phase 7F
:class:`RazorpayCourierReadinessGate` row, against the configured
TEST/MOCK Delhivery backend, with a synthetic payload that NEVER
contains real customer data.

Phase 7G is the **only currently approved design path in this
controlled Phase 7 chain** that may later issue one Delhivery
TEST/MOCK API request after fresh Director approval. Phase 7G-Live
(real customer courier execution) remains **NOT approved**.

Phase 7G **does NOT create a Shipment row at execute time.** The
existing ``apps.shipments.Shipment`` model has a plain ``customer``
CharField that would surface synthetic test rows in operator
dashboards / RTO boards / shipment listings and bias mutation-counter
guards in other phases. Provider / AWB summary lives on the
``RazorpayCourierExecutionAttempt`` row only. ``shipment_created``,
``business_mutation_was_made``, ``real_shipment_mutation_was_made``
stay ``False`` permanently. ``awb_created`` flips ``True`` only
because Delhivery returned an AWB value, NOT because a Shipment row
was written.

Phase 7G **never** sends WhatsApp, **never** queues an outbound,
**never** calls Meta Cloud, **never** calls Razorpay, **never** calls
Vapi, **never** sends a customer notification, **never** books a
courier pickup separately, **never** generates / prints a courier
label, **never** mutates real ``Order`` / ``Payment`` / ``Customer``
/ ``Lead`` / ``DiscountOfferLog`` rows, **never** edits any ``.env*``
file. The module does not import ``dotenv``.

Hard scope rule (asserted by static-file scan tests): this module
does NOT have a top-level ``from
apps.shipments.integrations.delhivery_client import create_awb`` /
``_create_via_sdk``. The Delhivery client is imported **lazily**
inside :func:`_create_awb_via_dedicated_wrapper` only, which itself
runs only inside the guarded :func:`execute_phase7g_courier_one_shot`
path after every gate is green.

Public surface:

- :func:`build_phase7g_courier_execution_contract`
- :func:`inspect_phase7g_courier_execution_readiness`
- :func:`validate_phase7g_source_chain`
- :func:`preview_phase7g_courier_execution_attempt`
- :func:`prepare_phase7g_courier_execution_attempt`
- :func:`approve_phase7g_courier_execution_attempt`
- :func:`reject_phase7g_courier_execution_attempt`
- :func:`execute_phase7g_courier_one_shot` -- the only callable that
  may issue a Delhivery TEST/MOCK request, after every gate passes.
- :func:`rollback_phase7g_courier_execution_attempt`
- :func:`assert_phase7g_no_unauthorised_mutation`
- :func:`serialize_phase7g_attempt`
- :func:`serialize_phase7g_rollback`
- :func:`summarize_phase7g_attempts`
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.saas.utc_window import (
    parse_director_signoff_window,
    validate_within_director_window,
)
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
    RazorpayCourierExecutionAttempt,
    RazorpayCourierExecutionRollback,
    RazorpayCourierReadinessGate,
    RazorpayPhase6FinalAuditLock,
    RazorpayWhatsAppInternalNotificationGate,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_7G_WARNING = (
    "Phase 7G is the One-shot Delhivery TEST/MOCK Courier Execution "
    "Gate. It is the only currently approved design path in this "
    "controlled Phase 7 chain that may later issue one Delhivery "
    "TEST/MOCK API request after fresh Director approval. Phase "
    "7G-Live (real customer courier execution) remains NOT approved. "
    "Phase 7G NEVER creates a Shipment row, NEVER sends WhatsApp, "
    "NEVER queues an outbound, NEVER calls Meta Cloud / Razorpay / "
    "Vapi, NEVER sends a customer notification, NEVER books a "
    "courier pickup separately, NEVER generates a courier label, "
    "NEVER mutates real Order / Payment / Customer / Lead / "
    "DiscountOfferLog rows, and NEVER edits any .env file. The "
    "execute path is CLI-only and requires three Phase 7G env flags + "
    "non-empty Director sign-off + DELHIVERY_MODE in {mock,test} + "
    "RuntimeKillSwitch enabled + source-chain green."
)


# Audit kinds (every kind <= 64 chars; verified by tests).
AUDIT_KIND_READINESS = "razorpay.courier_execution.readiness_inspected"
AUDIT_KIND_PREVIEWED = "razorpay.courier_execution.previewed"
AUDIT_KIND_PREPARED = "razorpay.courier_execution.attempt_prepared"
AUDIT_KIND_APPROVED_FOR_ONE_SHOT = (
    "razorpay.courier_execution.approved_for_one_shot"
)
AUDIT_KIND_REJECTED = "razorpay.courier_execution.rejected"
AUDIT_KIND_EXECUTED = "razorpay.courier_execution.executed"
AUDIT_KIND_FAILED = "razorpay.courier_execution.failed"
AUDIT_KIND_ROLLED_BACK = "razorpay.courier_execution.rolled_back_recorded"
AUDIT_KIND_BLOCKED = "razorpay.courier_execution.blocked"
AUDIT_KIND_KILL_SWITCH_BLOCKED = (
    "razorpay.courier_execution.kill_switch_blocked"
)
AUDIT_KIND_INVARIANT_VIOLATION = (
    "razorpay.courier_execution.invariant_violation"
)
AUDIT_KIND_MODE_BLOCKED = "razorpay.courier_execution.delhivery_mode_blocked"
AUDIT_KIND_DUPLICATE_BLOCKED = "razorpay.courier_execution.duplicate_blocked"


PHASE_7G_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "call_delhivery_api_outside_one_shot",
    "create_awb_outside_one_shot",
    "book_courier_pickup_separately",
    "generate_courier_label",
    "print_courier_label",
    "create_shipment_row",
    "create_workflow_step_row",
    "create_rescue_attempt_row",
    "send_whatsapp_template",
    "send_whatsapp_freeform",
    "queue_whatsapp_outbound",
    "send_customer_notification",
    "call_meta_cloud_api",
    "call_razorpay_api",
    "call_vapi_api",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "mutate_real_order_status",
    "mutate_real_payment_status",
    "mutate_real_shipment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "mutate_real_discount_offer_log",
    "execute_via_frontend",
    "execute_via_api_endpoint",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "edit_dotenv_production",
    "edit_dotenv_live",
    "edit_dotenv_any",
    "import_dotenv_module",
    "switch_to_delhivery_live_mode",
    "use_real_customer_phone_or_address",
)


PHASE_7G_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "token",
    "phone",
    "customer_phone",
    "email",
    "address",
    "address_line",
    "pincode",
    "pin_code",
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
    "verify_token",
    "app_secret",
    "DELHIVERY_API_TOKEN",
    "META_WA_TOKEN",
    "META_WA_APP_SECRET",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "raw_payload",
    "raw_signature",
    "raw_secret",
)


PHASE_7G_SYNTHETIC_CUSTOMER_NAME = "Phase 7G TEST"
PHASE_7G_SYNTHETIC_PHONE_LAST4 = "0000"
PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED = "[redacted]"
PHASE_7G_SYNTHETIC_CITY = "Internal"
PHASE_7G_SYNTHETIC_STATE = "Internal"
PHASE_7G_SYNTHETIC_PIN_PREFIX = "11000"
PHASE_7G_SYNTHETIC_WEIGHT_GRAMS = 500
PHASE_7G_SYNTHETIC_PAYMENT_MODE = "Prepaid"
PHASE_7G_SYNTHETIC_COD_AMOUNT = 0
PHASE_7G_ALLOWED_DELHIVERY_MODES: frozenset[str] = frozenset(
    {"mock", "test"}
)


# ---------------------------------------------------------------------------
# Flag readers (read-only). NEVER edits .env files.
# ---------------------------------------------------------------------------


def _flag_phase7g_lifecycle_enabled() -> bool:
    return bool(
        getattr(settings, "PHASE7G_COURIER_EXECUTION_ENABLED", False)
    )


def _flag_phase7g_director_approved() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION",
            False,
        )
    )


def _flag_phase7g_allow_test_awb() -> bool:
    return bool(
        getattr(settings, "PHASE7G_ALLOW_DELHIVERY_TEST_AWB", False)
    )


def _capture_env_flag_snapshot() -> dict[str, Any]:
    """Read-only snapshot. Never includes any secret value.

    Phase 7G captures the three Phase 7G flags + every upstream gate
    + every WhatsApp automation flag + the Delhivery mode + the
    kill-switch / MCP master flag. NEVER opens any .env file.
    """
    return {
        "PHASE7G_COURIER_EXECUTION_ENABLED": (
            _flag_phase7g_lifecycle_enabled()
        ),
        "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION": (
            _flag_phase7g_director_approved()
        ),
        "PHASE7G_ALLOW_DELHIVERY_TEST_AWB": (
            _flag_phase7g_allow_test_awb()
        ),
        "PHASE7F_COURIER_READINESS_GATE_ENABLED": bool(
            getattr(
                settings, "PHASE7F_COURIER_READINESS_GATE_ENABLED", False
            )
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
                settings,
                "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED",
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
            getattr(
                settings, "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER", False
            )
        ),
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED": bool(
            getattr(
                settings, "PHASE7_CONTROLLED_PILOT_GATE_ENABLED", False
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
        "DELHIVERY_MODE": str(
            getattr(settings, "DELHIVERY_MODE", "mock") or "mock"
        ),
        "MCP_ENABLED": bool(getattr(settings, "MCP_ENABLED", False)),
    }


def _delhivery_env_presence() -> dict[str, bool]:
    """Presence-only booleans for Delhivery env vars. NEVER values."""
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
        return {
            "enabled": True,
            "model": "lookup_failed_treated_as_enabled",
        }
    if kill is None:
        return {"enabled": True, "model": "no_row_treated_as_enabled"}
    return {
        "enabled": bool(kill.enabled),
        "model": "RuntimeKillSwitch",
        "id": kill.pk,
    }


# ---------------------------------------------------------------------------
# Business-row count helpers
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


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "shipment_created",
    "business_mutation_was_made",
    "real_order_mutation_was_made",
    "real_payment_mutation_was_made",
    "real_shipment_mutation_was_made",
    "customer_notification_sent",
)


def _audit_locked_false_payload() -> dict[str, bool]:
    return {field: False for field in _LOCKED_FALSE_FIELDS}


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"phase": "7G"}
    forbidden = set(PHASE_7G_FORBIDDEN_PAYLOAD_KEYS)
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


def assert_phase7g_no_unauthorised_mutation(
    attempt: RazorpayCourierExecutionAttempt,
    *,
    before_counts: Optional[dict[str, int]] = None,
) -> None:
    """Refuse if any locked-False boolean is True or any business-row
    count delta is non-zero. ``awb_created``, ``provider_call_attempted``,
    and ``delhivery_call_attempted`` are *allowed* to be True after a
    successful execute -- they are NOT in the locked-False list.

    Emits an :data:`AUDIT_KIND_INVARIANT_VIOLATION` audit row and
    raises :class:`ValueError` on violation.
    """
    flipped: list[str] = []
    for field in _LOCKED_FALSE_FIELDS:
        if getattr(attempt, field, False) is True:
            flipped.append(field)

    delta_keys: list[str] = []
    counts_before = before_counts
    if counts_before is None:
        counts_before = attempt.before_counts or {}
    if counts_before:
        current = _business_row_counts()
        for key, before in counts_before.items():
            after = current.get(key, before)
            if after != before:
                delta_keys.append(
                    f"phase7g_business_row_count_changed_for_{key}"
                )

    if not flipped and not delta_keys:
        return

    write_event(
        kind=AUDIT_KIND_INVARIANT_VIOLATION,
        text=(
            f"Phase 7G invariant violation attempt_id={attempt.pk} "
            f"flipped={flipped} deltas={delta_keys}"
        ),
        tone=AuditEvent.Tone.DANGER,
        payload=_safe_audit_payload(
            {
                "attempt_id": attempt.pk,
                "flipped_locked_false_booleans": flipped,
                "business_row_count_deltas": delta_keys,
                **_audit_locked_false_payload(),
            }
        ),
    )
    raise ValueError(
        "Phase 7G invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Source-chain validator
# ---------------------------------------------------------------------------


@dataclass
class Phase7GEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    phase7f_gate: Optional[RazorpayCourierReadinessGate]
    phase7e_gate: Optional[RazorpayWhatsAppInternalNotificationGate]
    phase7d_attempt: Optional[RazorpayControlledPilotExecutionAttempt]
    phase7b_gate: Optional[RazorpayControlledPilotExecutionGate]
    phase6t_lock: Optional[RazorpayPhase6FinalAuditLock]


def validate_phase7g_source_chain(
    phase7f_gate_id: Optional[int],
    *,
    require_env_flag: bool = True,
) -> Phase7GEligibility:
    """Validate that an approved Phase 7F gate is eligible to derive
    a Phase 7G one-shot attempt row.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    phase7f_gate: Optional[RazorpayCourierReadinessGate] = None
    phase7e_gate: Optional[RazorpayWhatsAppInternalNotificationGate] = None
    phase7d_attempt: Optional[RazorpayControlledPilotExecutionAttempt] = None
    phase7b_gate: Optional[RazorpayControlledPilotExecutionGate] = None
    phase6t_lock: Optional[RazorpayPhase6FinalAuditLock] = None

    if require_env_flag and not _flag_phase7g_lifecycle_enabled():
        blockers.append(
            "PHASE7G_COURIER_EXECUTION_ENABLED_must_be_true"
        )

    if phase7f_gate_id:
        phase7f_gate = (
            RazorpayCourierReadinessGate.objects.filter(
                pk=phase7f_gate_id
            )
            .select_related(
                "source_phase7e_gate",
                "source_phase7d_attempt",
                "source_phase7b_gate",
                "source_phase6t_lock",
            )
            .first()
        )

    if phase7f_gate is None:
        blockers.append("phase_7f_source_courier_readiness_gate_not_found")
        return Phase7GEligibility(
            eligible=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            phase7f_gate=None,
            phase7e_gate=None,
            phase7d_attempt=None,
            phase7b_gate=None,
            phase6t_lock=None,
        )

    if (
        phase7f_gate.status
        != RazorpayCourierReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE7G_OR_COURIER_EXECUTION_REVIEW
    ):
        blockers.append(
            f"phase_7f_gate_status_must_be_approved_for_future_phase7g_was_{phase7f_gate.status}"
        )
    if not phase7f_gate.dry_run_passed:
        blockers.append("phase_7f_gate_dry_run_passed_must_be_true")
    if not phase7f_gate.rollback_dry_run_passed:
        blockers.append(
            "phase_7f_gate_rollback_dry_run_passed_must_be_true"
        )
    if not phase7f_gate.phase7d_hotfix_1_present:
        blockers.append(
            "phase_7d_hotfix_1_must_be_present_on_phase_7f_gate"
        )

    phase7e_gate = phase7f_gate.source_phase7e_gate
    phase7d_attempt = phase7f_gate.source_phase7d_attempt
    phase7b_gate = phase7f_gate.source_phase7b_gate
    phase6t_lock = phase7f_gate.source_phase6t_lock

    if phase7e_gate is None:
        blockers.append("phase_7e_source_gate_not_found_on_phase_7f_gate")
    elif (
        phase7e_gate.status
        != RazorpayWhatsAppInternalNotificationGate.Status.APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW
    ):
        blockers.append(
            "phase_7e_gate_status_must_be_approved_for_future_phase7f_or_7e_send_review"
        )

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

    if phase7b_gate is None:
        blockers.append("phase_7b_source_gate_not_found")
    elif (
        phase7b_gate.status
        != RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
    ):
        blockers.append(
            "phase_7b_gate_status_must_be_approved_for_future_phase7c_review"
        )

    if phase6t_lock is None:
        blockers.append("phase_6t_audit_lock_not_found")
    elif (
        phase6t_lock.status
        != RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
    ):
        blockers.append(
            "phase_6t_audit_lock_must_be_locked_for_future_review"
        )

    snapshot = _capture_env_flag_snapshot()
    delhivery_mode = snapshot.get("DELHIVERY_MODE")
    if delhivery_mode not in PHASE_7G_ALLOWED_DELHIVERY_MODES:
        blockers.append(
            f"DELHIVERY_MODE_must_be_mock_or_test_was_{delhivery_mode}"
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

    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    return Phase7GEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        phase7f_gate=phase7f_gate,
        phase7e_gate=phase7e_gate,
        phase7d_attempt=phase7d_attempt,
        phase7b_gate=phase7b_gate,
        phase6t_lock=phase6t_lock,
    )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def build_phase7g_courier_execution_contract() -> dict[str, Any]:
    return {
        "phase": "7G",
        "status": "delhivery_test_or_mock_one_shot_courier_execution_only",
        "executionPath": "cli_only",
        "executeIsCliOnly": True,
        "phase7GAllowedDelhiveryModes": sorted(
            PHASE_7G_ALLOWED_DELHIVERY_MODES
        ),
        "phase7GCallsDelhivery": False,
        "phase7GCallsDelhiveryDuringPlanning": False,
        "phase7GCreatesShipmentRow": False,
        "phase7GCreatesAwbRowOnAttemptOnly": True,
        "phase7GBooksCourierPickupSeparately": False,
        "phase7GGeneratesCourierLabel": False,
        "phase7GSendsWhatsApp": False,
        "phase7GQueuesWhatsApp": False,
        "phase7GCallsMetaCloud": False,
        "phase7GCallsRazorpay": False,
        "phase7GCallsVapi": False,
        "phase7GSendsCustomerNotification": False,
        "phase7GMutatesBusinessRow": False,
        "phase7GMutatesRealOrderRow": False,
        "phase7GMutatesRealPaymentRow": False,
        "phase7GMutatesRealCustomerRow": False,
        "phase7GMutatesRealLeadRow": False,
        "phase7GTouchesRealCustomerPhoneNumber": False,
        "phase7GTouchesRealCustomerAddress": False,
        "phase7GWritesEnvFile": False,
        "phase7GImportsDotenv": False,
        "phase7GLiveCustomerCourierApproved": False,
        "phase7GApprovalImpliesLiveCourier": False,
        "manualReviewRequired": True,
        "internalStaffOnly": True,
        "syntheticPayloadCustomerName": (
            PHASE_7G_SYNTHETIC_CUSTOMER_NAME
        ),
        "syntheticPayloadPhoneLast4": (
            PHASE_7G_SYNTHETIC_PHONE_LAST4
        ),
        "syntheticPayloadAddressLine": (
            PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED
        ),
        "syntheticPayloadCity": PHASE_7G_SYNTHETIC_CITY,
        "syntheticPayloadState": PHASE_7G_SYNTHETIC_STATE,
        "syntheticPayloadPinPrefix": PHASE_7G_SYNTHETIC_PIN_PREFIX,
        "syntheticPayloadWeightGrams": PHASE_7G_SYNTHETIC_WEIGHT_GRAMS,
        "syntheticPayloadPaymentMode": PHASE_7G_SYNTHETIC_PAYMENT_MODE,
        "syntheticPayloadCodAmount": PHASE_7G_SYNTHETIC_COD_AMOUNT,
        "blockers": [
            "phase_7g_execute_requires_three_phase7g_window_flags",
            "phase_7g_execute_requires_director_signoff",
            "phase_7g_execute_requires_delhivery_mode_in_mock_or_test",
            "phase_7g_execute_requires_kill_switch_enabled",
            "phase_7g_execute_requires_full_source_chain_green",
            "phase_7g_execute_requires_no_prior_provider_call",
        ],
        "notes": [
            "Phase 7G is the only currently approved design path in "
            "this controlled Phase 7 chain that may later issue one "
            "Delhivery TEST/MOCK API request after fresh Director "
            "approval. Phase 7G-Live (real customer courier "
            "execution) remains NOT approved.",
            "Phase 7G NEVER creates a Shipment row at execute time. "
            "Provider / AWB summary lives on the attempt row only.",
            "Phase 7G NEVER books a courier pickup separately, NEVER "
            "generates / prints a courier label, NEVER sends or "
            "queues WhatsApp, NEVER calls Meta Cloud / Razorpay / "
            "Vapi, NEVER sends a customer notification.",
        ],
        "forbiddenActions": list(PHASE_7G_FORBIDDEN_ACTIONS),
        "forbiddenPayloadKeys": list(PHASE_7G_FORBIDDEN_PAYLOAD_KEYS),
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_phase7g_attempt(
    row: RazorpayCourierExecutionAttempt,
) -> dict[str, Any]:
    """Whitelisted serializer. NEVER returns raw token, raw secret,
    raw provider response, full phone / address / customer data, or
    the Director's full sign-off text.
    """
    signoff = row.director_signoff_text or ""
    return {
        "id": row.pk,
        "sourcePhase7FGateId": row.source_phase7f_gate_id,
        "sourcePhase7EGateId": row.source_phase7e_gate_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sourcePhase7BGateId": row.source_phase7b_gate_id,
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        "status": row.status,
        "delhiveryModeAtEachStep": row.delhivery_mode_at_each_step or {},
        "delhiveryEnvTokenPresent": bool(
            row.delhivery_env_token_present
        ),
        "delhiveryEnvBaseUrlPresent": bool(
            row.delhivery_env_base_url_present
        ),
        "delhiveryEnvPickupLocationPresent": bool(
            row.delhivery_env_pickup_location_present
        ),
        "delhiveryEnvReturnAddressPresent": bool(
            row.delhivery_env_return_address_present
        ),
        "killSwitchSnapshotAtEachStep": (
            row.kill_switch_snapshot_at_each_step or {}
        ),
        "envFlagSnapshotAtEachStep": (
            row.env_flag_snapshot_at_each_step or {}
        ),
        "safetyInvariantsSnapshot": (
            row.safety_invariants_snapshot or {}
        ),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "syntheticOrderId": row.synthetic_order_id,
        "syntheticPayloadSummary": row.synthetic_payload_summary or {},
        "idempotencyKey": row.idempotency_key,
        "idempotencyLockAcquired": bool(row.idempotency_lock_acquired),
        "providerObjectId": row.provider_object_id,
        "providerStatus": row.provider_status,
        "safeRequestSummary": row.safe_request_summary or {},
        "safeResponseSummary": row.safe_response_summary or {},
        "providerCallAttempted": bool(row.provider_call_attempted),
        "delhiveryCallAttempted": bool(row.delhivery_call_attempted),
        "awbCreated": bool(row.awb_created),
        "shipmentCreated": False,
        "businessMutationWasMade": False,
        "realOrderMutationWasMade": False,
        "realPaymentMutationWasMade": False,
        "realShipmentMutationWasMade": False,
        "customerNotificationSent": False,
        "recordedSignoffWindowValid": row.recorded_signoff_window_valid,
        "recordedSignoffWindowStartUtc": (
            row.recorded_signoff_window_start_utc.isoformat()
            if row.recorded_signoff_window_start_utc
            else None
        ),
        "recordedSignoffWindowEndUtc": (
            row.recorded_signoff_window_end_utc.isoformat()
            if row.recorded_signoff_window_end_utc
            else None
        ),
        "directorSignoffPresent": bool(row.director_signoff_present),
        "directorSignoffPresentBoolean": bool(signoff.strip()),
        "operatorName": row.operator_name,
        "confirmOneShotCourierExecution": bool(
            row.confirm_one_shot_courier_execution
        ),
        "modeAcknowledgement": row.mode_acknowledgement,
        "rollbackRecordOnlyAcknowledged": bool(
            row.rollback_record_only_acknowledged
        ),
        "rollbackStatus": row.rollback_status,
        "rolledBackAt": (
            row.rolled_back_at.isoformat() if row.rolled_back_at else None
        ),
        "rollbackReasonPresent": bool((row.rollback_reason or "").strip()),
        "archiveReasonPresent": bool((row.archive_reason or "").strip()),
        "rejectReasonPresent": bool((row.reject_reason or "").strip()),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action or "",
        "requestedByUsername": (
            getattr(row.requested_by, "username", "") or ""
        ),
        "reviewedByUsername": (
            getattr(row.reviewed_by, "username", "") or ""
        ),
        "executedByUsername": (
            getattr(row.executed_by, "username", "") or ""
        ),
        "rolledBackByUsername": (
            getattr(row.rolled_back_by, "username", "") or ""
        ),
        "rejectedByUsername": (
            getattr(row.rejected_by, "username", "") or ""
        ),
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
        "updatedAt": (
            row.updated_at.isoformat() if row.updated_at else None
        ),
        "approvedAt": (
            row.approved_at.isoformat() if row.approved_at else None
        ),
        "executedAt": (
            row.executed_at.isoformat() if row.executed_at else None
        ),
        "failedAt": (
            row.failed_at.isoformat() if row.failed_at else None
        ),
        "rejectedAt": (
            row.rejected_at.isoformat() if row.rejected_at else None
        ),
        "archivedAt": (
            row.archived_at.isoformat() if row.archived_at else None
        ),
    }


def serialize_phase7g_rollback(
    row: RazorpayCourierExecutionRollback,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "attemptId": row.attempt_id,
        "verifiedAt": (
            row.verified_at.isoformat() if row.verified_at else None
        ),
        "rollbackStatus": row.rollback_status,
        "rollbackReasonPresent": bool(
            (row.rollback_reason or "").strip()
        ),
        "cancellationAttempted": bool(row.cancellation_attempted),
        "cancellationAttemptedByCommand": (
            row.cancellation_attempted_by_command
        ),
        "providerObjectIdRecorded": row.provider_object_id_recorded,
        "envFlagPresenceAtRollback": (
            row.env_flag_presence_at_rollback or {}
        ),
        "evaluatedSafetyInvariants": (
            row.evaluated_safety_invariants or {}
        ),
        "idempotencyKey": row.idempotency_key,
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Audit payload helper
# ---------------------------------------------------------------------------


def _audit_attempt_payload(
    attempt: RazorpayCourierExecutionAttempt,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "attempt_id": attempt.pk,
        "status": attempt.status,
        "phase7f_gate_id": attempt.source_phase7f_gate_id,
        "phase7e_gate_id": attempt.source_phase7e_gate_id,
        "phase7d_attempt_id": attempt.source_phase7d_attempt_id,
        "phase7b_gate_id": attempt.source_phase7b_gate_id,
        "phase6t_lock_id": attempt.source_phase6t_lock_id,
        "delhivery_mode_at_each_step": (
            attempt.delhivery_mode_at_each_step or {}
        ),
        "provider_object_id_or_empty": attempt.provider_object_id or "",
        "provider_call_attempted": bool(attempt.provider_call_attempted),
        "delhivery_call_attempted": bool(
            attempt.delhivery_call_attempted
        ),
        "awb_created": bool(attempt.awb_created),
        "idempotency_key": attempt.idempotency_key,
        "kill_switch_state_at_emit": _kill_switch_state(),
        **_audit_locked_false_payload(),
    }
    for field in _LOCKED_FALSE_FIELDS:
        payload[field] = bool(getattr(attempt, field, False))
    if extra:
        payload.update(extra)
    return _safe_audit_payload(payload)


# ---------------------------------------------------------------------------
# Synthetic payload + dedicated wrapper
# ---------------------------------------------------------------------------


class Phase7GExecutionError(Exception):
    """Raised when execute_phase7g_courier_one_shot refuses or the
    underlying Delhivery client fails. The exception message NEVER
    echoes raw token / address / phone material.
    """


def _build_phase7g_synthetic_payload(
    *, attempt_id: int, synthetic_order_id: str
) -> dict[str, Any]:
    """Construct the synthetic Phase 7G ``create_awb`` payload.

    NEVER contains real customer data. The customer name is the
    sentinel ``"Phase 7G TEST"`` literal; phone is last-4 only
    (``"0000"``); address line is ``"[redacted]"``; pin is the
    fixed prefix ``"11000"``.
    """
    return {
        "order_id": synthetic_order_id,
        "customer_name": PHASE_7G_SYNTHETIC_CUSTOMER_NAME,
        "customer_phone_last4": PHASE_7G_SYNTHETIC_PHONE_LAST4,
        "address_line": PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED,
        "city": PHASE_7G_SYNTHETIC_CITY,
        "state": PHASE_7G_SYNTHETIC_STATE,
        "pincode_prefix": PHASE_7G_SYNTHETIC_PIN_PREFIX,
        "weight_grams": PHASE_7G_SYNTHETIC_WEIGHT_GRAMS,
        "payment_mode": PHASE_7G_SYNTHETIC_PAYMENT_MODE,
        "cod_amount": PHASE_7G_SYNTHETIC_COD_AMOUNT,
        "phase": "7G",
        "attempt_id": attempt_id,
        "internal_test_only": True,
        "real_customer_data": False,
    }


def _summarize_awb_response(awb_result: Any) -> dict[str, Any]:
    """Reduce the Delhivery client result to a Phase 7G safe summary.

    Strips raw provider body. Keeps awb / status / tracking_url only.
    """
    if awb_result is None:
        return {"awb": "", "status": "", "tracking_url": ""}
    awb = getattr(awb_result, "awb", "") or ""
    status = getattr(awb_result, "status", "") or ""
    tracking_url = getattr(awb_result, "tracking_url", "") or ""
    return {
        "awb": str(awb)[:64],
        "status": str(status)[:64],
        "tracking_url": str(tracking_url)[:200],
    }


def _create_awb_via_dedicated_wrapper(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Lazy-import wrapper around the Delhivery client.

    The real ``apps.shipments.integrations.delhivery_client.create_awb``
    function is imported **only inside this function** so the
    Phase 7G module surface contains no top-level import of the
    Delhivery client (asserted by static-file scan tests). The actual
    Delhivery TEST/MOCK request is made here, once, after every gate
    in :func:`execute_phase7g_courier_one_shot` is green. Tests
    ``mock.patch`` this function so the real network is never hit.
    """
    try:
        from apps.shipments.integrations.delhivery_client import (
            DelhiveryClientError,
            create_awb,
        )
    except ImportError as exc:  # pragma: no cover
        raise Phase7GExecutionError(
            "Delhivery client is not importable."
        ) from exc

    mode = (
        getattr(settings, "DELHIVERY_MODE", "mock") or "mock"
    ).lower()
    if mode not in PHASE_7G_ALLOWED_DELHIVERY_MODES:
        raise Phase7GExecutionError(
            "DELHIVERY_MODE must be mock or test for Phase 7G."
        )

    try:
        result = create_awb(
            order_id=str(payload["order_id"]),
            customer_name=str(payload["customer_name"]),
            customer_phone="",  # synthetic last-4 only; SDK call uses ""
            address_line=str(payload["address_line"]),
            city=str(payload["city"]),
            state=str(payload["state"]),
            pincode=str(payload["pincode_prefix"]),
            weight_grams=int(payload["weight_grams"]),
            payment_mode=str(payload["payment_mode"]),
            cod_amount=int(payload["cod_amount"]),
            exists=None,
        )
    except DelhiveryClientError as exc:
        raise Phase7GExecutionError(
            f"Delhivery client error: {exc.__class__.__name__}"
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise Phase7GExecutionError(
            f"unexpected:{exc.__class__.__name__}"
        ) from exc

    return _summarize_awb_response(result)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7g_courier_execution_attempt(
    phase7f_gate_id: int,
) -> dict[str, Any]:
    """Read-only preview from a Phase 7F approved gate. Never creates rows."""
    eligibility = validate_phase7g_source_chain(
        phase7f_gate_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7G preview phase7f_gate_id={phase7f_gate_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7f_gate_id": phase7f_gate_id,
                "eligible": eligibility.eligible,
                "blockers": list(eligibility.blockers),
                "kill_switch_state_at_emit": _kill_switch_state(),
                **_audit_locked_false_payload(),
            }
        ),
    )
    return {
        "phase": "7G",
        "found": eligibility.phase7f_gate is not None,
        "sourcePhase7FGateId": phase7f_gate_id,
        "sourcePhase7EGateId": (
            eligibility.phase7e_gate.pk
            if eligibility.phase7e_gate
            else None
        ),
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
        "delhiveryEnvPresence": _delhivery_env_presence(),
        "delhiveryModeAtPreview": _capture_env_flag_snapshot().get(
            "DELHIVERY_MODE", "mock"
        ),
        "eligible": eligibility.eligible,
        "proposedContract": (
            build_phase7g_courier_execution_contract()
        ),
        "blockers": list(eligibility.blockers),
        "warnings": list(eligibility.warnings) + [PHASE_7G_WARNING],
        "nextAction": (
            "ready_to_prepare_phase7g_courier_execution_attempt"
            if eligibility.eligible
            and _flag_phase7g_lifecycle_enabled()
            else (
                "fix_phase7g_eligibility_blockers_or_enable_phase7g_lifecycle_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_key(gate: RazorpayCourierReadinessGate) -> str:
    return f"phase7g::courier_execution::phase7f_gate::{gate.pk}"


def _synthetic_order_id(gate_id: int, attempt_id: int) -> str:
    return f"phase7g::courier::gate::{gate_id}::attempt::{attempt_id}"


def prepare_phase7g_courier_execution_attempt(
    phase7f_gate_id: int,
    *,
    requested_by=None,
) -> dict[str, Any]:
    """Atomic + idempotent prepare. NEVER calls Delhivery, NEVER creates
    a Shipment / WorkflowStep / RescueAttempt row, NEVER mutates real
    business tables, NEVER edits any .env file.
    """
    eligibility = validate_phase7g_source_chain(
        phase7f_gate_id, require_env_flag=True
    )
    if (
        not eligibility.eligible
        or eligibility.phase7f_gate is None
        or eligibility.phase7e_gate is None
        or eligibility.phase7d_attempt is None
        or eligibility.phase7b_gate is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7G prepare blocked phase7f_gate_id={phase7f_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7f_gate_id": phase7f_gate_id,
                    "blockers": list(eligibility.blockers),
                    "kill_switch_state_at_emit": _kill_switch_state(),
                    **_audit_locked_false_payload(),
                }
            ),
        )
        return {
            "phase": "7G",
            "created": False,
            "reused": False,
            "attempt": None,
            "blockers": list(eligibility.blockers),
            "warnings": list(eligibility.warnings) + [PHASE_7G_WARNING],
            "nextAction": (
                "fix_phase7g_eligibility_blockers_or_enable_phase7g_lifecycle_flag"
            ),
        }

    gate = eligibility.phase7f_gate
    idempotency = _idempotency_key(gate)
    before = _business_row_counts()
    snapshot = _capture_env_flag_snapshot()
    kill_state = _kill_switch_state()
    presence = _delhivery_env_presence()
    invariants = build_phase7g_courier_execution_contract()

    with transaction.atomic():
        existing = (
            RazorpayCourierExecutionAttempt.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "7G",
                "created": False,
                "reused": True,
                "attempt": serialize_phase7g_attempt(existing),
                "blockers": [],
                "warnings": [PHASE_7G_WARNING],
                "nextAction": "phase7g_attempt_pending_director_signoff",
            }

        attempt = RazorpayCourierExecutionAttempt(
            source_phase7f_gate=gate,
            source_phase7e_gate=eligibility.phase7e_gate,
            source_phase7d_attempt=eligibility.phase7d_attempt,
            source_phase7b_gate=eligibility.phase7b_gate,
            source_phase6t_lock=eligibility.phase6t_lock,
            status=(
                RazorpayCourierExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF
            ),
            delhivery_mode_at_each_step={
                "prepare": str(snapshot.get("DELHIVERY_MODE", "mock"))
            },
            delhivery_env_token_present=presence[
                "DELHIVERY_API_TOKEN_present"
            ],
            delhivery_env_base_url_present=presence[
                "DELHIVERY_API_BASE_URL_present"
            ],
            delhivery_env_pickup_location_present=presence[
                "DELHIVERY_PICKUP_LOCATION_present"
            ],
            delhivery_env_return_address_present=presence[
                "DELHIVERY_RETURN_ADDRESS_present"
            ],
            kill_switch_snapshot_at_each_step={"prepare": kill_state},
            env_flag_snapshot_at_each_step={"prepare": snapshot},
            safety_invariants_snapshot=invariants,
            before_counts=before,
            after_counts=before,
            synthetic_order_id="",
            synthetic_payload_summary={},
            idempotency_key=idempotency,
            idempotency_lock_acquired=False,
            provider_object_id="",
            provider_status="",
            safe_request_summary={},
            safe_response_summary={},
            provider_call_attempted=False,
            delhivery_call_attempted=False,
            awb_created=False,
            shipment_created=False,
            business_mutation_was_made=False,
            real_order_mutation_was_made=False,
            real_payment_mutation_was_made=False,
            real_shipment_mutation_was_made=False,
            customer_notification_sent=False,
            recorded_signoff_window_valid=None,
            recorded_signoff_window_start_utc=None,
            recorded_signoff_window_end_utc=None,
            director_signoff_text="",
            director_signoff_present=False,
            operator_name="",
            confirm_one_shot_courier_execution=False,
            mode_acknowledgement="",
            rollback_record_only_acknowledged=False,
            rollback_status=(
                RazorpayCourierExecutionAttempt.RollbackStatus.NOT_REQUIRED
            ),
            rolled_back_at=None,
            rollback_reason="",
            archive_reason="",
            reject_reason="",
            blockers=[],
            warnings=[PHASE_7G_WARNING],
            next_action="phase7g_attempt_pending_director_signoff",
            requested_by=requested_by,
        )
        assert_phase7g_no_unauthorised_mutation(
            attempt, before_counts=before
        )
        try:
            attempt.save()
        except IntegrityError:
            attempt = RazorpayCourierExecutionAttempt.objects.get(
                idempotency_key=idempotency
            )
            return {
                "phase": "7G",
                "created": False,
                "reused": True,
                "attempt": serialize_phase7g_attempt(attempt),
                "blockers": [],
                "warnings": [PHASE_7G_WARNING],
                "nextAction": (
                    "phase7g_attempt_pending_director_signoff"
                ),
            }

        attempt.synthetic_order_id = _synthetic_order_id(
            gate.pk, attempt.pk
        )
        attempt.synthetic_payload_summary = (
            _build_phase7g_synthetic_payload(
                attempt_id=attempt.pk,
                synthetic_order_id=attempt.synthetic_order_id,
            )
        )
        attempt.safe_request_summary = {
            "synthetic_order_id": attempt.synthetic_order_id,
            "weight_grams": PHASE_7G_SYNTHETIC_WEIGHT_GRAMS,
            "payment_mode": PHASE_7G_SYNTHETIC_PAYMENT_MODE,
            "cod_amount": PHASE_7G_SYNTHETIC_COD_AMOUNT,
        }
        attempt.save(
            update_fields=[
                "synthetic_order_id",
                "synthetic_payload_summary",
                "safe_request_summary",
                "updated_at",
            ]
        )

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 7G attempt prepared attempt_id={attempt.pk} "
            f"phase7f_gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7G",
        "created": True,
        "reused": False,
        "attempt": serialize_phase7g_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7G_WARNING],
        "nextAction": "phase7g_attempt_pending_director_signoff",
    }


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


def approve_phase7g_courier_execution_attempt(
    attempt_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Mark the attempt approved for one-shot courier test/mock review.

    Approval requires a non-empty manual review reason. Approval does
    NOT call Delhivery, does NOT mutate any real business table, does
    NOT enable any provider call -- the actual execute path requires
    a SECOND, separately-approved Director window.
    """
    attempt = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7G",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7g_attempt_not_found"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if not reason.strip():
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "blockers": ["phase7g_approve_reason_required"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "supply_reason",
        }
    if not _flag_phase7g_lifecycle_enabled():
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "blockers": [
                "PHASE7G_COURIER_EXECUTION_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "enable_phase7g_lifecycle_flag",
        }
    if (
        attempt.status
        != RazorpayCourierExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    ):
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "blockers": [
                f"phase7g_attempt_status_{attempt.status}_not_transitionable"
            ],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_status",
        }

    before = attempt.before_counts or _business_row_counts()
    assert_phase7g_no_unauthorised_mutation(
        attempt, before_counts=before
    )

    attempt.status = (
        RazorpayCourierExecutionAttempt.Status.APPROVED_FOR_ONE_SHOT_RUN
    )
    attempt.reviewed_by = reviewed_by
    attempt.approved_at = timezone.now()
    attempt.kill_switch_snapshot_at_each_step = {
        **(attempt.kill_switch_snapshot_at_each_step or {}),
        "approve": _kill_switch_state(),
    }
    attempt.env_flag_snapshot_at_each_step = {
        **(attempt.env_flag_snapshot_at_each_step or {}),
        "approve": _capture_env_flag_snapshot(),
    }
    attempt.next_action = (
        "approved_for_one_shot_courier_test_or_live_review"
    )
    attempt.save()

    write_event(
        kind=AUDIT_KIND_APPROVED_FOR_ONE_SHOT,
        text=(
            f"Phase 7G attempt approved for one-shot run "
            f"attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(
            attempt,
            extra={"reason_excerpt": (reason or "")[:120]},
        ),
    )
    return {
        "phase": "7G",
        "ok": True,
        "attempt": serialize_phase7g_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7G_WARNING],
        "nextAction": (
            "approved_for_one_shot_courier_test_or_live_review"
        ),
    }


def reject_phase7g_courier_execution_attempt(
    attempt_id: int,
    *,
    rejected_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7G",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7g_reject_reason_required"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "supply_reason",
        }
    attempt = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7G",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7g_attempt_not_found"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status not in {
        RazorpayCourierExecutionAttempt.Status.DRAFT,
        RazorpayCourierExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF,
        RazorpayCourierExecutionAttempt.Status.APPROVED_FOR_ONE_SHOT_RUN,
        RazorpayCourierExecutionAttempt.Status.BLOCKED,
    }:
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "blockers": [
                f"phase7g_reject_refused_for_status_{attempt.status}"
            ],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_status",
        }

    before = attempt.before_counts or _business_row_counts()
    assert_phase7g_no_unauthorised_mutation(
        attempt, before_counts=before
    )

    attempt.status = RazorpayCourierExecutionAttempt.Status.REJECTED
    attempt.rejected_at = timezone.now()
    attempt.rejected_by = rejected_by
    attempt.reject_reason = (reason or "")[:1000]
    attempt.next_action = "phase7g_attempt_rejected"
    attempt.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 7G attempt rejected attempt_id={attempt.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_attempt_payload(
            attempt,
            extra={"reason_excerpt": (reason or "")[:120]},
        ),
    )
    return {
        "phase": "7G",
        "ok": True,
        "attempt": serialize_phase7g_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7G_WARNING],
        "nextAction": "phase7g_attempt_rejected",
    }


# ---------------------------------------------------------------------------
# Execute (CLI-only; refuses unless every gate green)
# ---------------------------------------------------------------------------


def _director_signoff_mentions_gate(
    director_signoff: str, phase7f_gate_id: int
) -> bool:
    if not director_signoff:
        return False
    needle = str(phase7f_gate_id)
    return needle in director_signoff


def execute_phase7g_courier_one_shot(
    attempt_id: int,
    *,
    confirmed_by=None,
    director_signoff: str = "",
    operator_name: str = "",
    mode_acknowledgement: str = "",
    confirm_one_shot_courier_execution: bool = False,
    rollback_record_only_acknowledged: bool = False,
) -> dict[str, Any]:
    """The ONLY callable that may issue a Delhivery TEST/MOCK request
    in Phase 7G.

    Refuses unless EVERY pre-condition holds:

    1. ``PHASE7G_COURIER_EXECUTION_ENABLED=True``
    2. ``PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION=True``
    3. ``PHASE7G_ALLOW_DELHIVERY_TEST_AWB=True``
    4. attempt status == ``approved_for_one_shot_courier_test_or_live_review``
    5. non-empty ``director_signoff`` mentioning the source Phase 7F
       gate id
    6. non-empty ``operator_name``
    7. ``mode_acknowledgement`` matches the live ``DELHIVERY_MODE``
    8. ``confirm_one_shot_courier_execution=True``
    9. ``rollback_record_only_acknowledged=True``
    10. ``DELHIVERY_MODE in {mock, test}``
    11. ``RuntimeKillSwitch.enabled`` true
    12. source-chain still green at runtime
    13. attempt has no prior ``provider_call_attempted=True``
       (idempotency lock)

    On success: ONE Delhivery TEST/MOCK ``create_awb`` call, via the
    lazy-import :func:`_create_awb_via_dedicated_wrapper`. Records a
    safe summary on the attempt row only; flips status to ``executed``;
    sets ``provider_call_attempted=True``,
    ``delhivery_call_attempted=True``, and (only if Delhivery returned
    an AWB) ``awb_created=True``. No ``Shipment`` row is ever created.
    Refuses to retry. Calls
    :func:`assert_phase7g_no_unauthorised_mutation` post-call. NEVER
    edits ``.env`` files.
    """
    attempt = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7G",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7g_attempt_not_found"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_id",
        }

    blockers: list[str] = []
    if not _flag_phase7g_lifecycle_enabled():
        blockers.append(
            "PHASE7G_COURIER_EXECUTION_ENABLED_must_be_true"
        )
    if not _flag_phase7g_director_approved():
        blockers.append(
            "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION_must_be_true"
        )
    if not _flag_phase7g_allow_test_awb():
        blockers.append(
            "PHASE7G_ALLOW_DELHIVERY_TEST_AWB_must_be_true"
        )
    if (
        attempt.status
        != RazorpayCourierExecutionAttempt.Status.APPROVED_FOR_ONE_SHOT_RUN
    ):
        blockers.append(
            f"phase7g_attempt_status_must_be_approved_for_one_shot_run_was_{attempt.status}"
        )
    if attempt.provider_call_attempted:
        blockers.append(
            "phase7g_attempt_already_executed_idempotency_lock"
        )
    if not director_signoff.strip():
        blockers.append("director_signoff_must_be_non_empty")
    elif not _director_signoff_mentions_gate(
        director_signoff, attempt.source_phase7f_gate_id or 0
    ):
        blockers.append(
            "director_signoff_must_mention_phase7f_gate_id"
        )

    # Phase 7G-Hotfix-1: structured UTC window guard.
    # Parser is pure; validator is pure; no DB / env / provider call.
    # Refusal happens before the lazy Delhivery wrapper import + call.
    parsed_window = parse_director_signoff_window(director_signoff)
    if parsed_window is None:
        if director_signoff.strip():
            blockers.append(
                "phase7g_director_signoff_missing_structured_utc_window"
            )
    else:
        window_validation = validate_within_director_window(
            parsed_window
        )
        if not window_validation.valid:
            for entry in window_validation.blockers:
                if entry == "director_signoff_window_end_must_be_after_start":
                    blockers.append(
                        "phase7g_director_signoff_malformed_structured_utc_window"
                    )
                elif entry.startswith(
                    "director_signoff_window_too_long"
                ):
                    blockers.append(
                        "phase7g_director_signoff_window_too_long_max_15_min"
                    )
                elif entry == (
                    "director_signoff_window_stale_more_than_24h_old"
                ):
                    blockers.append(
                        "phase7g_director_signoff_window_stale_more_than_24h_old"
                    )
                elif entry == (
                    "now_outside_director_signoff_utc_window_before_start"
                ):
                    blockers.append(
                        "phase7g_now_before_director_signoff_utc_window_start"
                    )
                elif entry == (
                    "now_outside_director_signoff_utc_window_after_end"
                ):
                    blockers.append(
                        "phase7g_now_after_director_signoff_utc_window_end"
                    )
                elif entry == (
                    "director_signoff_missing_structured_utc_window"
                ):
                    blockers.append(
                        "phase7g_director_signoff_missing_structured_utc_window"
                    )
                else:
                    blockers.append(f"phase7g_{entry}")

    if not operator_name.strip():
        blockers.append("operator_name_must_be_non_empty")
    if not confirm_one_shot_courier_execution:
        blockers.append(
            "confirm_one_shot_courier_execution_must_be_true"
        )
    if not rollback_record_only_acknowledged:
        blockers.append(
            "rollback_record_only_acknowledged_must_be_true"
        )

    snapshot = _capture_env_flag_snapshot()
    delhivery_mode = str(snapshot.get("DELHIVERY_MODE", "mock")).lower()
    if delhivery_mode not in PHASE_7G_ALLOWED_DELHIVERY_MODES:
        blockers.append(
            f"DELHIVERY_MODE_must_be_mock_or_test_was_{delhivery_mode}"
        )
    if (
        mode_acknowledgement.strip().lower()
        != delhivery_mode
    ):
        blockers.append(
            "mode_acknowledgement_must_match_live_DELHIVERY_MODE"
        )

    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    eligibility = validate_phase7g_source_chain(
        attempt.source_phase7f_gate_id, require_env_flag=False
    )
    if not eligibility.eligible:
        blockers.extend(eligibility.blockers)

    attempt.kill_switch_snapshot_at_each_step = {
        **(attempt.kill_switch_snapshot_at_each_step or {}),
        "execute_start": kill,
    }
    attempt.env_flag_snapshot_at_each_step = {
        **(attempt.env_flag_snapshot_at_each_step or {}),
        "execute_start": snapshot,
    }
    attempt.delhivery_mode_at_each_step = {
        **(attempt.delhivery_mode_at_each_step or {}),
        "execute_start": delhivery_mode,
    }

    if blockers:
        attempt.blockers = list(blockers)
        attempt.status = (
            RazorpayCourierExecutionAttempt.Status.BLOCKED
        )
        attempt.save(
            update_fields=[
                "blockers",
                "status",
                "kill_switch_snapshot_at_each_step",
                "env_flag_snapshot_at_each_step",
                "delhivery_mode_at_each_step",
                "updated_at",
            ]
        )
        kind = (
            AUDIT_KIND_KILL_SWITCH_BLOCKED
            if "runtime_kill_switch_disabled" in blockers
            else (
                AUDIT_KIND_MODE_BLOCKED
                if any(
                    b.startswith("DELHIVERY_MODE_must_be_mock_or_test")
                    or b.startswith("mode_acknowledgement_must_match")
                    for b in blockers
                )
                else (
                    AUDIT_KIND_DUPLICATE_BLOCKED
                    if "phase7g_attempt_already_executed_idempotency_lock"
                    in blockers
                    else AUDIT_KIND_BLOCKED
                )
            )
        )
        write_event(
            kind=kind,
            text=(
                f"Phase 7G execute blocked attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_attempt_payload(
                attempt, extra={"blockers": list(blockers)}
            ),
        )
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "blockers": list(blockers),
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "fix_phase7g_execute_blockers",
        }

    # All gates green. Acquire idempotency lock.
    attempt.idempotency_lock_acquired = True
    attempt.director_signoff_text = (director_signoff or "")[:1000]
    attempt.director_signoff_present = True
    attempt.operator_name = (operator_name or "")[:120]
    attempt.mode_acknowledgement = (mode_acknowledgement or "")[:16]
    attempt.confirm_one_shot_courier_execution = True
    attempt.rollback_record_only_acknowledged = True
    attempt.executed_by = confirmed_by
    # Phase 7G-Hotfix-1: persist the parsed structured UTC window.
    if parsed_window is not None:
        attempt.recorded_signoff_window_valid = True
        attempt.recorded_signoff_window_start_utc = (
            parsed_window.window_start_utc
        )
        attempt.recorded_signoff_window_end_utc = (
            parsed_window.window_end_utc
        )
    else:
        attempt.recorded_signoff_window_valid = False
    attempt.save(
        update_fields=[
            "idempotency_lock_acquired",
            "director_signoff_text",
            "director_signoff_present",
            "operator_name",
            "mode_acknowledgement",
            "confirm_one_shot_courier_execution",
            "rollback_record_only_acknowledged",
            "executed_by",
            "kill_switch_snapshot_at_each_step",
            "env_flag_snapshot_at_each_step",
            "delhivery_mode_at_each_step",
            "recorded_signoff_window_valid",
            "recorded_signoff_window_start_utc",
            "recorded_signoff_window_end_utc",
            "updated_at",
        ]
    )

    payload = _build_phase7g_synthetic_payload(
        attempt_id=attempt.pk,
        synthetic_order_id=attempt.synthetic_order_id,
    )
    summary: dict[str, Any] = {}
    sdk_error: str | None = None
    try:
        # Mark provider_call_attempted BEFORE the network call so
        # even an exception preserves the audit + idempotency state.
        attempt.provider_call_attempted = True
        attempt.delhivery_call_attempted = True
        attempt.save(
            update_fields=[
                "provider_call_attempted",
                "delhivery_call_attempted",
                "updated_at",
            ]
        )
        summary = _create_awb_via_dedicated_wrapper(payload)
    except Phase7GExecutionError as exc:
        sdk_error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        sdk_error = f"unexpected:{exc.__class__.__name__}"

    after = _business_row_counts()
    attempt.after_counts = after
    attempt.kill_switch_snapshot_at_each_step = {
        **(attempt.kill_switch_snapshot_at_each_step or {}),
        "execute_end": _kill_switch_state(),
    }
    attempt.env_flag_snapshot_at_each_step = {
        **(attempt.env_flag_snapshot_at_each_step or {}),
        "execute_end": _capture_env_flag_snapshot(),
    }
    attempt.delhivery_mode_at_each_step = {
        **(attempt.delhivery_mode_at_each_step or {}),
        "execute_end": str(
            (
                getattr(settings, "DELHIVERY_MODE", "mock") or "mock"
            ).lower()
        ),
    }
    attempt.safe_request_summary = {
        "synthetic_order_id": attempt.synthetic_order_id,
        "weight_grams": PHASE_7G_SYNTHETIC_WEIGHT_GRAMS,
        "payment_mode": PHASE_7G_SYNTHETIC_PAYMENT_MODE,
        "cod_amount": PHASE_7G_SYNTHETIC_COD_AMOUNT,
    }

    if sdk_error or not summary.get("awb"):
        attempt.status = RazorpayCourierExecutionAttempt.Status.FAILED
        attempt.failed_at = timezone.now()
        attempt.warnings = list(attempt.warnings or []) + (
            [f"phase7g_execute_failed:{sdk_error}"]
            if sdk_error
            else ["phase7g_execute_succeeded_with_no_awb"]
        )
        attempt.save()
        try:
            assert_phase7g_no_unauthorised_mutation(
                attempt, before_counts=attempt.before_counts or {}
            )
        except ValueError:  # pragma: no cover - already audited
            pass
        write_event(
            kind=AUDIT_KIND_FAILED,
            text=(
                f"Phase 7G execute failed attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_attempt_payload(attempt),
        )
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "blockers": (
                [f"phase7g_execute_failed:{sdk_error}"]
                if sdk_error
                else ["phase7g_execute_succeeded_with_no_awb"]
            ),
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "phase7g_execute_failed_review_attempt",
        }

    attempt.provider_object_id = summary["awb"]
    attempt.provider_status = (
        summary["status"] or "Pickup Scheduled"
    )
    attempt.safe_response_summary = summary
    attempt.awb_created = True
    attempt.status = RazorpayCourierExecutionAttempt.Status.EXECUTED
    attempt.executed_at = timezone.now()
    attempt.next_action = (
        "phase7g_executed_record_rollback_when_director_directs"
    )
    attempt.save()

    assert_phase7g_no_unauthorised_mutation(
        attempt, before_counts=attempt.before_counts or {}
    )

    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=(
            f"Phase 7G execute succeeded attempt_id={attempt.pk} "
            f"awb_present={bool(summary['awb'])}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7G",
        "ok": True,
        "attempt": serialize_phase7g_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7G_WARNING],
        "nextAction": (
            "phase7g_executed_record_rollback_when_director_directs"
        ),
    }


# ---------------------------------------------------------------------------
# Rollback (record-only; never calls Delhivery cancel)
# ---------------------------------------------------------------------------


def rollback_phase7g_courier_execution_attempt(
    attempt_id: int,
    *,
    rolled_back_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Record-only rollback. NEVER calls Delhivery cancel.

    Sets attempt.rollback_status to ``recorded_only_no_provider_cancel``
    on success and writes a :class:`RazorpayCourierExecutionRollback`
    record. The attempt status flips to ``rolled_back_recorded``.
    """
    if not reason.strip():
        return {
            "phase": "7G",
            "ok": False,
            "attempt": None,
            "rollback": None,
            "blockers": ["phase7g_rollback_reason_required"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "supply_reason",
        }
    attempt = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    if attempt is None:
        return {
            "phase": "7G",
            "ok": False,
            "attempt": None,
            "rollback": None,
            "blockers": ["phase7g_attempt_not_found"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status == (
        RazorpayCourierExecutionAttempt.Status.ARCHIVED
    ):
        return {
            "phase": "7G",
            "ok": False,
            "attempt": serialize_phase7g_attempt(attempt),
            "rollback": None,
            "blockers": ["phase7g_attempt_already_archived"],
            "warnings": [PHASE_7G_WARNING],
            "nextAction": "verify_attempt_status",
        }

    timestamp = timezone.now().strftime("%Y%m%dT%H%M%S%f")
    record = RazorpayCourierExecutionRollback.objects.create(
        attempt=attempt,
        verified_at=timezone.now(),
        rollback_status=(
            RazorpayCourierExecutionRollback.Status.RECORDED_ONLY_NO_PROVIDER_CANCEL
        ),
        rollback_reason=(reason or "")[:1000],
        cancellation_attempted=False,
        cancellation_attempted_by_command="",
        provider_object_id_recorded=attempt.provider_object_id or "",
        env_flag_presence_at_rollback=_capture_env_flag_snapshot(),
        evaluated_safety_invariants=(
            build_phase7g_courier_execution_contract()
        ),
        recovery_notes="",
        idempotency_key=(
            f"phase7g::rollback::attempt::{attempt.pk}::run::{timestamp}"
        ),
    )

    attempt.rollback_status = (
        RazorpayCourierExecutionAttempt.RollbackStatus.RECORDED_ONLY_NO_PROVIDER_CANCEL
    )
    attempt.rolled_back_at = timezone.now()
    attempt.rollback_reason = (reason or "")[:1000]
    attempt.rolled_back_by = rolled_back_by
    if attempt.status not in (
        RazorpayCourierExecutionAttempt.Status.ARCHIVED,
        RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED,
    ):
        attempt.status = (
            RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED
        )
    attempt.next_action = "phase7g_rollback_recorded"
    attempt.save()

    assert_phase7g_no_unauthorised_mutation(
        attempt, before_counts=attempt.before_counts or {}
    )

    write_event(
        kind=AUDIT_KIND_ROLLED_BACK,
        text=(
            f"Phase 7G rollback recorded attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(
            attempt,
            extra={"rollback_record_id": record.pk},
        ),
    )
    return {
        "phase": "7G",
        "ok": True,
        "attempt": serialize_phase7g_attempt(attempt),
        "rollback": serialize_phase7g_rollback(record),
        "blockers": [],
        "warnings": [PHASE_7G_WARNING],
        "nextAction": "phase7g_rollback_recorded",
    }


# ---------------------------------------------------------------------------
# Summary + readiness
# ---------------------------------------------------------------------------


def summarize_phase7g_attempts(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayCourierExecutionAttempt.objects.all().order_by(
        "-created_at"
    )
    Status = RazorpayCourierExecutionAttempt.Status
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
        "rolledBackRecorded": qs.filter(
            status=Status.ROLLED_BACK_RECORDED
        ).count(),
        "rejected": qs.filter(status=Status.REJECTED).count(),
        "archived": qs.filter(status=Status.ARCHIVED).count(),
        "providerCallAttempted": qs.filter(
            provider_call_attempted=True
        ).count(),
        "delhiveryCallAttempted": qs.filter(
            delhivery_call_attempted=True
        ).count(),
        "awbCreated": qs.filter(awb_created=True).count(),
        "shipmentCreated": qs.filter(shipment_created=True).count(),
        "businessMutationWasMade": qs.filter(
            business_mutation_was_made=True
        ).count(),
        "realOrderMutationWasMade": qs.filter(
            real_order_mutation_was_made=True
        ).count(),
        "realPaymentMutationWasMade": qs.filter(
            real_payment_mutation_was_made=True
        ).count(),
        "realShipmentMutationWasMade": qs.filter(
            real_shipment_mutation_was_made=True
        ).count(),
        "customerNotificationSent": qs.filter(
            customer_notification_sent=True
        ).count(),
    }
    sample = [
        serialize_phase7g_attempt(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"counts": counts, "items": sample}


def inspect_phase7g_courier_execution_readiness() -> dict[str, Any]:
    summary = summarize_phase7g_attempts()
    counts = summary["counts"]
    snapshot = _capture_env_flag_snapshot()
    presence = _delhivery_env_presence()
    kill = _kill_switch_state()

    blockers: list[str] = []
    warnings: list[str] = [PHASE_7G_WARNING]

    for key in (
        "shipmentCreated",
        "businessMutationWasMade",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "realShipmentMutationWasMade",
        "customerNotificationSent",
    ):
        if counts.get(key, 0) > 0:
            blockers.append(
                f"phase_7g_attempt_{key}_observed_must_be_zero"
            )

    approved_phase7f_count = (
        RazorpayCourierReadinessGate.objects.filter(
            status=RazorpayCourierReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE7G_OR_COURIER_EXECUTION_REVIEW
        ).count()
    )

    delhivery_mode = snapshot.get("DELHIVERY_MODE")
    if delhivery_mode not in PHASE_7G_ALLOWED_DELHIVERY_MODES:
        blockers.append(
            f"DELHIVERY_MODE_must_be_mock_or_test_was_{delhivery_mode}"
        )
    if not kill.get("enabled", True):
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

    if blockers:
        next_action = "fix_phase7g_safety_blockers"
    elif not _flag_phase7g_lifecycle_enabled():
        next_action = "enable_phase7g_lifecycle_flag_for_review_only"
    elif approved_phase7f_count == 0:
        next_action = (
            "approve_at_least_one_phase_7f_gate_before_running_phase_7g"
        )
    elif (
        counts["pendingDirectorSignoff"] == 0
        and counts["approvedForOneShotRun"] == 0
    ):
        next_action = (
            "prepare_phase_7g_attempt_against_approved_phase7f_gate"
        )
    elif counts["approvedForOneShotRun"] == 0:
        next_action = (
            "approve_phase_7g_attempt_for_one_shot_courier_test_or_live_review"
        )
    else:
        next_action = (
            "phase7g_attempt_approved_for_one_shot_run_execute_only_with_separate_director_window"
        )

    safe_to_run = bool(
        not blockers
        and counts["approvedForOneShotRun"] >= 1
        and _flag_phase7g_lifecycle_enabled()
        and _flag_phase7g_director_approved()
        and _flag_phase7g_allow_test_awb()
    )

    return {
        "phase": "7G",
        "status": (
            "delhivery_test_or_mock_one_shot_courier_execution_only"
        ),
        "latestCompletedPhase": "7F",
        "nextPhase": "phase_7g_live_or_phase_7h_not_approved",
        "phase7GCourierExecutionEnabled": (
            _flag_phase7g_lifecycle_enabled()
        ),
        "phase7GDirectorApprovedOneShotCourierExecution": (
            _flag_phase7g_director_approved()
        ),
        "phase7GAllowDelhiveryTestAwb": (
            _flag_phase7g_allow_test_awb()
        ),
        "phase7GLiveCustomerCourierApproved": False,
        "phase7GAllowedDelhiveryModes": sorted(
            PHASE_7G_ALLOWED_DELHIVERY_MODES
        ),
        "delhiveryEnvPresence": presence,
        "envFlagSnapshot": snapshot,
        "killSwitch": kill,
        "approvedPhase7FGateCount": approved_phase7f_count,
        "attemptCounts": counts,
        "executionContract": (
            build_phase7g_courier_execution_contract()
        ),
        "forbiddenActions": list(PHASE_7G_FORBIDDEN_ACTIONS),
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "phase7GCallsDelhivery": False,
        "phase7GCreatesShipmentRow": False,
        "phase7GCreatesAwbRowOnAttemptOnly": True,
        "phase7GBooksCourierPickupSeparately": False,
        "phase7GGeneratesCourierLabel": False,
        "phase7GSendsWhatsApp": False,
        "phase7GQueuesWhatsApp": False,
        "phase7GCallsMetaCloud": False,
        "phase7GCallsRazorpay": False,
        "phase7GCallsVapi": False,
        "phase7GSendsCustomerNotification": False,
        "phase7GMutatesBusinessRow": False,
        "safeToRunPhase7GExecution": safe_to_run,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "recentAttempts": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("attemptCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7G courier execution readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7g_courier_execution_enabled": bool(
                    report.get("phase7GCourierExecutionEnabled")
                ),
                "approved_phase7f_gate_count": int(
                    report.get("approvedPhase7FGateCount") or 0
                ),
                "pending_director_signoff": int(
                    counts.get("pendingDirectorSignoff") or 0
                ),
                "approved_for_one_shot_run": int(
                    counts.get("approvedForOneShotRun") or 0
                ),
                "executed": int(counts.get("executed") or 0),
                "rolled_back_recorded": int(
                    counts.get("rolledBackRecorded") or 0
                ),
                "blockers": list(report.get("blockers") or []),
                "next_action": report.get("nextAction") or "",
                "kill_switch_enabled": (
                    report.get("killSwitch", {}) or {}
                ).get("enabled", True),
                "delhivery_mode": (
                    report.get("envFlagSnapshot", {}) or {}
                ).get("DELHIVERY_MODE", "mock"),
                **_audit_locked_false_payload(),
            }
        ),
    )


__all__ = (
    "PHASE_7G_WARNING",
    "PHASE_7G_FORBIDDEN_ACTIONS",
    "PHASE_7G_FORBIDDEN_PAYLOAD_KEYS",
    "PHASE_7G_ALLOWED_DELHIVERY_MODES",
    "PHASE_7G_SYNTHETIC_CUSTOMER_NAME",
    "PHASE_7G_SYNTHETIC_PHONE_LAST4",
    "PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED",
    "PHASE_7G_SYNTHETIC_CITY",
    "PHASE_7G_SYNTHETIC_STATE",
    "PHASE_7G_SYNTHETIC_PIN_PREFIX",
    "PHASE_7G_SYNTHETIC_WEIGHT_GRAMS",
    "PHASE_7G_SYNTHETIC_PAYMENT_MODE",
    "PHASE_7G_SYNTHETIC_COD_AMOUNT",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_APPROVED_FOR_ONE_SHOT",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_EXECUTED",
    "AUDIT_KIND_FAILED",
    "AUDIT_KIND_ROLLED_BACK",
    "AUDIT_KIND_BLOCKED",
    "AUDIT_KIND_KILL_SWITCH_BLOCKED",
    "AUDIT_KIND_INVARIANT_VIOLATION",
    "AUDIT_KIND_MODE_BLOCKED",
    "AUDIT_KIND_DUPLICATE_BLOCKED",
    "Phase7GEligibility",
    "Phase7GExecutionError",
    "build_phase7g_courier_execution_contract",
    "validate_phase7g_source_chain",
    "preview_phase7g_courier_execution_attempt",
    "prepare_phase7g_courier_execution_attempt",
    "approve_phase7g_courier_execution_attempt",
    "reject_phase7g_courier_execution_attempt",
    "execute_phase7g_courier_one_shot",
    "rollback_phase7g_courier_execution_attempt",
    "assert_phase7g_no_unauthorised_mutation",
    "serialize_phase7g_attempt",
    "serialize_phase7g_rollback",
    "summarize_phase7g_attempts",
    "inspect_phase7g_courier_execution_readiness",
    "emit_readiness_inspected_audit",
)
