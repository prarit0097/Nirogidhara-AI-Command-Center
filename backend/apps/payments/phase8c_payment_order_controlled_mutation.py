"""Phase 8C - Controlled Real Payment -> Order Mutation framework.

Phase 8C is a **CLI-only, one-shot controlled mutation** path
against a single explicitly selected internal / sandbox / test
``Order`` + ``Payment`` pair. Execute requires three env flags ALL
true, a structured Director sign-off UTC window (<= 15 min), the
kill switch enabled, and runtime safety proof that the target rows
are NOT real customer data.

Phase 8C NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi,
NEVER sends or queues WhatsApp, NEVER creates a ``Shipment`` / AWB
/ payment link, NEVER captures / refunds, NEVER sends a customer
notification, NEVER mutates ``Customer`` / ``Lead`` / ``Shipment``
/ ``DiscountOfferLog`` rows, NEVER edits any ``.env*`` file. Only
the explicitly selected target ``Order.payment_status`` and target
``Payment.status`` fields can be mutated by the execute path -- and
only after every gate above is satisfied.

Public surface:

- :func:`inspect_phase8c_payment_order_controlled_mutation_readiness`
- :func:`preview_phase8c_payment_order_controlled_mutation`
- :func:`prepare_phase8c_payment_order_controlled_mutation`
- :func:`dry_run_phase8c_payment_order_controlled_mutation`
- :func:`approve_phase8c_payment_order_controlled_mutation`
- :func:`execute_phase8c_payment_order_controlled_mutation`
- :func:`rollback_phase8c_payment_order_controlled_mutation`
- :func:`reject_phase8c_payment_order_controlled_mutation`
- :func:`archive_phase8c_payment_order_controlled_mutation`
- :func:`assert_phase8c_no_unauthorized_side_effect`
- :func:`assert_phase8c_no_provider_send_or_courier`
"""
from __future__ import annotations

import hashlib
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
    RazorpayPaymentOrderControlledMutationAttempt,
    RazorpayPaymentOrderControlledMutationGate,
    RazorpayPaymentOrderControlledMutationRollback,
    RazorpayPaymentOrderMutationReviewGate,
    RazorpayPaymentOrderMutationSandboxGate,
    RazorpayPhase7FinalAuditLock,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_8C_WARNING = (
    "Phase 8C is the Controlled Real Payment -> Order Mutation "
    "framework. Execute is CLI-only, one-shot, and refuses unless "
    "three env flags are true, the kill switch is enabled, a "
    "structured Director sign-off UTC window (<= 15 min) is "
    "supplied, and the target Order + Payment pair is proven "
    "internal / sandbox / test. Phase 8C NEVER calls Razorpay / "
    "Meta Cloud / Delhivery / Vapi, NEVER sends or queues WhatsApp, "
    "NEVER creates a Shipment / AWB / payment link, NEVER captures "
    "/ refunds, NEVER sends a customer notification, NEVER mutates "
    "Customer / Lead / Shipment / DiscountOfferLog rows, NEVER "
    "edits any .env file. Phase 7E-Live-B (real customer WhatsApp "
    "send) and Phase 7G-Live (real customer courier execution) "
    "remain NOT approved; broad customer automation remains NOT "
    "approved."
)


AUDIT_KIND_READINESS = "phase8c.payment_order.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase8c.payment_order.previewed"
AUDIT_KIND_PREPARED = "phase8c.payment_order.prepared"
AUDIT_KIND_DRY_RUN_PASSED = "phase8c.payment_order.dry_run_passed"
AUDIT_KIND_DRY_RUN_FAILED = "phase8c.payment_order.dry_run_failed"
AUDIT_KIND_APPROVED = "phase8c.payment_order.approved"
AUDIT_KIND_EXECUTED = "phase8c.payment_order.executed"
AUDIT_KIND_ROLLBACK_RECORDED = (
    "phase8c.payment_order.rollback_recorded"
)
AUDIT_KIND_REJECTED = "phase8c.payment_order.rejected"
AUDIT_KIND_ARCHIVED = "phase8c.payment_order.archived"
AUDIT_KIND_BLOCKED = "phase8c.payment_order.blocked"
AUDIT_KIND_FAILED = "phase8c.payment_order.failed"


PHASE_8C_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "call_razorpay_api",
    "call_meta_cloud_api",
    "call_delhivery_api",
    "call_vapi_api",
    "send_whatsapp_template",
    "send_whatsapp_freeform",
    "queue_whatsapp_outbound",
    "create_awb",
    "create_shipment_row",
    "create_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "send_customer_notification",
    "mutate_real_customer",
    "mutate_real_lead",
    "mutate_real_shipment",
    "mutate_real_discount_offer_log",
    "approve_real_customer_automation",
    "approve_phase7e_live_b",
    "approve_phase7g_live",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "execute_via_api_endpoint",
    "archive_via_api_endpoint",
    "dry_run_via_api_endpoint",
    "rollback_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_8C_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "token",
    "phone",
    "customer_phone",
    "email",
    "address",
    "address_line",
    "pincode",
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


# Locked-False contract fields on the Phase 8C gate row.
_GATE_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "real_customer_allowed",
    "customer_notification_allowed",
    "whatsapp_allowed",
    "courier_allowed",
    "provider_call_allowed",
    "shipment_creation_allowed",
    "payment_capture_allowed",
    "refund_allowed",
)


# Attempt-row locked-False contract. The mutation_was_made trio is
# explicitly excluded -- those flip True inside execute when (and
# only when) the model status fields are written.
_ATTEMPT_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "customer_notification_sent",
    "whatsapp_sent",
    "courier_called",
    "provider_call_attempted",
    "shipment_created",
)


# Phase 8B locked-False contract that must still hold on the source
# review gate.
_PHASE8B_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "real_mutation_allowed",
    "real_order_mutation_allowed",
    "real_payment_mutation_allowed",
    "customer_notification_allowed",
    "whatsapp_allowed",
    "courier_allowed",
)


# Review-only reference markers required on the proposed target.
_TARGET_ORDER_REFERENCE_PREFIXES: tuple[str, ...] = (
    "phase8c::controlled::order::",
    "phase8c-controlled-order-",
)
_TARGET_PAYMENT_REFERENCE_PREFIXES: tuple[str, ...] = (
    "phase8c::controlled::payment::",
    "phase8c-controlled-payment-",
)


# Safety-proof markers accepted on the target Order / Payment rows.
_INTERNAL_SANDBOX_PROOF_MARKERS: tuple[str, ...] = (
    "phase8c::controlled::",
    "phase8c-controlled-",
    "internal-test",
    "sandbox",
)


# Symbolic markers persisted on the gate row for evidence.
_SYMBOLIC_NEW_ORDER_STATUS = "paid_controlled_phase8c"
_SYMBOLIC_NEW_PAYMENT_STATUS = "captured_controlled_phase8c"

# Actual model values written at execute time. Order.payment_status
# is max_length=16 and choices include "Paid"; Payment.status is
# max_length=16 and choices include "Paid". The symbolic markers do
# NOT fit those fields -- so we write valid enum values and keep
# the symbolic intent in the snapshot fields on the gate row.
_ACTUAL_NEW_ORDER_PAYMENT_STATUS = "Paid"
_ACTUAL_NEW_PAYMENT_STATUS = "Paid"


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


def _flag_phase8c_gate_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED",
            False,
        )
    )


def _flag_phase8c_director_approved() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION",
            False,
        )
    )


def _flag_phase8c_allow_internal_mutation() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION",
            False,
        )
    )


def _flag_phase7e_live_b_approved() -> bool:
    return False


def _flag_phase7g_live_approved() -> bool:
    return False


def _kill_switch_state() -> dict[str, Any]:
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


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"phase": "8C"}
    forbidden = set(PHASE_8C_FORBIDDEN_PAYLOAD_KEYS)
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


def _business_row_counts() -> dict[str, int]:
    """Snapshot the protected business / send / courier tables. Phase
    8C is allowed to mutate only the *status* fields on the chosen
    target Order + Payment rows -- the *row counts* of every table
    below must stay constant across the full lifecycle."""
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


def _hash_signoff(signoff_text: str) -> str:
    if not signoff_text:
        return ""
    return hashlib.sha256(
        signoff_text.encode("utf-8", errors="replace")
    ).hexdigest()[:64]


# ---------------------------------------------------------------------------
# Defensive invariant guards
# ---------------------------------------------------------------------------


def assert_phase8c_no_unauthorized_side_effect(
    gate: RazorpayPaymentOrderControlledMutationGate,
    *,
    before_counts: dict[str, int],
    attempt: Optional[
        RazorpayPaymentOrderControlledMutationAttempt
    ] = None,
    rollback: Optional[
        RazorpayPaymentOrderControlledMutationRollback
    ] = None,
    allow_target_order_payment_status_drift: bool = False,
) -> None:
    """Raises ``ValueError`` (and writes an invariant audit row) if
    any locked-False boolean flipped True on the gate / attempt /
    rollback rows or if any protected business-row count drifted.

    ``allow_target_order_payment_status_drift`` is False everywhere
    except inside the guarded execute / rollback transaction --
    where the row *counts* still must be identical but the target
    rows are being intentionally status-mutated. The count-based
    guard is what matters; status drift is what the execute path
    explicitly authorises.
    """
    flipped: list[str] = []
    for field in _GATE_LOCKED_FALSE_FIELDS:
        if getattr(gate, field, False):
            flipped.append(f"gate.{field}_must_stay_false")
    if attempt is not None:
        for field in _ATTEMPT_LOCKED_FALSE_FIELDS:
            if getattr(attempt, field, False):
                flipped.append(f"attempt.{field}_must_stay_false")
    if rollback is not None:
        for field in (
            "customer_notification_sent",
            "whatsapp_sent",
            "courier_called",
            "provider_call_attempted",
        ):
            if getattr(rollback, field, False):
                flipped.append(f"rollback.{field}_must_stay_false")
    after = _business_row_counts()
    delta_keys: list[str] = []
    for key, count_before in before_counts.items():
        if after.get(key, count_before) != count_before:
            delta_keys.append(key)
    if not flipped and not delta_keys:
        return
    payload = _safe_audit_payload(
        {
            "gate_id": gate.pk,
            "attempt_id": attempt.pk if attempt is not None else None,
            "rollback_id": (
                rollback.pk if rollback is not None else None
            ),
            "flipped_locked_false_fields": flipped,
            "business_row_delta_keys": delta_keys,
            "allow_target_order_payment_status_drift": (
                allow_target_order_payment_status_drift
            ),
            "kill_switch_state_at_emit": _kill_switch_state(),
        }
    )
    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=(
            "Phase 8C invariant violation: locked-False or business "
            "row count drift detected; refusing the operation."
        ),
        tone=AuditEvent.Tone.DANGER,
        payload=payload,
    )
    raise ValueError(
        "Phase 8C invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


def assert_phase8c_no_provider_send_or_courier(
    *,
    attempt: Optional[
        RazorpayPaymentOrderControlledMutationAttempt
    ] = None,
    rollback: Optional[
        RazorpayPaymentOrderControlledMutationRollback
    ] = None,
) -> None:
    """Raises ``ValueError`` if a provider / send / courier flag
    flipped True on the supplied attempt / rollback row."""
    flipped: list[str] = []
    if attempt is not None:
        for field in (
            "provider_call_attempted",
            "customer_notification_sent",
            "whatsapp_sent",
            "courier_called",
            "shipment_created",
        ):
            if getattr(attempt, field, False):
                flipped.append(f"attempt.{field}_must_stay_false")
    if rollback is not None:
        for field in (
            "provider_call_attempted",
            "customer_notification_sent",
            "whatsapp_sent",
            "courier_called",
        ):
            if getattr(rollback, field, False):
                flipped.append(f"rollback.{field}_must_stay_false")
    if flipped:
        raise ValueError(
            "Phase 8C provider/send/courier invariant violation: "
            f"flipped={flipped}"
        )


# ---------------------------------------------------------------------------
# Target safety proof
# ---------------------------------------------------------------------------


def _order_is_internal_sandbox(order: Optional[Order]) -> bool:
    if order is None:
        return False
    haystack: list[str] = []
    pk = (getattr(order, "id", "") or "").lower()
    if pk:
        haystack.append(pk)
    notes = (getattr(order, "confirmation_notes", "") or "").lower()
    if notes:
        haystack.append(notes)
    checklist = (
        getattr(order, "confirmation_checklist", None) or {}
    )
    if isinstance(checklist, dict) and checklist.get(
        "phase8c_sandbox"
    ) is True:
        return True
    for needle in _INTERNAL_SANDBOX_PROOF_MARKERS:
        for hay in haystack:
            if needle in hay:
                return True
    return False


def _payment_is_internal_sandbox(payment: Optional[Payment]) -> bool:
    if payment is None:
        return False
    haystack: list[str] = []
    pk = (getattr(payment, "id", "") or "").lower()
    if pk:
        haystack.append(pk)
    gateway_ref = (
        getattr(payment, "gateway_reference_id", "") or ""
    ).lower()
    if gateway_ref:
        haystack.append(gateway_ref)
    raw = getattr(payment, "raw_response", None) or {}
    if isinstance(raw, dict) and raw.get("phase8c_sandbox") is True:
        return True
    for needle in _INTERNAL_SANDBOX_PROOF_MARKERS:
        for hay in haystack:
            if needle in hay:
                return True
    return False


def _validate_target_references(
    *,
    target_order_id: str,
    target_payment_id: str,
    target_order_reference: str,
    target_payment_reference: str,
) -> list[str]:
    blockers: list[str] = []
    if not (target_order_id or "").strip():
        blockers.append("phase8c_target_order_id_required")
    if not (target_payment_id or "").strip():
        blockers.append("phase8c_target_payment_id_required")
    order_ref = (target_order_reference or "").strip()
    payment_ref = (target_payment_reference or "").strip()
    if not order_ref:
        blockers.append("phase8c_target_order_reference_required")
    elif not any(
        order_ref.startswith(prefix)
        for prefix in _TARGET_ORDER_REFERENCE_PREFIXES
    ):
        blockers.append(
            "phase8c_target_order_reference_must_start_with_known_prefix"
        )
    if not payment_ref:
        blockers.append("phase8c_target_payment_reference_required")
    elif not any(
        payment_ref.startswith(prefix)
        for prefix in _TARGET_PAYMENT_REFERENCE_PREFIXES
    ):
        blockers.append(
            "phase8c_target_payment_reference_must_start_with_known_prefix"
        )
    if len(order_ref) > 120:
        blockers.append("phase8c_target_order_reference_too_long")
    if len(payment_ref) > 120:
        blockers.append("phase8c_target_payment_reference_too_long")
    return blockers


def _validate_target_safety(
    order: Optional[Order],
    payment: Optional[Payment],
) -> list[str]:
    blockers: list[str] = []
    if order is None:
        blockers.append("phase8c_target_order_not_found")
    elif not _order_is_internal_sandbox(order):
        blockers.append(
            "phase8c_target_order_not_proven_internal_sandbox"
        )
    if payment is None:
        blockers.append("phase8c_target_payment_not_found")
    elif not _payment_is_internal_sandbox(payment):
        blockers.append(
            "phase8c_target_payment_not_proven_internal_sandbox"
        )
    if (
        order is not None
        and payment is not None
        and (payment.order_id or "") != (order.id or "")
    ):
        blockers.append(
            "phase8c_target_payment_order_id_must_match_target_order_id"
        )
    return blockers


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_phase8b_gate(
    gate: Optional[RazorpayPaymentOrderMutationReviewGate],
) -> list[str]:
    blockers: list[str] = []
    if gate is None:
        blockers.append("phase8c_source_phase8b_gate_not_found")
        return blockers
    if (
        gate.status
        != RazorpayPaymentOrderMutationReviewGate.Status.APPROVED_FOR_FUTURE_PHASE8C_CONTROLLED_MUTATION_REVIEW
    ):
        blockers.append(
            "phase8c_source_phase8b_gate_status_must_be_"
            "approved_for_future_phase8c_controlled_mutation_review"
            f"_was_{gate.status}"
        )
    if not bool(gate.dry_run_passed):
        blockers.append(
            "phase8c_source_phase8b_dry_run_passed_must_be_true"
        )
    if not bool(gate.rollback_dry_run_passed):
        blockers.append(
            "phase8c_source_phase8b_rollback_dry_run_passed_must_be_true"
        )
    for field in _PHASE8B_LOCKED_FALSE_FIELDS:
        if getattr(gate, field, False):
            blockers.append(
                f"phase8c_source_phase8b_{field}_must_stay_false"
            )
    return blockers


def _validate_phase7i_lock(
    lock: Optional[RazorpayPhase7FinalAuditLock],
) -> list[str]:
    blockers: list[str] = []
    if lock is None:
        blockers.append("phase8c_source_phase7i_lock_not_found")
        return blockers
    if lock.status != RazorpayPhase7FinalAuditLock.Status.LOCKED:
        blockers.append(
            "phase8c_source_phase7i_lock_status_must_be_locked_was_"
            f"{lock.status}"
        )
    return blockers


def _validate_eligibility(
    *,
    phase8b_gate_id: Optional[int],
    require_env_flag: bool = True,
) -> dict[str, Any]:
    blockers: list[str] = []
    if require_env_flag and not _flag_phase8c_gate_enabled():
        blockers.append(
            "PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        )
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    phase8b_gate: Optional[
        RazorpayPaymentOrderMutationReviewGate
    ] = None
    if phase8b_gate_id:
        phase8b_gate = (
            RazorpayPaymentOrderMutationReviewGate.objects.filter(
                pk=phase8b_gate_id
            )
            .select_related(
                "source_phase8a_gate",
                "source_phase7i_lock",
                "source_phase7d_attempt",
            )
            .first()
        )
    blockers += _validate_phase8b_gate(phase8b_gate)

    phase8a_gate: Optional[
        RazorpayPaymentOrderMutationSandboxGate
    ] = None
    phase7i_lock: Optional[RazorpayPhase7FinalAuditLock] = None
    phase7d: Optional[RazorpayControlledPilotExecutionAttempt] = None
    if phase8b_gate is not None:
        phase8a_gate = phase8b_gate.source_phase8a_gate
        phase7i_lock = phase8b_gate.source_phase7i_lock
        phase7d = phase8b_gate.source_phase7d_attempt
    blockers += _validate_phase7i_lock(phase7i_lock)

    return {
        "phase8b_gate": phase8b_gate,
        "phase8a_gate": phase8a_gate,
        "phase7i_lock": phase7i_lock,
        "phase7d": phase7d,
        "blockers": blockers,
        "eligible": not blockers,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_phase8c_gate(
    row: RazorpayPaymentOrderControlledMutationGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase8BGateId": row.source_phase8b_gate_id,
        "sourcePhase8AGateId": row.source_phase8a_gate_id,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "controlledMutationOnly": bool(row.controlled_mutation_only),
        "realCustomerAllowed": bool(row.real_customer_allowed),
        "customerNotificationAllowed": bool(
            row.customer_notification_allowed
        ),
        "whatsAppAllowed": bool(row.whatsapp_allowed),
        "courierAllowed": bool(row.courier_allowed),
        "providerCallAllowed": bool(row.provider_call_allowed),
        "shipmentCreationAllowed": bool(row.shipment_creation_allowed),
        "paymentCaptureAllowed": bool(row.payment_capture_allowed),
        "refundAllowed": bool(row.refund_allowed),
        "rollbackRequired": bool(row.rollback_required),
        "directorSignoffRequired": bool(row.director_signoff_required),
        "structuredUtcWindowRequired": bool(
            row.structured_utc_window_required
        ),
        "sourcePaymentReferenceSnapshot": (
            row.source_payment_reference_snapshot
        ),
        "targetOrderReferenceSnapshot": (
            row.target_order_reference_snapshot
        ),
        "targetPaymentReferenceSnapshot": (
            row.target_payment_reference_snapshot
        ),
        "proposedOldOrderStatus": row.proposed_old_order_status,
        "proposedNewOrderStatus": row.proposed_new_order_status,
        "proposedOldPaymentStatus": row.proposed_old_payment_status,
        "proposedNewPaymentStatus": row.proposed_new_payment_status,
        "dryRunPassed": bool(row.dry_run_passed),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "reviewedByUsername": row.reviewed_by_username,
        "reviewedAt": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "reviewReasonPresent": bool(
            (row.review_reason or "").strip()
        ),
        "rejectReasonPresent": bool(
            (row.reject_reason or "").strip()
        ),
        "archiveReasonPresent": bool(
            (row.archive_reason or "").strip()
        ),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action or "",
        "evidenceJson": row.evidence_json or {},
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
        "updatedAt": (
            row.updated_at.isoformat() if row.updated_at else None
        ),
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


def serialize_phase8c_attempt(
    row: RazorpayPaymentOrderControlledMutationAttempt,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "sourcePhase8BGateId": row.source_phase8b_gate_id,
        "targetOrderId": row.target_order_id,
        "targetPaymentId": row.target_payment_id,
        "targetOrderReference": row.target_order_reference,
        "targetPaymentReference": row.target_payment_reference,
        "paymentReferenceSnapshot": row.payment_reference_snapshot,
        "status": row.status,
        "oldOrderStatus": row.old_order_status,
        "newOrderStatus": row.new_order_status,
        "oldPaymentStatus": row.old_payment_status,
        "newPaymentStatus": row.new_payment_status,
        "orderMutationWasMade": bool(row.order_mutation_was_made),
        "paymentMutationWasMade": bool(row.payment_mutation_was_made),
        "businessMutationWasMade": bool(
            row.business_mutation_was_made
        ),
        "customerNotificationSent": bool(
            row.customer_notification_sent
        ),
        "whatsAppSent": bool(row.whatsapp_sent),
        "courierCalled": bool(row.courier_called),
        "providerCallAttempted": bool(row.provider_call_attempted),
        "shipmentCreated": bool(row.shipment_created),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "directorSignoffTextHashPresent": bool(
            (row.director_signoff_text_hash or "").strip()
        ),
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
        "recordedSignoffWindowValid": bool(
            row.recorded_signoff_window_valid
        ),
        "operatorNamePresent": bool(
            (row.operator_name or "").strip()
        ),
        "executedAt": (
            row.executed_at.isoformat() if row.executed_at else None
        ),
        "failedAt": (
            row.failed_at.isoformat() if row.failed_at else None
        ),
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
        "updatedAt": (
            row.updated_at.isoformat() if row.updated_at else None
        ),
    }


def serialize_phase8c_rollback(
    row: RazorpayPaymentOrderControlledMutationRollback,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "attemptId": row.attempt_id,
        "status": row.status,
        "restoredOrderStatus": row.restored_order_status,
        "restoredPaymentStatus": row.restored_payment_status,
        "rollbackWasMade": bool(row.rollback_was_made),
        "customerNotificationSent": bool(
            row.customer_notification_sent
        ),
        "whatsAppSent": bool(row.whatsapp_sent),
        "courierCalled": bool(row.courier_called),
        "providerCallAttempted": bool(row.provider_call_attempted),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "reasonPresent": bool((row.reason or "").strip()),
        "rolledBackAt": (
            row.rolled_back_at.isoformat()
            if row.rolled_back_at
            else None
        ),
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
    }


def _audit_gate_payload(
    gate: RazorpayPaymentOrderControlledMutationGate,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gate_id": gate.pk,
        "status": gate.status,
        "phase8b_gate_id": gate.source_phase8b_gate_id,
        "phase8a_gate_id": gate.source_phase8a_gate_id,
        "phase7i_lock_id": gate.source_phase7i_lock_id,
        "phase7d_attempt_id": gate.source_phase7d_attempt_id,
        "controlled_mutation_only": bool(
            gate.controlled_mutation_only
        ),
        "real_customer_allowed": False,
        "customer_notification_allowed": False,
        "whatsapp_allowed": False,
        "courier_allowed": False,
        "provider_call_allowed": False,
        "shipment_creation_allowed": False,
        "payment_capture_allowed": False,
        "refund_allowed": False,
        "kill_switch_state_at_emit": _kill_switch_state(),
    }
    if extra:
        payload.update(extra)
    return _safe_audit_payload(payload)


# ---------------------------------------------------------------------------
# Evidence JSON composer
# ---------------------------------------------------------------------------


def _build_evidence_json(
    *,
    phase8b_gate: RazorpayPaymentOrderMutationReviewGate,
    phase8a_gate: RazorpayPaymentOrderMutationSandboxGate,
    phase7i_lock: RazorpayPhase7FinalAuditLock,
    phase7d: Optional[RazorpayControlledPilotExecutionAttempt],
) -> dict[str, Any]:
    return {
        "phase": "8C",
        "phase8b": {
            "gateId": phase8b_gate.pk,
            "status": phase8b_gate.status,
            "dryRunPassed": bool(phase8b_gate.dry_run_passed),
            "rollbackDryRunPassed": bool(
                phase8b_gate.rollback_dry_run_passed
            ),
            "reviewOnly": bool(phase8b_gate.review_only),
        },
        "phase8a": {
            "gateId": phase8a_gate.pk,
            "status": phase8a_gate.status,
            "sandboxOnly": bool(phase8a_gate.sandbox_only),
        },
        "phase7i": {
            "lockId": phase7i_lock.pk,
            "status": phase7i_lock.status,
        },
        "phase7d": (
            {
                "attemptId": phase7d.pk,
                "status": phase7d.status,
                "providerObjectId": phase7d.provider_object_id or "",
                "rollbackStatus": phase7d.rollback_status,
            }
            if phase7d is not None
            else None
        ),
        "controlledMutationContract": {
            "controlledMutationOnly": True,
            "realCustomerAllowed": False,
            "customerNotificationAllowed": False,
            "whatsAppAllowed": False,
            "courierAllowed": False,
            "providerCallAllowed": False,
            "shipmentCreationAllowed": False,
            "paymentCaptureAllowed": False,
            "refundAllowed": False,
            "rollbackRequired": True,
            "directorSignoffRequired": True,
            "structuredUtcWindowRequired": True,
            "structuredUtcWindowMaxSeconds": 900,
            "proposedNewOrderStatusSymbolic": (
                _SYMBOLIC_NEW_ORDER_STATUS
            ),
            "proposedNewPaymentStatusSymbolic": (
                _SYMBOLIC_NEW_PAYMENT_STATUS
            ),
            "actualNewOrderPaymentStatusWritten": (
                _ACTUAL_NEW_ORDER_PAYMENT_STATUS
            ),
            "actualNewPaymentStatusWritten": (
                _ACTUAL_NEW_PAYMENT_STATUS
            ),
        },
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase8c_payment_order_controlled_mutation(
    phase8b_gate_id: int,
) -> dict[str, Any]:
    eligibility = _validate_eligibility(
        phase8b_gate_id=phase8b_gate_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 8C preview phase8b_gate_id={phase8b_gate_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase8b_gate_id": phase8b_gate_id,
                "eligible": eligibility["eligible"],
                "blockers": list(eligibility["blockers"]),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    evidence: dict[str, Any] = {}
    if (
        eligibility["eligible"]
        and eligibility["phase8b_gate"] is not None
        and eligibility["phase8a_gate"] is not None
        and eligibility["phase7i_lock"] is not None
    ):
        evidence = _build_evidence_json(
            phase8b_gate=eligibility["phase8b_gate"],
            phase8a_gate=eligibility["phase8a_gate"],
            phase7i_lock=eligibility["phase7i_lock"],
            phase7d=eligibility["phase7d"],
        )
    return {
        "phase": "8C",
        "found": eligibility["phase8b_gate"] is not None,
        "sourcePhase8BGateId": phase8b_gate_id,
        "sourcePhase8AGateId": (
            eligibility["phase8a_gate"].pk
            if eligibility["phase8a_gate"]
            else None
        ),
        "sourcePhase7ILockId": (
            eligibility["phase7i_lock"].pk
            if eligibility["phase7i_lock"]
            else None
        ),
        "sourcePhase7DAttemptId": (
            eligibility["phase7d"].pk
            if eligibility["phase7d"]
            else None
        ),
        "eligible": eligibility["eligible"],
        "blockers": list(eligibility["blockers"]),
        "warnings": [PHASE_8C_WARNING],
        "evidence": evidence,
        "nextAction": (
            "ready_to_prepare_phase8c_payment_order_controlled_mutation"
            if eligibility["eligible"]
            and _flag_phase8c_gate_enabled()
            else (
                "fix_phase8c_eligibility_blockers_or_enable_phase8c_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase8c_payment_order_controlled_mutation(
    phase8b_gate_id: int,
) -> dict[str, Any]:
    """Atomic + idempotent prepare on the source Phase 8B gate.
    NEVER calls any provider; NEVER mutates business rows; NEVER
    edits any ``.env*`` file."""
    eligibility = _validate_eligibility(
        phase8b_gate_id=phase8b_gate_id, require_env_flag=True
    )
    if (
        not eligibility["eligible"]
        or eligibility["phase8b_gate"] is None
        or eligibility["phase8a_gate"] is None
        or eligibility["phase7i_lock"] is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8C prepare blocked phase8b_gate_id="
                f"{phase8b_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase8b_gate_id": phase8b_gate_id,
                    "blockers": list(eligibility["blockers"]),
                    "kill_switch_state_at_emit": _kill_switch_state(),
                }
            ),
        )
        return {
            "phase": "8C",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_8C_WARNING],
            "nextAction": (
                "fix_phase8c_eligibility_blockers_or_enable_phase8c_flag"
            ),
        }

    phase8b_gate = eligibility["phase8b_gate"]
    phase8a_gate = eligibility["phase8a_gate"]
    phase7i_lock = eligibility["phase7i_lock"]
    phase7d = eligibility["phase7d"]
    before = _business_row_counts()

    payment_reference_snapshot = (
        getattr(phase7d, "provider_object_id", "") or ""
    )[:120]

    with transaction.atomic():
        existing = (
            RazorpayPaymentOrderControlledMutationGate.objects.filter(
                source_phase8b_gate=phase8b_gate
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "8C",
                "created": False,
                "reused": True,
                "gate": serialize_phase8c_gate(existing),
                "blockers": [],
                "warnings": [PHASE_8C_WARNING],
                "nextAction": (
                    "phase8c_gate_pending_manual_review"
                    if existing.status
                    == RazorpayPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW
                    else f"phase8c_gate_status_{existing.status}"
                ),
            }

        gate = RazorpayPaymentOrderControlledMutationGate(
            source_phase8b_gate=phase8b_gate,
            source_phase8a_gate=phase8a_gate,
            source_phase7i_lock=phase7i_lock,
            source_phase7d_attempt=phase7d,
            status=(
                RazorpayPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW
            ),
            controlled_mutation_only=True,
            real_customer_allowed=False,
            customer_notification_allowed=False,
            whatsapp_allowed=False,
            courier_allowed=False,
            provider_call_allowed=False,
            shipment_creation_allowed=False,
            payment_capture_allowed=False,
            refund_allowed=False,
            rollback_required=True,
            director_signoff_required=True,
            structured_utc_window_required=True,
            source_payment_reference_snapshot=payment_reference_snapshot,
            target_order_reference_snapshot="",
            target_payment_reference_snapshot="",
            proposed_old_order_status=(
                "current_or_unknown_controlled_mutation_only"
            ),
            proposed_new_order_status=_SYMBOLIC_NEW_ORDER_STATUS,
            proposed_old_payment_status=(
                "current_or_unknown_controlled_mutation_only"
            ),
            proposed_new_payment_status=_SYMBOLIC_NEW_PAYMENT_STATUS,
            dry_run_passed=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            evidence_json=_build_evidence_json(
                phase8b_gate=phase8b_gate,
                phase8a_gate=phase8a_gate,
                phase7i_lock=phase7i_lock,
                phase7d=phase7d,
            ),
            blockers=[],
            warnings=[PHASE_8C_WARNING],
            next_action="phase8c_gate_pending_manual_review",
        )
        assert_phase8c_no_unauthorized_side_effect(
            gate, before_counts=before
        )
        gate.save()

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 8C gate prepared gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "8C",
        "created": True,
        "reused": False,
        "gate": serialize_phase8c_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8C_WARNING],
        "nextAction": "phase8c_gate_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def dry_run_phase8c_payment_order_controlled_mutation(
    gate_id: int,
    *,
    target_order_id: str = "",
    target_payment_id: str = "",
    target_order_reference: str = "",
    target_payment_reference: str = "",
) -> dict[str, Any]:
    """Controlled-mutation dry-run. NEVER mutates real rows. Requires
    target Order + Payment IDs that are proven internal / sandbox /
    test. Persists a pending_director_signoff attempt on success."""
    gate = (
        RazorpayPaymentOrderControlledMutationGate.objects.filter(
            pk=gate_id
        )
        .select_related("source_phase8b_gate")
        .first()
    )
    if gate is None:
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "attempt": None,
            "blockers": ["phase8c_gate_not_found"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderControlledMutationGate.Status.DRY_RUN_PASSED,
    }:
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "attempt": None,
            "blockers": [
                f"phase8c_gate_status_{gate.status}_not_dry_runnable"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_status",
        }

    eligibility = _validate_eligibility(
        phase8b_gate_id=gate.source_phase8b_gate_id,
        require_env_flag=True,
    )
    blockers: list[str] = list(eligibility["blockers"])
    blockers += _validate_target_references(
        target_order_id=target_order_id,
        target_payment_id=target_payment_id,
        target_order_reference=target_order_reference,
        target_payment_reference=target_payment_reference,
    )

    target_order = (
        Order.objects.filter(pk=target_order_id).first()
        if (target_order_id or "").strip()
        else None
    )
    target_payment = (
        Payment.objects.filter(pk=target_payment_id).first()
        if (target_payment_id or "").strip()
        else None
    )
    blockers += _validate_target_safety(target_order, target_payment)

    before = _business_row_counts()
    payment_reference_snapshot = (
        gate.source_payment_reference_snapshot or ""
    )[:120]
    actual_old_order_status = (
        getattr(target_order, "payment_status", "") or ""
    )[:32]
    actual_old_payment_status = (
        getattr(target_payment, "status", "") or ""
    )[:32]

    if blockers:
        # Persist a failed attempt so the operator can see why.
        attempt = RazorpayPaymentOrderControlledMutationAttempt.objects.create(
            gate=gate,
            source_phase8b_gate=gate.source_phase8b_gate,
            target_order_id=(target_order_id or "")[:32],
            target_payment_id=(target_payment_id or "")[:32],
            target_order_reference=(
                target_order_reference or ""
            )[:120],
            target_payment_reference=(
                target_payment_reference or ""
            )[:120],
            payment_reference_snapshot=payment_reference_snapshot,
            status=(
                RazorpayPaymentOrderControlledMutationAttempt.Status.BLOCKED
            ),
            old_order_status=actual_old_order_status,
            new_order_status="",
            old_payment_status=actual_old_payment_status,
            new_payment_status="",
            before_counts=before,
            after_counts=before,
            count_deltas={},
            blockers=list(blockers),
            warnings=[PHASE_8C_WARNING],
        )
        write_event(
            kind=AUDIT_KIND_DRY_RUN_FAILED,
            text=(
                f"Phase 8C dry-run failed gate_id={gate.pk} "
                f"attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(
                gate,
                extra={
                    "attempt_id": attempt.pk,
                    "blockers": list(blockers),
                },
            ),
        )
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "attempt": serialize_phase8c_attempt(attempt),
            "blockers": list(blockers),
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "fix_phase8c_dry_run_blockers",
        }

    # Eligible. Execute the controlled-mutation dry-run with no
    # mutation. We record the symbolic markers as the proposed new
    # values; the actual model values written at execute time
    # (Order.payment_status=Paid, Payment.status=Paid) live on the
    # evidence_json and are documented on the gate row.
    attempt = RazorpayPaymentOrderControlledMutationAttempt.objects.create(
        gate=gate,
        source_phase8b_gate=gate.source_phase8b_gate,
        target_order_id=(target_order_id or "")[:32],
        target_payment_id=(target_payment_id or "")[:32],
        target_order_reference=(target_order_reference or "")[:120],
        target_payment_reference=(
            target_payment_reference or ""
        )[:120],
        payment_reference_snapshot=payment_reference_snapshot,
        status=(
            RazorpayPaymentOrderControlledMutationAttempt.Status.PENDING_DIRECTOR_SIGNOFF
        ),
        old_order_status=actual_old_order_status,
        new_order_status=_ACTUAL_NEW_ORDER_PAYMENT_STATUS,
        old_payment_status=actual_old_payment_status,
        new_payment_status=_ACTUAL_NEW_PAYMENT_STATUS,
        before_counts=before,
        after_counts=before,
        count_deltas={},
        blockers=[],
        warnings=[PHASE_8C_WARNING],
    )

    after = _business_row_counts()
    deltas: dict[str, int] = {}
    for key, count_before in before.items():
        count_after = after.get(key, count_before)
        if count_after != count_before:
            deltas[key] = count_after - count_before

    passed = not deltas
    attempt.after_counts = after
    attempt.count_deltas = deltas
    if not passed:
        attempt.status = (
            RazorpayPaymentOrderControlledMutationAttempt.Status.BLOCKED
        )
        attempt.blockers = list(attempt.blockers or []) + [
            "phase8c_dry_run_business_row_count_changed"
        ]
    attempt.save()

    try:
        assert_phase8c_no_unauthorized_side_effect(
            gate, before_counts=before, attempt=attempt
        )
    except ValueError as exc:  # pragma: no cover - defensive
        attempt.status = (
            RazorpayPaymentOrderControlledMutationAttempt.Status.BLOCKED
        )
        attempt.blockers = list(attempt.blockers or []) + [str(exc)]
        attempt.save()

    if passed and attempt.status == (
        RazorpayPaymentOrderControlledMutationAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    ):
        gate.status = (
            RazorpayPaymentOrderControlledMutationGate.Status.DRY_RUN_PASSED
        )
        gate.dry_run_passed = True
        gate.target_order_reference_snapshot = (
            target_order_reference or ""
        )[:120]
        gate.target_payment_reference_snapshot = (
            target_payment_reference or ""
        )[:120]
        gate.next_action = (
            "phase8c_gate_dry_run_passed_awaiting_approve"
        )
        gate.save(
            update_fields=[
                "status",
                "dry_run_passed",
                "target_order_reference_snapshot",
                "target_payment_reference_snapshot",
                "next_action",
                "updated_at",
            ]
        )

    is_pass = bool(
        passed
        and attempt.status
        == RazorpayPaymentOrderControlledMutationAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    )
    write_event(
        kind=(
            AUDIT_KIND_DRY_RUN_PASSED
            if is_pass
            else AUDIT_KIND_DRY_RUN_FAILED
        ),
        text=(
            f"Phase 8C dry-run {'passed' if is_pass else 'failed'} "
            f"gate_id={gate.pk} attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO if is_pass else AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate,
            extra={
                "attempt_id": attempt.pk,
                "dry_run_passed": is_pass,
                "target_order_id": (
                    (target_order_id or "")[:32]
                ),
                "target_payment_id": (
                    (target_payment_id or "")[:32]
                ),
            },
        ),
    )
    return {
        "phase": "8C",
        "ok": is_pass,
        "gate": serialize_phase8c_gate(gate),
        "attempt": serialize_phase8c_attempt(attempt),
        "blockers": list(attempt.blockers or []),
        "warnings": [PHASE_8C_WARNING],
        "nextAction": (
            "phase8c_gate_dry_run_passed_awaiting_approve"
            if is_pass
            else "fix_phase8c_dry_run_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


def _gate_lookup(
    gate_id: int,
) -> Optional[RazorpayPaymentOrderControlledMutationGate]:
    return (
        RazorpayPaymentOrderControlledMutationGate.objects.filter(
            pk=gate_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def approve_phase8c_payment_order_controlled_mutation(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Flip status to
    ``approved_for_one_shot_controlled_mutation``. Non-empty reason
    + ``dry_run_passed=True`` + at least one ``pending_director_signoff``
    attempt required. Approval does NOT execute the mutation."""
    if not reason.strip():
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "blockers": ["phase8c_approve_reason_required"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "blockers": ["phase8c_gate_not_found"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_id",
        }
    if (
        gate.status
        != RazorpayPaymentOrderControlledMutationGate.Status.DRY_RUN_PASSED
    ):
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "blockers": [
                f"phase8c_gate_status_{gate.status}_not_transitionable_to_approved"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "run_phase8c_dry_run_first",
        }
    if not gate.dry_run_passed:
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "blockers": ["phase8c_gate_dry_run_passed_must_be_true"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "run_phase8c_dry_run_first",
        }
    pending_attempt_present = gate.attempts.filter(
        status=(
            RazorpayPaymentOrderControlledMutationAttempt.Status.PENDING_DIRECTOR_SIGNOFF
        )
    ).exists()
    if not pending_attempt_present:
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "blockers": [
                "phase8c_no_pending_director_signoff_attempt_present"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "run_phase8c_dry_run_first",
        }

    before = _business_row_counts()
    assert_phase8c_no_unauthorized_side_effect(
        gate, before_counts=before
    )

    with transaction.atomic():
        gate.status = (
            RazorpayPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_CONTROLLED_MUTATION
        )
        gate.approved_at = timezone.now()
        gate.reviewed_by = reviewed_by
        gate.reviewed_by_username = _reviewer_username(reviewed_by)
        gate.reviewed_at = timezone.now()
        gate.review_reason = (reason or "")[:1000]
        gate.next_action = (
            "phase8c_gate_approved_for_one_shot_controlled_mutation"
        )
        gate.save()
        # Promote each pending attempt to approved_for_one_shot_mutation.
        gate.attempts.filter(
            status=(
                RazorpayPaymentOrderControlledMutationAttempt.Status.PENDING_DIRECTOR_SIGNOFF
            )
        ).update(
            status=(
                RazorpayPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_MUTATION
            )
        )

    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            "Phase 8C approved-for-one-shot-controlled-mutation "
            f"gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8C",
        "ok": True,
        "gate": serialize_phase8c_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8C_WARNING],
        "nextAction": (
            "phase8c_gate_approved_for_one_shot_controlled_mutation"
        ),
    }


def reject_phase8c_payment_order_controlled_mutation(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "blockers": ["phase8c_reject_reason_required"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "blockers": ["phase8c_gate_not_found"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayPaymentOrderControlledMutationGate.Status.DRAFT,
        RazorpayPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderControlledMutationGate.Status.DRY_RUN_PASSED,
        RazorpayPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_CONTROLLED_MUTATION,
        RazorpayPaymentOrderControlledMutationGate.Status.BLOCKED,
    }:
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "blockers": [
                f"phase8c_reject_refused_for_status_{gate.status}"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_status",
        }
    before = _business_row_counts()
    assert_phase8c_no_unauthorized_side_effect(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayPaymentOrderControlledMutationGate.Status.REJECTED
    )
    gate.rejected_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.reject_reason = (reason or "")[:1000]
    gate.next_action = "phase8c_gate_rejected"
    gate.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 8C rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8C",
        "ok": True,
        "gate": serialize_phase8c_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8C_WARNING],
        "nextAction": "phase8c_gate_rejected",
    }


def archive_phase8c_payment_order_controlled_mutation(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "blockers": ["phase8c_archive_reason_required"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8C",
            "ok": False,
            "gate": None,
            "blockers": ["phase8c_gate_not_found"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status == (
        RazorpayPaymentOrderControlledMutationGate.Status.ARCHIVED
    ):
        return {
            "phase": "8C",
            "ok": False,
            "gate": serialize_phase8c_gate(gate),
            "blockers": ["phase8c_gate_already_archived"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_gate_status",
        }
    before = _business_row_counts()
    assert_phase8c_no_unauthorized_side_effect(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayPaymentOrderControlledMutationGate.Status.ARCHIVED
    )
    gate.archived_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.archive_reason = (reason or "")[:1000]
    gate.next_action = "phase8c_gate_archived"
    gate.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 8C archived gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8C",
        "ok": True,
        "gate": serialize_phase8c_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8C_WARNING],
        "nextAction": "phase8c_gate_archived",
    }


# ---------------------------------------------------------------------------
# Execute (one-shot, CLI-only)
# ---------------------------------------------------------------------------


def execute_phase8c_payment_order_controlled_mutation(
    attempt_id: int,
    *,
    director_signoff: str = "",
    operator_name: str = "",
    confirm_one_shot_mutation: bool = False,
    now=None,
) -> dict[str, Any]:
    """One-shot CLI-only execute. Refuses unless every safety gate
    is satisfied. The only mutation performed is writing the target
    Order's ``payment_status`` and target Payment's ``status`` to
    ``Paid`` (the actual model enum value). No provider call, no
    notification, no WhatsApp, no courier, no Shipment row."""
    from apps.saas.utc_window import (  # local import keeps module pure
        parse_director_signoff_window,
        validate_within_director_window,
    )

    attempt = (
        RazorpayPaymentOrderControlledMutationAttempt.objects.filter(
            pk=attempt_id
        )
        .select_related("gate", "gate__source_phase8b_gate")
        .first()
    )
    if attempt is None:
        return {
            "phase": "8C",
            "ok": False,
            "attempt": None,
            "rollback": None,
            "blockers": ["phase8c_attempt_not_found"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_attempt_id",
        }
    gate = attempt.gate

    blockers: list[str] = []
    if not _flag_phase8c_gate_enabled():
        blockers.append(
            "PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        )
    if not _flag_phase8c_director_approved():
        blockers.append(
            "PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION_must_be_true"
        )
    if not _flag_phase8c_allow_internal_mutation():
        blockers.append(
            "PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION_must_be_true"
        )
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if not bool(confirm_one_shot_mutation):
        blockers.append("phase8c_confirm_one_shot_mutation_required")
    if not (operator_name or "").strip():
        blockers.append("phase8c_operator_name_required")

    signoff = (director_signoff or "").strip()
    if not signoff:
        blockers.append("phase8c_director_signoff_required")
    else:
        if f"phase8c_attempt_id_{attempt.pk}" not in signoff:
            blockers.append(
                "phase8c_director_signoff_must_reference_phase8c_attempt_id"
            )
        if (
            f"phase8b_gate_id_{gate.source_phase8b_gate_id}"
            not in signoff
        ):
            blockers.append(
                "phase8c_director_signoff_must_reference_phase8b_gate_id"
            )
    parsed_window = (
        parse_director_signoff_window(signoff) if signoff else None
    )
    window_result = validate_within_director_window(
        parsed_window, now=now
    )
    if not window_result.valid:
        for marker in window_result.blockers:
            blockers.append(f"phase8c_{marker}")

    # Gate / attempt status pre-conditions.
    if (
        gate.status
        != RazorpayPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_CONTROLLED_MUTATION
    ):
        blockers.append(
            f"phase8c_gate_status_{gate.status}_not_executable"
        )
    if attempt.status != (
        RazorpayPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_MUTATION
    ):
        blockers.append(
            f"phase8c_attempt_status_{attempt.status}_not_executable"
        )

    # No prior execution.
    if (
        gate.attempts.filter(
            status=(
                RazorpayPaymentOrderControlledMutationAttempt.Status.EXECUTED
            )
        ).exists()
    ):
        blockers.append(
            "phase8c_gate_already_has_executed_attempt"
        )

    # Target safety proof must STILL hold at execute time.
    target_order = Order.objects.filter(
        pk=attempt.target_order_id
    ).first()
    target_payment = Payment.objects.filter(
        pk=attempt.target_payment_id
    ).first()
    blockers += _validate_target_safety(target_order, target_payment)

    if blockers:
        attempt.status = (
            RazorpayPaymentOrderControlledMutationAttempt.Status.BLOCKED
        )
        attempt.blockers = list(attempt.blockers or []) + list(blockers)
        attempt.save(update_fields=["status", "blockers", "updated_at"])
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8C execute blocked attempt_id={attempt.pk} "
                f"gate_id={gate.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(
                gate,
                extra={
                    "attempt_id": attempt.pk,
                    "blockers": list(blockers),
                    "operator_name_present": bool(
                        (operator_name or "").strip()
                    ),
                },
            ),
        )
        return {
            "phase": "8C",
            "ok": False,
            "attempt": serialize_phase8c_attempt(attempt),
            "rollback": None,
            "blockers": list(blockers),
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "fix_phase8c_execute_blockers",
        }

    # Capture before-counts + actual current status values.
    before = _business_row_counts()
    actual_old_order_payment_status = (
        target_order.payment_status if target_order else ""
    )[:32]
    actual_old_payment_status = (
        target_payment.status if target_payment else ""
    )[:32]

    try:
        with transaction.atomic():
            # Mutate ONLY the chosen target rows, ONLY the status
            # fields, using model-valid enum values.
            target_order.payment_status = (
                _ACTUAL_NEW_ORDER_PAYMENT_STATUS
            )
            target_order.save(update_fields=["payment_status"])
            target_payment.status = _ACTUAL_NEW_PAYMENT_STATUS
            target_payment.save(update_fields=["status"])

            attempt.old_order_status = (
                actual_old_order_payment_status
            )
            attempt.new_order_status = (
                _ACTUAL_NEW_ORDER_PAYMENT_STATUS
            )
            attempt.old_payment_status = actual_old_payment_status
            attempt.new_payment_status = _ACTUAL_NEW_PAYMENT_STATUS
            attempt.order_mutation_was_made = True
            attempt.payment_mutation_was_made = True
            attempt.business_mutation_was_made = True
            # NEVER flips: customer_notification_sent / whatsapp_sent /
            # courier_called / provider_call_attempted / shipment_created.
            attempt.director_signoff_text_hash = _hash_signoff(
                signoff
            )
            attempt.recorded_signoff_window_start_utc = (
                parsed_window.window_start_utc
                if parsed_window
                else None
            )
            attempt.recorded_signoff_window_end_utc = (
                parsed_window.window_end_utc
                if parsed_window
                else None
            )
            attempt.recorded_signoff_window_valid = bool(
                window_result.valid
            )
            attempt.operator_name = (operator_name or "")[:120]
            attempt.executed_at = timezone.now()
            attempt.status = (
                RazorpayPaymentOrderControlledMutationAttempt.Status.EXECUTED
            )

            after = _business_row_counts()
            deltas: dict[str, int] = {}
            for key, count_before in before.items():
                count_after = after.get(key, count_before)
                if count_after != count_before:
                    deltas[key] = count_after - count_before
            attempt.before_counts = before
            attempt.after_counts = after
            attempt.count_deltas = deltas
            attempt.save()

            # Count-based invariant: row counts must be identical
            # (status-only mutation; no row created / deleted).
            if deltas:
                raise ValueError(
                    "Phase 8C execute count drift: " + str(deltas)
                )
            # Provider / send / courier flags must still be False.
            assert_phase8c_no_provider_send_or_courier(
                attempt=attempt
            )

            gate.status = (
                RazorpayPaymentOrderControlledMutationGate.Status.EXECUTED
            )
            gate.next_action = "phase8c_gate_executed"
            gate.save(
                update_fields=["status", "next_action", "updated_at"]
            )
    except Exception as exc:
        attempt.refresh_from_db()
        attempt.status = (
            RazorpayPaymentOrderControlledMutationAttempt.Status.FAILED
        )
        attempt.failed_at = timezone.now()
        attempt.blockers = list(attempt.blockers or []) + [
            f"phase8c_execute_exception:{type(exc).__name__}"
        ]
        attempt.save(
            update_fields=[
                "status",
                "failed_at",
                "blockers",
                "updated_at",
            ]
        )
        write_event(
            kind=AUDIT_KIND_FAILED,
            text=(
                f"Phase 8C execute failed attempt_id={attempt.pk} "
                f"gate_id={gate.pk}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload=_audit_gate_payload(
                gate,
                extra={
                    "attempt_id": attempt.pk,
                    "exception_class": type(exc).__name__,
                },
            ),
        )
        return {
            "phase": "8C",
            "ok": False,
            "attempt": serialize_phase8c_attempt(attempt),
            "rollback": None,
            "blockers": [
                f"phase8c_execute_exception:{type(exc).__name__}"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "phase8c_execute_failed_review_required",
        }

    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=(
            f"Phase 8C executed attempt_id={attempt.pk} "
            f"gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload=_audit_gate_payload(
            gate,
            extra={
                "attempt_id": attempt.pk,
                "target_order_id": attempt.target_order_id,
                "target_payment_id": attempt.target_payment_id,
                "old_order_status": attempt.old_order_status,
                "new_order_status": attempt.new_order_status,
                "old_payment_status": attempt.old_payment_status,
                "new_payment_status": attempt.new_payment_status,
                "operator_name_present": bool(
                    (operator_name or "").strip()
                ),
                "director_signoff_text_hash_present": bool(
                    attempt.director_signoff_text_hash
                ),
            },
        ),
    )
    return {
        "phase": "8C",
        "ok": True,
        "attempt": serialize_phase8c_attempt(attempt),
        "rollback": None,
        "blockers": [],
        "warnings": [PHASE_8C_WARNING],
        "nextAction": "phase8c_attempt_executed_awaiting_rollback",
    }


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback_phase8c_payment_order_controlled_mutation(
    attempt_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Restore the originally captured ``old_order_status`` and
    ``old_payment_status`` on the previously mutated rows. No
    provider call, no notification, no WhatsApp, no courier, no
    Shipment row created."""
    if not (reason or "").strip():
        return {
            "phase": "8C",
            "ok": False,
            "rollback": None,
            "blockers": ["phase8c_rollback_reason_required"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "supply_reason",
        }
    attempt = (
        RazorpayPaymentOrderControlledMutationAttempt.objects.filter(
            pk=attempt_id
        )
        .select_related("gate")
        .first()
    )
    if attempt is None:
        return {
            "phase": "8C",
            "ok": False,
            "rollback": None,
            "blockers": ["phase8c_attempt_not_found"],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status != (
        RazorpayPaymentOrderControlledMutationAttempt.Status.EXECUTED
    ):
        return {
            "phase": "8C",
            "ok": False,
            "rollback": None,
            "blockers": [
                f"phase8c_attempt_status_{attempt.status}_not_rollback_eligible"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "verify_attempt_status",
        }

    target_order = Order.objects.filter(
        pk=attempt.target_order_id
    ).first()
    target_payment = Payment.objects.filter(
        pk=attempt.target_payment_id
    ).first()
    safety_blockers = _validate_target_safety(
        target_order, target_payment
    )
    if safety_blockers:
        return {
            "phase": "8C",
            "ok": False,
            "rollback": None,
            "blockers": safety_blockers,
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "fix_phase8c_rollback_blockers",
        }

    before = _business_row_counts()
    try:
        with transaction.atomic():
            rollback = (
                RazorpayPaymentOrderControlledMutationRollback.objects.create(
                    attempt=attempt,
                    status=(
                        RazorpayPaymentOrderControlledMutationRollback.Status.DRAFT
                    ),
                    restored_order_status=attempt.old_order_status,
                    restored_payment_status=(
                        attempt.old_payment_status
                    ),
                    rollback_was_made=False,
                    customer_notification_sent=False,
                    whatsapp_sent=False,
                    courier_called=False,
                    provider_call_attempted=False,
                    before_counts=before,
                    after_counts=before,
                    count_deltas={},
                    reason=(reason or "")[:1000],
                )
            )
            target_order.payment_status = (
                attempt.old_order_status or
                target_order.payment_status
            )
            target_order.save(update_fields=["payment_status"])
            target_payment.status = (
                attempt.old_payment_status or
                target_payment.status
            )
            target_payment.save(update_fields=["status"])

            after = _business_row_counts()
            deltas: dict[str, int] = {}
            for key, count_before in before.items():
                count_after = after.get(key, count_before)
                if count_after != count_before:
                    deltas[key] = count_after - count_before
            if deltas:
                raise ValueError(
                    "Phase 8C rollback count drift: " + str(deltas)
                )
            rollback.after_counts = after
            rollback.count_deltas = deltas
            rollback.rollback_was_made = True
            rollback.rolled_back_at = timezone.now()
            rollback.status = (
                RazorpayPaymentOrderControlledMutationRollback.Status.ROLLBACK_RECORDED
            )
            rollback.save()
            assert_phase8c_no_provider_send_or_courier(
                rollback=rollback
            )

            attempt.status = (
                RazorpayPaymentOrderControlledMutationAttempt.Status.ROLLED_BACK
            )
            attempt.save(update_fields=["status", "updated_at"])
            attempt.gate.status = (
                RazorpayPaymentOrderControlledMutationGate.Status.ROLLED_BACK
            )
            attempt.gate.next_action = "phase8c_gate_rolled_back"
            attempt.gate.save(
                update_fields=["status", "next_action", "updated_at"]
            )
    except Exception as exc:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8C rollback failed attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload=_audit_gate_payload(
                attempt.gate,
                extra={
                    "attempt_id": attempt.pk,
                    "exception_class": type(exc).__name__,
                },
            ),
        )
        return {
            "phase": "8C",
            "ok": False,
            "rollback": None,
            "blockers": [
                f"phase8c_rollback_exception:{type(exc).__name__}"
            ],
            "warnings": [PHASE_8C_WARNING],
            "nextAction": "phase8c_rollback_failed_review_required",
        }

    write_event(
        kind=AUDIT_KIND_ROLLBACK_RECORDED,
        text=(
            f"Phase 8C rollback recorded attempt_id={attempt.pk} "
            f"rollback_id={rollback.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            attempt.gate,
            extra={
                "attempt_id": attempt.pk,
                "rollback_id": rollback.pk,
                "restored_order_status": (
                    rollback.restored_order_status
                ),
                "restored_payment_status": (
                    rollback.restored_payment_status
                ),
                "reason_excerpt": (reason or "")[:120],
            },
        ),
    )
    return {
        "phase": "8C",
        "ok": True,
        "rollback": serialize_phase8c_rollback(rollback),
        "blockers": [],
        "warnings": [PHASE_8C_WARNING],
        "nextAction": "phase8c_rollback_recorded",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase8c_gates(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayPaymentOrderControlledMutationGate.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value
        for s in RazorpayPaymentOrderControlledMutationGate.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase8c_gate(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "8C", "counts": counts, "items": items}


def inspect_phase8c_payment_order_controlled_mutation_readiness() -> (
    dict[str, Any]
):
    summary = summarize_phase8c_gates(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    eligible_phase8b_gates = (
        RazorpayPaymentOrderMutationReviewGate.objects.filter(
            status=(
                RazorpayPaymentOrderMutationReviewGate.Status.APPROVED_FOR_FUTURE_PHASE8C_CONTROLLED_MUTATION_REVIEW
            ),
            real_mutation_allowed=False,
            real_order_mutation_allowed=False,
            real_payment_mutation_allowed=False,
            customer_notification_allowed=False,
            whatsapp_allowed=False,
            courier_allowed=False,
            dry_run_passed=True,
            rollback_dry_run_passed=True,
        ).count()
    )

    blockers: list[str] = []
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")

    if blockers:
        next_action = "fix_phase8c_safety_blockers"
    elif not _flag_phase8c_gate_enabled():
        next_action = (
            "enable_phase8c_payment_order_controlled_mutation_gate_flag"
        )
    elif eligible_phase8b_gates == 0:
        next_action = "no_eligible_phase8b_gate_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase8c_gates_pending_manual_review"
    elif counts.get("dry_run_passed", 0) > 0:
        next_action = "phase8c_gates_dry_run_passed_awaiting_approve"
    elif (
        counts.get(
            "approved_for_one_shot_controlled_mutation", 0
        )
        > 0
    ):
        next_action = (
            "phase8c_gates_approved_awaiting_director_signoff_execute"
        )
    elif counts.get("executed", 0) > 0:
        next_action = "phase8c_gates_executed_awaiting_rollback"
    elif counts.get("rolled_back", 0) > 0:
        next_action = "phase8c_gates_rolled_back_awaiting_archive"
    else:
        next_action = (
            "ready_to_prepare_phase8c_payment_order_controlled_mutation"
        )

    return {
        "phase": "8C",
        "status": "payment_order_controlled_mutation_only",
        "latestCompletedPhase": "8B",
        "nextPhase": (
            "phase8c_one_shot_internal_or_remains_not_approved"
        ),
        "phase8CGateEnabled": _flag_phase8c_gate_enabled(),
        "phase8CDirectorApproved": _flag_phase8c_director_approved(),
        "phase8CAllowInternalMutation": (
            _flag_phase8c_allow_internal_mutation()
        ),
        "killSwitch": kill,
        "eligiblePhase8BGateCount": eligible_phase8b_gates,
        "phase8CGateCounts": counts,
        "items": summary["items"],
        "phase8CCallsRazorpay": False,
        "phase8CCallsMetaCloud": False,
        "phase8CCallsDelhivery": False,
        "phase8CCallsVapi": False,
        "phase8CSendsWhatsApp": False,
        "phase8CQueuesWhatsApp": False,
        "phase8CCreatesShipmentRow": False,
        "phase8CCreatesAwb": False,
        "phase8CCreatesPaymentLink": False,
        "phase8CCapturesPayment": False,
        "phase8CRefundsPayment": False,
        "phase8CSendsCustomerNotification": False,
        "phase8CMutatesCustomer": False,
        "phase8CMutatesLead": False,
        "phase8CMutatesShipment": False,
        "phase8CMutatesDiscountOfferLog": False,
        "phase8CApprovesRealCustomerAutomation": False,
        "phase7ELiveBApproved": False,
        "phase7GLiveApproved": False,
        "executionPath": "cli_only_one_shot_controlled_mutation",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_8C_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_8C_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text=(
            "Phase 8C payment-order controlled mutation readiness "
            "inspected"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase8b_gate_count": int(
                    report.get("eligiblePhase8BGateCount") or 0
                ),
                "phase8c_gate_enabled": bool(
                    report.get("phase8CGateEnabled")
                ),
                "phase8c_director_approved": bool(
                    report.get("phase8CDirectorApproved")
                ),
                "phase8c_allow_internal_mutation": bool(
                    report.get("phase8CAllowInternalMutation")
                ),
                "gate_counts": (
                    report.get("phase8CGateCounts") or {}
                ),
                "next_action": report.get("nextAction") or "",
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
