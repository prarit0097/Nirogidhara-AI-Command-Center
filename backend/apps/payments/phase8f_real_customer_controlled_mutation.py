"""Phase 8F - Controlled Real Customer Payment -> Order Mutation.

Phase 8F is the **CLI-only one-shot controlled mutation** path for
the ONE real-customer ``Order`` + ``Payment`` candidate that Phase
8E approved for future-Phase-8F review. Execute requires three
Phase 8F env flags ALL true, a structured Director sign-off UTC
window (<= 15 min) that names the Phase 8F gate id + attempt id +
source Phase 8E gate id + the explicit target Order id + target
Payment id, the kill switch enabled, ``--confirm-one-shot-real-mutation``,
non-empty ``--operator-name``, and the candidate must still satisfy
its Partial+Pending / Pending+Pending contract at execute time.

Phase 8F NEVER calls Razorpay, NEVER calls Meta Cloud, NEVER calls
Delhivery, NEVER calls Vapi, NEVER sends or queues WhatsApp,
NEVER creates a ``Shipment`` / AWB / payment link, NEVER captures,
NEVER refunds, NEVER sends a customer notification, NEVER mutates
``Customer`` / ``Lead`` / ``Shipment`` / ``DiscountOfferLog`` /
``WhatsAppMessage`` / ``Order.state`` rows, NEVER edits any
``.env*`` file. Approval alone does NOT execute.
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
from apps.payments.models import (
    Payment,
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
    RazorpayRealCustomerPaymentOrderControlledMutationGate,
    RazorpayRealCustomerPaymentOrderControlledMutationRollback,
    RazorpayRealCustomerPaymentOrderMutationPilotGate,
)
from apps.shipments.models import Shipment
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)


PHASE_8F_WARNING = (
    "Phase 8F is the Controlled Real Customer Payment -> Order "
    "Mutation Gate. It is CLI-only one-shot controlled mutation "
    "against the ONE Phase 8E-approved real customer Order + "
    "Payment candidate. Execute requires three env flags ALL true, "
    "a structured 15-min Director sign-off UTC window, the runtime "
    "kill switch enabled, --confirm-one-shot-real-mutation, and "
    "non-empty --operator-name. Phase 8F NEVER calls Razorpay / "
    "Meta Cloud / Delhivery / Vapi, NEVER sends or queues WhatsApp, "
    "NEVER creates a Shipment / AWB / payment link, NEVER captures "
    "/ refunds, NEVER sends a customer notification, NEVER mutates "
    "Customer / Lead / Shipment / DiscountOfferLog / WhatsAppMessage "
    "/ Order.state rows, NEVER edits any .env file. Approval alone "
    "does NOT execute."
)

PHASE_8F_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "mutate_real_order_state",
    "mutate_real_customer",
    "mutate_real_lead",
    "mutate_real_shipment",
    "mutate_real_discount_offer_log",
    "mutate_real_whatsapp_message",
    "approve_real_customer_automation",
    "approve_phase7e_live_b",
    "approve_phase7g_live",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "execute_via_api_endpoint",
    "rollback_via_api_endpoint",
    "archive_via_api_endpoint",
    "edit_dotenv_any",
)


AUDIT_KIND_READINESS = "phase8f.real_mutation.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase8f.real_mutation.previewed"
AUDIT_KIND_PREPARED = "phase8f.real_mutation.prepared"
AUDIT_KIND_APPROVED = "phase8f.real_mutation.approved"
AUDIT_KIND_EXECUTED = "phase8f.real_mutation.executed"
AUDIT_KIND_ROLLBACK = "phase8f.real_mutation.rollback_recorded"
AUDIT_KIND_REJECTED = "phase8f.real_mutation.rejected"
AUDIT_KIND_ARCHIVED = "phase8f.real_mutation.archived"
AUDIT_KIND_BLOCKED = "phase8f.real_mutation.blocked"
AUDIT_KIND_FAILED = "phase8f.real_mutation.failed"


# Audit payloads NEVER carry these keys. Forensic scrub on every emit.
PHASE_8F_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "token",
    "access_token",
    "verify_token",
    "app_secret",
    "secret",
    "raw_secret",
    "raw_signature",
    "raw_payload",
    "raw_response",
    "META_WA_TOKEN",
    "META_WA_APP_SECRET",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "DELHIVERY_API_TOKEN",
    "phone",
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
    "gateway_reference_id",
    "payment_url",
    "customer_name",
    "director_signoff",
)


_ACCEPTED_SELECTED_ORDER_PAYMENT_STATUSES: tuple[str, ...] = (
    Order.PaymentStatus.PENDING.value,
    Order.PaymentStatus.PARTIAL.value,
)
_ACCEPTED_SELECTED_PAYMENT_STATUSES: tuple[str, ...] = (
    Payment.Status.PENDING.value,
)
_PROPOSED_NEW_ORDER_PAYMENT_STATUS = Order.PaymentStatus.PAID.value
_PROPOSED_NEW_PAYMENT_STATUS = Payment.Status.PAID.value


# Phase 8F-Hotfix-1: a gate that landed in `blocked` solely because
# the runtime gate env flag was False at the prior approve attempt
# may be recovered to approval AFTER the flag is flipped True — as
# long as every other safety condition still holds. This is the
# ONLY blocker that qualifies for safe recovery.
_RECOVERABLE_APPROVE_BLOCKER = (
    "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
)


def _is_blocked_only_by_missing_env_flag(
    gate: "RazorpayRealCustomerPaymentOrderControlledMutationGate",
) -> bool:
    """Return True iff the gate is in ``blocked`` AND its persisted
    ``blockers`` list contains exactly the missing-env-flag blocker
    (and nothing else)."""
    if gate.status != (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.BLOCKED
    ):
        return False
    raw_blockers = list(gate.blockers or [])
    # Tolerate whitespace, but no other blocker — the recovery path
    # is intentionally narrow to a single, env-flag-only cause.
    blocker_set = {(b or "").strip() for b in raw_blockers if b}
    return blocker_set == {_RECOVERABLE_APPROVE_BLOCKER}


def _attempt_has_executed_or_mutation(
    gate: "RazorpayRealCustomerPaymentOrderControlledMutationGate",
) -> bool:
    """Return True if ANY attempt on this gate carries
    ``executed_at`` OR has any *_mutation_was_made flag True. The
    recovery path must refuse if there's ANY trace of execution."""
    qs = gate.attempts.all()
    if qs.filter(executed_at__isnull=False).exists():
        return True
    if qs.filter(order_mutation_was_made=True).exists():
        return True
    if qs.filter(payment_mutation_was_made=True).exists():
        return True
    if qs.filter(business_mutation_was_made=True).exists():
        return True
    # And — for completeness — no attempt may carry a provider /
    # send / courier / customer-notification flag flipped True.
    if qs.filter(
        customer_notification_sent=True
    ).exists():
        return True
    if qs.filter(whatsapp_sent=True).exists():
        return True
    if qs.filter(courier_called=True).exists():
        return True
    if qs.filter(provider_call_attempted=True).exists():
        return True
    if qs.filter(shipment_created=True).exists():
        return True
    return False


_PHASE8E_APPROVED_STATUS = (
    RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.APPROVED_FOR_FUTURE_PHASE8F
)


# ---------------------------------------------------------------------------
# Env / runtime helpers
# ---------------------------------------------------------------------------


def _flag_phase8f_gate_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED",
            False,
        )
    )


def _flag_phase8f_director_approved() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION",
            False,
        )
    )


def _flag_phase8f_allow_real_customer_mutation() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION",
            False,
        )
    )


def _flag_phase7e_live_b_approved() -> bool:
    return bool(
        getattr(settings, "PHASE7E_LIVE_B_APPROVED", False)
    )


def _flag_phase7g_live_approved() -> bool:
    return bool(getattr(settings, "PHASE7G_LIVE_APPROVED", False))


def _flag_real_customer_automation_approved() -> bool:
    return bool(
        getattr(
            settings, "REAL_CUSTOMER_AUTOMATION_APPROVED", False
        )
    )


def _kill_switch_state() -> dict[str, Any]:
    try:
        from apps.saas.models import RuntimeKillSwitch

        row = (
            RuntimeKillSwitch.objects.filter(name="global")
            .order_by("-pk")
            .first()
        )
        if row is None:
            return {"enabled": True, "model": "RuntimeKillSwitch", "id": None}
        return {
            "enabled": bool(row.enabled),
            "model": "RuntimeKillSwitch",
            "id": row.pk,
        }
    except Exception:  # pragma: no cover - defensive
        return {"enabled": True, "model": "RuntimeKillSwitch", "id": None}


def _hash_signoff(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    """Strip forbidden keys from the audit payload."""
    forbidden = set(PHASE_8F_FORBIDDEN_PAYLOAD_KEYS)
    out: dict[str, Any] = {}
    for key, value in (extra or {}).items():
        if key in forbidden:
            continue
        out[key] = value
    return out


def _business_row_counts() -> dict[str, int]:
    """Snapshot of every protected business table. The Phase 8F
    execute path mutates ONLY the chosen Order.payment_status +
    Payment.status fields on the named target rows — row counts
    must remain identical before and after."""
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
        "whatsapp_handoff_to_call": (
            WhatsAppHandoffToCall.objects.count()
        ),
    }


# ---------------------------------------------------------------------------
# Serializers (read-only)
# ---------------------------------------------------------------------------


def serialize_phase8f_gate(
    row: RazorpayRealCustomerPaymentOrderControlledMutationGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "phase": "8F",
        "status": row.status,
        "sourcePhase8EGateId": row.source_phase8e_gate_id,
        "sourcePhase8DLockId": row.source_phase8d_lock_id,
        "sourcePhase8CGateId": row.source_phase8c_gate_id,
        "realCustomerControlledMutationOnly": row.real_customer_controlled_mutation_only,
        "realCustomerMutationAllowed": row.real_customer_mutation_allowed,
        "customerNotificationAllowed": row.customer_notification_allowed,
        "whatsappAllowed": row.whatsapp_allowed,
        "courierAllowed": row.courier_allowed,
        "providerCallAllowed": row.provider_call_allowed,
        "shipmentCreationAllowed": row.shipment_creation_allowed,
        "paymentCaptureAllowed": row.payment_capture_allowed,
        "refundAllowed": row.refund_allowed,
        "rollbackRequired": row.rollback_required,
        "directorSignoffRequired": row.director_signoff_required,
        "structuredUtcWindowRequired": row.structured_utc_window_required,
        "selectedOrderIdSnapshot": row.selected_order_id_snapshot,
        "selectedPaymentIdSnapshot": row.selected_payment_id_snapshot,
        "selectedOrderPaymentStatusSnapshot": (
            row.selected_order_payment_status_snapshot
        ),
        "selectedPaymentStatusSnapshot": row.selected_payment_status_snapshot,
        "proposedOrderPaymentStatusSnapshot": (
            row.proposed_order_payment_status_snapshot
        ),
        "proposedPaymentStatusSnapshot": row.proposed_payment_status_snapshot,
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "reviewedByUsername": row.reviewed_by_username,
        "reviewedAt": row.reviewed_at,
        "reviewReason": row.review_reason,
        "rejectReason": row.reject_reason,
        "archiveReason": row.archive_reason,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action,
        "evidenceJson": row.evidence_json or {},
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "approvedAt": row.approved_at,
        "rejectedAt": row.rejected_at,
        "archivedAt": row.archived_at,
    }


def serialize_phase8f_attempt(
    row: RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "phase": "8F",
        "gateId": row.gate_id,
        "status": row.status,
        "targetOrderId": row.target_order_id,
        "targetPaymentId": row.target_payment_id,
        "oldOrderPaymentStatus": row.old_order_payment_status,
        "newOrderPaymentStatus": row.new_order_payment_status,
        "oldPaymentStatus": row.old_payment_status,
        "newPaymentStatus": row.new_payment_status,
        "orderMutationWasMade": row.order_mutation_was_made,
        "paymentMutationWasMade": row.payment_mutation_was_made,
        "businessMutationWasMade": row.business_mutation_was_made,
        "customerNotificationSent": row.customer_notification_sent,
        "whatsappSent": row.whatsapp_sent,
        "courierCalled": row.courier_called,
        "providerCallAttempted": row.provider_call_attempted,
        "shipmentCreated": row.shipment_created,
        "directorSignoffTextHashPresent": bool(
            row.director_signoff_text_hash
        ),
        "recordedSignoffWindowStartUtc": (
            row.recorded_signoff_window_start_utc
        ),
        "recordedSignoffWindowEndUtc": (
            row.recorded_signoff_window_end_utc
        ),
        "recordedSignoffWindowValid": row.recorded_signoff_window_valid,
        "operatorNamePresent": bool((row.operator_name or "").strip()),
        "executedAt": row.executed_at,
        "failedAt": row.failed_at,
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def serialize_phase8f_rollback(
    row: RazorpayRealCustomerPaymentOrderControlledMutationRollback,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "phase": "8F",
        "attemptId": row.attempt_id,
        "status": row.status,
        "restoredOrderPaymentStatus": row.restored_order_payment_status,
        "restoredPaymentStatus": row.restored_payment_status,
        "rollbackWasMade": row.rollback_was_made,
        "customerNotificationSent": row.customer_notification_sent,
        "whatsappSent": row.whatsapp_sent,
        "courierCalled": row.courier_called,
        "providerCallAttempted": row.provider_call_attempted,
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "reason": row.reason,
        "rolledBackAt": row.rolled_back_at,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def _audit_gate_payload(
    gate: RazorpayRealCustomerPaymentOrderControlledMutationGate,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    base = {
        "gate_id": gate.pk,
        "phase8e_gate_id": gate.source_phase8e_gate_id,
        "status": gate.status,
        "selected_order_id_last8": (
            gate.selected_order_id_snapshot or ""
        )[-8:],
        "selected_payment_id_last8": (
            gate.selected_payment_id_snapshot or ""
        )[-8:],
        "selected_order_payment_status_snapshot": (
            gate.selected_order_payment_status_snapshot
        ),
        "selected_payment_status_snapshot": (
            gate.selected_payment_status_snapshot
        ),
        "proposed_order_payment_status_snapshot": (
            gate.proposed_order_payment_status_snapshot
        ),
        "proposed_payment_status_snapshot": (
            gate.proposed_payment_status_snapshot
        ),
        "real_customer_mutation_allowed": gate.real_customer_mutation_allowed,
        "customer_notification_allowed": gate.customer_notification_allowed,
        "whatsapp_allowed": gate.whatsapp_allowed,
        "courier_allowed": gate.courier_allowed,
        "provider_call_allowed": gate.provider_call_allowed,
        "shipment_creation_allowed": gate.shipment_creation_allowed,
    }
    if extra:
        base.update(extra)
    return _safe_audit_payload(base)


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


def assert_phase8f_no_unauthorized_side_effect(
    gate: RazorpayRealCustomerPaymentOrderControlledMutationGate,
    *,
    before_counts: Optional[dict[str, int]] = None,
    attempt: Optional[
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt
    ] = None,
    rollback: Optional[
        RazorpayRealCustomerPaymentOrderControlledMutationRollback
    ] = None,
) -> None:
    """Raise ValueError if any locked-False contract has flipped, OR
    if any protected business table grew/shrank since the snapshot.

    Phase 8F may mutate ONLY ``Order.payment_status`` AND
    ``Payment.status`` on the named target rows — every other
    boolean stays False and row counts must remain identical.
    """
    bad: list[str] = []
    locked_false_gate = (
        "real_customer_mutation_allowed",
        "customer_notification_allowed",
        "whatsapp_allowed",
        "courier_allowed",
        "provider_call_allowed",
        "shipment_creation_allowed",
        "payment_capture_allowed",
        "refund_allowed",
    )
    for flag in locked_false_gate:
        if getattr(gate, flag, False):
            bad.append(f"phase8f_gate_{flag}_must_remain_false")
    if attempt is not None:
        locked_false_attempt = (
            "customer_notification_sent",
            "whatsapp_sent",
            "courier_called",
            "provider_call_attempted",
            "shipment_created",
        )
        for flag in locked_false_attempt:
            if getattr(attempt, flag, False):
                bad.append(
                    f"phase8f_attempt_{flag}_must_remain_false"
                )
    if rollback is not None:
        locked_false_rb = (
            "customer_notification_sent",
            "whatsapp_sent",
            "courier_called",
            "provider_call_attempted",
        )
        for flag in locked_false_rb:
            if getattr(rollback, flag, False):
                bad.append(
                    f"phase8f_rollback_{flag}_must_remain_false"
                )
    if before_counts is not None:
        after_counts = _business_row_counts()
        for key, expected in before_counts.items():
            actual = after_counts.get(key, expected)
            if actual != expected:
                bad.append(
                    f"phase8f_protected_row_count_drift_{key}_"
                    f"before={expected}_after={actual}"
                )
    if bad:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                "Phase 8F locked-False / row-count invariant "
                "violated"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload=_safe_audit_payload(
                {
                    "gate_id": gate.pk if gate else None,
                    "attempt_id": attempt.pk if attempt else None,
                    "rollback_id": rollback.pk if rollback else None,
                    "violations": list(bad),
                }
            ),
        )
        raise ValueError(
            "Phase 8F invariant violation: " + "; ".join(bad)
        )


# ---------------------------------------------------------------------------
# Eligibility / candidate validation
# ---------------------------------------------------------------------------


def _validate_phase8e_gate(
    phase8e_gate: Optional[
        RazorpayRealCustomerPaymentOrderMutationPilotGate
    ],
) -> list[str]:
    blockers: list[str] = []
    if phase8e_gate is None:
        blockers.append("phase8f_source_phase8e_gate_not_found")
        return blockers
    if phase8e_gate.status != _PHASE8E_APPROVED_STATUS:
        blockers.append(
            "phase8f_source_phase8e_gate_status_must_be_approved_for_future_phase8f_"
            f"was_{phase8e_gate.status}"
        )
    if not phase8e_gate.dry_run_passed:
        blockers.append(
            "phase8f_source_phase8e_gate_dry_run_must_have_passed"
        )
    if not (phase8e_gate.candidate_order_id_snapshot or "").strip():
        blockers.append(
            "phase8f_source_phase8e_gate_candidate_order_id_snapshot_required"
        )
    if not (phase8e_gate.candidate_payment_id_snapshot or "").strip():
        blockers.append(
            "phase8f_source_phase8e_gate_candidate_payment_id_snapshot_required"
        )
    return blockers


def _validate_target_pair_currentness(
    order: Optional[Order], payment: Optional[Payment]
) -> list[str]:
    blockers: list[str] = []
    if order is None:
        blockers.append("phase8f_target_order_not_found")
    if payment is None:
        blockers.append("phase8f_target_payment_not_found")
    if order is not None and payment is not None:
        if (payment.order_id or "") != (order.id or ""):
            blockers.append(
                "phase8f_target_payment_order_id_must_match_order_id"
            )
        if (
            order.payment_status
            not in _ACCEPTED_SELECTED_ORDER_PAYMENT_STATUSES
        ):
            blockers.append(
                "phase8f_target_order_payment_status_must_be_pending_or_partial_was_"
                f"{order.payment_status}"
            )
        if payment.status not in _ACCEPTED_SELECTED_PAYMENT_STATUSES:
            blockers.append(
                "phase8f_target_payment_status_must_be_pending_was_"
                f"{payment.status}"
            )
    return blockers


def _eligibility_blockers(
    phase8e_gate: Optional[
        RazorpayRealCustomerPaymentOrderMutationPilotGate
    ],
    *,
    target_order: Optional[Order] = None,
    target_payment: Optional[Payment] = None,
) -> list[str]:
    blockers: list[str] = []
    if not _flag_phase8f_gate_enabled():
        blockers.append(
            "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        )
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    if _flag_real_customer_automation_approved():
        blockers.append(
            "real_customer_automation_must_remain_not_broadly_approved"
        )
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    blockers += _validate_phase8e_gate(phase8e_gate)
    if target_order is not None or target_payment is not None:
        blockers += _validate_target_pair_currentness(
            target_order, target_payment
        )
    return blockers


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def inspect_phase8f_real_customer_controlled_mutation_readiness() -> (
    dict[str, Any]
):
    """Read-only readiness composition. NEVER mutates a row."""
    eligible_phase8e_gates = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            status=_PHASE8E_APPROVED_STATUS, dry_run_passed=True
        ).count()
    )
    status_counts: dict[str, int] = {}
    for choice, _ in (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.choices
    ):
        status_counts[choice] = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.filter(
                status=choice
            ).count()
        )

    flags = {
        "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED": (
            _flag_phase8f_gate_enabled()
        ),
        "PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION": (
            _flag_phase8f_director_approved()
        ),
        "PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION": (
            _flag_phase8f_allow_real_customer_mutation()
        ),
    }
    blockers: list[str] = []
    if not _flag_phase8f_gate_enabled():
        blockers.append(
            "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true_to_prepare"
        )
    if eligible_phase8e_gates < 1:
        blockers.append(
            "phase8f_at_least_one_phase8e_gate_must_be_approved_for_future_phase8f"
        )
    if blockers:
        next_action = "fix_phase8f_readiness_blockers"
    else:
        next_action = "ready_for_phase8f_prepare"

    status = "ready" if not blockers else "blocked"
    return {
        "phase": "8F",
        "status": status,
        "killSwitch": _kill_switch_state(),
        "phase8FFlags": flags,
        "eligiblePhase8EGateCount": int(eligible_phase8e_gates),
        "phase8FGateCounts": status_counts,
        "phase8FMutatesOrderState": False,
        "phase8FMutatesCustomer": False,
        "phase8FMutatesLead": False,
        "phase8FMutatesShipment": False,
        "phase8FMutatesDiscountOfferLog": False,
        "phase8FMutatesWhatsAppMessage": False,
        "phase8FCallsRazorpay": False,
        "phase8FCallsMetaCloud": False,
        "phase8FCallsDelhivery": False,
        "phase8FCallsVapi": False,
        "phase8FSendsWhatsApp": False,
        "phase8FSendsCustomerNotification": False,
        "phase8FCreatesShipment": False,
        "phase8FCreatesAwb": False,
        "phase8FCreatesPaymentLink": False,
        "phase8FCapturesPayment": False,
        "phase8FRefundsPayment": False,
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "executionPath": (
            "cli_only_one_shot_controlled_mutation_no_provider_no_send_no_notify"
        ),
        "blockers": blockers,
        "warnings": [PHASE_8F_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_8F_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text=(
            "Phase 8F controlled real customer payment-order "
            "mutation readiness inspected"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase8e_gate_count": int(
                    report.get("eligiblePhase8EGateCount") or 0
                ),
                "phase8f_flags": report.get("phase8FFlags") or {},
                "phase8f_gate_counts": (
                    report.get("phase8FGateCounts") or {}
                ),
                "next_action": report.get("nextAction") or "",
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase8f_real_customer_controlled_mutation(
    *, phase8e_gate_id: int
) -> dict[str, Any]:
    """Read-only preview. NEVER persists a row."""
    phase8e_gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            pk=phase8e_gate_id
        ).first()
    )
    blockers = _eligibility_blockers(phase8e_gate)
    target_order: Optional[Order] = None
    target_payment: Optional[Payment] = None
    if phase8e_gate is not None:
        target_order = (
            Order.objects.filter(
                pk=phase8e_gate.candidate_order_id_snapshot
            ).first()
            if (phase8e_gate.candidate_order_id_snapshot or "").strip()
            else None
        )
        target_payment = (
            Payment.objects.filter(
                pk=phase8e_gate.candidate_payment_id_snapshot
            ).first()
            if (phase8e_gate.candidate_payment_id_snapshot or "").strip()
            else None
        )
        blockers += _validate_target_pair_currentness(
            target_order, target_payment
        )
    next_action = (
        "ready_for_phase8f_prepare"
        if not blockers
        else "fix_phase8f_preview_blockers"
    )
    payload = {
        "phase": "8F",
        "ok": not blockers,
        "phase8EGateId": phase8e_gate.pk if phase8e_gate else None,
        "phase8EGateStatus": (
            phase8e_gate.status if phase8e_gate else ""
        ),
        "candidateOrderId": (
            phase8e_gate.candidate_order_id_snapshot
            if phase8e_gate
            else ""
        ),
        "candidatePaymentId": (
            phase8e_gate.candidate_payment_id_snapshot
            if phase8e_gate
            else ""
        ),
        "currentOrderPaymentStatus": (
            target_order.payment_status if target_order else ""
        ),
        "currentPaymentStatus": (
            target_payment.status if target_payment else ""
        ),
        "proposedOrderPaymentStatus": _PROPOSED_NEW_ORDER_PAYMENT_STATUS,
        "proposedPaymentStatus": _PROPOSED_NEW_PAYMENT_STATUS,
        "blockers": blockers,
        "warnings": [PHASE_8F_WARNING],
        "nextAction": next_action,
        "phase8FMutatesOrderState": False,
        "phase8FCallsRazorpay": False,
        "phase8FCallsMetaCloud": False,
        "phase8FCallsDelhivery": False,
        "phase8FSendsWhatsApp": False,
        "phase8FSendsCustomerNotification": False,
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
    }
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 8F preview phase8e_gate_id={phase8e_gate_id} "
            f"ok={payload['ok']}"
        ),
        tone=(
            AuditEvent.Tone.INFO
            if payload["ok"]
            else AuditEvent.Tone.WARNING
        ),
        payload=_safe_audit_payload(
            {
                "phase8e_gate_id": phase8e_gate_id,
                "ok": payload["ok"],
                "blockers": list(blockers),
                "current_order_payment_status": payload[
                    "currentOrderPaymentStatus"
                ],
                "current_payment_status": payload["currentPaymentStatus"],
            }
        ),
    )
    return payload


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _build_evidence_json(
    phase8e_gate: RazorpayRealCustomerPaymentOrderMutationPilotGate,
    target_order: Optional[Order],
    target_payment: Optional[Payment],
) -> dict[str, Any]:
    return {
        "phase8e": {
            "id": phase8e_gate.pk,
            "status": phase8e_gate.status,
            "dryRunPassed": phase8e_gate.dry_run_passed,
            "candidateOrderId": phase8e_gate.candidate_order_id_snapshot,
            "candidatePaymentId": (
                phase8e_gate.candidate_payment_id_snapshot
            ),
        },
        "currentTarget": {
            "orderPaymentStatus": (
                target_order.payment_status if target_order else ""
            ),
            "paymentStatus": (
                target_payment.status if target_payment else ""
            ),
        },
        "proposed": {
            "orderPaymentStatus": _PROPOSED_NEW_ORDER_PAYMENT_STATUS,
            "paymentStatus": _PROPOSED_NEW_PAYMENT_STATUS,
        },
        "contract": {
            "callsRazorpay": False,
            "callsMetaCloud": False,
            "callsDelhivery": False,
            "callsVapi": False,
            "sendsWhatsApp": False,
            "sendsCustomerNotification": False,
            "createsShipment": False,
            "createsAwb": False,
            "createsPaymentLink": False,
            "capturesPayment": False,
            "refundsPayment": False,
            "mutatesOrderState": False,
            "mutatesCustomer": False,
            "mutatesLead": False,
            "mutatesShipment": False,
            "mutatesDiscountOfferLog": False,
            "mutatesWhatsAppMessage": False,
        },
    }


def prepare_phase8f_real_customer_controlled_mutation(
    *, phase8e_gate_id: int
) -> dict[str, Any]:
    """Idempotent prepare. Reuses an existing draft gate for the
    same source Phase 8E gate; otherwise creates a new one with a
    frozen candidate snapshot. NEVER mutates business rows."""
    phase8e_gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            pk=phase8e_gate_id
        ).first()
    )
    blockers = _eligibility_blockers(phase8e_gate)
    target_order: Optional[Order] = None
    target_payment: Optional[Payment] = None
    if phase8e_gate is not None:
        target_order = (
            Order.objects.filter(
                pk=phase8e_gate.candidate_order_id_snapshot
            ).first()
            if (phase8e_gate.candidate_order_id_snapshot or "").strip()
            else None
        )
        target_payment = (
            Payment.objects.filter(
                pk=phase8e_gate.candidate_payment_id_snapshot
            ).first()
            if (phase8e_gate.candidate_payment_id_snapshot or "").strip()
            else None
        )
        blockers += _validate_target_pair_currentness(
            target_order, target_payment
        )
    if blockers:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8F prepare blocked phase8e_gate_id="
                f"{phase8e_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase8e_gate_id": phase8e_gate_id,
                    "blockers": list(blockers),
                }
            ),
        )
        return {
            "phase": "8F",
            "ok": False,
            "gate": None,
            "blockers": blockers,
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "fix_phase8f_prepare_blockers",
        }

    before = _business_row_counts()
    with transaction.atomic():
        gate, created = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get_or_create(
                source_phase8e_gate=phase8e_gate,
                status__in=(
                    RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.DRAFT,
                    RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW,
                ),
                defaults={
                    "source_phase8d_lock": (
                        phase8e_gate.source_phase8d_lock
                    ),
                    "source_phase8c_gate": (
                        phase8e_gate.source_phase8c_gate
                    ),
                    "status": (
                        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW
                    ),
                    "selected_order_id_snapshot": (
                        phase8e_gate.candidate_order_id_snapshot
                    ),
                    "selected_payment_id_snapshot": (
                        phase8e_gate.candidate_payment_id_snapshot
                    ),
                    "selected_order_payment_status_snapshot": (
                        (
                            target_order.payment_status
                            if target_order
                            else ""
                        )
                    ),
                    "selected_payment_status_snapshot": (
                        target_payment.status if target_payment else ""
                    ),
                    "proposed_order_payment_status_snapshot": (
                        _PROPOSED_NEW_ORDER_PAYMENT_STATUS
                    ),
                    "proposed_payment_status_snapshot": (
                        _PROPOSED_NEW_PAYMENT_STATUS
                    ),
                    "real_customer_controlled_mutation_only": True,
                    "real_customer_mutation_allowed": False,
                    "customer_notification_allowed": False,
                    "whatsapp_allowed": False,
                    "courier_allowed": False,
                    "provider_call_allowed": False,
                    "shipment_creation_allowed": False,
                    "payment_capture_allowed": False,
                    "refund_allowed": False,
                    "rollback_required": True,
                    "director_signoff_required": True,
                    "structured_utc_window_required": True,
                    "evidence_json": _build_evidence_json(
                        phase8e_gate, target_order, target_payment
                    ),
                    "warnings": [PHASE_8F_WARNING],
                    "next_action": "phase8f_pending_manual_review",
                },
            )
        )
        if not created:
            # Refresh evidence + snapshots so we don't carry a
            # stale view of current statuses.
            gate.selected_order_payment_status_snapshot = (
                target_order.payment_status if target_order else ""
            )
            gate.selected_payment_status_snapshot = (
                target_payment.status if target_payment else ""
            )
            gate.evidence_json = _build_evidence_json(
                phase8e_gate, target_order, target_payment
            )
            gate.warnings = [PHASE_8F_WARNING]
            gate.save()
        assert_phase8f_no_unauthorized_side_effect(
            gate, before_counts=before
        )

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 8F prepared gate_id={gate.pk} "
            f"phase8e_gate_id={phase8e_gate.pk} created={created}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"created": bool(created)}
        ),
    )
    return {
        "phase": "8F",
        "ok": True,
        "gate": serialize_phase8f_gate(gate),
        "created": bool(created),
        "blockers": [],
        "warnings": [PHASE_8F_WARNING],
        "nextAction": "phase8f_review_then_approve",
    }


# ---------------------------------------------------------------------------
# Approve / Reject / Archive
# ---------------------------------------------------------------------------


def _gate_lookup(
    gate_id: int,
) -> Optional[RazorpayRealCustomerPaymentOrderControlledMutationGate]:
    return (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.filter(
            pk=gate_id
        )
        .select_related("source_phase8e_gate")
        .first()
    )


def _reviewer_username(reviewed_by) -> str:
    if reviewed_by is None:
        return "cli"
    return getattr(reviewed_by, "username", "") or "cli"


def approve_phase8f_real_customer_controlled_mutation(
    gate_id: int,
    *,
    reason: str,
    reviewed_by=None,
) -> dict[str, Any]:
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8F",
            "ok": False,
            "gate": None,
            "attempt": None,
            "blockers": ["phase8f_gate_not_found"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not (reason or "").strip():
        return {
            "phase": "8F",
            "ok": False,
            "gate": serialize_phase8f_gate(gate),
            "attempt": None,
            "blockers": ["phase8f_approve_reason_required"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_approve_reason_required",
        }
    # Phase 8F-Hotfix-1: allow approval from EITHER
    # `pending_manual_review` (canonical) OR `blocked` IFF the
    # gate's persisted blockers list contains exactly the
    # missing-env-flag blocker AND nothing else AND no attempt has
    # executed/mutated/sent anything. Any other blocker keeps the
    # canonical refusal.
    recovered_from_missing_env_flag = (
        _is_blocked_only_by_missing_env_flag(gate)
        and _flag_phase8f_gate_enabled()
        and not _attempt_has_executed_or_mutation(gate)
    )
    in_canonical_pending = gate.status == (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW
    )
    if not (in_canonical_pending or recovered_from_missing_env_flag):
        return {
            "phase": "8F",
            "ok": False,
            "gate": serialize_phase8f_gate(gate),
            "attempt": None,
            "blockers": [
                f"phase8f_gate_status_{gate.status}_not_transitionable_to_approved"
            ],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_gate_not_in_pending_manual_review",
        }

    # Re-validate eligibility at approve time so a drifted target
    # pair refuses to be promoted.
    phase8e_gate = gate.source_phase8e_gate
    target_order = (
        Order.objects.filter(
            pk=gate.selected_order_id_snapshot
        ).first()
        if (gate.selected_order_id_snapshot or "").strip()
        else None
    )
    target_payment = (
        Payment.objects.filter(
            pk=gate.selected_payment_id_snapshot
        ).first()
        if (gate.selected_payment_id_snapshot or "").strip()
        else None
    )
    blockers = _eligibility_blockers(
        phase8e_gate,
        target_order=target_order,
        target_payment=target_payment,
    )
    if blockers:
        gate.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.BLOCKED
        )
        gate.blockers = list(gate.blockers or []) + list(blockers)
        gate.save(
            update_fields=["status", "blockers", "updated_at"]
        )
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8F approve blocked gate_id={gate.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(
                gate, extra={"blockers": list(blockers)}
            ),
        )
        return {
            "phase": "8F",
            "ok": False,
            "gate": serialize_phase8f_gate(gate),
            "attempt": None,
            "blockers": blockers,
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "fix_phase8f_approve_blockers",
        }

    before = _business_row_counts()
    with transaction.atomic():
        gate.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_REAL_CUSTOMER_MUTATION
        )
        gate.review_reason = (reason or "").strip()
        gate.reviewed_at = timezone.now()
        gate.approved_at = timezone.now()
        gate.reviewed_by = reviewed_by
        gate.reviewed_by_username = _reviewer_username(reviewed_by)
        gate.next_action = (
            "phase8f_attempt_pending_director_signoff_then_execute"
        )
        if recovered_from_missing_env_flag:
            # Clear stale blockers from the prior missing-env-flag
            # failure; stamp Phase 8F-Hotfix-1 recovery markers on
            # the immutable evidence_json blob so the audit + future
            # readers can see exactly how this gate got promoted.
            gate.blockers = []
            evidence = dict(gate.evidence_json or {})
            recovery_marker = {
                "recoveredFromMissingEnvApprovalBlock": True,
                "recoveredBlocker": _RECOVERABLE_APPROVE_BLOCKER,
                "executionStillNotRun": True,
                "recoveredAtUtc": (
                    timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                ),
                "phase8fHotfix1": True,
            }
            evidence["phase8fHotfix1Recovery"] = recovery_marker
            gate.evidence_json = evidence
            gate.warnings = list(gate.warnings or []) + [
                "phase8f_hotfix1_recovered_from_missing_env_flag"
            ]
        gate.save()

        # Create the matching attempt row in
        # `approved_for_one_shot_real_mutation` status so execute
        # can find a transitionable attempt.
        attempt = (
            RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.create(
                gate=gate,
                target_order_id=gate.selected_order_id_snapshot,
                target_payment_id=gate.selected_payment_id_snapshot,
                status=(
                    RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_REAL_MUTATION
                ),
                old_order_payment_status=(
                    target_order.payment_status
                    if target_order
                    else ""
                )[:32],
                old_payment_status=(
                    target_payment.status if target_payment else ""
                )[:32],
                new_order_payment_status="",
                new_payment_status="",
                blockers=[],
                warnings=[PHASE_8F_WARNING],
            )
        )
        assert_phase8f_no_unauthorized_side_effect(
            gate, before_counts=before, attempt=attempt
        )

    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            f"Phase 8F approved gate_id={gate.pk} "
            f"attempt_id={attempt.pk}"
            + (
                " (recovered from missing-env-flag block)"
                if recovered_from_missing_env_flag
                else ""
            )
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload=_audit_gate_payload(
            gate,
            extra={
                "attempt_id": attempt.pk,
                "reviewed_by_username": gate.reviewed_by_username,
                "review_reason_present": bool(
                    (gate.review_reason or "").strip()
                ),
                "phase8f_hotfix1_recovered_from_missing_env_flag": bool(
                    recovered_from_missing_env_flag
                ),
                "phase8f_hotfix1_execution_still_not_run": True,
            },
        ),
    )
    return {
        "phase": "8F",
        "ok": True,
        "gate": serialize_phase8f_gate(gate),
        "attempt": serialize_phase8f_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_8F_WARNING],
        "nextAction": (
            "phase8f_attempt_pending_director_signoff_then_execute"
        ),
        "phase8fHotfix1RecoveredFromMissingEnvApprovalBlock": bool(
            recovered_from_missing_env_flag
        ),
    }


def reject_phase8f_real_customer_controlled_mutation(
    gate_id: int,
    *,
    reason: str,
    reviewed_by=None,
) -> dict[str, Any]:
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8F",
            "ok": False,
            "gate": None,
            "blockers": ["phase8f_gate_not_found"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not (reason or "").strip():
        return {
            "phase": "8F",
            "ok": False,
            "gate": serialize_phase8f_gate(gate),
            "blockers": ["phase8f_reject_reason_required"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_reject_reason_required",
        }
    rejectable = {
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.DRAFT,
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.BLOCKED,
    }
    if gate.status not in rejectable:
        return {
            "phase": "8F",
            "ok": False,
            "gate": serialize_phase8f_gate(gate),
            "blockers": [
                f"phase8f_gate_status_{gate.status}_not_transitionable_to_rejected"
            ],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_gate_not_rejectable",
        }
    before = _business_row_counts()
    with transaction.atomic():
        gate.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.REJECTED
        )
        gate.reject_reason = (reason or "").strip()
        gate.reviewed_at = timezone.now()
        gate.rejected_at = timezone.now()
        gate.reviewed_by = reviewed_by
        gate.reviewed_by_username = _reviewer_username(reviewed_by)
        gate.next_action = "phase8f_gate_rejected"
        gate.save()
        assert_phase8f_no_unauthorized_side_effect(
            gate, before_counts=before
        )

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 8F rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate,
            extra={
                "reject_reason_present": bool(
                    (gate.reject_reason or "").strip()
                ),
                "reviewed_by_username": gate.reviewed_by_username,
            },
        ),
    )
    return {
        "phase": "8F",
        "ok": True,
        "gate": serialize_phase8f_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8F_WARNING],
        "nextAction": "phase8f_gate_rejected",
    }


def archive_phase8f_real_customer_controlled_mutation(
    gate_id: int,
    *,
    reason: str,
    reviewed_by=None,
) -> dict[str, Any]:
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8F",
            "ok": False,
            "gate": None,
            "blockers": ["phase8f_gate_not_found"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "verify_gate_id",
        }
    if not (reason or "").strip():
        return {
            "phase": "8F",
            "ok": False,
            "gate": serialize_phase8f_gate(gate),
            "blockers": ["phase8f_archive_reason_required"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_archive_reason_required",
        }
    before = _business_row_counts()
    with transaction.atomic():
        gate.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.ARCHIVED
        )
        gate.archive_reason = (reason or "").strip()
        gate.archived_at = timezone.now()
        gate.reviewed_by = reviewed_by
        gate.reviewed_by_username = _reviewer_username(reviewed_by)
        gate.next_action = "phase8f_gate_archived"
        gate.save()
        assert_phase8f_no_unauthorized_side_effect(
            gate, before_counts=before
        )

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 8F archived gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate,
            extra={
                "archive_reason_present": bool(
                    (gate.archive_reason or "").strip()
                ),
                "reviewed_by_username": gate.reviewed_by_username,
            },
        ),
    )
    return {
        "phase": "8F",
        "ok": True,
        "gate": serialize_phase8f_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8F_WARNING],
        "nextAction": "phase8f_gate_archived",
    }


# ---------------------------------------------------------------------------
# Execute / Rollback
# ---------------------------------------------------------------------------


def execute_phase8f_real_customer_controlled_mutation(
    attempt_id: int,
    *,
    director_signoff: str = "",
    operator_name: str = "",
    confirm_one_shot_real_mutation: bool = False,
    now=None,
) -> dict[str, Any]:
    """One-shot CLI-only execute. Refuses unless every safety gate
    is satisfied. The only mutation performed is writing the target
    Order's ``payment_status`` and target Payment's ``status`` to
    ``Paid``. No provider call, no notification, no WhatsApp, no
    courier, no Shipment row, no Order.state change."""
    from apps.saas.utc_window import (  # local import keeps module pure
        parse_director_signoff_window,
        validate_within_director_window,
    )

    attempt = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.filter(
            pk=attempt_id
        )
        .select_related("gate", "gate__source_phase8e_gate")
        .first()
    )
    if attempt is None:
        return {
            "phase": "8F",
            "ok": False,
            "attempt": None,
            "rollback": None,
            "blockers": ["phase8f_attempt_not_found"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "verify_attempt_id",
        }
    gate = attempt.gate

    blockers: list[str] = []
    if not _flag_phase8f_gate_enabled():
        blockers.append(
            "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        )
    if not _flag_phase8f_director_approved():
        blockers.append(
            "PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION_must_be_true"
        )
    if not _flag_phase8f_allow_real_customer_mutation():
        blockers.append(
            "PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION_must_be_true"
        )
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    if _flag_real_customer_automation_approved():
        blockers.append(
            "real_customer_automation_must_remain_not_broadly_approved"
        )
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if not bool(confirm_one_shot_real_mutation):
        blockers.append(
            "phase8f_confirm_one_shot_real_mutation_required"
        )
    if not (operator_name or "").strip():
        blockers.append("phase8f_operator_name_required")

    signoff = (director_signoff or "").strip()
    if not signoff:
        blockers.append("phase8f_director_signoff_required")
    else:
        if f"phase8f_attempt_id_{attempt.pk}" not in signoff:
            blockers.append(
                "phase8f_director_signoff_must_reference_phase8f_attempt_id"
            )
        if f"phase8f_gate_id_{gate.pk}" not in signoff:
            blockers.append(
                "phase8f_director_signoff_must_reference_phase8f_gate_id"
            )
        if (
            f"phase8e_gate_id_{gate.source_phase8e_gate_id}"
            not in signoff
        ):
            blockers.append(
                "phase8f_director_signoff_must_reference_phase8e_gate_id"
            )
        if (
            f"target_order_{attempt.target_order_id}"
            not in signoff
        ):
            blockers.append(
                "phase8f_director_signoff_must_reference_target_order_id"
            )
        if (
            f"target_payment_{attempt.target_payment_id}"
            not in signoff
        ):
            blockers.append(
                "phase8f_director_signoff_must_reference_target_payment_id"
            )
    parsed_window = (
        parse_director_signoff_window(signoff) if signoff else None
    )
    window_result = validate_within_director_window(
        parsed_window, now=now
    )
    if not window_result.valid:
        for marker in window_result.blockers:
            blockers.append(f"phase8f_{marker}")

    # Gate / attempt status pre-conditions.
    if (
        gate.status
        != RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_REAL_CUSTOMER_MUTATION
    ):
        blockers.append(
            f"phase8f_gate_status_{gate.status}_not_executable"
        )
    if attempt.status != (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_REAL_MUTATION
    ):
        blockers.append(
            f"phase8f_attempt_status_{attempt.status}_not_executable"
        )

    # No prior execution on this gate.
    if (
        gate.attempts.filter(
            status=(
                RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.EXECUTED
            )
        ).exists()
    ):
        blockers.append(
            "phase8f_gate_already_has_executed_attempt"
        )

    target_order = Order.objects.filter(
        pk=attempt.target_order_id
    ).first()
    target_payment = Payment.objects.filter(
        pk=attempt.target_payment_id
    ).first()
    blockers += _validate_target_pair_currentness(
        target_order, target_payment
    )

    if blockers:
        attempt.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
        )
        attempt.blockers = list(attempt.blockers or []) + list(
            blockers
        )
        attempt.save(
            update_fields=["status", "blockers", "updated_at"]
        )
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8F execute blocked attempt_id={attempt.pk} "
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
            "phase": "8F",
            "ok": False,
            "attempt": serialize_phase8f_attempt(attempt),
            "rollback": None,
            "blockers": list(blockers),
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "fix_phase8f_execute_blockers",
        }

    before = _business_row_counts()
    actual_old_order_payment_status = (
        target_order.payment_status if target_order else ""
    )[:32]
    actual_old_payment_status = (
        target_payment.status if target_payment else ""
    )[:32]

    try:
        with transaction.atomic():
            # Mutate ONLY the chosen target rows, ONLY the
            # payment_status / status fields.
            target_order.payment_status = (
                _PROPOSED_NEW_ORDER_PAYMENT_STATUS
            )
            target_order.save(update_fields=["payment_status"])
            target_payment.status = _PROPOSED_NEW_PAYMENT_STATUS
            target_payment.save(update_fields=["status"])

            attempt.old_order_payment_status = (
                actual_old_order_payment_status
            )
            attempt.new_order_payment_status = (
                _PROPOSED_NEW_ORDER_PAYMENT_STATUS
            )
            attempt.old_payment_status = actual_old_payment_status
            attempt.new_payment_status = _PROPOSED_NEW_PAYMENT_STATUS
            attempt.order_mutation_was_made = True
            attempt.payment_mutation_was_made = True
            attempt.business_mutation_was_made = True
            # NEVER flips: customer_notification_sent / whatsapp_sent
            # / courier_called / provider_call_attempted /
            # shipment_created.
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
                RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.EXECUTED
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

            if deltas:
                raise ValueError(
                    "Phase 8F execute count drift: " + str(deltas)
                )
            # Defensive: locked-False contract still intact.
            assert_phase8f_no_unauthorized_side_effect(
                gate, attempt=attempt
            )

            gate.status = (
                RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.EXECUTED
            )
            gate.next_action = "phase8f_gate_executed"
            gate.save(
                update_fields=["status", "next_action", "updated_at"]
            )
    except Exception as exc:
        attempt.refresh_from_db()
        attempt.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.FAILED
        )
        attempt.failed_at = timezone.now()
        attempt.blockers = list(attempt.blockers or []) + [
            f"phase8f_execute_exception:{type(exc).__name__}"
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
                f"Phase 8F execute failed attempt_id={attempt.pk} "
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
            "phase": "8F",
            "ok": False,
            "attempt": serialize_phase8f_attempt(attempt),
            "rollback": None,
            "blockers": [
                f"phase8f_execute_exception:{type(exc).__name__}"
            ],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_execute_failed_review_required",
        }

    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=(
            f"Phase 8F executed attempt_id={attempt.pk} "
            f"gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload=_audit_gate_payload(
            gate,
            extra={
                "attempt_id": attempt.pk,
                "target_order_id_last8": (
                    attempt.target_order_id or ""
                )[-8:],
                "target_payment_id_last8": (
                    attempt.target_payment_id or ""
                )[-8:],
                "old_order_payment_status": (
                    attempt.old_order_payment_status
                ),
                "new_order_payment_status": (
                    attempt.new_order_payment_status
                ),
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
        "phase": "8F",
        "ok": True,
        "attempt": serialize_phase8f_attempt(attempt),
        "rollback": None,
        "blockers": [],
        "warnings": [PHASE_8F_WARNING],
        "nextAction": "phase8f_attempt_executed_awaiting_rollback_or_evidence",
    }


def rollback_phase8f_real_customer_controlled_mutation(
    attempt_id: int,
    *,
    reason: str,
) -> dict[str, Any]:
    """Rollback an executed Phase 8F attempt. Restores the original
    ``Order.payment_status`` + ``Payment.status`` values from the
    attempt's old_* snapshots. No provider call, no notification,
    no WhatsApp, no business row count drift."""
    attempt = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.filter(
            pk=attempt_id
        )
        .select_related("gate")
        .first()
    )
    if attempt is None:
        return {
            "phase": "8F",
            "ok": False,
            "attempt": None,
            "rollback": None,
            "blockers": ["phase8f_attempt_not_found"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if not (reason or "").strip():
        return {
            "phase": "8F",
            "ok": False,
            "attempt": serialize_phase8f_attempt(attempt),
            "rollback": None,
            "blockers": ["phase8f_rollback_reason_required"],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_rollback_reason_required",
        }
    if attempt.executed_at is None or attempt.status != (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.EXECUTED
    ):
        return {
            "phase": "8F",
            "ok": False,
            "attempt": serialize_phase8f_attempt(attempt),
            "rollback": None,
            "blockers": [
                f"phase8f_attempt_status_{attempt.status}_not_rollbackable"
            ],
            "warnings": [PHASE_8F_WARNING],
            "nextAction": "phase8f_attempt_not_executed",
        }
    gate = attempt.gate
    target_order = Order.objects.filter(
        pk=attempt.target_order_id
    ).first()
    target_payment = Payment.objects.filter(
        pk=attempt.target_payment_id
    ).first()

    before = _business_row_counts()
    with transaction.atomic():
        if target_order is not None and (
            attempt.old_order_payment_status or ""
        ):
            target_order.payment_status = (
                attempt.old_order_payment_status
            )
            target_order.save(update_fields=["payment_status"])
        if target_payment is not None and (
            attempt.old_payment_status or ""
        ):
            target_payment.status = attempt.old_payment_status
            target_payment.save(update_fields=["status"])

        rollback = (
            RazorpayRealCustomerPaymentOrderControlledMutationRollback.objects.create(
                attempt=attempt,
                status=(
                    RazorpayRealCustomerPaymentOrderControlledMutationRollback.Status.ROLLBACK_RECORDED
                ),
                restored_order_payment_status=(
                    attempt.old_order_payment_status or ""
                )[:32],
                restored_payment_status=(
                    attempt.old_payment_status or ""
                )[:32],
                rollback_was_made=True,
                customer_notification_sent=False,
                whatsapp_sent=False,
                courier_called=False,
                provider_call_attempted=False,
                reason=(reason or "").strip(),
                rolled_back_at=timezone.now(),
            )
        )
        after = _business_row_counts()
        deltas: dict[str, int] = {}
        for key, count_before in before.items():
            count_after = after.get(key, count_before)
            if count_after != count_before:
                deltas[key] = count_after - count_before
        rollback.before_counts = before
        rollback.after_counts = after
        rollback.count_deltas = deltas
        rollback.save(
            update_fields=[
                "before_counts",
                "after_counts",
                "count_deltas",
                "updated_at",
            ]
        )
        if deltas:
            raise ValueError(
                "Phase 8F rollback count drift: " + str(deltas)
            )
        assert_phase8f_no_unauthorized_side_effect(
            gate, attempt=attempt, rollback=rollback
        )

        attempt.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.ROLLED_BACK
        )
        attempt.save(update_fields=["status", "updated_at"])
        gate.status = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.ROLLED_BACK
        )
        gate.next_action = "phase8f_gate_rolled_back"
        gate.save(
            update_fields=["status", "next_action", "updated_at"]
        )

    write_event(
        kind=AUDIT_KIND_ROLLBACK,
        text=(
            f"Phase 8F rollback recorded attempt_id={attempt.pk} "
            f"gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate,
            extra={
                "attempt_id": attempt.pk,
                "rollback_id": rollback.pk,
                "restored_order_payment_status": (
                    rollback.restored_order_payment_status
                ),
                "restored_payment_status": (
                    rollback.restored_payment_status
                ),
                "reason_present": bool(
                    (rollback.reason or "").strip()
                ),
            },
        ),
    )
    return {
        "phase": "8F",
        "ok": True,
        "attempt": serialize_phase8f_attempt(attempt),
        "rollback": serialize_phase8f_rollback(rollback),
        "blockers": [],
        "warnings": [PHASE_8F_WARNING],
        "nextAction": "phase8f_attempt_rolled_back",
    }


# ---------------------------------------------------------------------------
# Summaries (used by the read-only DRF views)
# ---------------------------------------------------------------------------


def summarize_phase8f_gates(limit: int = 25) -> dict[str, Any]:
    rows = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.all().order_by(
            "-created_at"
        )[: max(1, min(int(limit or 25), 200))]
    )
    counts: dict[str, int] = {}
    for choice, _ in (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.choices
    ):
        counts[choice] = (
            RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.filter(
                status=choice
            ).count()
        )
    return {
        "phase": "8F",
        "limit": int(limit or 25),
        "counts": counts,
        "items": [serialize_phase8f_gate(r) for r in rows],
        "executionPath": (
            "cli_only_one_shot_controlled_mutation_no_provider_no_send_no_notify"
        ),
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "phase8FCallsRazorpay": False,
        "phase8FCallsMetaCloud": False,
        "phase8FCallsDelhivery": False,
        "phase8FCallsVapi": False,
        "phase8FSendsWhatsApp": False,
        "phase8FSendsCustomerNotification": False,
        "phase8FCreatesShipment": False,
        "phase8FCreatesAwb": False,
        "phase8FCreatesPaymentLink": False,
        "phase8FCapturesPayment": False,
        "phase8FRefundsPayment": False,
        "phase8FMutatesOrderState": False,
        "phase8FMutatesCustomer": False,
        "phase8FMutatesLead": False,
        "phase8FMutatesShipment": False,
        "phase8FMutatesDiscountOfferLog": False,
        "phase8FMutatesWhatsAppMessage": False,
    }
