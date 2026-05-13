"""Phase 8D - Phase 8C Controlled Mutation Evidence Lock.

Phase 8D is a **lock-only meta-audit** over the completed Phase 8C
controlled mutation chain (Phase 8B → 8A → 7I → 7D + Phase 8C gate /
attempt / rollback). It snapshots every field that matters for
evidence into a single immutable ``RazorpayPaymentOrderControlled
MutationEvidenceLock`` row.

Phase 8D NEVER executes Phase 8C again, NEVER rolls back Phase 8C
again, NEVER mutates real ``Order`` / ``Payment`` / ``Customer`` /
``Lead`` / ``Shipment`` / ``DiscountOfferLog`` rows, NEVER calls
Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends or queues
WhatsApp, NEVER creates a ``Shipment`` / AWB / payment link, NEVER
captures / refunds, NEVER sends a customer notification, NEVER
edits any ``.env*`` file.

Public surface:

- :func:`inspect_phase8d_controlled_mutation_evidence_lock_readiness`
- :func:`preview_phase8d_controlled_mutation_evidence_lock`
- :func:`prepare_phase8d_controlled_mutation_evidence_lock`
- :func:`lock_phase8d_controlled_mutation_evidence_lock`
- :func:`reject_phase8d_controlled_mutation_evidence_lock`
- :func:`archive_phase8d_controlled_mutation_evidence_lock`
- :func:`assert_phase8d_no_provider_or_business_mutation`
- :func:`serialize_phase8d_lock`
- :func:`summarize_phase8d_locks`
"""
from __future__ import annotations

from typing import Any, Optional

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
    RazorpayPaymentOrderControlledMutationAttempt,
    RazorpayPaymentOrderControlledMutationEvidenceLock,
    RazorpayPaymentOrderControlledMutationGate,
    RazorpayPaymentOrderControlledMutationRollback,
    RazorpayPaymentOrderMutationReviewGate,
    RazorpayPaymentOrderMutationSandboxGate,
    RazorpayPhase7FinalAuditLock,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_8D_WARNING = (
    "Phase 8D is the Phase 8C Controlled Mutation Evidence Lock. "
    "It is a lock-only meta-audit over the completed Phase 8C "
    "executed + rolled_back chain. Phase 8D NEVER executes Phase "
    "8C again, NEVER rolls back Phase 8C again, NEVER calls "
    "Razorpay / Meta Cloud / Delhivery / Vapi, NEVER sends or "
    "queues WhatsApp, NEVER creates a Shipment / AWB / payment "
    "link, NEVER captures / refunds, NEVER sends a customer "
    "notification, NEVER mutates real Order / Payment / Customer "
    "/ Lead / Shipment / DiscountOfferLog / WhatsAppMessage rows, "
    "NEVER edits any .env file. Phase 7E-Live-B (real customer "
    "WhatsApp send) and Phase 7G-Live (real customer courier "
    "execution) remain NOT approved; real-customer automation "
    "remains NOT approved."
)


AUDIT_KIND_READINESS = "phase8d.evidence.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase8d.evidence.previewed"
AUDIT_KIND_PREPARED = "phase8d.evidence.prepared"
AUDIT_KIND_LOCKED = "phase8d.evidence.locked"
AUDIT_KIND_REJECTED = "phase8d.evidence.rejected"
AUDIT_KIND_ARCHIVED = "phase8d.evidence.archived"
AUDIT_KIND_BLOCKED = "phase8d.evidence.blocked"


PHASE_8D_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "execute_phase8c_again",
    "rollback_phase8c_again",
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
    "mutate_real_customer",
    "mutate_real_lead",
    "mutate_real_shipment",
    "mutate_real_discount_offer_log",
    "approve_real_customer_automation",
    "approve_phase7e_live_b",
    "approve_phase7g_live",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "lock_via_api_endpoint",
    "archive_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_8D_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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
    "director_signoff_text",
)


# Locked-False contract booleans on the lock row.
_LOCK_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "phase8d_calls_razorpay_snapshot",
    "phase8d_calls_meta_cloud_snapshot",
    "phase8d_calls_delhivery_snapshot",
    "phase8d_sends_whatsapp_snapshot",
    "phase8d_sends_customer_notification_snapshot",
    "phase8d_creates_shipment_snapshot",
    "phase8d_captures_payment_snapshot",
    "phase8d_refunds_payment_snapshot",
)


_ALLOWED_FINAL_ORDER_PAYMENT_STATUS = "Pending"
_ALLOWED_FINAL_PAYMENT_STATUS = "Pending"


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


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
    safe: dict[str, Any] = {"phase": "8D"}
    forbidden = set(PHASE_8D_FORBIDDEN_PAYLOAD_KEYS)
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
# Defensive invariant guard
# ---------------------------------------------------------------------------


def assert_phase8d_no_provider_or_business_mutation(
    lock: RazorpayPaymentOrderControlledMutationEvidenceLock,
    *,
    before_counts: dict[str, int],
) -> None:
    """Raises ``ValueError`` (and writes an invariant audit row) if
    any locked-False boolean flipped True on the lock row or if any
    protected business-row count drifted."""
    flipped: list[str] = []
    for field in _LOCK_LOCKED_FALSE_FIELDS:
        if getattr(lock, field, False):
            flipped.append(f"lock.{field}_must_stay_false")
    after = _business_row_counts()
    delta_keys: list[str] = []
    for key, count_before in before_counts.items():
        if after.get(key, count_before) != count_before:
            delta_keys.append(key)
    if not flipped and not delta_keys:
        return
    payload = _safe_audit_payload(
        {
            "lock_id": lock.pk,
            "flipped_locked_false_fields": flipped,
            "business_row_delta_keys": delta_keys,
            "kill_switch_state_at_emit": _kill_switch_state(),
        }
    )
    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=(
            "Phase 8D invariant violation: locked-False or business "
            "row count drift detected; refusing the operation."
        ),
        tone=AuditEvent.Tone.DANGER,
        payload=payload,
    )
    raise ValueError(
        "Phase 8D invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_phase8c_gate(
    gate: Optional[RazorpayPaymentOrderControlledMutationGate],
) -> list[str]:
    blockers: list[str] = []
    if gate is None:
        blockers.append("phase8d_source_phase8c_gate_not_found")
        return blockers
    if (
        gate.status
        != RazorpayPaymentOrderControlledMutationGate.Status.ROLLED_BACK
    ):
        blockers.append(
            "phase8d_source_phase8c_gate_status_must_be_rolled_back_was_"
            f"{gate.status}"
        )
    if not bool(gate.dry_run_passed):
        blockers.append(
            "phase8d_source_phase8c_dry_run_passed_must_be_true"
        )
    return blockers


def _validate_phase8c_attempt(
    attempt: Optional[RazorpayPaymentOrderControlledMutationAttempt],
) -> list[str]:
    blockers: list[str] = []
    if attempt is None:
        blockers.append("phase8d_source_phase8c_attempt_not_found")
        return blockers
    # Phase 8D-Hotfix-1: we deliberately do NOT check
    # `attempt.status == ROLLED_BACK`. A later blocked re-run may
    # have flipped attempt.status="blocked" AFTER execute+rollback
    # had already completed; the executed_at + rollback_recorded
    # evidence is still the real proof. The evidence checks below
    # (executed_at, recorded_signoff_window_valid, mutation flags
    # True, side-effect flags False) are what must hold.
    if attempt.executed_at is None:
        blockers.append(
            "phase8d_source_phase8c_attempt_executed_at_must_be_set"
        )
    if not bool(attempt.recorded_signoff_window_valid):
        blockers.append(
            "phase8d_source_phase8c_attempt_recorded_signoff_window_valid_must_be_true"
        )
    if not bool(attempt.order_mutation_was_made):
        blockers.append(
            "phase8d_source_phase8c_attempt_order_mutation_was_made_must_be_true"
        )
    if not bool(attempt.payment_mutation_was_made):
        blockers.append(
            "phase8d_source_phase8c_attempt_payment_mutation_was_made_must_be_true"
        )
    if not bool(attempt.business_mutation_was_made):
        blockers.append(
            "phase8d_source_phase8c_attempt_business_mutation_was_made_must_be_true"
        )
    # Provider / send / courier / customer-notification booleans
    # MUST still be False -- if Phase 8C accidentally flipped any
    # of them, Phase 8D refuses to lock.
    for field in (
        "customer_notification_sent",
        "whatsapp_sent",
        "courier_called",
        "provider_call_attempted",
        "shipment_created",
    ):
        if getattr(attempt, field, False):
            blockers.append(
                f"phase8d_source_phase8c_attempt_{field}_must_stay_false"
            )
    return blockers


def _resolve_phase8c_evidence_via_rollback(
    phase8c_gate: Optional[RazorpayPaymentOrderControlledMutationGate],
) -> tuple[
    Optional[RazorpayPaymentOrderControlledMutationAttempt],
    Optional[RazorpayPaymentOrderControlledMutationRollback],
]:
    """Phase 8D-Hotfix-1: resolve the Phase 8C source attempt via
    the rollback record, not via ``attempt.status``.

    A later blocked re-run may have flipped ``attempt.status="blocked"``
    AFTER execute + rollback had already completed; the rollback
    record is the strongest single source of truth for "Phase 8C
    executed and rolled back". We pick the rollback record with
    ``status=rollback_recorded``, ``rollback_was_made=True``, and
    ``restored_order_status="Pending"``/``restored_payment_status="Pending"``,
    then return ``rollback.attempt`` -- ignoring whatever the
    current attempt.status happens to be.
    """
    if phase8c_gate is None:
        return None, None
    rollback = (
        RazorpayPaymentOrderControlledMutationRollback.objects.filter(
            attempt__gate=phase8c_gate,
            status=(
                RazorpayPaymentOrderControlledMutationRollback.Status.ROLLBACK_RECORDED
            ),
            rollback_was_made=True,
            restored_order_status=_ALLOWED_FINAL_ORDER_PAYMENT_STATUS,
            restored_payment_status=_ALLOWED_FINAL_PAYMENT_STATUS,
        )
        .select_related("attempt")
        .order_by("-rolled_back_at", "-created_at")
        .first()
    )
    if rollback is None:
        return None, None
    return rollback.attempt, rollback


def _validate_phase8c_rollback_record(
    rollback: Optional[
        RazorpayPaymentOrderControlledMutationRollback
    ],
) -> list[str]:
    """Validate a rollback record found via
    :func:`_resolve_phase8c_evidence_via_rollback`. The resolver
    already pre-filters on ``status=rollback_recorded`` /
    ``rollback_was_made=True`` / ``restored_*=Pending``, so a
    missing rollback here means **no rollback record exists that
    satisfies the Phase 8D evidence contract** -- which is the
    primary diagnostic. The defensive recheck below catches any
    drift between the resolver filter and the field-level
    semantics (e.g. if the resolver is loosened in the future)."""
    blockers: list[str] = []
    if rollback is None:
        blockers.append(
            "phase8d_source_phase8c_rollback_not_recorded"
        )
        return blockers
    if (
        rollback.status
        != RazorpayPaymentOrderControlledMutationRollback.Status.ROLLBACK_RECORDED
    ):
        blockers.append(
            "phase8d_source_phase8c_rollback_status_must_be_rollback_recorded_was_"
            f"{rollback.status}"
        )
    if not bool(rollback.rollback_was_made):
        blockers.append(
            "phase8d_source_phase8c_rollback_was_made_must_be_true"
        )
    if (
        rollback.restored_order_status
        != _ALLOWED_FINAL_ORDER_PAYMENT_STATUS
    ):
        blockers.append(
            "phase8d_source_phase8c_rollback_restored_order_status_must_be_pending_was_"
            f"{rollback.restored_order_status}"
        )
    if (
        rollback.restored_payment_status
        != _ALLOWED_FINAL_PAYMENT_STATUS
    ):
        blockers.append(
            "phase8d_source_phase8c_rollback_restored_payment_status_must_be_pending_was_"
            f"{rollback.restored_payment_status}"
        )
    for field in (
        "customer_notification_sent",
        "whatsapp_sent",
        "courier_called",
        "provider_call_attempted",
    ):
        if getattr(rollback, field, False):
            blockers.append(
                f"phase8d_source_phase8c_rollback_{field}_must_stay_false"
            )
    return blockers


# Backwards-compatible alias for any callers that still import the
# old name. The old name took (attempt) and returned (blockers,
# rollback) -- which is no longer the right shape now that the
# rollback is the source of truth. We keep the alias as a no-op
# wrapper around the new resolver+validator so external callers
# (if any) keep working.
def _validate_phase8c_rollback(
    attempt: Optional[RazorpayPaymentOrderControlledMutationAttempt],
) -> tuple[
    list[str],
    Optional[RazorpayPaymentOrderControlledMutationRollback],
]:
    if attempt is None:
        return [], None
    _, rollback = _resolve_phase8c_evidence_via_rollback(
        attempt.gate
    )
    return _validate_phase8c_rollback_record(rollback), rollback


def _validate_final_target_state(
    attempt: Optional[RazorpayPaymentOrderControlledMutationAttempt],
) -> tuple[list[str], Optional[Order], Optional[Payment]]:
    blockers: list[str] = []
    if attempt is None:
        return blockers, None, None
    target_order = Order.objects.filter(
        pk=attempt.target_order_id
    ).first()
    target_payment = Payment.objects.filter(
        pk=attempt.target_payment_id
    ).first()
    if target_order is None:
        blockers.append("phase8d_target_order_not_found")
    elif (
        target_order.payment_status
        != _ALLOWED_FINAL_ORDER_PAYMENT_STATUS
    ):
        blockers.append(
            "phase8d_target_order_final_payment_status_must_be_pending_was_"
            f"{target_order.payment_status}"
        )
    if target_payment is None:
        blockers.append("phase8d_target_payment_not_found")
    elif target_payment.status != _ALLOWED_FINAL_PAYMENT_STATUS:
        blockers.append(
            "phase8d_target_payment_final_status_must_be_pending_was_"
            f"{target_payment.status}"
        )
    # Phase 8D-Hotfix-1: confirm the target Payment still carries
    # the explicit sandbox marker in raw_response (the same proof
    # Phase 8C's safety guard relies on at execute / rollback time).
    if target_payment is not None:
        raw = target_payment.raw_response or {}
        if (
            not isinstance(raw, dict)
            or raw.get("phase8c_sandbox") is not True
        ):
            blockers.append(
                "phase8d_target_payment_raw_response_phase8c_sandbox_must_be_true"
            )
    return blockers, target_order, target_payment


def _validate_eligibility(
    *,
    phase8c_gate_id: Optional[int],
) -> dict[str, Any]:
    blockers: list[str] = []
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    phase8c_gate: Optional[
        RazorpayPaymentOrderControlledMutationGate
    ] = None
    if phase8c_gate_id:
        phase8c_gate = (
            RazorpayPaymentOrderControlledMutationGate.objects.filter(
                pk=phase8c_gate_id
            )
            .select_related(
                "source_phase8b_gate",
                "source_phase8a_gate",
                "source_phase7i_lock",
                "source_phase7d_attempt",
            )
            .first()
        )
    blockers += _validate_phase8c_gate(phase8c_gate)

    # Phase 8D-Hotfix-1: resolve the Phase 8C attempt via the
    # rollback record, not via attempt.status. The rollback record
    # is the strongest single source of truth for "Phase 8C
    # executed and rolled back" -- a later blocked re-run may have
    # flipped attempt.status="blocked" but the execute + rollback
    # evidence is still valid.
    phase8c_attempt, rollback = (
        _resolve_phase8c_evidence_via_rollback(phase8c_gate)
    )
    blockers += _validate_phase8c_attempt(phase8c_attempt)
    blockers += _validate_phase8c_rollback_record(rollback)

    final_blockers, target_order, target_payment = (
        _validate_final_target_state(phase8c_attempt)
    )
    blockers += final_blockers

    return {
        "phase8c_gate": phase8c_gate,
        "phase8c_attempt": phase8c_attempt,
        "phase8c_rollback": rollback,
        "phase8b_gate": (
            phase8c_gate.source_phase8b_gate
            if phase8c_gate is not None
            else None
        ),
        "phase8a_gate": (
            phase8c_gate.source_phase8a_gate
            if phase8c_gate is not None
            else None
        ),
        "phase7i_lock": (
            phase8c_gate.source_phase7i_lock
            if phase8c_gate is not None
            else None
        ),
        "phase7d": (
            phase8c_gate.source_phase7d_attempt
            if phase8c_gate is not None
            else None
        ),
        "target_order": target_order,
        "target_payment": target_payment,
        "blockers": blockers,
        "eligible": not blockers,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_phase8d_lock(
    row: RazorpayPaymentOrderControlledMutationEvidenceLock,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase8CGateId": row.source_phase8c_gate_id,
        "sourcePhase8CAttemptId": row.source_phase8c_attempt_id,
        "sourcePhase8BGateId": row.source_phase8b_gate_id,
        "sourcePhase8AGateId": row.source_phase8a_gate_id,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "phase8CGateStatusSnapshot": (
            row.phase8c_gate_status_snapshot
        ),
        "phase8CAttemptStatusSnapshot": (
            row.phase8c_attempt_status_snapshot
        ),
        "phase8CAttemptExecutedAtSnapshot": (
            row.phase8c_attempt_executed_at_snapshot.isoformat()
            if row.phase8c_attempt_executed_at_snapshot
            else None
        ),
        "recordedSignoffWindowValidSnapshot": bool(
            row.recorded_signoff_window_valid_snapshot
        ),
        "targetOrderIdSnapshot": row.target_order_id_snapshot,
        "targetPaymentIdSnapshot": row.target_payment_id_snapshot,
        "targetOrderReferenceSnapshot": (
            row.target_order_reference_snapshot
        ),
        "targetPaymentReferenceSnapshot": (
            row.target_payment_reference_snapshot
        ),
        "oldOrderStatusSnapshot": row.old_order_status_snapshot,
        "executedOrderStatusSnapshot": (
            row.executed_order_status_snapshot
        ),
        "finalOrderStatusSnapshot": row.final_order_status_snapshot,
        "oldPaymentStatusSnapshot": row.old_payment_status_snapshot,
        "executedPaymentStatusSnapshot": (
            row.executed_payment_status_snapshot
        ),
        "finalPaymentStatusSnapshot": (
            row.final_payment_status_snapshot
        ),
        "orderMutationWasMadeSnapshot": bool(
            row.order_mutation_was_made_snapshot
        ),
        "paymentMutationWasMadeSnapshot": bool(
            row.payment_mutation_was_made_snapshot
        ),
        "businessMutationWasMadeSnapshot": bool(
            row.business_mutation_was_made_snapshot
        ),
        "rollbackCompletedSnapshot": bool(
            row.rollback_completed_snapshot
        ),
        "finalDbRestoredSnapshot": bool(
            row.final_db_restored_snapshot
        ),
        "phase8DCallsRazorpaySnapshot": bool(
            row.phase8d_calls_razorpay_snapshot
        ),
        "phase8DCallsMetaCloudSnapshot": bool(
            row.phase8d_calls_meta_cloud_snapshot
        ),
        "phase8DCallsDelhiverySnapshot": bool(
            row.phase8d_calls_delhivery_snapshot
        ),
        "phase8DSendsWhatsAppSnapshot": bool(
            row.phase8d_sends_whatsapp_snapshot
        ),
        "phase8DSendsCustomerNotificationSnapshot": bool(
            row.phase8d_sends_customer_notification_snapshot
        ),
        "phase8DCreatesShipmentSnapshot": bool(
            row.phase8d_creates_shipment_snapshot
        ),
        "phase8DCapturesPaymentSnapshot": bool(
            row.phase8d_captures_payment_snapshot
        ),
        "phase8DRefundsPaymentSnapshot": bool(
            row.phase8d_refunds_payment_snapshot
        ),
        "beforeCountsSnapshot": row.before_counts_snapshot or {},
        "afterExecuteCountsSnapshot": (
            row.after_execute_counts_snapshot or {}
        ),
        "afterRollbackCountsSnapshot": (
            row.after_rollback_counts_snapshot or {}
        ),
        "countDeltasSnapshot": row.count_deltas_snapshot or {},
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action or "",
        "evidenceJson": row.evidence_json or {},
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
        "lockedAt": (
            row.locked_at.isoformat() if row.locked_at else None
        ),
        "rejectedAt": (
            row.rejected_at.isoformat() if row.rejected_at else None
        ),
        "archivedAt": (
            row.archived_at.isoformat() if row.archived_at else None
        ),
    }


def _audit_lock_payload(
    lock: RazorpayPaymentOrderControlledMutationEvidenceLock,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lock_id": lock.pk,
        "status": lock.status,
        "phase8c_gate_id": lock.source_phase8c_gate_id,
        "phase8c_attempt_id": lock.source_phase8c_attempt_id,
        "phase8b_gate_id": lock.source_phase8b_gate_id,
        "phase8a_gate_id": lock.source_phase8a_gate_id,
        "phase7i_lock_id": lock.source_phase7i_lock_id,
        "phase7d_attempt_id": lock.source_phase7d_attempt_id,
        "phase8d_calls_razorpay": False,
        "phase8d_calls_meta_cloud": False,
        "phase8d_calls_delhivery": False,
        "phase8d_sends_whatsapp": False,
        "phase8d_sends_customer_notification": False,
        "phase8d_creates_shipment": False,
        "phase8d_captures_payment": False,
        "phase8d_refunds_payment": False,
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
    phase8c_gate = eligibility["phase8c_gate"]
    phase8c_attempt = eligibility["phase8c_attempt"]
    phase8c_rollback = eligibility["phase8c_rollback"]
    phase8b_gate = eligibility["phase8b_gate"]
    phase8a_gate = eligibility["phase8a_gate"]
    phase7i_lock = eligibility["phase7i_lock"]
    phase7d = eligibility["phase7d"]
    target_order = eligibility["target_order"]
    target_payment = eligibility["target_payment"]
    final_db_restored = bool(
        target_order is not None
        and target_payment is not None
        and target_order.payment_status
        == _ALLOWED_FINAL_ORDER_PAYMENT_STATUS
        and target_payment.status == _ALLOWED_FINAL_PAYMENT_STATUS
    )
    # Phase 8D-Hotfix-1: normalized top-level evidence keys. These
    # are the canonical signals downstream readers should consume
    # instead of inspecting nested fields.
    execution_evidence_valid = bool(
        phase8c_attempt is not None
        and phase8c_attempt.executed_at is not None
        and phase8c_attempt.recorded_signoff_window_valid
        and phase8c_attempt.order_mutation_was_made
        and phase8c_attempt.payment_mutation_was_made
        and phase8c_attempt.business_mutation_was_made
        and not phase8c_attempt.provider_call_attempted
        and not phase8c_attempt.customer_notification_sent
        and not phase8c_attempt.whatsapp_sent
        and not phase8c_attempt.courier_called
        and not phase8c_attempt.shipment_created
    )
    rollback_evidence_valid = bool(
        phase8c_rollback is not None
        and phase8c_rollback.rollback_was_made
        and phase8c_rollback.status
        == RazorpayPaymentOrderControlledMutationRollback.Status.ROLLBACK_RECORDED
        and phase8c_rollback.restored_order_status
        == _ALLOWED_FINAL_ORDER_PAYMENT_STATUS
        and phase8c_rollback.restored_payment_status
        == _ALLOWED_FINAL_PAYMENT_STATUS
        and not phase8c_rollback.provider_call_attempted
        and not phase8c_rollback.customer_notification_sent
        and not phase8c_rollback.whatsapp_sent
        and not phase8c_rollback.courier_called
    )
    return {
        "phase": "8D",
        # Phase 8D-Hotfix-1 normalized fields:
        "executionEvidenceValid": execution_evidence_valid,
        "rollbackEvidenceValid": rollback_evidence_valid,
        "attemptStatusAtEvidenceLock": (
            phase8c_attempt.status if phase8c_attempt is not None else ""
        ),
        "rollbackStatus": (
            phase8c_rollback.status
            if phase8c_rollback is not None
            else ""
        ),
        "finalDbRestored": final_db_restored,
        "phase8c": {
            "gateId": phase8c_gate.pk,
            "gateStatus": phase8c_gate.status,
            "attemptId": phase8c_attempt.pk,
            "attemptStatus": phase8c_attempt.status,
            "executedAt": (
                phase8c_attempt.executed_at.isoformat()
                if phase8c_attempt.executed_at
                else None
            ),
            "recordedSignoffWindowValid": bool(
                phase8c_attempt.recorded_signoff_window_valid
            ),
            "orderMutationWasMade": True,
            "paymentMutationWasMade": True,
            "businessMutationWasMade": True,
            "rollbackId": (
                phase8c_rollback.pk
                if phase8c_rollback is not None
                else None
            ),
            "rollbackStatus": (
                phase8c_rollback.status
                if phase8c_rollback is not None
                else None
            ),
            "rollbackWasMade": (
                bool(phase8c_rollback.rollback_was_made)
                if phase8c_rollback is not None
                else False
            ),
        },
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
        "target": {
            "orderId": (
                target_order.id if target_order is not None else ""
            ),
            "paymentId": (
                target_payment.id
                if target_payment is not None
                else ""
            ),
            "orderReference": (
                phase8c_attempt.target_order_reference
                if phase8c_attempt is not None
                else ""
            ),
            "paymentReference": (
                phase8c_attempt.target_payment_reference
                if phase8c_attempt is not None
                else ""
            ),
        },
        "statusTimeline": {
            "order": [
                phase8c_attempt.old_order_status,
                phase8c_attempt.new_order_status,
                (
                    target_order.payment_status
                    if target_order is not None
                    else ""
                ),
            ],
            "payment": [
                phase8c_attempt.old_payment_status,
                phase8c_attempt.new_payment_status,
                (
                    target_payment.status
                    if target_payment is not None
                    else ""
                ),
            ],
        },
        "evidenceContract": {
            "lockOnly": True,
            "phase8DCallsRazorpay": False,
            "phase8DCallsMetaCloud": False,
            "phase8DCallsDelhivery": False,
            "phase8DSendsWhatsApp": False,
            "phase8DSendsCustomerNotification": False,
            "phase8DCreatesShipment": False,
            "phase8DCapturesPayment": False,
            "phase8DRefundsPayment": False,
            "phase8DExecutesPhase8CAgain": False,
            "phase8DRollsBackPhase8CAgain": False,
        },
    }


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _snapshot_counts_for_lock(
    *,
    phase8c_attempt: RazorpayPaymentOrderControlledMutationAttempt,
    phase8c_rollback: Optional[
        RazorpayPaymentOrderControlledMutationRollback
    ],
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, int],
    dict[str, int],
]:
    before_counts = dict(phase8c_attempt.before_counts or {})
    after_execute_counts = dict(phase8c_attempt.after_counts or {})
    after_rollback_counts = (
        dict(phase8c_rollback.after_counts or {})
        if phase8c_rollback is not None
        else dict(after_execute_counts)
    )
    deltas: dict[str, int] = {}
    for key, count_before in before_counts.items():
        final = after_rollback_counts.get(key, count_before)
        if final != count_before:
            deltas[key] = final - count_before
    return (
        before_counts,
        after_execute_counts,
        after_rollback_counts,
        deltas,
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase8d_controlled_mutation_evidence_lock(
    phase8c_gate_id: int,
) -> dict[str, Any]:
    eligibility = _validate_eligibility(
        phase8c_gate_id=phase8c_gate_id
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 8D preview phase8c_gate_id={phase8c_gate_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase8c_gate_id": phase8c_gate_id,
                "eligible": eligibility["eligible"],
                "blockers": list(eligibility["blockers"]),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    evidence: dict[str, Any] = {}
    if (
        eligibility["eligible"]
        and eligibility["phase8c_attempt"] is not None
    ):
        evidence = _build_evidence_json(eligibility=eligibility)
    return {
        "phase": "8D",
        "found": eligibility["phase8c_gate"] is not None,
        "sourcePhase8CGateId": phase8c_gate_id,
        "sourcePhase8CAttemptId": (
            eligibility["phase8c_attempt"].pk
            if eligibility["phase8c_attempt"]
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
        "sourcePhase7DAttemptId": (
            eligibility["phase7d"].pk
            if eligibility["phase7d"]
            else None
        ),
        "eligible": eligibility["eligible"],
        "blockers": list(eligibility["blockers"]),
        "warnings": [PHASE_8D_WARNING],
        "evidence": evidence,
        "nextAction": (
            "ready_to_prepare_phase8d_controlled_mutation_evidence_lock"
            if eligibility["eligible"]
            else "fix_phase8d_eligibility_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase8d_controlled_mutation_evidence_lock(
    phase8c_gate_id: int,
) -> dict[str, Any]:
    """Atomic + idempotent prepare on the source Phase 8C gate.
    NEVER mutates business rows; NEVER calls any provider."""
    eligibility = _validate_eligibility(
        phase8c_gate_id=phase8c_gate_id
    )
    if (
        not eligibility["eligible"]
        or eligibility["phase8c_gate"] is None
        or eligibility["phase8c_attempt"] is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8D prepare blocked phase8c_gate_id="
                f"{phase8c_gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase8c_gate_id": phase8c_gate_id,
                    "blockers": list(eligibility["blockers"]),
                    "kill_switch_state_at_emit": _kill_switch_state(),
                }
            ),
        )
        return {
            "phase": "8D",
            "created": False,
            "reused": False,
            "lock": None,
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "fix_phase8d_eligibility_blockers",
        }

    phase8c_gate = eligibility["phase8c_gate"]
    phase8c_attempt = eligibility["phase8c_attempt"]
    phase8c_rollback = eligibility["phase8c_rollback"]
    target_order = eligibility["target_order"]
    target_payment = eligibility["target_payment"]
    before = _business_row_counts()

    (
        before_counts_snapshot,
        after_execute_counts_snapshot,
        after_rollback_counts_snapshot,
        count_deltas_snapshot,
    ) = _snapshot_counts_for_lock(
        phase8c_attempt=phase8c_attempt,
        phase8c_rollback=phase8c_rollback,
    )

    with transaction.atomic():
        existing = (
            RazorpayPaymentOrderControlledMutationEvidenceLock.objects.filter(
                source_phase8c_gate=phase8c_gate
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "8D",
                "created": False,
                "reused": True,
                "lock": serialize_phase8d_lock(existing),
                "blockers": [],
                "warnings": [PHASE_8D_WARNING],
                "nextAction": (
                    "phase8d_lock_pending_manual_review"
                    if existing.status
                    == RazorpayPaymentOrderControlledMutationEvidenceLock.Status.PENDING_MANUAL_REVIEW
                    else f"phase8d_lock_status_{existing.status}"
                ),
            }

        lock = RazorpayPaymentOrderControlledMutationEvidenceLock(
            source_phase8c_gate=phase8c_gate,
            source_phase8c_attempt=phase8c_attempt,
            source_phase8b_gate=eligibility["phase8b_gate"],
            source_phase8a_gate=eligibility["phase8a_gate"],
            source_phase7i_lock=eligibility["phase7i_lock"],
            source_phase7d_attempt=eligibility["phase7d"],
            status=(
                RazorpayPaymentOrderControlledMutationEvidenceLock.Status.PENDING_MANUAL_REVIEW
            ),
            phase8c_gate_status_snapshot=phase8c_gate.status,
            phase8c_attempt_status_snapshot=phase8c_attempt.status,
            phase8c_attempt_executed_at_snapshot=(
                phase8c_attempt.executed_at
            ),
            recorded_signoff_window_valid_snapshot=bool(
                phase8c_attempt.recorded_signoff_window_valid
            ),
            target_order_id_snapshot=phase8c_attempt.target_order_id,
            target_payment_id_snapshot=(
                phase8c_attempt.target_payment_id
            ),
            target_order_reference_snapshot=(
                phase8c_attempt.target_order_reference
            ),
            target_payment_reference_snapshot=(
                phase8c_attempt.target_payment_reference
            ),
            old_order_status_snapshot=(
                phase8c_attempt.old_order_status
            ),
            executed_order_status_snapshot=(
                phase8c_attempt.new_order_status
            ),
            final_order_status_snapshot=(
                target_order.payment_status
                if target_order is not None
                else ""
            ),
            old_payment_status_snapshot=(
                phase8c_attempt.old_payment_status
            ),
            executed_payment_status_snapshot=(
                phase8c_attempt.new_payment_status
            ),
            final_payment_status_snapshot=(
                target_payment.status
                if target_payment is not None
                else ""
            ),
            order_mutation_was_made_snapshot=True,
            payment_mutation_was_made_snapshot=True,
            business_mutation_was_made_snapshot=True,
            rollback_completed_snapshot=(
                phase8c_rollback is not None
                and bool(phase8c_rollback.rollback_was_made)
            ),
            final_db_restored_snapshot=(
                target_order is not None
                and target_payment is not None
                and target_order.payment_status
                == phase8c_attempt.old_order_status
                and target_payment.status
                == phase8c_attempt.old_payment_status
            ),
            phase8d_calls_razorpay_snapshot=False,
            phase8d_calls_meta_cloud_snapshot=False,
            phase8d_calls_delhivery_snapshot=False,
            phase8d_sends_whatsapp_snapshot=False,
            phase8d_sends_customer_notification_snapshot=False,
            phase8d_creates_shipment_snapshot=False,
            phase8d_captures_payment_snapshot=False,
            phase8d_refunds_payment_snapshot=False,
            before_counts_snapshot=before_counts_snapshot,
            after_execute_counts_snapshot=(
                after_execute_counts_snapshot
            ),
            after_rollback_counts_snapshot=(
                after_rollback_counts_snapshot
            ),
            count_deltas_snapshot=count_deltas_snapshot,
            blockers=[],
            warnings=[PHASE_8D_WARNING],
            next_action="phase8d_lock_pending_manual_review",
            evidence_json=_build_evidence_json(
                eligibility=eligibility
            ),
        )
        assert_phase8d_no_provider_or_business_mutation(
            lock, before_counts=before
        )
        try:
            lock.save()
        except IntegrityError:  # pragma: no cover - defensive
            lock = (
                RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
                    source_phase8c_gate=phase8c_gate
                )
            )
            return {
                "phase": "8D",
                "created": False,
                "reused": True,
                "lock": serialize_phase8d_lock(lock),
                "blockers": [],
                "warnings": [PHASE_8D_WARNING],
                "nextAction": "phase8d_lock_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 8D lock prepared lock_id={lock.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(lock),
    )
    return {
        "phase": "8D",
        "created": True,
        "reused": False,
        "lock": serialize_phase8d_lock(lock),
        "blockers": [],
        "warnings": [PHASE_8D_WARNING],
        "nextAction": "phase8d_lock_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Lock / reject / archive
# ---------------------------------------------------------------------------


def _lock_lookup(
    lock_id: int,
) -> Optional[RazorpayPaymentOrderControlledMutationEvidenceLock]:
    return (
        RazorpayPaymentOrderControlledMutationEvidenceLock.objects.filter(
            pk=lock_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def lock_phase8d_controlled_mutation_evidence_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Flip status to ``locked``. Non-empty reason required. Lock
    is final — does NOT execute, never authorises any further
    mutation."""
    if not reason.strip():
        return {
            "phase": "8D",
            "ok": False,
            "lock": None,
            "blockers": ["phase8d_lock_reason_required"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _lock_lookup(lock_id)
    if lock is None:
        return {
            "phase": "8D",
            "ok": False,
            "lock": None,
            "blockers": ["phase8d_lock_not_found"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status not in {
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.DRAFT,
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.BLOCKED,
    }:
        return {
            "phase": "8D",
            "ok": False,
            "lock": serialize_phase8d_lock(lock),
            "blockers": [
                f"phase8d_lock_refused_for_status_{lock.status}"
            ],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "verify_lock_status",
        }

    # Re-validate eligibility at lock time -- the underlying Phase
    # 8C chain must STILL be in its expected post-rollback state.
    eligibility = _validate_eligibility(
        phase8c_gate_id=lock.source_phase8c_gate_id
    )
    if not eligibility["eligible"]:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8D lock blocked at lock-time lock_id="
                f"{lock.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_lock_payload(
                lock,
                extra={
                    "blockers": list(eligibility["blockers"]),
                },
            ),
        )
        return {
            "phase": "8D",
            "ok": False,
            "lock": serialize_phase8d_lock(lock),
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "fix_phase8d_eligibility_blockers",
        }

    before = _business_row_counts()
    assert_phase8d_no_provider_or_business_mutation(
        lock, before_counts=before
    )

    lock.status = (
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.LOCKED
    )
    lock.locked_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.review_reason = (reason or "")[:1000]
    lock.next_action = "phase8d_lock_locked"
    lock.save()

    write_event(
        kind=AUDIT_KIND_LOCKED,
        text=(
            f"Phase 8D evidence lock locked lock_id={lock.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8D",
        "ok": True,
        "lock": serialize_phase8d_lock(lock),
        "blockers": [],
        "warnings": [PHASE_8D_WARNING],
        "nextAction": "phase8d_lock_locked",
    }


def reject_phase8d_controlled_mutation_evidence_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8D",
            "ok": False,
            "lock": None,
            "blockers": ["phase8d_reject_reason_required"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _lock_lookup(lock_id)
    if lock is None:
        return {
            "phase": "8D",
            "ok": False,
            "lock": None,
            "blockers": ["phase8d_lock_not_found"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status not in {
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.DRAFT,
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.BLOCKED,
    }:
        return {
            "phase": "8D",
            "ok": False,
            "lock": serialize_phase8d_lock(lock),
            "blockers": [
                f"phase8d_reject_refused_for_status_{lock.status}"
            ],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "verify_lock_status",
        }
    before = _business_row_counts()
    assert_phase8d_no_provider_or_business_mutation(
        lock, before_counts=before
    )
    lock.status = (
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.REJECTED
    )
    lock.rejected_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.reject_reason = (reason or "")[:1000]
    lock.next_action = "phase8d_lock_rejected"
    lock.save()
    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 8D evidence lock rejected lock_id={lock.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8D",
        "ok": True,
        "lock": serialize_phase8d_lock(lock),
        "blockers": [],
        "warnings": [PHASE_8D_WARNING],
        "nextAction": "phase8d_lock_rejected",
    }


def archive_phase8d_controlled_mutation_evidence_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8D",
            "ok": False,
            "lock": None,
            "blockers": ["phase8d_archive_reason_required"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _lock_lookup(lock_id)
    if lock is None:
        return {
            "phase": "8D",
            "ok": False,
            "lock": None,
            "blockers": ["phase8d_lock_not_found"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status == (
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.ARCHIVED
    ):
        return {
            "phase": "8D",
            "ok": False,
            "lock": serialize_phase8d_lock(lock),
            "blockers": ["phase8d_lock_already_archived"],
            "warnings": [PHASE_8D_WARNING],
            "nextAction": "verify_lock_status",
        }
    before = _business_row_counts()
    assert_phase8d_no_provider_or_business_mutation(
        lock, before_counts=before
    )
    lock.status = (
        RazorpayPaymentOrderControlledMutationEvidenceLock.Status.ARCHIVED
    )
    lock.archived_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.archive_reason = (reason or "")[:1000]
    lock.next_action = "phase8d_lock_archived"
    lock.save()
    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 8D evidence lock archived lock_id={lock.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8D",
        "ok": True,
        "lock": serialize_phase8d_lock(lock),
        "blockers": [],
        "warnings": [PHASE_8D_WARNING],
        "nextAction": "phase8d_lock_archived",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase8d_locks(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayPaymentOrderControlledMutationEvidenceLock.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value
        for s in RazorpayPaymentOrderControlledMutationEvidenceLock.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase8d_lock(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "8D", "counts": counts, "items": items}


def inspect_phase8d_controlled_mutation_evidence_lock_readiness() -> (
    dict[str, Any]
):
    summary = summarize_phase8d_locks(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    # Phase 8D-Hotfix-1: a gate is "eligible" only if it both
    # carries `status=rolled_back` AND has at least one attempt
    # whose rollback record satisfies the evidence contract
    # (status=rollback_recorded, rollback_was_made=True,
    # restored_*=Pending). This makes the readiness signal accurate
    # for the post-rollback scenario where attempt.status may be
    # "blocked" after a later re-run.
    eligible_phase8c_gates = (
        RazorpayPaymentOrderControlledMutationGate.objects.filter(
            status=(
                RazorpayPaymentOrderControlledMutationGate.Status.ROLLED_BACK
            ),
            dry_run_passed=True,
            attempts__rollbacks__status=(
                RazorpayPaymentOrderControlledMutationRollback.Status.ROLLBACK_RECORDED
            ),
            attempts__rollbacks__rollback_was_made=True,
            attempts__rollbacks__restored_order_status=(
                _ALLOWED_FINAL_ORDER_PAYMENT_STATUS
            ),
            attempts__rollbacks__restored_payment_status=(
                _ALLOWED_FINAL_PAYMENT_STATUS
            ),
        )
        .distinct()
        .count()
    )

    blockers: list[str] = []
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if _flag_phase7e_live_b_approved():
        blockers.append("phase7e_live_b_must_remain_not_approved")
    if _flag_phase7g_live_approved():
        blockers.append("phase7g_live_must_remain_not_approved")

    if blockers:
        next_action = "fix_phase8d_safety_blockers"
    elif eligible_phase8c_gates == 0:
        next_action = "no_eligible_phase8c_gate_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase8d_locks_pending_manual_review"
    elif counts.get("locked", 0) > 0:
        next_action = "phase8d_locks_locked_awaiting_archive"
    else:
        next_action = (
            "ready_to_prepare_phase8d_controlled_mutation_evidence_lock"
        )

    return {
        "phase": "8D",
        "status": "controlled_mutation_evidence_lock_only",
        "latestCompletedPhase": "8C",
        "nextPhase": "phase8d_locked_or_phase8_live_not_approved",
        "killSwitch": kill,
        "eligiblePhase8CGateCount": eligible_phase8c_gates,
        "phase8DLockCounts": counts,
        "items": summary["items"],
        "phase8DExecutesPhase8CAgain": False,
        "phase8DRollsBackPhase8CAgain": False,
        "phase8DCallsRazorpay": False,
        "phase8DCallsMetaCloud": False,
        "phase8DCallsDelhivery": False,
        "phase8DCallsVapi": False,
        "phase8DSendsWhatsApp": False,
        "phase8DQueuesWhatsApp": False,
        "phase8DCreatesShipmentRow": False,
        "phase8DCreatesAwb": False,
        "phase8DCreatesPaymentLink": False,
        "phase8DCapturesPayment": False,
        "phase8DRefundsPayment": False,
        "phase8DSendsCustomerNotification": False,
        "phase8DMutatesOrder": False,
        "phase8DMutatesPayment": False,
        "phase8DMutatesCustomer": False,
        "phase8DMutatesLead": False,
        "phase8DMutatesShipment": False,
        "phase8DMutatesDiscountOfferLog": False,
        "phase8DMutatesWhatsAppMessage": False,
        "phase8DApprovesRealCustomerAutomation": False,
        "phase7ELiveBApproved": False,
        "phase7GLiveApproved": False,
        "executionPath": "lock_only_cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_8D_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_8D_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text=(
            "Phase 8D controlled mutation evidence lock readiness "
            "inspected"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase8c_gate_count": int(
                    report.get("eligiblePhase8CGateCount") or 0
                ),
                "lock_counts": report.get("phase8DLockCounts") or {},
                "next_action": report.get("nextAction") or "",
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
