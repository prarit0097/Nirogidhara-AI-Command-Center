"""Phase 7I — Final Phase 7 Payment + WhatsApp + Courier Audit Lock.

Phase 7I is a **lock-only meta-audit**. It snapshots the immutable
fields off four source records — Phase 7D (Razorpay TEST execute,
rolled back), Phase 7E-Live-A (internal allowed-list WhatsApp send,
rollback_recorded with `whatsapp_message_created=True`), Phase 7G
(Delhivery TEST/MOCK execute, rolled_back_recorded with
`awb_created=True`), and Phase 7H (courier execution evidence lock,
status=locked) — into a single
:class:`RazorpayPhase7FinalAuditLock` row. Approval flips status to
``locked`` and freezes the snapshot.

Phase 7I NEVER calls Razorpay, NEVER calls Meta Cloud, NEVER calls
Delhivery, NEVER calls Vapi, NEVER sends or queues WhatsApp, NEVER
creates a ``Shipment`` / ``WorkflowStep`` / ``RescueAttempt`` row,
NEVER creates an AWB, NEVER creates a payment link, NEVER captures,
NEVER refunds, NEVER sends a customer notification, NEVER mutates
real ``Order`` / ``Payment`` / ``Customer`` / ``Lead`` /
``DiscountOfferLog`` rows, NEVER edits any ``.env*`` file.

Public surface:

- :func:`inspect_phase7i_final_audit_lock_readiness`
- :func:`preview_phase7i_final_audit_lock`
- :func:`prepare_phase7i_final_audit_lock`
- :func:`approve_phase7i_final_audit_lock`
- :func:`reject_phase7i_final_audit_lock`
- :func:`archive_phase7i_final_audit_lock`
- :func:`assert_phase7i_no_provider_or_business_mutation`
- :func:`serialize_phase7i_final_audit_lock`
- :func:`summarize_phase7i_final_audit_locks`
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
    RazorpayCourierExecutionAttempt,
    RazorpayCourierExecutionEvidenceLock,
    RazorpayPhase7FinalAuditLock,
    RazorpayWhatsAppInternalSendAttempt,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_7I_WARNING = (
    "Phase 7I is the Final Phase 7 Payment + WhatsApp + Courier "
    "Audit Lock. It is lock-only meta-audit over Phase 7D + 7E-Live-A "
    "+ 7G + 7H. Approval flips status to `locked` and freezes the "
    "composite snapshot. Phase 7I NEVER calls Razorpay / Meta Cloud "
    "/ Delhivery / Vapi, NEVER sends or queues WhatsApp, NEVER "
    "creates a Shipment / AWB / payment link, NEVER captures, NEVER "
    "refunds, NEVER sends a customer notification, NEVER mutates "
    "real Order / Payment / Customer / Lead / DiscountOfferLog "
    "rows, NEVER edits any .env file. Phase 7E-Live-B (real customer "
    "WhatsApp send) and Phase 7G-Live (real customer courier "
    "execution) remain NOT approved."
)


AUDIT_KIND_READINESS = "phase7i.final_audit.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase7i.final_audit.previewed"
AUDIT_KIND_PREPARED = "phase7i.final_audit.prepared"
AUDIT_KIND_LOCKED = "phase7i.final_audit.locked"
AUDIT_KIND_REJECTED = "phase7i.final_audit.rejected"
AUDIT_KIND_ARCHIVED = "phase7i.final_audit.archived"
AUDIT_KIND_BLOCKED = "phase7i.final_audit.blocked"


PHASE_7I_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "execute_via_api_endpoint",
    "archive_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_7I_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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


# Locked-False snapshot fields that MUST stay False on the Phase 7I
# row at all times (mirrored from each source-phase contract).
_LOCKED_FALSE_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "phase7d_business_mutation_was_made_snapshot",
    "phase7d_customer_notification_sent_snapshot",
    "phase7e_live_customer_notification_sent_snapshot",
    "phase7e_live_business_mutation_was_made_snapshot",
    "phase7e_live_real_customer_phone_used_snapshot",
    "phase7g_shipment_created_snapshot",
    "phase7g_business_mutation_was_made_snapshot",
    "phase7g_customer_notification_sent_snapshot",
    "phase7h_shipment_created_snapshot",
    "phase7h_business_mutation_was_made_snapshot",
    "phase7h_customer_notification_sent_snapshot",
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
    safe: dict[str, Any] = {"phase": "7I"}
    forbidden = set(PHASE_7I_FORBIDDEN_PAYLOAD_KEYS)
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


def assert_phase7i_no_provider_or_business_mutation(
    lock: RazorpayPhase7FinalAuditLock,
    *,
    before_counts: Optional[dict[str, int]] = None,
) -> None:
    """Refuse if any of the locked-False snapshot booleans is True
    OR any business-row count delta is non-zero. Emits an
    invariant-violation audit row + raises :class:`ValueError`.
    """
    flipped: list[str] = []
    for field in _LOCKED_FALSE_SNAPSHOT_FIELDS:
        if getattr(lock, field, False) is True:
            flipped.append(field)

    delta_keys: list[str] = []
    if before_counts is not None:
        current = _business_row_counts()
        for key, count_before in before_counts.items():
            count_after = current.get(key, count_before)
            if count_after != count_before:
                delta_keys.append(
                    f"phase7i_business_row_count_changed_for_{key}"
                )

    if not flipped and not delta_keys:
        return

    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=f"Phase 7I invariant violation lock_id={lock.pk}",
        tone=AuditEvent.Tone.DANGER,
        payload=_safe_audit_payload(
            {
                "lock_id": lock.pk,
                "flipped_snapshot_booleans": flipped,
                "business_row_count_deltas": delta_keys,
            }
        ),
    )
    raise ValueError(
        "Phase 7I invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_phase7d_attempt(
    attempt: Optional[RazorpayControlledPilotExecutionAttempt],
) -> list[str]:
    blockers: list[str] = []
    if attempt is None:
        blockers.append("phase7i_source_phase7d_attempt_not_found")
        return blockers
    Status = RazorpayControlledPilotExecutionAttempt.Status
    if attempt.status not in {Status.EXECUTED, Status.ROLLED_BACK}:
        blockers.append(
            f"phase7i_source_phase7d_attempt_status_must_be_executed_or_rolled_back_was_{attempt.status}"
        )
    for locked_false_field in (
        "business_mutation_was_made",
        "customer_notification_sent",
        "shipment_created",
        "awb_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "payment_link_created",
        "payment_captured",
        "payment_refunded",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
    ):
        if getattr(attempt, locked_false_field, False):
            blockers.append(
                f"phase7i_source_phase7d_attempt_{locked_false_field}_must_be_false"
            )
    return blockers


def _validate_phase7e_live_attempt(
    attempt: Optional[RazorpayWhatsAppInternalSendAttempt],
) -> list[str]:
    blockers: list[str] = []
    if attempt is None:
        blockers.append(
            "phase7i_source_phase7e_live_attempt_not_found"
        )
        return blockers
    Status = RazorpayWhatsAppInternalSendAttempt.Status
    if attempt.status != Status.ROLLBACK_RECORDED:
        blockers.append(
            f"phase7i_source_phase7e_live_attempt_status_must_be_rollback_recorded_was_{attempt.status}"
        )
    if not (attempt.provider_message_id or "").strip():
        blockers.append(
            "phase7i_source_phase7e_live_attempt_provider_message_id_must_be_present"
        )
    if not attempt.whatsapp_message_created:
        blockers.append(
            "phase7i_source_phase7e_live_attempt_whatsapp_message_created_must_be_true"
        )
    if attempt.recorded_signoff_window_valid is not True:
        blockers.append(
            "phase7i_source_phase7e_live_attempt_recorded_signoff_window_valid_must_be_true"
        )
    if not attempt.claim_vault_grounded:
        blockers.append(
            "phase7i_source_phase7e_live_attempt_claim_vault_grounded_must_be_true"
        )
    if (
        attempt.recipient_scope
        != RazorpayWhatsAppInternalSendAttempt.RecipientScope.INTERNAL_STAFF_ALLOW_LIST
    ):
        blockers.append(
            "phase7i_source_phase7e_live_attempt_recipient_scope_must_be_internal_staff_allow_list"
        )
    for locked_false_field in (
        "customer_notification_sent",
        "business_mutation_was_made",
        "real_customer_allowed",
        "real_customer_phone_used",
    ):
        if getattr(attempt, locked_false_field, False):
            blockers.append(
                f"phase7i_source_phase7e_live_attempt_{locked_false_field}_must_be_false"
            )
    return blockers


def _validate_phase7g_attempt(
    attempt: Optional[RazorpayCourierExecutionAttempt],
) -> list[str]:
    blockers: list[str] = []
    if attempt is None:
        blockers.append("phase7i_source_phase7g_attempt_not_found")
        return blockers
    Status = RazorpayCourierExecutionAttempt.Status
    if attempt.status != Status.ROLLED_BACK_RECORDED:
        blockers.append(
            f"phase7i_source_phase7g_attempt_status_must_be_rolled_back_recorded_was_{attempt.status}"
        )
    if not attempt.provider_call_attempted:
        blockers.append(
            "phase7i_source_phase7g_attempt_provider_call_attempted_must_be_true"
        )
    if not attempt.delhivery_call_attempted:
        blockers.append(
            "phase7i_source_phase7g_attempt_delhivery_call_attempted_must_be_true"
        )
    if not attempt.awb_created:
        blockers.append(
            "phase7i_source_phase7g_attempt_awb_created_must_be_true"
        )
    if not (attempt.provider_object_id or "").strip():
        blockers.append(
            "phase7i_source_phase7g_attempt_provider_object_id_must_be_present"
        )
    if attempt.recorded_signoff_window_valid is not True:
        blockers.append(
            "phase7i_source_phase7g_attempt_recorded_signoff_window_valid_must_be_true"
        )
    if (
        attempt.rollback_status
        != RazorpayCourierExecutionAttempt.RollbackStatus.RECORDED_ONLY_NO_PROVIDER_CANCEL
    ):
        blockers.append(
            "phase7i_source_phase7g_attempt_rollback_status_must_be_recorded_only_no_provider_cancel"
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
                f"phase7i_source_phase7g_attempt_{locked_false_field}_must_be_false"
            )
    return blockers


def _validate_phase7h_evidence_lock(
    lock: Optional[RazorpayCourierExecutionEvidenceLock],
) -> list[str]:
    blockers: list[str] = []
    if lock is None:
        blockers.append("phase7i_source_phase7h_evidence_lock_not_found")
        return blockers
    if (
        lock.status
        != RazorpayCourierExecutionEvidenceLock.Status.LOCKED
    ):
        blockers.append(
            f"phase7i_source_phase7h_evidence_lock_status_must_be_locked_was_{lock.status}"
        )
    for locked_false_field in (
        "shipment_created_snapshot",
        "business_mutation_was_made_snapshot",
        "customer_notification_sent_snapshot",
    ):
        if getattr(lock, locked_false_field, False):
            blockers.append(
                f"phase7i_source_phase7h_evidence_lock_{locked_false_field}_must_be_false"
            )
    return blockers


def _validate_chain_consistency(
    *,
    phase7e_live: Optional[RazorpayWhatsAppInternalSendAttempt],
    phase7g: Optional[RazorpayCourierExecutionAttempt],
    phase7h: Optional[RazorpayCourierExecutionEvidenceLock],
    phase7d: Optional[RazorpayControlledPilotExecutionAttempt],
) -> list[str]:
    """Cross-check that the four source records are actually
    consistent with each other: Phase 7H must point at Phase 7G, and
    Phase 7G's Phase-7D source must match the Phase 7D the caller
    supplied."""
    blockers: list[str] = []
    if phase7h is not None and phase7g is not None:
        if phase7h.source_phase7g_attempt_id != phase7g.pk:
            blockers.append(
                "phase7i_phase7h_lock_does_not_reference_supplied_phase7g_attempt"
            )
    if phase7g is not None and phase7d is not None:
        if phase7g.source_phase7d_attempt_id != phase7d.pk:
            blockers.append(
                "phase7i_phase7g_attempt_does_not_reference_supplied_phase7d_attempt"
            )
    return blockers


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def serialize_phase7i_final_audit_lock(
    row: RazorpayPhase7FinalAuditLock,
) -> dict[str, Any]:
    """Whitelisted serializer. NEVER returns raw token / phone /
    address / customer data / raw provider response / Director
    sign-off text."""
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sourcePhase7ELiveSendAttemptId": (
            row.source_phase7e_live_send_attempt_id
        ),
        "sourcePhase7GAttemptId": row.source_phase7g_attempt_id,
        "sourcePhase7HEvidenceLockId": (
            row.source_phase7h_evidence_lock_id
        ),
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        # Phase 7D snapshot
        "phase7DAttemptStatusSnapshot": (
            row.phase7d_attempt_status_snapshot
        ),
        "phase7DProviderObjectIdSnapshot": (
            row.phase7d_provider_object_id_snapshot
        ),
        "phase7DBusinessMutationWasMadeSnapshot": bool(
            row.phase7d_business_mutation_was_made_snapshot
        ),
        "phase7DCustomerNotificationSentSnapshot": bool(
            row.phase7d_customer_notification_sent_snapshot
        ),
        # Phase 7E-Live-A snapshot
        "phase7ELiveAttemptStatusSnapshot": (
            row.phase7e_live_attempt_status_snapshot
        ),
        "phase7ELiveProviderMessageIdSnapshot": (
            row.phase7e_live_provider_message_id_snapshot
        ),
        "phase7ELiveProviderStatusSnapshot": (
            row.phase7e_live_provider_status_snapshot
        ),
        "phase7ELiveTemplateNameSnapshot": (
            row.phase7e_live_template_name_snapshot
        ),
        "phase7ELiveTemplateLanguageSnapshot": (
            row.phase7e_live_template_language_snapshot
        ),
        "phase7ELiveAllowedRecipientLast4Snapshot": (
            row.phase7e_live_allowed_recipient_last4_snapshot
        ),
        "phase7ELiveRecipientScopeSnapshot": (
            row.phase7e_live_recipient_scope_snapshot
        ),
        "phase7ELiveWhatsAppMessageCreatedSnapshot": bool(
            row.phase7e_live_whatsapp_message_created_snapshot
        ),
        "phase7ELiveWhatsAppMessageQueuedSnapshot": bool(
            row.phase7e_live_whatsapp_message_queued_snapshot
        ),
        "phase7ELiveCustomerNotificationSentSnapshot": bool(
            row.phase7e_live_customer_notification_sent_snapshot
        ),
        "phase7ELiveBusinessMutationWasMadeSnapshot": bool(
            row.phase7e_live_business_mutation_was_made_snapshot
        ),
        "phase7ELiveRealCustomerPhoneUsedSnapshot": bool(
            row.phase7e_live_real_customer_phone_used_snapshot
        ),
        "phase7ELiveClaimVaultGroundedSnapshot": bool(
            row.phase7e_live_claim_vault_grounded_snapshot
        ),
        "phase7ELiveRecordedSignoffWindowValidSnapshot": (
            row.phase7e_live_recorded_signoff_window_valid_snapshot
        ),
        # Phase 7G snapshot
        "phase7GAttemptStatusSnapshot": (
            row.phase7g_attempt_status_snapshot
        ),
        "phase7GProviderObjectIdSnapshot": (
            row.phase7g_provider_object_id_snapshot
        ),
        "phase7GProviderStatusSnapshot": (
            row.phase7g_provider_status_snapshot
        ),
        "phase7GRollbackStatusSnapshot": (
            row.phase7g_rollback_status_snapshot
        ),
        "phase7GAwbCreatedSnapshot": bool(
            row.phase7g_awb_created_snapshot
        ),
        "phase7GShipmentCreatedSnapshot": bool(
            row.phase7g_shipment_created_snapshot
        ),
        "phase7GBusinessMutationWasMadeSnapshot": bool(
            row.phase7g_business_mutation_was_made_snapshot
        ),
        "phase7GCustomerNotificationSentSnapshot": bool(
            row.phase7g_customer_notification_sent_snapshot
        ),
        "phase7GRecordedSignoffWindowValidSnapshot": (
            row.phase7g_recorded_signoff_window_valid_snapshot
        ),
        # Phase 7H snapshot
        "phase7HEvidenceLockStatusSnapshot": (
            row.phase7h_evidence_lock_status_snapshot
        ),
        "phase7HProviderObjectIdSnapshot": (
            row.phase7h_provider_object_id_snapshot
        ),
        "phase7HShipmentCreatedSnapshot": bool(
            row.phase7h_shipment_created_snapshot
        ),
        "phase7HBusinessMutationWasMadeSnapshot": bool(
            row.phase7h_business_mutation_was_made_snapshot
        ),
        "phase7HCustomerNotificationSentSnapshot": bool(
            row.phase7h_customer_notification_sent_snapshot
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
    lock: RazorpayPhase7FinalAuditLock,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lock_id": lock.pk,
        "status": lock.status,
        "phase7d_attempt_id": lock.source_phase7d_attempt_id,
        "phase7e_live_send_attempt_id": (
            lock.source_phase7e_live_send_attempt_id
        ),
        "phase7g_attempt_id": lock.source_phase7g_attempt_id,
        "phase7h_evidence_lock_id": (
            lock.source_phase7h_evidence_lock_id
        ),
        "kill_switch_state_at_emit": _kill_switch_state(),
    }
    # Echo every locked-False snapshot field for parity.
    for field in _LOCKED_FALSE_SNAPSHOT_FIELDS:
        payload[field] = bool(getattr(lock, field, False))
    if extra:
        payload.update(extra)
    return _safe_audit_payload(payload)


# ---------------------------------------------------------------------------
# Evidence JSON composer
# ---------------------------------------------------------------------------


def _build_evidence_json(
    *,
    phase7d: RazorpayControlledPilotExecutionAttempt,
    phase7e_live: RazorpayWhatsAppInternalSendAttempt,
    phase7g: RazorpayCourierExecutionAttempt,
    phase7h: RazorpayCourierExecutionEvidenceLock,
) -> dict[str, Any]:
    return {
        "phase": "7I",
        "phase7d": {
            "attemptId": phase7d.pk,
            "status": phase7d.status,
            "providerObjectId": phase7d.provider_object_id or "",
            "executedAt": (
                phase7d.executed_at.isoformat()
                if phase7d.executed_at
                else None
            ),
            "rolledBackAt": (
                phase7d.rolled_back_at.isoformat()
                if phase7d.rolled_back_at
                else None
            ),
            "rollbackStatus": phase7d.rollback_status,
            "businessMutationWasMade": bool(
                phase7d.business_mutation_was_made
            ),
            "customerNotificationSent": bool(
                phase7d.customer_notification_sent
            ),
        },
        "phase7eLiveA": {
            "attemptId": phase7e_live.pk,
            "status": phase7e_live.status,
            "providerMessageId": (
                phase7e_live.provider_message_id or ""
            ),
            "providerStatus": phase7e_live.provider_status or "",
            "templateName": phase7e_live.template_name or "",
            "templateLanguage": (
                phase7e_live.template_language or ""
            ),
            "allowedRecipientLast4": (
                phase7e_live.allowed_recipient_last4 or ""
            ),
            "recipientScope": phase7e_live.recipient_scope,
            "whatsAppMessageCreated": bool(
                phase7e_live.whatsapp_message_created
            ),
            "whatsAppMessageQueued": bool(
                phase7e_live.whatsapp_message_queued
            ),
            "customerNotificationSent": False,
            "businessMutationWasMade": False,
            "realCustomerPhoneUsed": False,
            "claimVaultGrounded": bool(
                phase7e_live.claim_vault_grounded
            ),
            "recordedSignoffWindowValid": (
                phase7e_live.recorded_signoff_window_valid
            ),
            "executedAt": (
                phase7e_live.executed_at.isoformat()
                if phase7e_live.executed_at
                else None
            ),
            "rolledBackAt": (
                phase7e_live.rolled_back_at.isoformat()
                if phase7e_live.rolled_back_at
                else None
            ),
        },
        "phase7g": {
            "attemptId": phase7g.pk,
            "status": phase7g.status,
            "providerObjectId": phase7g.provider_object_id or "",
            "providerStatus": phase7g.provider_status or "",
            "rollbackStatus": phase7g.rollback_status,
            "awbCreated": bool(phase7g.awb_created),
            "shipmentCreated": False,
            "businessMutationWasMade": False,
            "customerNotificationSent": False,
            "recordedSignoffWindowValid": (
                phase7g.recorded_signoff_window_valid
            ),
            "executedAt": (
                phase7g.executed_at.isoformat()
                if phase7g.executed_at
                else None
            ),
            "rolledBackAt": (
                phase7g.rolled_back_at.isoformat()
                if phase7g.rolled_back_at
                else None
            ),
        },
        "phase7h": {
            "lockId": phase7h.pk,
            "status": phase7h.status,
            "providerObjectIdSnapshot": (
                phase7h.provider_object_id_snapshot or ""
            ),
            "shipmentCreatedSnapshot": False,
            "businessMutationWasMadeSnapshot": False,
            "customerNotificationSentSnapshot": False,
            "lockedAt": (
                phase7h.locked_at.isoformat()
                if phase7h.locked_at
                else None
            ),
        },
    }


# ---------------------------------------------------------------------------
# Eligibility composer
# ---------------------------------------------------------------------------


def _resolve_phase7e_live_attempt(
    phase7g: Optional[RazorpayCourierExecutionAttempt],
    explicit_id: Optional[int] = None,
) -> Optional[RazorpayWhatsAppInternalSendAttempt]:
    """Resolve the Phase 7E-Live-A attempt: prefer an explicitly
    supplied id; otherwise fall back to the latest
    `rollback_recorded` attempt against the Phase 7E gate the Phase
    7G attempt was sourced from.
    """
    if explicit_id is not None:
        return (
            RazorpayWhatsAppInternalSendAttempt.objects.filter(
                pk=explicit_id
            ).first()
        )
    if phase7g is None or phase7g.source_phase7e_gate_id is None:
        return None
    return (
        RazorpayWhatsAppInternalSendAttempt.objects.filter(
            source_phase7e_gate_id=phase7g.source_phase7e_gate_id,
            status=RazorpayWhatsAppInternalSendAttempt.Status.ROLLBACK_RECORDED,
        )
        .exclude(provider_message_id="")
        .order_by("-rolled_back_at", "-created_at")
        .first()
    )


def _validate_eligibility(
    *,
    phase7d_attempt_id: Optional[int] = None,
    phase7e_live_attempt_id: Optional[int] = None,
    phase7g_attempt_id: Optional[int] = None,
    phase7h_evidence_lock_id: Optional[int] = None,
) -> dict[str, Any]:
    """Resolve + validate the four source records. Returns a dict
    carrying the resolved rows and the blocker list."""
    phase7g = (
        RazorpayCourierExecutionAttempt.objects.filter(
            pk=phase7g_attempt_id
        ).first()
        if phase7g_attempt_id
        else None
    )
    phase7h = (
        RazorpayCourierExecutionEvidenceLock.objects.filter(
            pk=phase7h_evidence_lock_id
        ).first()
        if phase7h_evidence_lock_id
        else None
    )
    phase7d = (
        RazorpayControlledPilotExecutionAttempt.objects.filter(
            pk=phase7d_attempt_id
        ).first()
        if phase7d_attempt_id
        else None
    )
    # If Phase 7D was not explicitly supplied, derive from Phase 7G.
    if phase7d is None and phase7g is not None:
        phase7d = phase7g.source_phase7d_attempt
    phase7e_live = _resolve_phase7e_live_attempt(
        phase7g, phase7e_live_attempt_id
    )

    blockers: list[str] = []
    blockers += _validate_phase7d_attempt(phase7d)
    blockers += _validate_phase7e_live_attempt(phase7e_live)
    blockers += _validate_phase7g_attempt(phase7g)
    blockers += _validate_phase7h_evidence_lock(phase7h)
    blockers += _validate_chain_consistency(
        phase7e_live=phase7e_live,
        phase7g=phase7g,
        phase7h=phase7h,
        phase7d=phase7d,
    )

    return {
        "phase7d": phase7d,
        "phase7e_live": phase7e_live,
        "phase7g": phase7g,
        "phase7h": phase7h,
        "blockers": blockers,
        "eligible": not blockers,
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7i_final_audit_lock(
    *,
    phase7g_attempt_id: int,
    phase7h_evidence_lock_id: int,
    phase7e_live_attempt_id: Optional[int] = None,
    phase7d_attempt_id: Optional[int] = None,
) -> dict[str, Any]:
    """Read-only preview. NEVER creates rows; NEVER calls any
    provider."""
    eligibility = _validate_eligibility(
        phase7d_attempt_id=phase7d_attempt_id,
        phase7e_live_attempt_id=phase7e_live_attempt_id,
        phase7g_attempt_id=phase7g_attempt_id,
        phase7h_evidence_lock_id=phase7h_evidence_lock_id,
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=(
            f"Phase 7I preview phase7g={phase7g_attempt_id} "
            f"phase7h={phase7h_evidence_lock_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7d_attempt_id": phase7d_attempt_id,
                "phase7e_live_attempt_id": phase7e_live_attempt_id,
                "phase7g_attempt_id": phase7g_attempt_id,
                "phase7h_evidence_lock_id": phase7h_evidence_lock_id,
                "eligible": eligibility["eligible"],
                "blockers": list(eligibility["blockers"]),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    evidence: dict[str, Any] = {}
    if eligibility["eligible"]:
        evidence = _build_evidence_json(
            phase7d=eligibility["phase7d"],
            phase7e_live=eligibility["phase7e_live"],
            phase7g=eligibility["phase7g"],
            phase7h=eligibility["phase7h"],
        )
    return {
        "phase": "7I",
        "eligible": eligibility["eligible"],
        "blockers": list(eligibility["blockers"]),
        "warnings": [PHASE_7I_WARNING],
        "phase7DAttemptId": (
            eligibility["phase7d"].pk
            if eligibility["phase7d"]
            else None
        ),
        "phase7ELiveAttemptId": (
            eligibility["phase7e_live"].pk
            if eligibility["phase7e_live"]
            else None
        ),
        "phase7GAttemptId": (
            eligibility["phase7g"].pk
            if eligibility["phase7g"]
            else None
        ),
        "phase7HEvidenceLockId": (
            eligibility["phase7h"].pk
            if eligibility["phase7h"]
            else None
        ),
        "evidence": evidence,
        "nextAction": (
            "ready_to_prepare_phase7i_final_audit_lock"
            if eligibility["eligible"]
            else "fix_phase7i_eligibility_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase7i_final_audit_lock(
    *,
    phase7g_attempt_id: int,
    phase7h_evidence_lock_id: int,
    phase7e_live_attempt_id: Optional[int] = None,
    phase7d_attempt_id: Optional[int] = None,
) -> dict[str, Any]:
    """Atomic + idempotent prepare. NEVER calls any provider; NEVER
    mutates real business rows; NEVER edits any ``.env*`` file.
    """
    eligibility = _validate_eligibility(
        phase7d_attempt_id=phase7d_attempt_id,
        phase7e_live_attempt_id=phase7e_live_attempt_id,
        phase7g_attempt_id=phase7g_attempt_id,
        phase7h_evidence_lock_id=phase7h_evidence_lock_id,
    )

    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7I prepare blocked kill-switch off "
                f"phase7g={phase7g_attempt_id} "
                f"phase7h={phase7h_evidence_lock_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7g_attempt_id": phase7g_attempt_id,
                    "phase7h_evidence_lock_id": phase7h_evidence_lock_id,
                    "blockers": ["runtime_kill_switch_disabled"],
                    "kill_switch_state_at_emit": kill,
                }
            ),
        )
        return {
            "phase": "7I",
            "created": False,
            "reused": False,
            "lock": None,
            "blockers": ["runtime_kill_switch_disabled"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "fix_phase7i_eligibility_blockers",
        }

    if not eligibility["eligible"]:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7I prepare blocked "
                f"phase7g={phase7g_attempt_id} "
                f"phase7h={phase7h_evidence_lock_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7d_attempt_id": phase7d_attempt_id,
                    "phase7e_live_attempt_id": phase7e_live_attempt_id,
                    "phase7g_attempt_id": phase7g_attempt_id,
                    "phase7h_evidence_lock_id": phase7h_evidence_lock_id,
                    "blockers": list(eligibility["blockers"]),
                }
            ),
        )
        return {
            "phase": "7I",
            "created": False,
            "reused": False,
            "lock": None,
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "fix_phase7i_eligibility_blockers",
        }

    phase7d = eligibility["phase7d"]
    phase7e_live = eligibility["phase7e_live"]
    phase7g = eligibility["phase7g"]
    phase7h = eligibility["phase7h"]
    before = _business_row_counts()

    with transaction.atomic():
        existing = (
            RazorpayPhase7FinalAuditLock.objects.filter(
                source_phase7h_evidence_lock=phase7h
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "7I",
                "created": False,
                "reused": True,
                "lock": serialize_phase7i_final_audit_lock(existing),
                "blockers": [],
                "warnings": [PHASE_7I_WARNING],
                "nextAction": (
                    "phase7i_lock_pending_manual_review"
                    if existing.status
                    == RazorpayPhase7FinalAuditLock.Status.PENDING_MANUAL_REVIEW
                    else f"phase7i_lock_status_{existing.status}"
                ),
            }

        lock = RazorpayPhase7FinalAuditLock(
            source_phase7d_attempt=phase7d,
            source_phase7e_live_send_attempt=phase7e_live,
            source_phase7g_attempt=phase7g,
            source_phase7h_evidence_lock=phase7h,
            source_phase6t_lock=getattr(
                phase7g, "source_phase6t_lock", None
            ),
            status=(
                RazorpayPhase7FinalAuditLock.Status.PENDING_MANUAL_REVIEW
            ),
            # Phase 7D snapshot.
            phase7d_attempt_status_snapshot=phase7d.status[:64],
            phase7d_provider_object_id_snapshot=(
                phase7d.provider_object_id or ""
            )[:64],
            phase7d_business_mutation_was_made_snapshot=bool(
                phase7d.business_mutation_was_made
            ),
            phase7d_customer_notification_sent_snapshot=bool(
                phase7d.customer_notification_sent
            ),
            # Phase 7E-Live-A snapshot.
            phase7e_live_attempt_status_snapshot=(
                phase7e_live.status[:64]
            ),
            phase7e_live_provider_message_id_snapshot=(
                phase7e_live.provider_message_id or ""
            )[:64],
            phase7e_live_provider_status_snapshot=(
                phase7e_live.provider_status or ""
            )[:64],
            phase7e_live_template_name_snapshot=(
                phase7e_live.template_name or ""
            )[:120],
            phase7e_live_template_language_snapshot=(
                phase7e_live.template_language or ""
            )[:16],
            phase7e_live_allowed_recipient_last4_snapshot=(
                phase7e_live.allowed_recipient_last4 or ""
            )[:8],
            phase7e_live_recipient_scope_snapshot=(
                phase7e_live.recipient_scope or ""
            )[:40],
            phase7e_live_whatsapp_message_created_snapshot=bool(
                phase7e_live.whatsapp_message_created
            ),
            phase7e_live_whatsapp_message_queued_snapshot=bool(
                phase7e_live.whatsapp_message_queued
            ),
            phase7e_live_customer_notification_sent_snapshot=bool(
                phase7e_live.customer_notification_sent
            ),
            phase7e_live_business_mutation_was_made_snapshot=bool(
                phase7e_live.business_mutation_was_made
            ),
            phase7e_live_real_customer_phone_used_snapshot=bool(
                phase7e_live.real_customer_phone_used
            ),
            phase7e_live_claim_vault_grounded_snapshot=bool(
                phase7e_live.claim_vault_grounded
            ),
            phase7e_live_recorded_signoff_window_valid_snapshot=(
                phase7e_live.recorded_signoff_window_valid
            ),
            # Phase 7G snapshot.
            phase7g_attempt_status_snapshot=phase7g.status[:64],
            phase7g_provider_object_id_snapshot=(
                phase7g.provider_object_id or ""
            )[:64],
            phase7g_provider_status_snapshot=(
                phase7g.provider_status or ""
            )[:64],
            phase7g_rollback_status_snapshot=(
                phase7g.rollback_status or ""
            )[:40],
            phase7g_awb_created_snapshot=bool(phase7g.awb_created),
            phase7g_shipment_created_snapshot=bool(
                phase7g.shipment_created
            ),
            phase7g_business_mutation_was_made_snapshot=bool(
                phase7g.business_mutation_was_made
            ),
            phase7g_customer_notification_sent_snapshot=bool(
                phase7g.customer_notification_sent
            ),
            phase7g_recorded_signoff_window_valid_snapshot=(
                phase7g.recorded_signoff_window_valid
            ),
            # Phase 7H snapshot.
            phase7h_evidence_lock_status_snapshot=phase7h.status[:40],
            phase7h_provider_object_id_snapshot=(
                phase7h.provider_object_id_snapshot or ""
            )[:64],
            phase7h_shipment_created_snapshot=bool(
                phase7h.shipment_created_snapshot
            ),
            phase7h_business_mutation_was_made_snapshot=bool(
                phase7h.business_mutation_was_made_snapshot
            ),
            phase7h_customer_notification_sent_snapshot=bool(
                phase7h.customer_notification_sent_snapshot
            ),
            evidence_json=_build_evidence_json(
                phase7d=phase7d,
                phase7e_live=phase7e_live,
                phase7g=phase7g,
                phase7h=phase7h,
            ),
            blockers=[],
            warnings=[PHASE_7I_WARNING],
            next_action="phase7i_lock_pending_manual_review",
        )
        assert_phase7i_no_provider_or_business_mutation(
            lock, before_counts=before
        )
        try:
            lock.save()
        except IntegrityError:  # pragma: no cover - defensive
            lock = (
                RazorpayPhase7FinalAuditLock.objects.filter(
                    source_phase7h_evidence_lock=phase7h
                ).first()
            )
            return {
                "phase": "7I",
                "created": False,
                "reused": True,
                "lock": (
                    serialize_phase7i_final_audit_lock(lock)
                    if lock
                    else None
                ),
                "blockers": [],
                "warnings": [PHASE_7I_WARNING],
                "nextAction": "phase7i_lock_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 7I final audit lock prepared lock_id={lock.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(lock),
    )
    return {
        "phase": "7I",
        "created": True,
        "reused": False,
        "lock": serialize_phase7i_final_audit_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7I_WARNING],
        "nextAction": "phase7i_lock_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


def _lookup(
    lock_id: int,
) -> Optional[RazorpayPhase7FinalAuditLock]:
    return (
        RazorpayPhase7FinalAuditLock.objects.filter(
            pk=lock_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def approve_phase7i_final_audit_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Flip status to ``locked``. Non-empty reason required."""
    if not reason.strip():
        return {
            "phase": "7I",
            "ok": False,
            "lock": None,
            "blockers": ["phase7i_approve_reason_required"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _lookup(lock_id)
    if lock is None:
        return {
            "phase": "7I",
            "ok": False,
            "lock": None,
            "blockers": ["phase7i_lock_not_found"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "verify_lock_id",
        }
    if (
        lock.status
        != RazorpayPhase7FinalAuditLock.Status.PENDING_MANUAL_REVIEW
    ):
        return {
            "phase": "7I",
            "ok": False,
            "lock": serialize_phase7i_final_audit_lock(lock),
            "blockers": [
                f"phase7i_lock_status_{lock.status}_not_transitionable_to_locked"
            ],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "verify_lock_status",
        }

    before = _business_row_counts()
    assert_phase7i_no_provider_or_business_mutation(
        lock, before_counts=before
    )

    lock.status = RazorpayPhase7FinalAuditLock.Status.LOCKED
    lock.locked_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.review_reason = (reason or "")[:1000]
    lock.next_action = "phase7i_lock_locked"
    lock.save()

    write_event(
        kind=AUDIT_KIND_LOCKED,
        text=f"Phase 7I final audit locked lock_id={lock.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "7I",
        "ok": True,
        "lock": serialize_phase7i_final_audit_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7I_WARNING],
        "nextAction": "phase7i_lock_locked",
    }


def reject_phase7i_final_audit_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7I",
            "ok": False,
            "lock": None,
            "blockers": ["phase7i_reject_reason_required"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _lookup(lock_id)
    if lock is None:
        return {
            "phase": "7I",
            "ok": False,
            "lock": None,
            "blockers": ["phase7i_lock_not_found"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status not in {
        RazorpayPhase7FinalAuditLock.Status.DRAFT,
        RazorpayPhase7FinalAuditLock.Status.PENDING_MANUAL_REVIEW,
        RazorpayPhase7FinalAuditLock.Status.BLOCKED,
    }:
        return {
            "phase": "7I",
            "ok": False,
            "lock": serialize_phase7i_final_audit_lock(lock),
            "blockers": [
                f"phase7i_reject_refused_for_status_{lock.status}"
            ],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "verify_lock_status",
        }

    before = _business_row_counts()
    assert_phase7i_no_provider_or_business_mutation(
        lock, before_counts=before
    )
    lock.status = RazorpayPhase7FinalAuditLock.Status.REJECTED
    lock.rejected_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.reject_reason = (reason or "")[:1000]
    lock.next_action = "phase7i_lock_rejected"
    lock.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 7I final audit rejected lock_id={lock.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "7I",
        "ok": True,
        "lock": serialize_phase7i_final_audit_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7I_WARNING],
        "nextAction": "phase7i_lock_rejected",
    }


def archive_phase7i_final_audit_lock(
    lock_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7I",
            "ok": False,
            "lock": None,
            "blockers": ["phase7i_archive_reason_required"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "supply_reason",
        }
    lock = _lookup(lock_id)
    if lock is None:
        return {
            "phase": "7I",
            "ok": False,
            "lock": None,
            "blockers": ["phase7i_lock_not_found"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "verify_lock_id",
        }
    if lock.status == RazorpayPhase7FinalAuditLock.Status.ARCHIVED:
        return {
            "phase": "7I",
            "ok": False,
            "lock": serialize_phase7i_final_audit_lock(lock),
            "blockers": ["phase7i_lock_already_archived"],
            "warnings": [PHASE_7I_WARNING],
            "nextAction": "verify_lock_status",
        }
    before = _business_row_counts()
    assert_phase7i_no_provider_or_business_mutation(
        lock, before_counts=before
    )
    lock.status = RazorpayPhase7FinalAuditLock.Status.ARCHIVED
    lock.archived_at = timezone.now()
    lock.reviewed_by = reviewed_by
    lock.reviewed_by_username = _reviewer_username(reviewed_by)
    lock.reviewed_at = timezone.now()
    lock.archive_reason = (reason or "")[:1000]
    lock.next_action = "phase7i_lock_archived"
    lock.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 7I final audit archived lock_id={lock.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_lock_payload(
            lock, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "7I",
        "ok": True,
        "lock": serialize_phase7i_final_audit_lock(lock),
        "blockers": [],
        "warnings": [PHASE_7I_WARNING],
        "nextAction": "phase7i_lock_archived",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase7i_final_audit_locks(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpayPhase7FinalAuditLock.objects.all().order_by(
        "-created_at"
    )
    statuses = [s.value for s in RazorpayPhase7FinalAuditLock.Status]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase7i_final_audit_lock(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "7I", "counts": counts, "items": items}


def _count_eligible_phase7h_locks() -> int:
    """Phase 7H locks that are in ``locked`` status and not yet
    referenced by a Phase 7I row are the pool of available source
    locks."""
    locked_ids = list(
        RazorpayCourierExecutionEvidenceLock.objects.filter(
            status=RazorpayCourierExecutionEvidenceLock.Status.LOCKED,
        ).values_list("pk", flat=True)
    )
    if not locked_ids:
        return 0
    used = set(
        RazorpayPhase7FinalAuditLock.objects.filter(
            source_phase7h_evidence_lock_id__in=locked_ids,
        ).values_list("source_phase7h_evidence_lock_id", flat=True)
    )
    return sum(1 for pk in locked_ids if pk not in used)


def inspect_phase7i_final_audit_lock_readiness() -> dict[str, Any]:
    summary = summarize_phase7i_final_audit_locks(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    eligible_phase7h_locks = _count_eligible_phase7h_locks()
    eligible_phase7e_live_attempts = (
        RazorpayWhatsAppInternalSendAttempt.objects.filter(
            status=RazorpayWhatsAppInternalSendAttempt.Status.ROLLBACK_RECORDED,
            whatsapp_message_created=True,
            recorded_signoff_window_valid=True,
            customer_notification_sent=False,
            business_mutation_was_made=False,
            real_customer_phone_used=False,
        )
        .exclude(provider_message_id="")
        .count()
    )
    eligible_phase7g_attempts = (
        RazorpayCourierExecutionAttempt.objects.filter(
            status=RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED,
            provider_call_attempted=True,
            delhivery_call_attempted=True,
            awb_created=True,
            shipment_created=False,
            business_mutation_was_made=False,
            customer_notification_sent=False,
        ).count()
    )

    blockers: list[str] = []
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    if blockers:
        next_action = "fix_phase7i_safety_blockers"
    elif (
        eligible_phase7h_locks == 0
        or eligible_phase7e_live_attempts == 0
        or eligible_phase7g_attempts == 0
    ):
        next_action = "no_eligible_source_chain_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase7i_locks_pending_manual_review"
    elif counts.get("locked", 0) > 0:
        next_action = "phase7i_locks_locked"
    else:
        next_action = "ready_to_prepare_phase7i_final_audit_lock"

    return {
        "phase": "7I",
        "status": "final_phase7_audit_lock_only",
        "latestCompletedPhase": "7H",
        "nextPhase": (
            "phase7i_locked_or_phase7_live_not_approved"
        ),
        "killSwitch": kill,
        "eligiblePhase7HEvidenceLockCount": eligible_phase7h_locks,
        "eligiblePhase7ELiveAttemptCount": (
            eligible_phase7e_live_attempts
        ),
        "eligiblePhase7GAttemptCount": eligible_phase7g_attempts,
        "phase7ILockCounts": counts,
        "items": summary["items"],
        "phase7ICallsRazorpay": False,
        "phase7ICallsMetaCloud": False,
        "phase7ICallsDelhivery": False,
        "phase7ICallsVapi": False,
        "phase7ISendsWhatsApp": False,
        "phase7IQueuesWhatsApp": False,
        "phase7ICreatesShipmentRow": False,
        "phase7ICreatesAwb": False,
        "phase7ICreatesPaymentLink": False,
        "phase7ICapturesPayment": False,
        "phase7IRefundsPayment": False,
        "phase7ISendsCustomerNotification": False,
        "phase7IMutatesBusinessRow": False,
        "phase7ELiveBApproved": False,
        "phase7GLiveApproved": False,
        "executionPath": "lock_only_cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_7I_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_7I_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7I final audit lock readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase7h_lock_count": int(
                    report.get("eligiblePhase7HEvidenceLockCount") or 0
                ),
                "eligible_phase7e_live_attempt_count": int(
                    report.get("eligiblePhase7ELiveAttemptCount") or 0
                ),
                "eligible_phase7g_attempt_count": int(
                    report.get("eligiblePhase7GAttemptCount") or 0
                ),
                "lock_counts": report.get("phase7ILockCounts") or {},
                "next_action": report.get("nextAction") or "",
                "kill_switch_enabled": (
                    report.get("killSwitch", {}) or {}
                ).get("enabled", True),
            }
        ),
    )


__all__ = (
    "PHASE_7I_WARNING",
    "PHASE_7I_FORBIDDEN_ACTIONS",
    "PHASE_7I_FORBIDDEN_PAYLOAD_KEYS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_LOCKED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "assert_phase7i_no_provider_or_business_mutation",
    "preview_phase7i_final_audit_lock",
    "prepare_phase7i_final_audit_lock",
    "approve_phase7i_final_audit_lock",
    "reject_phase7i_final_audit_lock",
    "archive_phase7i_final_audit_lock",
    "inspect_phase7i_final_audit_lock_readiness",
    "summarize_phase7i_final_audit_locks",
    "serialize_phase7i_final_audit_lock",
    "emit_readiness_inspected_audit",
)
