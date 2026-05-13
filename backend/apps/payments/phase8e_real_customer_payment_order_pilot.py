"""Phase 8E - Real Customer Payment -> Order Mutation Pilot Gate.

Phase 8E is **review / dry-run only** against ONE explicitly
selected real customer ``Order`` + ``Payment`` candidate. It
converts a locked Phase 8D evidence chain into a single
pilot-review row, validates the chosen real candidate, masks
customer PII, and dry-runs the proposed Pending -> Paid mutation
without writing any field on any business row.

Phase 8E NEVER mutates real ``Order`` / ``Payment`` /
``Customer`` / ``Lead`` / ``Shipment`` / ``DiscountOfferLog`` /
``WhatsAppMessage`` rows, NEVER calls Razorpay / Meta Cloud /
Delhivery / Vapi, NEVER sends or queues WhatsApp, NEVER sends a
customer notification, NEVER creates a ``Shipment`` / AWB /
payment link, NEVER captures / refunds, NEVER edits any
``.env*`` file.

Approval flips status to
``approved_for_future_phase8f_real_customer_controlled_mutation``
only -- it does NOT authorize any real mutation.

Public surface:

- :func:`inspect_phase8e_real_customer_payment_order_pilot_readiness`
- :func:`preview_phase8e_real_customer_payment_order_pilot`
- :func:`prepare_phase8e_real_customer_payment_order_pilot`
- :func:`select_phase8e_real_customer_candidate`
- :func:`dry_run_phase8e_real_customer_payment_order_pilot`
- :func:`approve_phase8e_real_customer_payment_order_pilot`
- :func:`reject_phase8e_real_customer_payment_order_pilot`
- :func:`archive_phase8e_real_customer_payment_order_pilot`
- :func:`assert_phase8e_no_business_mutation`
- :func:`serialize_phase8e_gate`
- :func:`serialize_phase8e_candidate`
- :func:`serialize_phase8e_dry_run`
- :func:`summarize_phase8e_gates`
"""
from __future__ import annotations

import re
from typing import Any, Optional

from django.conf import settings
from django.db import IntegrityError, transaction
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
    RazorpayPaymentOrderControlledMutationEvidenceLock,
    RazorpayRealCustomerPaymentOrderMutationCandidate,
    RazorpayRealCustomerPaymentOrderMutationPilotDryRun,
    RazorpayRealCustomerPaymentOrderMutationPilotGate,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_8E_WARNING = (
    "Phase 8E is the Real Customer Payment -> Order Mutation "
    "Pilot Gate. It is review / dry-run only against ONE explicit "
    "real customer Order + Payment candidate. Approval flips "
    "status to "
    "`approved_for_future_phase8f_real_customer_controlled_mutation` "
    "and freezes the candidate snapshot. Phase 8E NEVER mutates "
    "real Order / Payment / Customer / Lead / Shipment / "
    "DiscountOfferLog / WhatsAppMessage rows, NEVER calls Razorpay "
    "/ Meta Cloud / Delhivery / Vapi, NEVER sends or queues "
    "WhatsApp, NEVER creates a Shipment / AWB / payment link, "
    "NEVER captures, NEVER refunds, NEVER sends a customer "
    "notification, NEVER edits any .env file. Phase 8F (real "
    "customer controlled mutation) remains NOT approved. Phase "
    "7E-Live-B / 7G-Live / broad customer automation remain NOT "
    "approved."
)


AUDIT_KIND_READINESS = "phase8e.pilot.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase8e.pilot.previewed"
AUDIT_KIND_PREPARED = "phase8e.pilot.prepared"
AUDIT_KIND_CANDIDATE_SELECTED = "phase8e.pilot.candidate_selected"
AUDIT_KIND_DRY_RUN_PASSED = "phase8e.pilot.dry_run_passed"
AUDIT_KIND_DRY_RUN_FAILED = "phase8e.pilot.dry_run_failed"
AUDIT_KIND_APPROVED = "phase8e.pilot.approved"
AUDIT_KIND_REJECTED = "phase8e.pilot.rejected"
AUDIT_KIND_ARCHIVED = "phase8e.pilot.archived"
AUDIT_KIND_BLOCKED = "phase8e.pilot.blocked"


PHASE_8E_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "execute_real_customer_mutation",
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
    "mutate_real_order_status",
    "mutate_real_order_payment_status",
    "mutate_real_order_state",
    "mutate_real_payment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "mutate_real_shipment",
    "mutate_real_discount_offer_log",
    "approve_phase8f_real_customer_mutation",
    "approve_real_customer_automation",
    "approve_phase7e_live_b",
    "approve_phase7g_live",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "select_via_api_endpoint",
    "dry_run_via_api_endpoint",
    "archive_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_8E_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "token",
    "phone",
    "raw_phone",
    "customer_phone",
    "email",
    "customer_email",
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
    "raw_response",
    "raw_payload",
    "raw_signature",
    "raw_secret",
    "gateway_reference_id",
    "payment_url",
    "customer_name",
)


# Locked-False contract on the gate row.
_GATE_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "real_mutation_allowed",
    "real_order_mutation_allowed",
    "real_payment_mutation_allowed",
    "customer_notification_allowed",
    "whatsapp_allowed",
    "courier_allowed",
    "provider_call_allowed",
)


# Locked-False contract on the candidate row.
_CANDIDATE_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "customer_notification_allowed",
    "whatsapp_allowed",
    "courier_allowed",
)


# Locked-False contract on the dry-run row.
_DRY_RUN_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "would_mutate_order",
    "would_mutate_payment",
    "would_send_customer_notification",
    "would_send_whatsapp",
    "would_call_courier",
    "would_create_shipment",
    "would_call_provider",
)


# Phase 8C sandbox markers; Phase 8E refuses candidates carrying
# any of these.
_PHASE8C_SANDBOX_MARKERS: tuple[str, ...] = (
    "phase8c::controlled::",
    "phase8c-controlled-",
    "internal-test",
    "sandbox",
)


# Terminal Order stages Phase 8E refuses (cannot pilot a Pending
# -> Paid transition on an order that's already past payment).
_TERMINAL_ORDER_STAGES: tuple[str, ...] = (
    Order.Stage.DELIVERED.value,
    Order.Stage.RTO.value,
    Order.Stage.CANCELLED.value,
)


# Terminal Payment statuses Phase 8E refuses.
_TERMINAL_PAYMENT_STATUSES: tuple[str, ...] = (
    Payment.Status.PAID.value,
    Payment.Status.REFUNDED.value,
    Payment.Status.CANCELLED.value,
    Payment.Status.EXPIRED.value,
    Payment.Status.FAILED.value,
)


_PROPOSED_NEW_ORDER_PAYMENT_STATUS = Order.PaymentStatus.PAID.value
_PROPOSED_NEW_PAYMENT_STATUS = Payment.Status.PAID.value


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


def _flag_phase8e_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED",
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
    safe: dict[str, Any] = {"phase": "8E"}
    forbidden = set(PHASE_8E_FORBIDDEN_PAYLOAD_KEYS)
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


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
# PII masking helpers
# ---------------------------------------------------------------------------


def _mask_phone_last4(raw_phone: str) -> str:
    """Extract the last 4 digits of a phone string. Returns empty
    string if fewer than 4 digits."""
    digits = re.sub(r"\D", "", raw_phone or "")
    if len(digits) < 4:
        return ""
    return digits[-4:]


def _mask_customer_name(raw_name: str) -> str:
    """Mask a customer name to its first letter of each word.

    "Prarit Sidana" -> "P***** S*****"
    Empty -> "" .
    """
    if not raw_name:
        return ""
    parts = [p for p in re.split(r"\s+", raw_name.strip()) if p]
    masked_parts: list[str] = []
    for part in parts:
        if len(part) == 1:
            masked_parts.append(part)
        else:
            masked_parts.append(part[0] + "*" * max(len(part) - 1, 1))
    return " ".join(masked_parts)[:120]


# ---------------------------------------------------------------------------
# Defensive invariant guard
# ---------------------------------------------------------------------------


def assert_phase8e_no_business_mutation(
    gate: RazorpayRealCustomerPaymentOrderMutationPilotGate,
    *,
    before_counts: dict[str, int],
    candidate: Optional[
        RazorpayRealCustomerPaymentOrderMutationCandidate
    ] = None,
    dry_run: Optional[
        RazorpayRealCustomerPaymentOrderMutationPilotDryRun
    ] = None,
) -> None:
    flipped: list[str] = []
    for field in _GATE_LOCKED_FALSE_FIELDS:
        if getattr(gate, field, False):
            flipped.append(f"gate.{field}_must_stay_false")
    if candidate is not None:
        for field in _CANDIDATE_LOCKED_FALSE_FIELDS:
            if getattr(candidate, field, False):
                flipped.append(
                    f"candidate.{field}_must_stay_false"
                )
    if dry_run is not None:
        for field in _DRY_RUN_LOCKED_FALSE_FIELDS:
            if getattr(dry_run, field, False):
                flipped.append(f"dry_run.{field}_must_stay_false")
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
            "candidate_id": (
                candidate.pk if candidate is not None else None
            ),
            "dry_run_id": dry_run.pk if dry_run is not None else None,
            "flipped_locked_false_fields": flipped,
            "business_row_delta_keys": delta_keys,
            "kill_switch_state_at_emit": _kill_switch_state(),
        }
    )
    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=(
            "Phase 8E invariant violation: locked-False or business "
            "row count drift detected; refusing the operation."
        ),
        tone=AuditEvent.Tone.DANGER,
        payload=payload,
    )
    raise ValueError(
        "Phase 8E invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_phase8d_lock(
    lock: Optional[
        RazorpayPaymentOrderControlledMutationEvidenceLock
    ],
) -> list[str]:
    blockers: list[str] = []
    if lock is None:
        blockers.append("phase8e_source_phase8d_lock_not_found")
        return blockers
    if (
        lock.status
        != RazorpayPaymentOrderControlledMutationEvidenceLock.Status.LOCKED
    ):
        blockers.append(
            "phase8e_source_phase8d_lock_status_must_be_locked_was_"
            f"{lock.status}"
        )
    if not bool(lock.final_db_restored_snapshot):
        blockers.append(
            "phase8e_source_phase8d_final_db_restored_snapshot_must_be_true"
        )
    # Phase 8C gate snapshot must reflect rolled_back. The Phase 8D
    # lock snapshots this on `phase8c_gate_status_snapshot`.
    if (
        lock.phase8c_gate_status_snapshot
        and lock.phase8c_gate_status_snapshot != "rolled_back"
    ):
        blockers.append(
            "phase8e_source_phase8d_phase8c_gate_status_snapshot_must_be_rolled_back_was_"
            f"{lock.phase8c_gate_status_snapshot}"
        )
    return blockers


def _validate_eligibility(
    *,
    phase8d_lock_id: Optional[int],
    require_env_flag: bool = True,
) -> dict[str, Any]:
    blockers: list[str] = []
    if require_env_flag and not _flag_phase8e_enabled():
        blockers.append(
            "PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED_must_be_true"
        )
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    phase8d_lock: Optional[
        RazorpayPaymentOrderControlledMutationEvidenceLock
    ] = None
    if phase8d_lock_id:
        phase8d_lock = (
            RazorpayPaymentOrderControlledMutationEvidenceLock.objects.filter(
                pk=phase8d_lock_id
            )
            .select_related(
                "source_phase8c_gate",
                "source_phase8b_gate",
                "source_phase8a_gate",
                "source_phase7i_lock",
            )
            .first()
        )
    blockers += _validate_phase8d_lock(phase8d_lock)
    return {
        "phase8d_lock": phase8d_lock,
        "phase8c_gate": (
            phase8d_lock.source_phase8c_gate
            if phase8d_lock is not None
            else None
        ),
        "phase8b_gate": (
            phase8d_lock.source_phase8b_gate
            if phase8d_lock is not None
            else None
        ),
        "phase8a_gate": (
            phase8d_lock.source_phase8a_gate
            if phase8d_lock is not None
            else None
        ),
        "phase7i_lock": (
            phase8d_lock.source_phase7i_lock
            if phase8d_lock is not None
            else None
        ),
        "blockers": blockers,
        "eligible": not blockers,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_phase8e_gate(
    row: RazorpayRealCustomerPaymentOrderMutationPilotGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase8DLockId": row.source_phase8d_lock_id,
        "sourcePhase8CGateId": row.source_phase8c_gate_id,
        "sourcePhase8BGateId": row.source_phase8b_gate_id,
        "sourcePhase8AGateId": row.source_phase8a_gate_id,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "realCustomerPilotOnly": bool(row.real_customer_pilot_only),
        "realMutationAllowed": bool(row.real_mutation_allowed),
        "realOrderMutationAllowed": bool(
            row.real_order_mutation_allowed
        ),
        "realPaymentMutationAllowed": bool(
            row.real_payment_mutation_allowed
        ),
        "customerNotificationAllowed": bool(
            row.customer_notification_allowed
        ),
        "whatsAppAllowed": bool(row.whatsapp_allowed),
        "courierAllowed": bool(row.courier_allowed),
        "providerCallAllowed": bool(row.provider_call_allowed),
        "phase8FRequired": bool(row.phase8f_required),
        "manualReviewRequired": bool(row.manual_review_required),
        "directorSignoffRequired": bool(row.director_signoff_required),
        "rollbackRequired": bool(row.rollback_required),
        "candidateOrderIdSnapshot": row.candidate_order_id_snapshot,
        "candidatePaymentIdSnapshot": row.candidate_payment_id_snapshot,
        "candidateOrderCurrentStatusSnapshot": (
            row.candidate_order_current_status_snapshot
        ),
        "candidatePaymentCurrentStatusSnapshot": (
            row.candidate_payment_current_status_snapshot
        ),
        "proposedOrderNewStatusSnapshot": (
            row.proposed_order_new_status_snapshot
        ),
        "proposedPaymentNewStatusSnapshot": (
            row.proposed_payment_new_status_snapshot
        ),
        "dryRunPassed": bool(row.dry_run_passed),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "evidenceJson": row.evidence_json or {},
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action or "",
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


def serialize_phase8e_candidate(
    row: RazorpayRealCustomerPaymentOrderMutationCandidate,
) -> dict[str, Any]:
    """Serialize a candidate row. PII masked / never exposed:
    raw phone, raw email, raw address, raw provider payload, full
    customer name -- only the masked fields surface."""
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "orderId": row.order_id,
        "paymentId": row.payment_id,
        "orderCustomerNameMasked": row.order_customer_name_masked,
        "orderPhoneLast4": row.order_phone_last4,
        "paymentGateway": row.payment_gateway,
        "paymentReferencePrefix": (
            (row.payment_reference or "")[:8]
        ),
        "orderCurrentPaymentStatus": (
            row.order_current_payment_status
        ),
        "paymentCurrentStatus": row.payment_current_status,
        "orderAmount": int(row.order_amount or 0),
        "paymentAmount": int(row.payment_amount or 0),
        "isRealCustomerCandidate": bool(
            row.is_real_customer_candidate
        ),
        "candidateValidationPassed": bool(
            row.candidate_validation_passed
        ),
        "candidateValidationBlockers": list(
            row.candidate_validation_blockers or []
        ),
        "candidateValidationWarnings": list(
            row.candidate_validation_warnings or []
        ),
        "consentRequired": bool(row.consent_required),
        "customerNotificationAllowed": bool(
            row.customer_notification_allowed
        ),
        "whatsAppAllowed": bool(row.whatsapp_allowed),
        "courierAllowed": bool(row.courier_allowed),
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
        "updatedAt": (
            row.updated_at.isoformat() if row.updated_at else None
        ),
    }


def serialize_phase8e_dry_run(
    row: RazorpayRealCustomerPaymentOrderMutationPilotDryRun,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "candidateId": row.candidate_id,
        "targetOrderId": row.target_order_id,
        "targetPaymentId": row.target_payment_id,
        "oldOrderPaymentStatus": row.old_order_payment_status,
        "newOrderPaymentStatusCandidate": (
            row.new_order_payment_status_candidate
        ),
        "oldPaymentStatus": row.old_payment_status,
        "newPaymentStatusCandidate": (
            row.new_payment_status_candidate
        ),
        "wouldMutateOrder": bool(row.would_mutate_order),
        "wouldMutatePayment": bool(row.would_mutate_payment),
        "wouldSendCustomerNotification": bool(
            row.would_send_customer_notification
        ),
        "wouldSendWhatsApp": bool(row.would_send_whatsapp),
        "wouldCallCourier": bool(row.would_call_courier),
        "wouldCreateShipment": bool(row.would_create_shipment),
        "wouldCallProvider": bool(row.would_call_provider),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "passed": bool(row.passed),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "createdAt": (
            row.created_at.isoformat() if row.created_at else None
        ),
    }


def _audit_gate_payload(
    gate: RazorpayRealCustomerPaymentOrderMutationPilotGate,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gate_id": gate.pk,
        "status": gate.status,
        "phase8d_lock_id": gate.source_phase8d_lock_id,
        "phase8c_gate_id": gate.source_phase8c_gate_id,
        "phase8b_gate_id": gate.source_phase8b_gate_id,
        "phase8a_gate_id": gate.source_phase8a_gate_id,
        "phase7i_lock_id": gate.source_phase7i_lock_id,
        "real_customer_pilot_only": True,
        "real_mutation_allowed": False,
        "real_order_mutation_allowed": False,
        "real_payment_mutation_allowed": False,
        "customer_notification_allowed": False,
        "whatsapp_allowed": False,
        "courier_allowed": False,
        "provider_call_allowed": False,
        "phase8f_required": True,
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
    eligibility: dict[str, Any],
) -> dict[str, Any]:
    phase8d_lock = eligibility["phase8d_lock"]
    phase8c_gate = eligibility["phase8c_gate"]
    phase8b_gate = eligibility["phase8b_gate"]
    phase8a_gate = eligibility["phase8a_gate"]
    phase7i_lock = eligibility["phase7i_lock"]
    return {
        "phase": "8E",
        "phase8d": {
            "lockId": phase8d_lock.pk,
            "status": phase8d_lock.status,
            "finalDbRestoredSnapshot": bool(
                phase8d_lock.final_db_restored_snapshot
            ),
        },
        "phase8c": (
            {
                "gateId": phase8c_gate.pk,
                "status": phase8c_gate.status,
            }
            if phase8c_gate is not None
            else None
        ),
        "phase8b": (
            {
                "gateId": phase8b_gate.pk,
                "status": phase8b_gate.status,
            }
            if phase8b_gate is not None
            else None
        ),
        "phase8a": (
            {
                "gateId": phase8a_gate.pk,
                "status": phase8a_gate.status,
            }
            if phase8a_gate is not None
            else None
        ),
        "phase7i": (
            {
                "lockId": phase7i_lock.pk,
                "status": phase7i_lock.status,
            }
            if phase7i_lock is not None
            else None
        ),
        "realCustomerPilotContract": {
            "realCustomerPilotOnly": True,
            "realMutationAllowed": False,
            "realOrderMutationAllowed": False,
            "realPaymentMutationAllowed": False,
            "customerNotificationAllowed": False,
            "whatsAppAllowed": False,
            "courierAllowed": False,
            "providerCallAllowed": False,
            "phase8FRequired": True,
            "directorSignoffRequiredAtPhase8F": True,
            "rollbackRequiredAtPhase8F": True,
        },
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase8e_real_customer_payment_order_pilot(
    phase8d_lock_id: int,
) -> dict[str, Any]:
    eligibility = _validate_eligibility(
        phase8d_lock_id=phase8d_lock_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 8E preview phase8d_lock_id={phase8d_lock_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase8d_lock_id": phase8d_lock_id,
                "eligible": eligibility["eligible"],
                "blockers": list(eligibility["blockers"]),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    evidence: dict[str, Any] = {}
    if (
        eligibility["eligible"]
        and eligibility["phase8d_lock"] is not None
    ):
        evidence = _build_evidence_json(eligibility=eligibility)
    return {
        "phase": "8E",
        "found": eligibility["phase8d_lock"] is not None,
        "sourcePhase8DLockId": phase8d_lock_id,
        "sourcePhase8CGateId": (
            eligibility["phase8c_gate"].pk
            if eligibility["phase8c_gate"]
            else None
        ),
        "sourcePhase8BGateId": (
            eligibility["phase8b_gate"].pk
            if eligibility["phase8b_gate"]
            else None
        ),
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
        "eligible": eligibility["eligible"],
        "blockers": list(eligibility["blockers"]),
        "warnings": [PHASE_8E_WARNING],
        "evidence": evidence,
        "nextAction": (
            "ready_to_prepare_phase8e_real_customer_payment_order_pilot"
            if eligibility["eligible"] and _flag_phase8e_enabled()
            else (
                "fix_phase8e_eligibility_blockers_or_enable_phase8e_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase8e_real_customer_payment_order_pilot(
    phase8d_lock_id: int,
) -> dict[str, Any]:
    """Atomic + idempotent prepare on the source Phase 8D lock.
    NEVER mutates business rows; NEVER calls any provider."""
    eligibility = _validate_eligibility(
        phase8d_lock_id=phase8d_lock_id, require_env_flag=True
    )
    if (
        not eligibility["eligible"]
        or eligibility["phase8d_lock"] is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8E prepare blocked phase8d_lock_id="
                f"{phase8d_lock_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase8d_lock_id": phase8d_lock_id,
                    "blockers": list(eligibility["blockers"]),
                    "kill_switch_state_at_emit": _kill_switch_state(),
                }
            ),
        )
        return {
            "phase": "8E",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_8E_WARNING],
            "nextAction": (
                "fix_phase8e_eligibility_blockers_or_enable_phase8e_flag"
            ),
        }

    phase8d_lock = eligibility["phase8d_lock"]
    before = _business_row_counts()

    with transaction.atomic():
        existing = (
            RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
                source_phase8d_lock=phase8d_lock
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "8E",
                "created": False,
                "reused": True,
                "gate": serialize_phase8e_gate(existing),
                "blockers": [],
                "warnings": [PHASE_8E_WARNING],
                "nextAction": (
                    "phase8e_gate_pending_manual_review"
                    if existing.status
                    == RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.PENDING_MANUAL_REVIEW
                    else f"phase8e_gate_status_{existing.status}"
                ),
            }

        gate = RazorpayRealCustomerPaymentOrderMutationPilotGate(
            source_phase8d_lock=phase8d_lock,
            source_phase8c_gate=eligibility["phase8c_gate"],
            source_phase8b_gate=eligibility["phase8b_gate"],
            source_phase8a_gate=eligibility["phase8a_gate"],
            source_phase7i_lock=eligibility["phase7i_lock"],
            status=(
                RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.PENDING_MANUAL_REVIEW
            ),
            real_customer_pilot_only=True,
            real_mutation_allowed=False,
            real_order_mutation_allowed=False,
            real_payment_mutation_allowed=False,
            customer_notification_allowed=False,
            whatsapp_allowed=False,
            courier_allowed=False,
            provider_call_allowed=False,
            phase8f_required=True,
            manual_review_required=True,
            director_signoff_required=True,
            rollback_required=True,
            candidate_order_id_snapshot="",
            candidate_payment_id_snapshot="",
            candidate_order_current_status_snapshot="",
            candidate_payment_current_status_snapshot="",
            proposed_order_new_status_snapshot=(
                _PROPOSED_NEW_ORDER_PAYMENT_STATUS
            ),
            proposed_payment_new_status_snapshot=(
                _PROPOSED_NEW_PAYMENT_STATUS
            ),
            dry_run_passed=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            evidence_json=_build_evidence_json(
                eligibility=eligibility
            ),
            blockers=[],
            warnings=[PHASE_8E_WARNING],
            next_action="phase8e_gate_pending_manual_review",
        )
        assert_phase8e_no_business_mutation(
            gate, before_counts=before
        )
        try:
            gate.save()
        except IntegrityError:  # pragma: no cover - defensive
            gate = (
                RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
                    source_phase8d_lock=phase8d_lock
                )
            )
            return {
                "phase": "8E",
                "created": False,
                "reused": True,
                "gate": serialize_phase8e_gate(gate),
                "blockers": [],
                "warnings": [PHASE_8E_WARNING],
                "nextAction": "phase8e_gate_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 8E gate prepared gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "8E",
        "created": True,
        "reused": False,
        "gate": serialize_phase8e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8E_WARNING],
        "nextAction": "phase8e_gate_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _looks_like_phase8c_sandbox(
    order: Optional[Order], payment: Optional[Payment]
) -> bool:
    haystack: list[str] = []
    if order is not None:
        haystack.append((order.id or "").lower())
        haystack.append((order.confirmation_notes or "").lower())
        checklist = order.confirmation_checklist or {}
        if (
            isinstance(checklist, dict)
            and checklist.get("phase8c_sandbox") is True
        ):
            return True
    if payment is not None:
        haystack.append((payment.id or "").lower())
        haystack.append(
            (payment.gateway_reference_id or "").lower()
        )
        raw = payment.raw_response or {}
        if (
            isinstance(raw, dict)
            and raw.get("phase8c_sandbox") is True
        ):
            return True
    for needle in _PHASE8C_SANDBOX_MARKERS:
        for hay in haystack:
            if hay and needle in hay:
                return True
    return False


def _validate_candidate_pair(
    *,
    gate_id: int,
    order_id: str,
    payment_id: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    if not (order_id or "").strip():
        blockers.append("phase8e_candidate_order_id_required")
    if not (payment_id or "").strip():
        blockers.append("phase8e_candidate_payment_id_required")

    order = (
        Order.objects.filter(pk=order_id).first()
        if (order_id or "").strip()
        else None
    )
    payment = (
        Payment.objects.filter(pk=payment_id).first()
        if (payment_id or "").strip()
        else None
    )
    if order is None:
        blockers.append("phase8e_candidate_order_not_found")
    if payment is None:
        blockers.append("phase8e_candidate_payment_not_found")
    if (
        order is not None
        and payment is not None
        and (payment.order_id or "") != (order.id or "")
    ):
        blockers.append(
            "phase8e_candidate_payment_order_id_must_match_order_id"
        )

    if order is not None and _looks_like_phase8c_sandbox(
        order, payment
    ):
        blockers.append(
            "phase8e_candidate_must_not_be_phase8c_sandbox_row"
        )
    if payment is not None and _looks_like_phase8c_sandbox(
        None, payment
    ):
        # Already covered above when both rows present; this branch
        # catches the case where order is None but payment carries
        # markers.
        if (
            "phase8e_candidate_must_not_be_phase8c_sandbox_row"
            not in blockers
        ):
            blockers.append(
                "phase8e_candidate_must_not_be_phase8c_sandbox_row"
            )

    if order is not None and order.stage in _TERMINAL_ORDER_STAGES:
        blockers.append(
            "phase8e_candidate_order_stage_terminal_was_"
            f"{order.stage}"
        )
    if (
        order is not None
        and order.payment_status != Order.PaymentStatus.PENDING.value
    ):
        blockers.append(
            "phase8e_candidate_order_payment_status_must_be_pending_was_"
            f"{order.payment_status}"
        )
    if (
        payment is not None
        and payment.status != Payment.Status.PENDING.value
    ):
        # Note: PAID/REFUNDED/FAILED/etc. are terminal-equivalent
        # for our Pending -> Paid pilot; reject all non-Pending.
        blockers.append(
            "phase8e_candidate_payment_status_must_be_pending_was_"
            f"{payment.status}"
        )
    if (
        payment is not None
        and payment.status in _TERMINAL_PAYMENT_STATUSES
    ):
        # Defensive: this is subsumed by the Pending check above,
        # but explicit for diagnostic clarity.
        if (
            f"phase8e_candidate_payment_status_must_be_pending_was_{payment.status}"
            not in blockers
        ):
            blockers.append(
                "phase8e_candidate_payment_terminal_status_was_"
                f"{payment.status}"
            )

    # Soft warnings (do not block, but surface to operator).
    if order is not None and order.amount <= 0:
        warnings.append("phase8e_candidate_order_amount_non_positive")
    if (
        order is not None
        and payment is not None
        and order.amount > 0
        and payment.amount > 0
        and order.amount != payment.amount
    ):
        warnings.append(
            "phase8e_candidate_order_amount_does_not_match_payment_amount"
        )

    return {
        "order": order,
        "payment": payment,
        "blockers": blockers,
        "warnings": warnings,
        "validation_passed": not blockers,
    }


def select_phase8e_real_customer_candidate(
    gate_id: int,
    *,
    order_id: str,
    payment_id: str,
) -> dict[str, Any]:
    """Add (or update) ONE real-customer candidate on the Phase 8E
    pilot gate. NEVER mutates Order / Payment / Customer rows.
    NEVER persists the raw phone / email / address / provider
    payload -- only the masked fields. Idempotent on
    ``(gate, order_id, payment_id)``."""
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            pk=gate_id
        ).first()
    )
    if gate is None:
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "candidate": None,
            "blockers": ["phase8e_gate_not_found"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRY_RUN_PASSED,
    }:
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "candidate": None,
            "blockers": [
                f"phase8e_gate_status_{gate.status}_not_candidate_selectable"
            ],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_status",
        }

    validation = _validate_candidate_pair(
        gate_id=gate.pk,
        order_id=order_id,
        payment_id=payment_id,
    )
    order = validation["order"]
    payment = validation["payment"]
    before = _business_row_counts()

    with transaction.atomic():
        candidate, _created = (
            RazorpayRealCustomerPaymentOrderMutationCandidate.objects.update_or_create(
                gate=gate,
                order_id=(order_id or "")[:32],
                payment_id=(payment_id or "")[:32],
                defaults={
                    "order_customer_name_masked": (
                        _mask_customer_name(
                            getattr(order, "customer_name", "")
                        )
                        if order is not None
                        else ""
                    ),
                    "order_phone_last4": (
                        _mask_phone_last4(
                            getattr(order, "phone", "")
                        )
                        if order is not None
                        else ""
                    ),
                    "payment_gateway": (
                        getattr(payment, "gateway", "")
                        if payment is not None
                        else ""
                    ),
                    "payment_reference": (
                        getattr(
                            payment, "gateway_reference_id", ""
                        )[:120]
                        if payment is not None
                        else ""
                    ),
                    "order_current_payment_status": (
                        getattr(order, "payment_status", "")
                        if order is not None
                        else ""
                    ),
                    "payment_current_status": (
                        getattr(payment, "status", "")
                        if payment is not None
                        else ""
                    ),
                    "order_amount": int(
                        getattr(order, "amount", 0) or 0
                    ),
                    "payment_amount": int(
                        getattr(payment, "amount", 0) or 0
                    ),
                    "is_real_customer_candidate": True,
                    "candidate_validation_passed": bool(
                        validation["validation_passed"]
                    ),
                    "candidate_validation_blockers": list(
                        validation["blockers"]
                    ),
                    "candidate_validation_warnings": list(
                        validation["warnings"]
                    ),
                    "consent_required": True,
                    "customer_notification_allowed": False,
                    "whatsapp_allowed": False,
                    "courier_allowed": False,
                },
            )
        )
        assert_phase8e_no_business_mutation(
            gate, before_counts=before, candidate=candidate
        )

    write_event(
        kind=AUDIT_KIND_CANDIDATE_SELECTED,
        text=(
            f"Phase 8E candidate selected gate_id={gate.pk} "
            f"candidate_id={candidate.pk}"
        ),
        tone=(
            AuditEvent.Tone.INFO
            if candidate.candidate_validation_passed
            else AuditEvent.Tone.WARNING
        ),
        payload=_audit_gate_payload(
            gate,
            extra={
                "candidate_id": candidate.pk,
                "order_id_last8": (order_id or "")[-8:],
                "payment_id_last8": (payment_id or "")[-8:],
                "candidate_validation_passed": bool(
                    candidate.candidate_validation_passed
                ),
                "candidate_blocker_count": len(
                    candidate.candidate_validation_blockers or []
                ),
            },
        ),
    )
    return {
        "phase": "8E",
        "ok": bool(candidate.candidate_validation_passed),
        "gate": serialize_phase8e_gate(gate),
        "candidate": serialize_phase8e_candidate(candidate),
        "blockers": list(
            candidate.candidate_validation_blockers or []
        ),
        "warnings": [PHASE_8E_WARNING]
        + list(candidate.candidate_validation_warnings or []),
        "nextAction": (
            "phase8e_candidate_validation_passed_ready_for_dry_run"
            if candidate.candidate_validation_passed
            else "fix_phase8e_candidate_validation_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def dry_run_phase8e_real_customer_payment_order_pilot(
    gate_id: int,
    *,
    candidate_id: int,
) -> dict[str, Any]:
    """Review-only dry-run. NEVER mutates real rows. Requires a
    candidate that has already passed validation."""
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            pk=gate_id
        ).first()
    )
    if gate is None:
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "dryRun": None,
            "blockers": ["phase8e_gate_not_found"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRY_RUN_PASSED,
    }:
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "dryRun": None,
            "blockers": [
                f"phase8e_gate_status_{gate.status}_not_dry_runnable"
            ],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_status",
        }

    candidate = (
        RazorpayRealCustomerPaymentOrderMutationCandidate.objects.filter(
            pk=candidate_id, gate=gate
        ).first()
    )
    if candidate is None:
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "dryRun": None,
            "blockers": ["phase8e_candidate_not_found_for_gate"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_candidate_id",
        }

    eligibility = _validate_eligibility(
        phase8d_lock_id=gate.source_phase8d_lock_id,
        require_env_flag=True,
    )
    revalidation = _validate_candidate_pair(
        gate_id=gate.pk,
        order_id=candidate.order_id,
        payment_id=candidate.payment_id,
    )

    blockers: list[str] = list(eligibility["blockers"])
    if not bool(candidate.candidate_validation_passed):
        blockers.append(
            "phase8e_candidate_validation_not_passed_re_run_select"
        )
    blockers += revalidation["blockers"]

    before = _business_row_counts()

    if blockers:
        record = RazorpayRealCustomerPaymentOrderMutationPilotDryRun.objects.create(
            gate=gate,
            candidate=candidate,
            target_order_id=candidate.order_id,
            target_payment_id=candidate.payment_id,
            old_order_payment_status=(
                candidate.order_current_payment_status
            ),
            new_order_payment_status_candidate=(
                _PROPOSED_NEW_ORDER_PAYMENT_STATUS
            ),
            old_payment_status=candidate.payment_current_status,
            new_payment_status_candidate=(
                _PROPOSED_NEW_PAYMENT_STATUS
            ),
            would_mutate_order=False,
            would_mutate_payment=False,
            would_send_customer_notification=False,
            would_send_whatsapp=False,
            would_call_courier=False,
            would_create_shipment=False,
            would_call_provider=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            passed=False,
            blockers=list(blockers),
            warnings=[PHASE_8E_WARNING],
        )
        write_event(
            kind=AUDIT_KIND_DRY_RUN_FAILED,
            text=(
                f"Phase 8E dry-run failed gate_id={gate.pk} "
                f"record_id={record.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(
                gate,
                extra={
                    "dry_run_id": record.pk,
                    "candidate_id": candidate.pk,
                    "blockers": list(blockers),
                },
            ),
        )
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "dryRun": serialize_phase8e_dry_run(record),
            "blockers": list(blockers),
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "fix_phase8e_dry_run_blockers",
        }

    # Eligible. Execute the review dry-run with no mutation.
    record = (
        RazorpayRealCustomerPaymentOrderMutationPilotDryRun.objects.create(
            gate=gate,
            candidate=candidate,
            target_order_id=candidate.order_id,
            target_payment_id=candidate.payment_id,
            old_order_payment_status=(
                candidate.order_current_payment_status
            ),
            new_order_payment_status_candidate=(
                _PROPOSED_NEW_ORDER_PAYMENT_STATUS
            ),
            old_payment_status=candidate.payment_current_status,
            new_payment_status_candidate=(
                _PROPOSED_NEW_PAYMENT_STATUS
            ),
            would_mutate_order=False,
            would_mutate_payment=False,
            would_send_customer_notification=False,
            would_send_whatsapp=False,
            would_call_courier=False,
            would_create_shipment=False,
            would_call_provider=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            passed=False,  # filled below
            blockers=[],
            warnings=[PHASE_8E_WARNING],
        )
    )
    after = _business_row_counts()
    deltas: dict[str, int] = {}
    for key, count_before in before.items():
        count_after = after.get(key, count_before)
        if count_after != count_before:
            deltas[key] = count_after - count_before

    passed = not deltas
    record.after_counts = after
    record.count_deltas = deltas
    record.passed = passed
    if not passed:
        record.blockers = list(record.blockers or []) + [
            "phase8e_dry_run_business_row_count_changed"
        ]
    record.save()

    try:
        assert_phase8e_no_business_mutation(
            gate,
            before_counts=before,
            candidate=candidate,
            dry_run=record,
        )
    except ValueError as exc:  # pragma: no cover - defensive
        record.passed = False
        record.blockers = list(record.blockers or []) + [str(exc)]
        record.save()

    if passed and record.passed:
        gate.status = (
            RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRY_RUN_PASSED
        )
        gate.dry_run_passed = True
        gate.candidate_order_id_snapshot = candidate.order_id
        gate.candidate_payment_id_snapshot = candidate.payment_id
        gate.candidate_order_current_status_snapshot = (
            candidate.order_current_payment_status
        )
        gate.candidate_payment_current_status_snapshot = (
            candidate.payment_current_status
        )
        gate.proposed_order_new_status_snapshot = (
            _PROPOSED_NEW_ORDER_PAYMENT_STATUS
        )
        gate.proposed_payment_new_status_snapshot = (
            _PROPOSED_NEW_PAYMENT_STATUS
        )
        gate.next_action = (
            "phase8e_gate_dry_run_passed_awaiting_approve"
        )
        gate.save(
            update_fields=[
                "status",
                "dry_run_passed",
                "candidate_order_id_snapshot",
                "candidate_payment_id_snapshot",
                "candidate_order_current_status_snapshot",
                "candidate_payment_current_status_snapshot",
                "proposed_order_new_status_snapshot",
                "proposed_payment_new_status_snapshot",
                "next_action",
                "updated_at",
            ]
        )

    write_event(
        kind=(
            AUDIT_KIND_DRY_RUN_PASSED
            if passed and record.passed
            else AUDIT_KIND_DRY_RUN_FAILED
        ),
        text=(
            f"Phase 8E dry-run "
            f"{'passed' if (passed and record.passed) else 'failed'} "
            f"gate_id={gate.pk} record_id={record.pk}"
        ),
        tone=AuditEvent.Tone.INFO
        if passed and record.passed
        else AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate,
            extra={
                "dry_run_id": record.pk,
                "candidate_id": candidate.pk,
                "dry_run_passed": bool(passed and record.passed),
            },
        ),
    )
    return {
        "phase": "8E",
        "ok": bool(passed and record.passed),
        "gate": serialize_phase8e_gate(gate),
        "dryRun": serialize_phase8e_dry_run(record),
        "blockers": list(record.blockers or []),
        "warnings": [PHASE_8E_WARNING],
        "nextAction": (
            "phase8e_gate_dry_run_passed_awaiting_approve"
            if (passed and record.passed)
            else "fix_phase8e_dry_run_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


def _gate_lookup(
    gate_id: int,
) -> Optional[RazorpayRealCustomerPaymentOrderMutationPilotGate]:
    return (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            pk=gate_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def approve_phase8e_real_customer_payment_order_pilot(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "blockers": ["phase8e_approve_reason_required"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "blockers": ["phase8e_gate_not_found"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if (
        gate.status
        != RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRY_RUN_PASSED
    ):
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "blockers": [
                f"phase8e_gate_status_{gate.status}_not_transitionable_to_approved"
            ],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "run_phase8e_dry_run_first",
        }
    if not gate.dry_runs.filter(passed=True).exists():
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "blockers": ["phase8e_no_passed_dry_run_present"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "run_phase8e_dry_run_first",
        }
    if not gate.candidates.filter(
        candidate_validation_passed=True
    ).exists():
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "blockers": [
                "phase8e_no_validated_candidate_present"
            ],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "run_phase8e_select_candidate_first",
        }

    before = _business_row_counts()
    assert_phase8e_no_business_mutation(
        gate, before_counts=before
    )

    gate.status = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.APPROVED_FOR_FUTURE_PHASE8F
    )
    gate.approved_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.review_reason = (reason or "")[:1000]
    gate.next_action = (
        "phase8e_gate_approved_for_future_phase8f_real_customer_controlled_mutation"
    )
    gate.save()

    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            "Phase 8E approved-for-future-phase8f gate_id="
            f"{gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8E",
        "ok": True,
        "gate": serialize_phase8e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8E_WARNING],
        "nextAction": (
            "phase8e_gate_approved_for_future_phase8f_real_customer_controlled_mutation"
        ),
    }


def reject_phase8e_real_customer_payment_order_pilot(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "blockers": ["phase8e_reject_reason_required"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "blockers": ["phase8e_gate_not_found"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRAFT,
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRY_RUN_PASSED,
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.BLOCKED,
    }:
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "blockers": [
                f"phase8e_reject_refused_for_status_{gate.status}"
            ],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    assert_phase8e_no_business_mutation(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.REJECTED
    )
    gate.rejected_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.reject_reason = (reason or "")[:1000]
    gate.next_action = "phase8e_gate_rejected"
    gate.save()
    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 8E rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8E",
        "ok": True,
        "gate": serialize_phase8e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8E_WARNING],
        "nextAction": "phase8e_gate_rejected",
    }


def archive_phase8e_real_customer_payment_order_pilot(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "blockers": ["phase8e_archive_reason_required"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8E",
            "ok": False,
            "gate": None,
            "blockers": ["phase8e_gate_not_found"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status == (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.ARCHIVED
    ):
        return {
            "phase": "8E",
            "ok": False,
            "gate": serialize_phase8e_gate(gate),
            "blockers": ["phase8e_gate_already_archived"],
            "warnings": [PHASE_8E_WARNING],
            "nextAction": "verify_gate_status",
        }
    before = _business_row_counts()
    assert_phase8e_no_business_mutation(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.ARCHIVED
    )
    gate.archived_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.archive_reason = (reason or "")[:1000]
    gate.next_action = "phase8e_gate_archived"
    gate.save()
    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 8E archived gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8E",
        "ok": True,
        "gate": serialize_phase8e_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8E_WARNING],
        "nextAction": "phase8e_gate_archived",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase8e_gates(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value
        for s in RazorpayRealCustomerPaymentOrderMutationPilotGate.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase8e_gate(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "8E", "counts": counts, "items": items}


def inspect_phase8e_real_customer_payment_order_pilot_readiness() -> (
    dict[str, Any]
):
    summary = summarize_phase8e_gates(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    eligible_phase8d_locks = (
        RazorpayPaymentOrderControlledMutationEvidenceLock.objects.filter(
            status=(
                RazorpayPaymentOrderControlledMutationEvidenceLock.Status.LOCKED
            ),
            final_db_restored_snapshot=True,
            phase8c_gate_status_snapshot="rolled_back",
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
        next_action = "fix_phase8e_safety_blockers"
    elif not _flag_phase8e_enabled():
        next_action = (
            "enable_phase8e_real_customer_payment_order_pilot_flag"
        )
    elif eligible_phase8d_locks == 0:
        next_action = "no_eligible_phase8d_lock_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase8e_gates_pending_manual_review"
    elif counts.get("dry_run_passed", 0) > 0:
        next_action = (
            "phase8e_gates_dry_run_passed_awaiting_approve"
        )
    elif (
        counts.get(
            "approved_for_future_phase8f_real_customer_controlled_mutation",
            0,
        )
        > 0
    ):
        next_action = (
            "phase8e_gates_approved_for_future_phase8f_real_customer_controlled_mutation"
        )
    else:
        next_action = (
            "ready_to_prepare_phase8e_real_customer_payment_order_pilot"
        )

    return {
        "phase": "8E",
        "status": "real_customer_payment_order_pilot_review_only",
        "latestCompletedPhase": "8D",
        "nextPhase": (
            "phase8f_real_customer_controlled_mutation_not_approved"
        ),
        "phase8EPaymentOrderPilotEnabled": _flag_phase8e_enabled(),
        "killSwitch": kill,
        "eligiblePhase8DLockCount": eligible_phase8d_locks,
        "phase8EGateCounts": counts,
        "items": summary["items"],
        "phase8ECallsRazorpay": False,
        "phase8ECallsMetaCloud": False,
        "phase8ECallsDelhivery": False,
        "phase8ECallsVapi": False,
        "phase8ESendsWhatsApp": False,
        "phase8EQueuesWhatsApp": False,
        "phase8ECreatesShipmentRow": False,
        "phase8ECreatesAwb": False,
        "phase8ECreatesPaymentLink": False,
        "phase8ECapturesPayment": False,
        "phase8ERefundsPayment": False,
        "phase8ESendsCustomerNotification": False,
        "phase8EMutatesOrder": False,
        "phase8EMutatesPayment": False,
        "phase8EMutatesCustomer": False,
        "phase8EMutatesLead": False,
        "phase8EMutatesShipment": False,
        "phase8EMutatesDiscountOfferLog": False,
        "phase8EMutatesWhatsAppMessage": False,
        "phase8EApprovesRealCustomerAutomation": False,
        "phase8FApproved": False,
        "phase7ELiveBApproved": False,
        "phase7GLiveApproved": False,
        "executionPath": "review_dry_run_only_cli_only_no_execute",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_8E_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_8E_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text=(
            "Phase 8E real customer payment-order pilot readiness "
            "inspected"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase8d_lock_count": int(
                    report.get("eligiblePhase8DLockCount") or 0
                ),
                "phase8e_enabled": bool(
                    report.get("phase8EPaymentOrderPilotEnabled")
                ),
                "gate_counts": (
                    report.get("phase8EGateCounts") or {}
                ),
                "next_action": report.get("nextAction") or "",
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
