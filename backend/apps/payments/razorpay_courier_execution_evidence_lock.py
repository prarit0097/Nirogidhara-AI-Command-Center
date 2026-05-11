"""Phase 7H - Final audit / evidence lock for the completed Phase 7G
TEST/MOCK courier execution.

Phase 7H is **lock-only**. The service snapshots the immutable
fields off a completed Phase 7G attempt (status =
``rolled_back_recorded`` with `provider_call_attempted=True` +
`awb_created=True` AND all locked-False booleans staying False)
into a separate :class:`RazorpayCourierExecutionEvidenceLock`
row. Approval flips status to ``locked`` only — it does NOT
authorize any live execution, never calls Delhivery, never
creates a ``Shipment`` / ``WorkflowStep`` / ``RescueAttempt`` /
AWB row, never sends or queues WhatsApp, never calls Meta Cloud
/ Razorpay / Vapi, never sends a customer notification, never
mutates real ``Order`` / ``Payment`` / ``Customer`` / ``Lead`` /
``DiscountOfferLog`` rows, never edits any ``.env*`` file.

Public surface:

- :func:`inspect_phase7h_evidence_lock_readiness`
- :func:`preview_phase7h_evidence_lock`
- :func:`prepare_phase7h_evidence_lock`
- :func:`approve_phase7h_evidence_lock`
- :func:`reject_phase7h_evidence_lock`
- :func:`archive_phase7h_evidence_lock`
- :func:`assert_phase7h_no_provider_or_business_mutation`
- :func:`serialize_phase7h_evidence_lock`
- :func:`summarize_phase7h_evidence_locks`
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
    RazorpayCourierExecutionAttempt,
    RazorpayCourierExecutionEvidenceLock,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_7H_WARNING = (
    "Phase 7H is the Final Audit / Evidence Lock for the completed "
    "Phase 7G TEST/MOCK courier execution. It is lock-only. Approval "
    "flips status to `locked` and freezes the snapshot. Phase 7H "
    "NEVER calls Delhivery, NEVER creates a Shipment / WorkflowStep "
    "/ RescueAttempt / AWB row, NEVER sends or queues WhatsApp, "
    "NEVER calls Meta Cloud / Razorpay / Vapi, NEVER sends a customer "
    "notification, NEVER mutates real Order / Payment / Customer / "
    "Lead / DiscountOfferLog rows, NEVER edits any .env file. Phase "
    "7G-Live (real customer courier execution) remains NOT approved."
)


AUDIT_KIND_READINESS = "phase7h.courier_evidence.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase7h.courier_evidence.previewed"
AUDIT_KIND_PREPARED = "phase7h.courier_evidence.prepared"
AUDIT_KIND_LOCKED = "phase7h.courier_evidence.locked"
AUDIT_KIND_REJECTED = "phase7h.courier_evidence.rejected"
AUDIT_KIND_ARCHIVED = "phase7h.courier_evidence.archived"
AUDIT_KIND_BLOCKED = "phase7h.courier_evidence.blocked"


PHASE_7H_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "call_delhivery_api",
    "create_awb",
    "create_shipment_row",
    "send_whatsapp_template",
    "send_whatsapp_freeform",
    "queue_whatsapp_outbound",
    "send_customer_notification",
    "call_meta_cloud_api",
    "call_razorpay_api",
    "call_vapi_api",
    "mutate_real_order_status",
    "mutate_real_payment_status",
    "mutate_real_shipment_status",
    "mutate_real_customer",
    "mutate_real_lead",
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "execute_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_7H_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "token",
    "phone",
    "customer_phone",
    "email",
    "address",
    "pincode",
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
    "DELHIVERY_API_TOKEN",
    "META_WA_TOKEN",
    "META_WA_APP_SECRET",
    "RAZORPAY_KEY_SECRET",
    "raw_payload",
    "raw_signature",
    "raw_secret",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    safe: dict[str, Any] = {"phase": "7H"}
    forbidden = set(PHASE_7H_FORBIDDEN_PAYLOAD_KEYS)
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


def assert_phase7h_no_provider_or_business_mutation(
    lock: RazorpayCourierExecutionEvidenceLock,
    *,
    before_counts: Optional[dict[str, int]] = None,
) -> None:
    """Refuse if any of the locked-False snapshot booleans is True, or
    if any business-row count has moved. Emits an
    invariant-violation audit + raises ``ValueError``.
    """
    flipped: list[str] = []
    for field in (
        "shipment_created_snapshot",
        "business_mutation_was_made_snapshot",
        "customer_notification_sent_snapshot",
    ):
        if getattr(lock, field, False) is True:
            flipped.append(field)

    delta_keys: list[str] = []
    if before_counts is not None:
        current = _business_row_counts()
        for key, count_before in before_counts.items():
            count_after = current.get(key, count_before)
            if count_after != count_before:
                delta_keys.append(
                    f"phase7h_business_row_count_changed_for_{key}"
                )

    if not flipped and not delta_keys:
        return

    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=f"Phase 7H invariant violation lock_id={lock.pk}",
        tone=AuditEvent.Tone.DANGER,
        payload=_safe_audit_payload(
            {
                "lock_id": lock.pk,
                "flipped_snapshot_booleans": flipped,
                "business_row_count_deltas": delta_keys,
                "shipment_created_snapshot": False,
                "business_mutation_was_made_snapshot": False,
                "customer_notification_sent_snapshot": False,
            }
        ),
    )
    raise ValueError(
        "Phase 7H invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_attempt(
    attempt: Optional[RazorpayCourierExecutionAttempt],
) -> list[str]:
    """Pure: return a list of blocker codes (empty means eligible).

    Eligibility for the lock:
    - attempt exists
    - status == rolled_back_recorded
    - provider_call_attempted = True
    - delhivery_call_attempted = True
    - awb_created = True
    - provider_object_id present
    - recorded_signoff_window_valid = True
    - rollback_status = recorded_only_no_provider_cancel
    - shipment_created = False
    - business_mutation_was_made = False
    - customer_notification_sent = False
    - real_order/payment/shipment_mutation_was_made = False
    """
    blockers: list[str] = []
    if attempt is None:
        blockers.append(
            "phase7h_source_phase7g_attempt_not_found"
        )
        return blockers

    if (
        attempt.status
        != RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED
    ):
        blockers.append(
            f"phase7h_source_attempt_status_must_be_rolled_back_recorded_was_{attempt.status}"
        )
    if not attempt.provider_call_attempted:
        blockers.append(
            "phase7h_source_attempt_provider_call_attempted_must_be_true"
        )
    if not attempt.delhivery_call_attempted:
        blockers.append(
            "phase7h_source_attempt_delhivery_call_attempted_must_be_true"
        )
    if not attempt.awb_created:
        blockers.append(
            "phase7h_source_attempt_awb_created_must_be_true"
        )
    if not (attempt.provider_object_id or "").strip():
        blockers.append(
            "phase7h_source_attempt_provider_object_id_must_be_present"
        )
    if attempt.recorded_signoff_window_valid is not True:
        blockers.append(
            "phase7h_source_attempt_recorded_signoff_window_valid_must_be_true"
        )
    if (
        attempt.rollback_status
        != RazorpayCourierExecutionAttempt.RollbackStatus.RECORDED_ONLY_NO_PROVIDER_CANCEL
    ):
        blockers.append(
            "phase7h_source_attempt_rollback_status_must_be_recorded_only_no_provider_cancel"
        )
    for locked_false_field in (
        "shipment_created",
        "business_mutation_was_made",
        "customer_notification_sent",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "real_shipment_mutation_was_made",
    ):
        if getattr(attempt, locked_false_field, False):
            blockers.append(
                f"phase7h_source_attempt_{locked_false_field}_must_be_false"
            )

    return blockers


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def serialize_phase7h_evidence_lock(
    row: RazorpayCourierExecutionEvidenceLock,
) -> dict[str, Any]:
    """Whitelisted serializer. NEVER returns raw token / phone /
    address / customer data / raw provider response."""
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase7GAttemptId": row.source_phase7g_attempt_id,
        "sourcePhase7FGateId": row.source_phase7f_gate_id,
        "sourcePhase7EGateId": row.source_phase7e_gate_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sourcePhase7BGateId": row.source_phase7b_gate_id,
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        "providerObjectIdSnapshot": row.provider_object_id_snapshot,
        "providerStatusSnapshot": row.provider_status_snapshot,
        "recordedSignoffWindowValidSnapshot": (
            row.recorded_signoff_window_valid_snapshot
        ),
        "executedAtSnapshot": (
            row.executed_at_snapshot.isoformat()
            if row.executed_at_snapshot
            else None
        ),
        "rolledBackAtSnapshot": (
            row.rolled_back_at_snapshot.isoformat()
            if row.rolled_back_at_snapshot
            else None
        ),
        "rollbackStatusSnapshot": row.rollback_status_snapshot,
        "shipmentCreatedSnapshot": bool(row.shipment_created_snapshot),
        "businessMutationWasMadeSnapshot": bool(
            row.business_mutation_was_made_snapshot
        ),
        "customerNotificationSentSnapshot": bool(
            row.customer_notification_sent_snapshot
        ),
        "evidenceJson": row.evidence_json or {},
        "reviewedByUsername": row.reviewed_by_username,
        "reviewedAt": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "reviewReasonPresent": bool((row.review_reason or "").strip()),
        "rejectReasonPresent": bool((row.reject_reason or "").strip()),
        "archiveReasonPresent": bool(
            (row.archive_reason or "").strip()
        ),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "nextAction": row.next_action or "",
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
    lock: RazorpayCourierExecutionEvidenceLock,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lock_id": lock.pk,
        "status": lock.status,
        "phase7g_attempt_id": lock.source_phase7g_attempt_id,
        "phase7f_gate_id": lock.source_phase7f_gate_id,
        "phase7e_gate_id": lock.source_phase7e_gate_id,
        "phase7d_attempt_id": lock.source_phase7d_attempt_id,
        "phase7b_gate_id": lock.source_phase7b_gate_id,
        "provider_object_id_or_empty": (
            lock.provider_object_id_snapshot or ""
        ),
        "shipment_created_snapshot": bool(
            lock.shipment_created_snapshot
        ),
        "business_mutation_was_made_snapshot": bool(
            lock.business_mutation_was_made_snapshot
        ),
        "customer_notification_sent_snapshot": bool(
            lock.customer_notification_sent_snapshot
        ),
        "recorded_signoff_window_valid_snapshot": (
            lock.recorded_signoff_window_valid_snapshot
        ),
        "kill_switch_state_at_emit": _kill_switch_state(),
    }
    if extra:
        payload.update(extra)
    return _safe_audit_payload(payload)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _build_evidence_json(
    attempt: RazorpayCourierExecutionAttempt,
) -> dict[str, Any]:
    return {
        "phase": "7H",
        "phase7gAttemptId": attempt.pk,
        "phase7fGateId": attempt.source_phase7f_gate_id,
        "phase7eGateId": attempt.source_phase7e_gate_id,
        "phase7dAttemptId": attempt.source_phase7d_attempt_id,
        "phase7bGateId": attempt.source_phase7b_gate_id,
        "providerObjectId": attempt.provider_object_id or "",
        "providerStatus": attempt.provider_status or "",
        "recordedSignoffWindowValid": (
            attempt.recorded_signoff_window_valid
        ),
        "recordedSignoffWindowStartUtc": (
            attempt.recorded_signoff_window_start_utc.isoformat()
            if attempt.recorded_signoff_window_start_utc
            else None
        ),
        "recordedSignoffWindowEndUtc": (
            attempt.recorded_signoff_window_end_utc.isoformat()
            if attempt.recorded_signoff_window_end_utc
            else None
        ),
        "executedAt": (
            attempt.executed_at.isoformat()
            if attempt.executed_at
            else None
        ),
        "rolledBackAt": (
            attempt.rolled_back_at.isoformat()
            if attempt.rolled_back_at
            else None
        ),
        "rollbackStatus": attempt.rollback_status,
        "providerCallAttempted": bool(attempt.provider_call_attempted),
        "delhiveryCallAttempted": bool(
            attempt.delhivery_call_attempted
        ),
        "awbCreated": bool(attempt.awb_created),
        "shipmentCreated": bool(attempt.shipment_created),
        "businessMutationWasMade": bool(
            attempt.business_mutation_was_made
        ),
        "customerNotificationSent": bool(
            attempt.customer_notification_sent
        ),
    }


def preview_phase7h_evidence_lock(attempt_id: int) -> dict[str, Any]:
    """Read-only preview. NEVER creates rows."""
    attempt = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    blockers = _validate_attempt(attempt)
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7H preview attempt_id={attempt_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "attempt_id": attempt_id,
                "eligible": not blockers,
                "blockers": blockers,
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    return {
        "phase": "7H",
        "found": attempt is not None,
        "attemptId": attempt_id,
        "eligible": not blockers,
        "blockers": blockers,
        "warnings": [PHASE_7H_WARNING],
        "evidence": (
            _build_evidence_json(attempt)
            if attempt is not None
            else {}
        ),
        "nextAction": (
            "ready_to_prepare_phase7h_evidence_lock"
            if not blockers
            else "fix_phase7h_eligibility_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _idempotency_blockers(blockers: list[str]) -> list[str]:
    """Sub-set of blockers that mean 'reject this prepare call'."""
    return blockers


def prepare_phase7h_evidence_lock(attempt_id: int) -> dict[str, Any]:
    """Atomic + idempotent prepare. Creates ONE evidence-lock row per
    source Phase 7G attempt id. NEVER calls Delhivery / Meta / Vapi
    / Razorpay; NEVER mutates business tables; NEVER edits .env.
    """
    attempt = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )
    blockers = _validate_attempt(attempt)

    if blockers:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7H prepare blocked attempt_id={attempt_id}",
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "attempt_id": attempt_id,
                    "blockers": blockers,
                    "kill_switch_state_at_emit": _kill_switch_state(),
                }
            ),
        )
        return {
            "phase": "7H",
            "created": False,
            "reused": False,
            "lock": None,
            "blockers": blockers,
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "fix_phase7h_eligibility_blockers",
        }

    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7H prepare blocked kill-switch off attempt_id="
                f"{attempt_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "attempt_id": attempt_id,
                    "blockers": ["runtime_kill_switch_disabled"],
                    "kill_switch_state_at_emit": kill,
                }
            ),
        )
        return {
            "phase": "7H",
            "created": False,
            "reused": False,
            "lock": None,
            "blockers": ["runtime_kill_switch_disabled"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "fix_phase7h_eligibility_blockers",
        }

    assert attempt is not None  # narrowed by `_validate_attempt`
    before = _business_row_counts()

    with transaction.atomic():
        existing = (
            RazorpayCourierExecutionEvidenceLock.objects.filter(
                source_phase7g_attempt=attempt
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "7H",
                "created": False,
                "reused": True,
                "lock": serialize_phase7h_evidence_lock(existing),
                "blockers": [],
                "warnings": [PHASE_7H_WARNING],
                "nextAction": (
                    "phase7h_lock_pending_manual_review"
                    if existing.status
                    == RazorpayCourierExecutionEvidenceLock.Status.PENDING_MANUAL_REVIEW
                    else f"phase7h_lock_status_{existing.status}"
                ),
            }

        lock = RazorpayCourierExecutionEvidenceLock(
            source_phase7g_attempt=attempt,
            source_phase7f_gate=attempt.source_phase7f_gate,
            source_phase7e_gate=attempt.source_phase7e_gate,
            source_phase7d_attempt=attempt.source_phase7d_attempt,
            source_phase7b_gate=attempt.source_phase7b_gate,
            source_phase6t_lock=attempt.source_phase6t_lock,
            status=(
                RazorpayCourierExecutionEvidenceLock.Status.PENDING_MANUAL_REVIEW
            ),
            provider_object_id_snapshot=(
                attempt.provider_object_id or ""
            )[:64],
            provider_status_snapshot=(
                attempt.provider_status or ""
            )[:64],
            recorded_signoff_window_valid_snapshot=(
                attempt.recorded_signoff_window_valid
            ),
            executed_at_snapshot=attempt.executed_at,
            rolled_back_at_snapshot=attempt.rolled_back_at,
            rollback_status_snapshot=attempt.rollback_status or "",
            shipment_created_snapshot=bool(attempt.shipment_created),
            business_mutation_was_made_snapshot=bool(
                attempt.business_mutation_was_made
            ),
            customer_notification_sent_snapshot=bool(
                attempt.customer_notification_sent
            ),
            evidence_json=_build_evidence_json(attempt),
            blockers=[],
            warnings=[PHASE_7H_WARNING],
            next_action="phase7h_lock_pending_manual_review",
        )
        assert_phase7h_no_provider_or_business_mutation(
            lock, before_counts=before
        )
        try:
            lock.save()
        except IntegrityError:
            lock = RazorpayCourierExecutionEvidenceLock.objects.get(
                source_phase7g_attempt=attempt
            )
            return {
                "phase": "7H",
                "created": False,
                "reused": True,
                "lock": serialize_phase7h_evidence_lock(lock),
                "blockers": [],
                "warnings": [PHASE_7H_WARNING],
                "nextAction": "phase7h_lock_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 7H evidence lock prepared lock_id={lock.pk} "
            f"phase7g_attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(lock),
    )
    return {
        "phase": "7H",
        "created": True,
        "reused": False,
        "lock": serialize_phase7h_evidence_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7H_WARNING],
        "nextAction": "phase7h_lock_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


def _terminal_lookup(
    lock_id: int,
) -> Optional[RazorpayCourierExecutionEvidenceLock]:
    return (
        RazorpayCourierExecutionEvidenceLock.objects.filter(
            pk=lock_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def approve_phase7h_evidence_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Flip status to ``locked``. Non-empty reason required."""
    if not reason.strip():
        return {
            "phase": "7H",
            "ok": False,
            "lock": None,
            "blockers": ["phase7h_approve_reason_required"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _terminal_lookup(lock_id)
    if lock is None:
        return {
            "phase": "7H",
            "ok": False,
            "lock": None,
            "blockers": ["phase7h_lock_not_found"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "verify_lock_id",
        }
    if (
        lock.status
        != RazorpayCourierExecutionEvidenceLock.Status.PENDING_MANUAL_REVIEW
    ):
        return {
            "phase": "7H",
            "ok": False,
            "lock": serialize_phase7h_evidence_lock(lock),
            "blockers": [
                f"phase7h_lock_status_{lock.status}_not_transitionable_to_locked"
            ],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "verify_lock_status",
        }

    before = _business_row_counts()
    assert_phase7h_no_provider_or_business_mutation(
        lock, before_counts=before
    )

    lock.status = RazorpayCourierExecutionEvidenceLock.Status.LOCKED
    lock.locked_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.review_reason = (reason or "")[:1000]
    lock.next_action = "phase7h_lock_locked"
    lock.save()

    write_event(
        kind=AUDIT_KIND_LOCKED,
        text=f"Phase 7H evidence lock locked lock_id={lock.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(
            lock,
            extra={"reason_excerpt": (reason or "")[:120]},
        ),
    )
    return {
        "phase": "7H",
        "ok": True,
        "lock": serialize_phase7h_evidence_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7H_WARNING],
        "nextAction": "phase7h_lock_locked",
    }


def reject_phase7h_evidence_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7H",
            "ok": False,
            "lock": None,
            "blockers": ["phase7h_reject_reason_required"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _terminal_lookup(lock_id)
    if lock is None:
        return {
            "phase": "7H",
            "ok": False,
            "lock": None,
            "blockers": ["phase7h_lock_not_found"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status not in {
        RazorpayCourierExecutionEvidenceLock.Status.DRAFT,
        RazorpayCourierExecutionEvidenceLock.Status.PENDING_MANUAL_REVIEW,
        RazorpayCourierExecutionEvidenceLock.Status.BLOCKED,
    }:
        return {
            "phase": "7H",
            "ok": False,
            "lock": serialize_phase7h_evidence_lock(lock),
            "blockers": [
                f"phase7h_reject_refused_for_status_{lock.status}"
            ],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "verify_lock_status",
        }

    before = _business_row_counts()
    assert_phase7h_no_provider_or_business_mutation(
        lock, before_counts=before
    )
    lock.status = RazorpayCourierExecutionEvidenceLock.Status.REJECTED
    lock.rejected_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.reject_reason = (reason or "")[:1000]
    lock.next_action = "phase7h_lock_rejected"
    lock.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 7H evidence lock rejected lock_id={lock.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "7H",
        "ok": True,
        "lock": serialize_phase7h_evidence_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7H_WARNING],
        "nextAction": "phase7h_lock_rejected",
    }


def archive_phase7h_evidence_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7H",
            "ok": False,
            "lock": None,
            "blockers": ["phase7h_archive_reason_required"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _terminal_lookup(lock_id)
    if lock is None:
        return {
            "phase": "7H",
            "ok": False,
            "lock": None,
            "blockers": ["phase7h_lock_not_found"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status == (
        RazorpayCourierExecutionEvidenceLock.Status.ARCHIVED
    ):
        return {
            "phase": "7H",
            "ok": False,
            "lock": serialize_phase7h_evidence_lock(lock),
            "blockers": ["phase7h_lock_already_archived"],
            "warnings": [PHASE_7H_WARNING],
            "nextAction": "verify_lock_status",
        }
    before = _business_row_counts()
    assert_phase7h_no_provider_or_business_mutation(
        lock, before_counts=before
    )
    lock.status = RazorpayCourierExecutionEvidenceLock.Status.ARCHIVED
    lock.archived_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.archive_reason = (reason or "")[:1000]
    lock.next_action = "phase7h_lock_archived"
    lock.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 7H evidence lock archived lock_id={lock.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "7H",
        "ok": True,
        "lock": serialize_phase7h_evidence_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7H_WARNING],
        "nextAction": "phase7h_lock_archived",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase7h_evidence_locks(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayCourierExecutionEvidenceLock.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value for s in RazorpayCourierExecutionEvidenceLock.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase7h_evidence_lock(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "7H", "counts": counts, "items": items}


def inspect_phase7h_evidence_lock_readiness() -> dict[str, Any]:
    summary = summarize_phase7h_evidence_locks(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    # Count Phase 7G attempts that satisfy lock-eligibility.
    eligible_attempts = (
        RazorpayCourierExecutionAttempt.objects.filter(
            status=RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED,
            provider_call_attempted=True,
            delhivery_call_attempted=True,
            awb_created=True,
            recorded_signoff_window_valid=True,
            shipment_created=False,
            business_mutation_was_made=False,
            customer_notification_sent=False,
        ).count()
    )

    blockers: list[str] = []
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    if blockers:
        next_action = "fix_phase7h_safety_blockers"
    elif eligible_attempts == 0 and (
        counts.get("pending_manual_review", 0) == 0
        and counts.get("locked", 0) == 0
    ):
        next_action = "no_eligible_phase7g_attempt_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase7h_locks_pending_manual_review"
    elif counts.get("locked", 0) > 0:
        next_action = "phase7h_locks_locked"
    else:
        next_action = "ready_to_prepare_phase7h_evidence_lock"

    return {
        "phase": "7H",
        "status": "courier_evidence_lock_only",
        "latestCompletedPhase": "7G",
        "nextPhase": "phase_7g_live_or_phase_7h_complete",
        "killSwitch": kill,
        "eligiblePhase7GAttemptCount": eligible_attempts,
        "phase7HLockCounts": counts,
        "items": summary["items"],
        "phase7HCallsDelhivery": False,
        "phase7HCreatesShipmentRow": False,
        "phase7HCreatesAwb": False,
        "phase7HSendsWhatsApp": False,
        "phase7HQueuesWhatsApp": False,
        "phase7HCallsMetaCloud": False,
        "phase7HCallsRazorpay": False,
        "phase7HSendsCustomerNotification": False,
        "phase7HMutatesBusinessRow": False,
        "phase7HLiveCustomerCourierApproved": False,
        "executionPath": "lock_only_cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_7H_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_7H_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7H courier evidence lock readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase7g_attempt_count": int(
                    report.get("eligiblePhase7GAttemptCount") or 0
                ),
                "lock_counts": report.get("phase7HLockCounts") or {},
                "next_action": report.get("nextAction") or "",
                "kill_switch_enabled": (
                    report.get("killSwitch", {}) or {}
                ).get("enabled", True),
            }
        ),
    )


__all__ = (
    "PHASE_7H_WARNING",
    "PHASE_7H_FORBIDDEN_ACTIONS",
    "PHASE_7H_FORBIDDEN_PAYLOAD_KEYS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_LOCKED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "assert_phase7h_no_provider_or_business_mutation",
    "preview_phase7h_evidence_lock",
    "prepare_phase7h_evidence_lock",
    "approve_phase7h_evidence_lock",
    "reject_phase7h_evidence_lock",
    "archive_phase7h_evidence_lock",
    "inspect_phase7h_evidence_lock_readiness",
    "summarize_phase7h_evidence_locks",
    "serialize_phase7h_evidence_lock",
    "emit_readiness_inspected_audit",
)
