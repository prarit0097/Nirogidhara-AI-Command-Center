"""Phase 8B - Payment -> Order Mutation Review Gate.

Phase 8B is **review / dry-run only**. It converts an approved
Phase 8A sandbox gate into a review-only contract for a future
Phase 8C controlled mutation phase. Phase 8B NEVER calls Razorpay
/ Meta Cloud / Delhivery / Vapi, NEVER sends or queues WhatsApp,
NEVER creates a ``Shipment`` / AWB / payment link, NEVER captures
/ refunds, NEVER sends a customer notification, NEVER mutates real
``Order`` / ``Payment`` / ``Customer`` / ``Lead`` / ``Shipment`` /
``DiscountOfferLog`` rows, NEVER edits any ``.env*`` file.

Approval flips status to
``approved_for_future_phase8c_controlled_mutation_review`` only --
it does NOT authorize any real mutation.

Public surface:

- :func:`inspect_phase8b_payment_order_mutation_review_readiness`
- :func:`preview_phase8b_payment_order_mutation_review_gate`
- :func:`prepare_phase8b_payment_order_mutation_review_gate`
- :func:`dry_run_phase8b_payment_order_mutation_review_gate`
- :func:`rollback_dry_run_phase8b_payment_order_mutation_review_gate`
- :func:`approve_phase8b_payment_order_mutation_review_gate`
- :func:`reject_phase8b_payment_order_mutation_review_gate`
- :func:`archive_phase8b_payment_order_mutation_review_gate`
- :func:`assert_phase8b_no_business_mutation`
- :func:`serialize_phase8b_gate`
- :func:`serialize_phase8b_dry_run`
- :func:`summarize_phase8b_gates`
"""
from __future__ import annotations

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
    RazorpayControlledPilotExecutionAttempt,
    RazorpayPaymentOrderMutationReviewDryRun,
    RazorpayPaymentOrderMutationReviewGate,
    RazorpayPaymentOrderMutationSandboxGate,
    RazorpayPhase7FinalAuditLock,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_8B_WARNING = (
    "Phase 8B is the Payment -> Order Mutation Review Gate. It is "
    "review / dry-run only. Approval flips status to "
    "`approved_for_future_phase8c_controlled_mutation_review` and "
    "freezes the design contract. Phase 8B NEVER calls Razorpay / "
    "Meta Cloud / Delhivery / Vapi, NEVER sends or queues WhatsApp, "
    "NEVER creates a Shipment / AWB / payment link, NEVER captures, "
    "NEVER refunds, NEVER sends a customer notification, NEVER "
    "mutates real Order / Payment / Customer / Lead / Shipment / "
    "DiscountOfferLog rows, NEVER edits any .env file. Phase 8C "
    "(controlled real mutation) remains NOT approved. Phase "
    "7E-Live-B (real customer WhatsApp send) and Phase 7G-Live "
    "(real customer courier execution) remain NOT approved; "
    "real-customer automation remains NOT approved."
)


AUDIT_KIND_READINESS = "phase8b.payment_order.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase8b.payment_order.previewed"
AUDIT_KIND_PREPARED = "phase8b.payment_order.prepared"
AUDIT_KIND_DRY_RUN_PASSED = "phase8b.payment_order.dry_run_passed"
AUDIT_KIND_DRY_RUN_FAILED = "phase8b.payment_order.dry_run_failed"
AUDIT_KIND_ROLLBACK_RECORDED = (
    "phase8b.payment_order.rollback_recorded"
)
AUDIT_KIND_APPROVED = "phase8b.payment_order.approved"
AUDIT_KIND_REJECTED = "phase8b.payment_order.rejected"
AUDIT_KIND_ARCHIVED = "phase8b.payment_order.archived"
AUDIT_KIND_BLOCKED = "phase8b.payment_order.blocked"


PHASE_8B_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "mutate_real_payment_status",
    "mutate_real_shipment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "mutate_real_discount_offer_log",
    "approve_phase8c_real_mutation",
    "approve_real_customer_automation",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "execute_via_api_endpoint",
    "archive_via_api_endpoint",
    "dry_run_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_8B_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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


# Locked-False contract fields on the Phase 8B gate row.
_GATE_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "real_mutation_allowed",
    "real_order_mutation_allowed",
    "real_payment_mutation_allowed",
    "customer_notification_allowed",
    "whatsapp_allowed",
    "courier_allowed",
)


# Locked-False contract fields on every dry-run row.
_DRY_RUN_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "would_mutate_order",
    "would_mutate_payment",
    "would_notify_customer",
    "would_send_whatsapp",
    "would_call_courier",
    "would_create_shipment",
)


# Review-only reference markers; dry-run input MUST match.
_REVIEW_REFERENCE_PREFIXES: tuple[str, ...] = (
    "phase8b::review::order::",
    "phase8b-review-",
    "review::phase8b::",
)


# Phase 8A locked-False contract that must still hold on the source
# sandbox gate.
_PHASE8A_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "real_business_mutation_allowed",
    "real_order_mutation_allowed",
    "real_payment_mutation_allowed",
    "customer_notification_allowed",
    "whatsapp_allowed",
    "courier_allowed",
)


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


def _flag_phase8b_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED",
            False,
        )
    )


def _flag_phase7e_live_b_approved() -> bool:
    # Phase 7E-Live-B never lands as a settings flag in Phase 8B;
    # surface a hard False so the gate cannot be approved if a
    # future toggle accidentally tries to flip it.
    return False


def _flag_phase7g_live_approved() -> bool:
    return False


def _flag_phase8c_approved() -> bool:
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
    safe: dict[str, Any] = {"phase": "8B"}
    forbidden = set(PHASE_8B_FORBIDDEN_PAYLOAD_KEYS)
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


def _business_row_counts() -> dict[str, int]:
    """Snapshot the protected business / send / courier tables. Phase 8B
    is a strict no-op against every one of these tables."""
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
# Defensive invariant guard
# ---------------------------------------------------------------------------


def assert_phase8b_no_business_mutation(
    gate: RazorpayPaymentOrderMutationReviewGate,
    *,
    before_counts: dict[str, int],
    dry_run: Optional[
        RazorpayPaymentOrderMutationReviewDryRun
    ] = None,
) -> None:
    """Defensive guard. Raises ``ValueError`` (and writes an
    invariant audit row) if any locked-False boolean flipped True
    or if any protected business-row count drifted."""
    flipped: list[str] = []
    for field in _GATE_LOCKED_FALSE_FIELDS:
        if getattr(gate, field, False):
            flipped.append(f"gate.{field}_must_stay_false")
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
            "flipped_locked_false_fields": flipped,
            "business_row_delta_keys": delta_keys,
            "kill_switch_state_at_emit": _kill_switch_state(),
        }
    )
    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=(
            "Phase 8B invariant violation: locked-False or business "
            "row count drift detected; refusing the operation."
        ),
        tone=AuditEvent.Tone.DANGER,
        payload=payload,
    )
    raise ValueError(
        "Phase 8B invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_phase8a_gate(
    gate: Optional[RazorpayPaymentOrderMutationSandboxGate],
) -> list[str]:
    blockers: list[str] = []
    if gate is None:
        blockers.append("phase8b_source_phase8a_gate_not_found")
        return blockers
    if (
        gate.status
        != RazorpayPaymentOrderMutationSandboxGate.Status.APPROVED_FOR_FUTURE_PHASE8B_REVIEW
    ):
        blockers.append(
            "phase8b_source_phase8a_gate_status_must_be_"
            f"approved_for_future_phase8b_review_was_{gate.status}"
        )
    for field in _PHASE8A_LOCKED_FALSE_FIELDS:
        if getattr(gate, field, False):
            blockers.append(
                f"phase8b_source_phase8a_{field}_must_stay_false"
            )
    return blockers


def _validate_phase7i_lock(
    lock: Optional[RazorpayPhase7FinalAuditLock],
) -> list[str]:
    blockers: list[str] = []
    if lock is None:
        blockers.append("phase8b_source_phase7i_lock_not_found")
        return blockers
    if lock.status != RazorpayPhase7FinalAuditLock.Status.LOCKED:
        blockers.append(
            "phase8b_source_phase7i_lock_status_must_be_locked_was_"
            f"{lock.status}"
        )
    return blockers


def _validate_phase7d_attempt(
    attempt: Optional[RazorpayControlledPilotExecutionAttempt],
) -> list[str]:
    blockers: list[str] = []
    if attempt is None:
        blockers.append("phase8b_source_phase7d_attempt_not_found")
        return blockers
    if (
        attempt.status
        != RazorpayControlledPilotExecutionAttempt.Status.ROLLED_BACK
    ):
        blockers.append(
            "phase8b_source_phase7d_attempt_status_must_be_rolled_back_was_"
            f"{attempt.status}"
        )
    if getattr(attempt, "business_mutation_was_made", False):
        blockers.append(
            "phase8b_source_phase7d_business_mutation_was_made_must_stay_false"
        )
    if getattr(attempt, "customer_notification_sent", False):
        blockers.append(
            "phase8b_source_phase7d_customer_notification_sent_must_stay_false"
        )
    return blockers


def _validate_eligibility(
    *,
    phase8a_gate_id: Optional[int],
    require_env_flag: bool = True,
) -> dict[str, Any]:
    blockers: list[str] = []
    if require_env_flag and not _flag_phase8b_enabled():
        blockers.append(
            "PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED_must_be_true"
        )
    if _flag_phase8c_approved():
        blockers.append("phase8c_must_remain_not_approved")
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    phase8a_gate: Optional[
        RazorpayPaymentOrderMutationSandboxGate
    ] = None
    if phase8a_gate_id:
        phase8a_gate = (
            RazorpayPaymentOrderMutationSandboxGate.objects.filter(
                pk=phase8a_gate_id
            )
            .select_related(
                "source_phase7i_lock", "source_phase7d_attempt"
            )
            .first()
        )
    blockers += _validate_phase8a_gate(phase8a_gate)

    phase7i_lock: Optional[RazorpayPhase7FinalAuditLock] = None
    phase7d: Optional[RazorpayControlledPilotExecutionAttempt] = None
    if phase8a_gate is not None:
        phase7i_lock = phase8a_gate.source_phase7i_lock
        phase7d = phase8a_gate.source_phase7d_attempt
    blockers += _validate_phase7i_lock(phase7i_lock)
    blockers += _validate_phase7d_attempt(phase7d)

    return {
        "phase8a_gate": phase8a_gate,
        "phase7i_lock": phase7i_lock,
        "phase7d": phase7d,
        "blockers": blockers,
        "eligible": not blockers,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_phase8b_gate(
    row: RazorpayPaymentOrderMutationReviewGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase8AGateId": row.source_phase8a_gate_id,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "reviewOnly": bool(row.review_only),
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
        "phase8CRequired": bool(row.phase8c_required),
        "manualReviewRequired": bool(row.manual_review_required),
        "paymentReferenceSnapshot": row.payment_reference_snapshot,
        "orderReferenceStrategySnapshot": (
            row.order_reference_strategy_snapshot
        ),
        "syntheticOrderReferenceSnapshot": (
            row.synthetic_order_reference_snapshot
        ),
        "proposedRealOrderMatchingStrategy": (
            row.proposed_real_order_matching_strategy
        ),
        "proposedPaymentToOrderMappingJson": (
            row.proposed_payment_to_order_mapping_json or {}
        ),
        "dryRunPassed": bool(row.dry_run_passed),
        "rollbackDryRunPassed": bool(row.rollback_dry_run_passed),
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


def serialize_phase8b_dry_run(
    row: RazorpayPaymentOrderMutationReviewDryRun,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "sourcePhase8AGateId": row.source_phase8a_gate_id,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "paymentReference": row.payment_reference,
        "paymentStatusSnapshot": row.payment_status_snapshot,
        "targetOrderReference": row.target_order_reference,
        "targetOrderMatchType": row.target_order_match_type,
        "proposedOldOrderStatus": row.proposed_old_order_status,
        "proposedNewOrderStatus": row.proposed_new_order_status,
        "proposedOldPaymentStatus": row.proposed_old_payment_status,
        "proposedNewPaymentStatus": row.proposed_new_payment_status,
        "wouldMutateOrder": bool(row.would_mutate_order),
        "wouldMutatePayment": bool(row.would_mutate_payment),
        "wouldNotifyCustomer": bool(row.would_notify_customer),
        "wouldSendWhatsApp": bool(row.would_send_whatsapp),
        "wouldCallCourier": bool(row.would_call_courier),
        "wouldCreateShipment": bool(row.would_create_shipment),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "passed": bool(row.passed),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "rollbackRecorded": bool(row.rollback_recorded),
        "rollbackReasonPresent": bool(
            (row.rollback_reason or "").strip()
        ),
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
    gate: RazorpayPaymentOrderMutationReviewGate,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gate_id": gate.pk,
        "status": gate.status,
        "phase8a_gate_id": gate.source_phase8a_gate_id,
        "phase7i_lock_id": gate.source_phase7i_lock_id,
        "phase7d_attempt_id": gate.source_phase7d_attempt_id,
        "review_only": bool(gate.review_only),
        "real_mutation_allowed": False,
        "real_order_mutation_allowed": False,
        "real_payment_mutation_allowed": False,
        "customer_notification_allowed": False,
        "whatsapp_allowed": False,
        "courier_allowed": False,
        "phase8c_required": True,
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
    phase8a_gate: RazorpayPaymentOrderMutationSandboxGate,
    phase7i_lock: RazorpayPhase7FinalAuditLock,
    phase7d: Optional[RazorpayControlledPilotExecutionAttempt],
) -> dict[str, Any]:
    return {
        "phase": "8B",
        "phase8a": {
            "gateId": phase8a_gate.pk,
            "status": phase8a_gate.status,
            "sandboxOnly": bool(phase8a_gate.sandbox_only),
        },
        "phase7i": {
            "lockId": phase7i_lock.pk,
            "status": phase7i_lock.status,
            "phase7dAttemptId": (
                phase7i_lock.source_phase7d_attempt_id
            ),
            "phase7eLiveSendAttemptId": (
                phase7i_lock.source_phase7e_live_send_attempt_id
            ),
            "phase7gAttemptId": (
                phase7i_lock.source_phase7g_attempt_id
            ),
            "phase7hEvidenceLockId": (
                phase7i_lock.source_phase7h_evidence_lock_id
            ),
        },
        "phase7d": (
            {
                "attemptId": phase7d.pk,
                "status": phase7d.status,
                "providerObjectId": phase7d.provider_object_id or "",
                "rollbackStatus": phase7d.rollback_status,
                "businessMutationWasMade": False,
                "customerNotificationSent": False,
            }
            if phase7d is not None
            else None
        ),
        "reviewContract": {
            "reviewOnly": True,
            "realMutationAllowed": False,
            "realOrderMutationAllowed": False,
            "realPaymentMutationAllowed": False,
            "customerNotificationAllowed": False,
            "whatsAppAllowed": False,
            "courierAllowed": False,
            "phase8CRequired": True,
            "manualReviewRequired": True,
        },
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase8b_payment_order_mutation_review_gate(
    phase8a_gate_id: int,
) -> dict[str, Any]:
    eligibility = _validate_eligibility(
        phase8a_gate_id=phase8a_gate_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 8B preview phase8a_gate_id={phase8a_gate_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase8a_gate_id": phase8a_gate_id,
                "eligible": eligibility["eligible"],
                "blockers": list(eligibility["blockers"]),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    evidence: dict[str, Any] = {}
    if (
        eligibility["eligible"]
        and eligibility["phase8a_gate"] is not None
        and eligibility["phase7i_lock"] is not None
    ):
        evidence = _build_evidence_json(
            phase8a_gate=eligibility["phase8a_gate"],
            phase7i_lock=eligibility["phase7i_lock"],
            phase7d=eligibility["phase7d"],
        )
    return {
        "phase": "8B",
        "found": eligibility["phase8a_gate"] is not None,
        "sourcePhase8AGateId": phase8a_gate_id,
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
        "warnings": [PHASE_8B_WARNING],
        "evidence": evidence,
        "nextAction": (
            "ready_to_prepare_phase8b_payment_order_mutation_review_gate"
            if eligibility["eligible"]
            and _flag_phase8b_enabled()
            else (
                "fix_phase8b_eligibility_blockers_or_enable_phase8b_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase8b_payment_order_mutation_review_gate(
    phase8a_gate_id: int,
) -> dict[str, Any]:
    """Atomic + idempotent prepare on the source Phase 8A gate.
    NEVER calls any provider; NEVER mutates business rows; NEVER
    edits any ``.env*`` file."""
    eligibility = _validate_eligibility(
        phase8a_gate_id=phase8a_gate_id, require_env_flag=True
    )
    if (
        not eligibility["eligible"]
        or eligibility["phase8a_gate"] is None
        or eligibility["phase7i_lock"] is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8B prepare blocked phase8a_gate_id="
                f"{phase8a_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase8a_gate_id": phase8a_gate_id,
                    "blockers": list(eligibility["blockers"]),
                    "kill_switch_state_at_emit": _kill_switch_state(),
                }
            ),
        )
        return {
            "phase": "8B",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_8B_WARNING],
            "nextAction": (
                "fix_phase8b_eligibility_blockers_or_enable_phase8b_flag"
            ),
        }

    phase8a_gate = eligibility["phase8a_gate"]
    phase7i_lock = eligibility["phase7i_lock"]
    phase7d = eligibility["phase7d"]
    before = _business_row_counts()

    payment_reference_snapshot = (
        getattr(phase7d, "provider_object_id", "") or ""
    )[:120]
    proposed_mapping = {
        "phase": "8B",
        "paymentReference": payment_reference_snapshot,
        "targetOrderReferenceStrategy": (
            "future_synthetic_or_real_lookup_phase8c_decides"
        ),
        "realMutationAllowed": False,
    }

    with transaction.atomic():
        existing = (
            RazorpayPaymentOrderMutationReviewGate.objects.filter(
                source_phase8a_gate=phase8a_gate
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "8B",
                "created": False,
                "reused": True,
                "gate": serialize_phase8b_gate(existing),
                "blockers": [],
                "warnings": [PHASE_8B_WARNING],
                "nextAction": (
                    "phase8b_gate_pending_manual_review"
                    if existing.status
                    == RazorpayPaymentOrderMutationReviewGate.Status.PENDING_MANUAL_REVIEW
                    else f"phase8b_gate_status_{existing.status}"
                ),
            }

        gate = RazorpayPaymentOrderMutationReviewGate(
            source_phase8a_gate=phase8a_gate,
            source_phase7i_lock=phase7i_lock,
            source_phase7d_attempt=phase7d,
            status=(
                RazorpayPaymentOrderMutationReviewGate.Status.PENDING_MANUAL_REVIEW
            ),
            review_only=True,
            real_mutation_allowed=False,
            real_order_mutation_allowed=False,
            real_payment_mutation_allowed=False,
            customer_notification_allowed=False,
            whatsapp_allowed=False,
            courier_allowed=False,
            phase8c_required=True,
            manual_review_required=True,
            payment_reference_snapshot=payment_reference_snapshot,
            order_reference_strategy_snapshot=(
                "review_only_future_phase8c"
            ),
            synthetic_order_reference_snapshot="",
            proposed_real_order_matching_strategy=(
                "future_phase8c_real_order_lookup_not_executed"
            ),
            proposed_payment_to_order_mapping_json=proposed_mapping,
            dry_run_passed=False,
            rollback_dry_run_passed=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            evidence_json=_build_evidence_json(
                phase8a_gate=phase8a_gate,
                phase7i_lock=phase7i_lock,
                phase7d=phase7d,
            ),
            blockers=[],
            warnings=[PHASE_8B_WARNING],
            next_action="phase8b_gate_pending_manual_review",
        )
        assert_phase8b_no_business_mutation(
            gate, before_counts=before
        )
        try:
            gate.save()
        except IntegrityError:  # pragma: no cover - defensive
            gate = (
                RazorpayPaymentOrderMutationReviewGate.objects.get(
                    source_phase8a_gate=phase8a_gate
                )
            )
            return {
                "phase": "8B",
                "created": False,
                "reused": True,
                "gate": serialize_phase8b_gate(gate),
                "blockers": [],
                "warnings": [PHASE_8B_WARNING],
                "nextAction": "phase8b_gate_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 8B gate prepared gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "8B",
        "created": True,
        "reused": False,
        "gate": serialize_phase8b_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8B_WARNING],
        "nextAction": "phase8b_gate_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def _validate_review_reference(reference: str) -> list[str]:
    blockers: list[str] = []
    if not (reference or "").strip():
        blockers.append(
            "phase8b_dry_run_target_order_reference_required"
        )
        return blockers
    if not any(
        reference.startswith(prefix)
        for prefix in _REVIEW_REFERENCE_PREFIXES
    ):
        blockers.append(
            "phase8b_dry_run_target_order_reference_must_start_with_known_review_prefix"
        )
    if len(reference) > 120:
        blockers.append(
            "phase8b_dry_run_target_order_reference_too_long"
        )
    return blockers


def dry_run_phase8b_payment_order_mutation_review_gate(
    gate_id: int,
    target_order_reference: str = "",
) -> dict[str, Any]:
    """Review-only dry-run. NEVER mutates real rows. Requires a
    review-only ``target_order_reference`` (one of the known
    prefixes)."""
    gate = (
        RazorpayPaymentOrderMutationReviewGate.objects.filter(
            pk=gate_id
        ).first()
    )
    if gate is None:
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "dryRun": None,
            "blockers": ["phase8b_gate_not_found"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_id",
        }

    if gate.status not in {
        RazorpayPaymentOrderMutationReviewGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderMutationReviewGate.Status.DRY_RUN_PASSED,
    }:
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "dryRun": None,
            "blockers": [
                f"phase8b_gate_status_{gate.status}_not_dry_runnable"
            ],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_status",
        }

    eligibility = _validate_eligibility(
        phase8a_gate_id=gate.source_phase8a_gate_id,
        require_env_flag=True,
    )
    blockers: list[str] = list(eligibility["blockers"])
    blockers += _validate_review_reference(target_order_reference)

    payment_reference = (
        getattr(
            gate.source_phase7d_attempt,
            "provider_object_id",
            "",
        )
        or ""
    )[:120]

    if blockers:
        # Persist a failed dry-run record so the operator can see why.
        before = _business_row_counts()
        record = RazorpayPaymentOrderMutationReviewDryRun.objects.create(
            gate=gate,
            source_phase8a_gate=gate.source_phase8a_gate,
            source_phase7i_lock=gate.source_phase7i_lock,
            source_phase7d_attempt=gate.source_phase7d_attempt,
            payment_reference=payment_reference,
            payment_status_snapshot=(
                "current_or_unknown_review_only"
            ),
            target_order_reference=(
                target_order_reference or ""
            )[:120],
            target_order_match_type=(
                RazorpayPaymentOrderMutationReviewDryRun.TargetOrderMatchType.SYNTHETIC_REFERENCE_ONLY
            ),
            proposed_old_order_status="",
            proposed_new_order_status="",
            proposed_old_payment_status="",
            proposed_new_payment_status="",
            would_mutate_order=False,
            would_mutate_payment=False,
            would_notify_customer=False,
            would_send_whatsapp=False,
            would_call_courier=False,
            would_create_shipment=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            passed=False,
            blockers=list(blockers),
            warnings=[PHASE_8B_WARNING],
        )
        write_event(
            kind=AUDIT_KIND_DRY_RUN_FAILED,
            text=(
                f"Phase 8B dry-run failed gate_id={gate.pk} "
                f"record_id={record.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_gate_payload(
                gate,
                extra={
                    "dry_run_id": record.pk,
                    "blockers": list(blockers),
                },
            ),
        )
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "dryRun": serialize_phase8b_dry_run(record),
            "blockers": list(blockers),
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "fix_phase8b_dry_run_blockers",
        }

    # Eligible. Execute the review dry-run with no mutation.
    before = _business_row_counts()
    record = RazorpayPaymentOrderMutationReviewDryRun.objects.create(
        gate=gate,
        source_phase8a_gate=gate.source_phase8a_gate,
        source_phase7i_lock=gate.source_phase7i_lock,
        source_phase7d_attempt=gate.source_phase7d_attempt,
        payment_reference=payment_reference,
        payment_status_snapshot="current_or_unknown_review_only",
        target_order_reference=(
            target_order_reference or ""
        )[:120],
        target_order_match_type=(
            RazorpayPaymentOrderMutationReviewDryRun.TargetOrderMatchType.SYNTHETIC_REFERENCE_ONLY
        ),
        proposed_old_order_status="current_or_unknown_review_only",
        proposed_new_order_status="paid_review_candidate",
        proposed_old_payment_status="current_or_unknown_review_only",
        proposed_new_payment_status="captured_review_candidate",
        would_mutate_order=False,
        would_mutate_payment=False,
        would_notify_customer=False,
        would_send_whatsapp=False,
        would_call_courier=False,
        would_create_shipment=False,
        before_counts=before,
        after_counts=before,
        count_deltas={},
        passed=False,
        blockers=[],
        warnings=[PHASE_8B_WARNING],
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
            "phase8b_dry_run_business_row_count_changed",
        ]
    record.save()

    # Guard re-checks the locked-False contract + counts.
    try:
        assert_phase8b_no_business_mutation(
            gate, before_counts=before, dry_run=record
        )
    except ValueError as exc:  # pragma: no cover - defensive
        record.passed = False
        record.blockers = list(record.blockers or []) + [str(exc)]
        record.save()

    if passed and record.passed:
        gate.status = (
            RazorpayPaymentOrderMutationReviewGate.Status.DRY_RUN_PASSED
        )
        gate.dry_run_passed = True
        gate.synthetic_order_reference_snapshot = (
            target_order_reference or ""
        )[:120]
        gate.next_action = (
            "phase8b_gate_dry_run_passed_awaiting_rollback_dry_run_or_approve"
        )
        gate.save(
            update_fields=[
                "status",
                "dry_run_passed",
                "synthetic_order_reference_snapshot",
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
            f"Phase 8B dry-run "
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
                "dry_run_passed": bool(passed and record.passed),
            },
        ),
    )
    return {
        "phase": "8B",
        "ok": bool(passed and record.passed),
        "gate": serialize_phase8b_gate(gate),
        "dryRun": serialize_phase8b_dry_run(record),
        "blockers": list(record.blockers or []),
        "warnings": [PHASE_8B_WARNING],
        "nextAction": (
            "phase8b_gate_dry_run_passed_awaiting_rollback_dry_run_or_approve"
            if (passed and record.passed)
            else "fix_phase8b_dry_run_blockers"
        ),
    }


def rollback_dry_run_phase8b_payment_order_mutation_review_gate(
    dry_run_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Record-only rollback for a dry-run. NEVER calls a provider;
    NEVER mutates business rows; the dry-run never created business
    data so there is nothing to revert."""
    if not reason.strip():
        return {
            "phase": "8B",
            "ok": False,
            "dryRun": None,
            "blockers": [
                "phase8b_dry_run_rollback_reason_required"
            ],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "supply_reason",
        }
    record = (
        RazorpayPaymentOrderMutationReviewDryRun.objects.filter(
            pk=dry_run_id
        ).first()
    )
    if record is None:
        return {
            "phase": "8B",
            "ok": False,
            "dryRun": None,
            "blockers": ["phase8b_dry_run_not_found"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_dry_run_id",
        }
    record.rollback_recorded = True
    record.rolled_back_at = timezone.now()
    record.rollback_reason = (reason or "")[:1000]
    record.save(
        update_fields=[
            "rollback_recorded",
            "rolled_back_at",
            "rollback_reason",
        ]
    )
    # Mark the parent gate's rollback_dry_run_passed if this dry-run
    # had previously passed.
    if record.passed:
        gate = record.gate
        if not gate.rollback_dry_run_passed:
            gate.rollback_dry_run_passed = True
            gate.next_action = (
                "phase8b_gate_dry_run_passed_rollback_recorded_awaiting_approve"
            )
            gate.save(
                update_fields=[
                    "rollback_dry_run_passed",
                    "next_action",
                    "updated_at",
                ]
            )
    write_event(
        kind=AUDIT_KIND_ROLLBACK_RECORDED,
        text=(
            f"Phase 8B dry-run rollback recorded record_id="
            f"{record.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "gate_id": record.gate_id,
                "dry_run_id": record.pk,
                "reason_excerpt": (reason or "")[:120],
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    return {
        "phase": "8B",
        "ok": True,
        "dryRun": serialize_phase8b_dry_run(record),
        "blockers": [],
        "warnings": [PHASE_8B_WARNING],
        "nextAction": "phase8b_dry_run_rollback_recorded",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


def _gate_lookup(
    gate_id: int,
) -> Optional[RazorpayPaymentOrderMutationReviewGate]:
    return (
        RazorpayPaymentOrderMutationReviewGate.objects.filter(
            pk=gate_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def approve_phase8b_payment_order_mutation_review_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Flip status to
    ``approved_for_future_phase8c_controlled_mutation_review``. Non-
    empty reason + at least one passed dry-run + a recorded rollback
    dry-run required. Approval does NOT enable any mutation."""
    if not reason.strip():
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "blockers": ["phase8b_approve_reason_required"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "blockers": ["phase8b_gate_not_found"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if (
        gate.status
        != RazorpayPaymentOrderMutationReviewGate.Status.DRY_RUN_PASSED
    ):
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "blockers": [
                f"phase8b_gate_status_{gate.status}_not_transitionable_to_approved"
            ],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "run_phase8b_dry_run_first",
        }
    if not gate.dry_runs.filter(passed=True).exists():
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "blockers": ["phase8b_no_passed_dry_run_present"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "run_phase8b_dry_run_first",
        }
    rollback_recorded_dry_run_present = (
        gate.dry_runs.filter(
            passed=True, rollback_recorded=True
        ).exists()
    )
    if not (
        gate.rollback_dry_run_passed
        or rollback_recorded_dry_run_present
    ):
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "blockers": [
                "phase8b_no_rollback_dry_run_recorded"
            ],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "run_phase8b_rollback_dry_run_first",
        }

    before = _business_row_counts()
    assert_phase8b_no_business_mutation(
        gate, before_counts=before
    )

    gate.status = (
        RazorpayPaymentOrderMutationReviewGate.Status.APPROVED_FOR_FUTURE_PHASE8C_CONTROLLED_MUTATION_REVIEW
    )
    gate.rollback_dry_run_passed = True
    gate.approved_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.review_reason = (reason or "")[:1000]
    gate.next_action = (
        "phase8b_gate_approved_for_future_phase8c_controlled_mutation_review"
    )
    gate.save()

    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            "Phase 8B approved-for-future-phase8c gate_id="
            f"{gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8B",
        "ok": True,
        "gate": serialize_phase8b_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8B_WARNING],
        "nextAction": (
            "phase8b_gate_approved_for_future_phase8c_controlled_mutation_review"
        ),
    }


def reject_phase8b_payment_order_mutation_review_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "blockers": ["phase8b_reject_reason_required"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "blockers": ["phase8b_gate_not_found"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayPaymentOrderMutationReviewGate.Status.DRAFT,
        RazorpayPaymentOrderMutationReviewGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderMutationReviewGate.Status.DRY_RUN_PASSED,
        RazorpayPaymentOrderMutationReviewGate.Status.BLOCKED,
    }:
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "blockers": [
                f"phase8b_reject_refused_for_status_{gate.status}"
            ],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    assert_phase8b_no_business_mutation(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayPaymentOrderMutationReviewGate.Status.REJECTED
    )
    gate.rejected_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.reject_reason = (reason or "")[:1000]
    gate.next_action = "phase8b_gate_rejected"
    gate.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 8B rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8B",
        "ok": True,
        "gate": serialize_phase8b_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8B_WARNING],
        "nextAction": "phase8b_gate_rejected",
    }


def archive_phase8b_payment_order_mutation_review_gate(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "blockers": ["phase8b_archive_reason_required"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8B",
            "ok": False,
            "gate": None,
            "blockers": ["phase8b_gate_not_found"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status == (
        RazorpayPaymentOrderMutationReviewGate.Status.ARCHIVED
    ):
        return {
            "phase": "8B",
            "ok": False,
            "gate": serialize_phase8b_gate(gate),
            "blockers": ["phase8b_gate_already_archived"],
            "warnings": [PHASE_8B_WARNING],
            "nextAction": "verify_gate_status",
        }
    before = _business_row_counts()
    assert_phase8b_no_business_mutation(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayPaymentOrderMutationReviewGate.Status.ARCHIVED
    )
    gate.archived_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.archive_reason = (reason or "")[:1000]
    gate.next_action = "phase8b_gate_archived"
    gate.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 8B archived gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8B",
        "ok": True,
        "gate": serialize_phase8b_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8B_WARNING],
        "nextAction": "phase8b_gate_archived",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase8b_gates(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayPaymentOrderMutationReviewGate.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value
        for s in RazorpayPaymentOrderMutationReviewGate.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase8b_gate(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "8B", "counts": counts, "items": items}


def inspect_phase8b_payment_order_mutation_review_readiness() -> (
    dict[str, Any]
):
    summary = summarize_phase8b_gates(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    eligible_phase8a_gates = (
        RazorpayPaymentOrderMutationSandboxGate.objects.filter(
            status=RazorpayPaymentOrderMutationSandboxGate.Status.APPROVED_FOR_FUTURE_PHASE8B_REVIEW,
            real_business_mutation_allowed=False,
            real_order_mutation_allowed=False,
            real_payment_mutation_allowed=False,
            customer_notification_allowed=False,
            whatsapp_allowed=False,
            courier_allowed=False,
        ).count()
    )

    blockers: list[str] = []
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if _flag_phase8c_approved():
        blockers.append("phase8c_must_remain_not_approved")
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")

    if blockers:
        next_action = "fix_phase8b_safety_blockers"
    elif not _flag_phase8b_enabled():
        next_action = (
            "enable_phase8b_payment_order_mutation_review_gate_flag"
        )
    elif eligible_phase8a_gates == 0:
        next_action = "no_eligible_phase8a_gate_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase8b_gates_pending_manual_review"
    elif counts.get("dry_run_passed", 0) > 0:
        next_action = (
            "phase8b_gates_dry_run_passed_awaiting_rollback_or_approve"
        )
    elif (
        counts.get(
            "approved_for_future_phase8c_controlled_mutation_review",
            0,
        )
        > 0
    ):
        next_action = (
            "phase8b_gates_approved_for_future_phase8c_controlled_mutation_review"
        )
    else:
        next_action = (
            "ready_to_prepare_phase8b_payment_order_mutation_review_gate"
        )

    return {
        "phase": "8B",
        "status": "payment_order_mutation_review_gate_only",
        "latestCompletedPhase": "8A",
        "nextPhase": (
            "phase8c_planning_or_real_mutation_not_approved"
        ),
        "phase8BPaymentOrderMutationReviewGateEnabled": (
            _flag_phase8b_enabled()
        ),
        "killSwitch": kill,
        "eligiblePhase8AGateCount": eligible_phase8a_gates,
        "phase8BGateCounts": counts,
        "items": summary["items"],
        "phase8BCallsRazorpay": False,
        "phase8BCallsMetaCloud": False,
        "phase8BCallsDelhivery": False,
        "phase8BCallsVapi": False,
        "phase8BSendsWhatsApp": False,
        "phase8BQueuesWhatsApp": False,
        "phase8BCreatesShipmentRow": False,
        "phase8BCreatesAwb": False,
        "phase8BCreatesPaymentLink": False,
        "phase8BCapturesPayment": False,
        "phase8BRefundsPayment": False,
        "phase8BSendsCustomerNotification": False,
        "phase8BMutatesBusinessRow": False,
        "phase8BMutatesRealOrder": False,
        "phase8BMutatesRealPayment": False,
        "phase8BApprovesPhase8C": False,
        "phase8BApprovesRealCustomerAutomation": False,
        "phase8CApproved": False,
        "phase7ELiveBApproved": False,
        "phase7GLiveApproved": False,
        "executionPath": "review_dry_run_only_cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_8B_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_8B_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text=(
            "Phase 8B payment-order mutation review readiness "
            "inspected"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase8a_gate_count": int(
                    report.get("eligiblePhase8AGateCount") or 0
                ),
                "phase8b_enabled": bool(
                    report.get(
                        "phase8BPaymentOrderMutationReviewGateEnabled"
                    )
                ),
                "gate_counts": report.get("phase8BGateCounts") or {},
                "next_action": report.get("nextAction") or "",
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
