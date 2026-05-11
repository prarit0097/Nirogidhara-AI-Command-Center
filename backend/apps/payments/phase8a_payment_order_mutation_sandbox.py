"""Phase 8A - Payment -> Order Mutation Sandbox Gate.

Phase 8A is **sandbox / dry-run only**. It designs and dry-runs how
a verified Razorpay paid/test evidence (Phase 7D + 7I locked
audit) could map to a synthetic / test Order status change in
*future* phases. Phase 8A NEVER calls Razorpay / Meta Cloud /
Delhivery / Vapi, NEVER sends or queues WhatsApp, NEVER creates a
``Shipment`` / AWB / payment link, NEVER captures / refunds, NEVER
sends a customer notification, NEVER mutates real ``Order`` /
``Payment`` / ``Customer`` / ``Lead`` / ``Shipment`` /
``DiscountOfferLog`` rows, NEVER edits any ``.env*`` file.

Approval flips status to ``approved_for_future_phase8b_review``
only -- it does NOT authorize any real mutation.

Public surface:

- :func:`inspect_phase8a_payment_order_mutation_sandbox_readiness`
- :func:`preview_phase8a_payment_order_mutation_sandbox`
- :func:`prepare_phase8a_payment_order_mutation_sandbox`
- :func:`dry_run_phase8a_payment_order_mutation_sandbox`
- :func:`rollback_dry_run_phase8a_payment_order_mutation_sandbox`
- :func:`approve_phase8a_payment_order_mutation_sandbox`
- :func:`reject_phase8a_payment_order_mutation_sandbox`
- :func:`archive_phase8a_payment_order_mutation_sandbox`
- :func:`assert_phase8a_no_business_mutation`
- :func:`serialize_phase8a_gate`
- :func:`serialize_phase8a_dry_run`
- :func:`summarize_phase8a_gates`
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
    RazorpayPaymentOrderMutationDryRun,
    RazorpayPaymentOrderMutationSandboxGate,
    RazorpayPhase7FinalAuditLock,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_8A_WARNING = (
    "Phase 8A is the Payment -> Order Mutation Sandbox Gate. It is "
    "sandbox / dry-run only. Approval flips status to "
    "`approved_for_future_phase8b_review` and freezes the design "
    "contract. Phase 8A NEVER calls Razorpay / Meta Cloud / "
    "Delhivery / Vapi, NEVER sends or queues WhatsApp, NEVER "
    "creates a Shipment / AWB / payment link, NEVER captures, "
    "NEVER refunds, NEVER sends a customer notification, NEVER "
    "mutates real Order / Payment / Customer / Lead / Shipment / "
    "DiscountOfferLog rows, NEVER edits any .env file. "
    "Phase 7E-Live-B (real customer WhatsApp send) and Phase "
    "7G-Live (real customer courier execution) remain NOT "
    "approved; real-customer automation remains NOT approved."
)


AUDIT_KIND_READINESS = "phase8a.payment_order.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase8a.payment_order.previewed"
AUDIT_KIND_PREPARED = "phase8a.payment_order.prepared"
AUDIT_KIND_DRY_RUN_PASSED = "phase8a.payment_order.dry_run_passed"
AUDIT_KIND_DRY_RUN_FAILED = "phase8a.payment_order.dry_run_failed"
AUDIT_KIND_ROLLBACK_RECORDED = (
    "phase8a.payment_order.rollback_recorded"
)
AUDIT_KIND_APPROVED = "phase8a.payment_order.approved"
AUDIT_KIND_REJECTED = "phase8a.payment_order.rejected"
AUDIT_KIND_ARCHIVED = "phase8a.payment_order.archived"
AUDIT_KIND_BLOCKED = "phase8a.payment_order.blocked"


PHASE_8A_FORBIDDEN_ACTIONS: tuple[str, ...] = (
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
    "approve_via_api_endpoint",
    "reject_via_api_endpoint",
    "execute_via_api_endpoint",
    "archive_via_api_endpoint",
    "dry_run_via_api_endpoint",
    "edit_dotenv_any",
)


PHASE_8A_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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


# Locked-False contract fields on the Phase 8A gate row. The gate
# row itself is *defined* with these as False at the model layer;
# the guard re-checks them at every state transition.
_GATE_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "real_business_mutation_allowed",
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
    "would_send_customer_notification",
    "would_send_whatsapp",
    "would_call_courier",
)


# Synthetic-only reference markers; dry-run input MUST match.
_SYNTHETIC_REFERENCE_PREFIXES: tuple[str, ...] = (
    "phase8a::sandbox::",
    "phase8a-sandbox-",
    "sandbox::",
)


# ---------------------------------------------------------------------------
# Flag readers (read-only)
# ---------------------------------------------------------------------------


def _flag_phase8a_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED",
            False,
        )
    )


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
    safe: dict[str, Any] = {"phase": "8A"}
    forbidden = set(PHASE_8A_FORBIDDEN_PAYLOAD_KEYS)
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
# Defensive guard
# ---------------------------------------------------------------------------


def assert_phase8a_no_business_mutation(
    gate: RazorpayPaymentOrderMutationSandboxGate,
    *,
    before_counts: Optional[dict[str, int]] = None,
    dry_run: Optional[RazorpayPaymentOrderMutationDryRun] = None,
) -> None:
    """Refuse if any of the locked-False contract booleans on the
    gate or dry-run has flipped True, or if any business-row count
    has moved between ``before_counts`` and the current snapshot.
    Emits an invariant-violation audit row + raises ``ValueError``.
    """
    flipped: list[str] = []
    for field in _GATE_LOCKED_FALSE_FIELDS:
        if getattr(gate, field, False) is True:
            flipped.append(f"gate.{field}")
    # The two "True by design" gate fields must stay True.
    if gate.sandbox_only is False:
        flipped.append("gate.sandbox_only_must_be_true")
    if gate.synthetic_order_required is False:
        flipped.append("gate.synthetic_order_required_must_be_true")
    if dry_run is not None:
        for field in _DRY_RUN_LOCKED_FALSE_FIELDS:
            if getattr(dry_run, field, False) is True:
                flipped.append(f"dry_run.{field}")

    delta_keys: list[str] = []
    if before_counts is not None:
        current = _business_row_counts()
        for key, count_before in before_counts.items():
            count_after = current.get(key, count_before)
            if count_after != count_before:
                delta_keys.append(
                    f"phase8a_business_row_count_changed_for_{key}"
                )

    if not flipped and not delta_keys:
        return

    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=f"Phase 8A invariant violation gate_id={gate.pk}",
        tone=AuditEvent.Tone.DANGER,
        payload=_safe_audit_payload(
            {
                "gate_id": gate.pk,
                "dry_run_id": getattr(dry_run, "pk", None),
                "flipped_locked_false_contract": flipped,
                "business_row_count_deltas": delta_keys,
            }
        ),
    )
    raise ValueError(
        "Phase 8A invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_phase7i_lock(
    lock: Optional[RazorpayPhase7FinalAuditLock],
) -> list[str]:
    blockers: list[str] = []
    if lock is None:
        blockers.append("phase8a_source_phase7i_lock_not_found")
        return blockers
    if lock.status != RazorpayPhase7FinalAuditLock.Status.LOCKED:
        blockers.append(
            f"phase8a_source_phase7i_lock_status_must_be_locked_was_{lock.status}"
        )
    for snapshot_field in (
        "phase7d_business_mutation_was_made_snapshot",
        "phase7d_customer_notification_sent_snapshot",
        "phase7e_live_business_mutation_was_made_snapshot",
        "phase7e_live_customer_notification_sent_snapshot",
        "phase7e_live_real_customer_phone_used_snapshot",
        "phase7g_business_mutation_was_made_snapshot",
        "phase7g_shipment_created_snapshot",
        "phase7g_customer_notification_sent_snapshot",
        "phase7h_business_mutation_was_made_snapshot",
        "phase7h_shipment_created_snapshot",
        "phase7h_customer_notification_sent_snapshot",
    ):
        if getattr(lock, snapshot_field, False):
            blockers.append(
                f"phase8a_phase7i_lock_{snapshot_field}_must_be_false"
            )
    return blockers


def _validate_eligibility(
    *,
    phase7i_lock_id: Optional[int],
    require_env_flag: bool = True,
) -> dict[str, Any]:
    blockers: list[str] = []
    if require_env_flag and not _flag_phase8a_enabled():
        blockers.append(
            "PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED_must_be_true"
        )
    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    lock: Optional[RazorpayPhase7FinalAuditLock] = None
    if phase7i_lock_id:
        lock = (
            RazorpayPhase7FinalAuditLock.objects.filter(
                pk=phase7i_lock_id
            )
            .select_related(
                "source_phase7d_attempt",
                "source_phase7e_live_send_attempt",
                "source_phase7g_attempt",
                "source_phase7h_evidence_lock",
            )
            .first()
        )
    blockers += _validate_phase7i_lock(lock)

    phase7d = (
        lock.source_phase7d_attempt if lock is not None else None
    )
    return {
        "phase7i_lock": lock,
        "phase7d": phase7d,
        "blockers": blockers,
        "eligible": not blockers,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_phase8a_gate(
    row: RazorpayPaymentOrderMutationSandboxGate,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sandboxOnly": bool(row.sandbox_only),
        "realBusinessMutationAllowed": bool(
            row.real_business_mutation_allowed
        ),
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
        "syntheticOrderRequired": bool(row.synthetic_order_required),
        "manualReviewRequired": bool(row.manual_review_required),
        "claimVaultNotRequiredForPaymentStatus": bool(
            row.claim_vault_not_required_for_payment_status
        ),
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


def serialize_phase8a_dry_run(
    row: RazorpayPaymentOrderMutationDryRun,
) -> dict[str, Any]:
    return {
        "id": row.pk,
        "gateId": row.gate_id,
        "sourcePhase7ILockId": row.source_phase7i_lock_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "proposedSourcePaymentReference": (
            row.proposed_source_payment_reference
        ),
        "proposedTargetOrderReference": (
            row.proposed_target_order_reference
        ),
        "proposedTargetOrderIsSynthetic": bool(
            row.proposed_target_order_is_synthetic
        ),
        "proposedOldOrderStatus": row.proposed_old_order_status,
        "proposedNewOrderStatus": row.proposed_new_order_status,
        "proposedOldPaymentStatus": row.proposed_old_payment_status,
        "proposedNewPaymentStatus": row.proposed_new_payment_status,
        "wouldMutateOrder": bool(row.would_mutate_order),
        "wouldMutatePayment": bool(row.would_mutate_payment),
        "wouldSendCustomerNotification": bool(
            row.would_send_customer_notification
        ),
        "wouldSendWhatsApp": bool(row.would_send_whatsapp),
        "wouldCallCourier": bool(row.would_call_courier),
        "beforeCounts": row.before_counts or {},
        "afterCounts": row.after_counts or {},
        "countDeltas": row.count_deltas or {},
        "passed": bool(row.passed),
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
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
    gate: RazorpayPaymentOrderMutationSandboxGate,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gate_id": gate.pk,
        "status": gate.status,
        "phase7i_lock_id": gate.source_phase7i_lock_id,
        "phase7d_attempt_id": gate.source_phase7d_attempt_id,
        "sandbox_only": bool(gate.sandbox_only),
        "real_business_mutation_allowed": False,
        "real_order_mutation_allowed": False,
        "real_payment_mutation_allowed": False,
        "customer_notification_allowed": False,
        "whatsapp_allowed": False,
        "courier_allowed": False,
        "synthetic_order_required": True,
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
    phase7i_lock: RazorpayPhase7FinalAuditLock,
    phase7d: Optional[RazorpayControlledPilotExecutionAttempt],
) -> dict[str, Any]:
    return {
        "phase": "8A",
        "phase7i": {
            "lockId": phase7i_lock.pk,
            "status": phase7i_lock.status,
            "phase7dAttemptId": phase7i_lock.source_phase7d_attempt_id,
            "phase7eLiveSendAttemptId": (
                phase7i_lock.source_phase7e_live_send_attempt_id
            ),
            "phase7gAttemptId": phase7i_lock.source_phase7g_attempt_id,
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
        "sandboxContract": {
            "sandboxOnly": True,
            "realBusinessMutationAllowed": False,
            "realOrderMutationAllowed": False,
            "realPaymentMutationAllowed": False,
            "customerNotificationAllowed": False,
            "whatsAppAllowed": False,
            "courierAllowed": False,
            "syntheticOrderRequired": True,
            "manualReviewRequired": True,
            "claimVaultNotRequiredForPaymentStatus": True,
        },
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase8a_payment_order_mutation_sandbox(
    phase7i_lock_id: int,
) -> dict[str, Any]:
    eligibility = _validate_eligibility(
        phase7i_lock_id=phase7i_lock_id, require_env_flag=False
    )
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 8A preview phase7i_lock_id={phase7i_lock_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7i_lock_id": phase7i_lock_id,
                "eligible": eligibility["eligible"],
                "blockers": list(eligibility["blockers"]),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    evidence: dict[str, Any] = {}
    if (
        eligibility["eligible"]
        and eligibility["phase7i_lock"] is not None
    ):
        evidence = _build_evidence_json(
            phase7i_lock=eligibility["phase7i_lock"],
            phase7d=eligibility["phase7d"],
        )
    return {
        "phase": "8A",
        "found": eligibility["phase7i_lock"] is not None,
        "sourcePhase7ILockId": phase7i_lock_id,
        "sourcePhase7DAttemptId": (
            eligibility["phase7d"].pk
            if eligibility["phase7d"]
            else None
        ),
        "eligible": eligibility["eligible"],
        "blockers": list(eligibility["blockers"]),
        "warnings": [PHASE_8A_WARNING],
        "evidence": evidence,
        "nextAction": (
            "ready_to_prepare_phase8a_payment_order_mutation_sandbox_gate"
            if eligibility["eligible"]
            and _flag_phase8a_enabled()
            else (
                "fix_phase8a_eligibility_blockers_or_enable_phase8a_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def prepare_phase8a_payment_order_mutation_sandbox(
    phase7i_lock_id: int,
) -> dict[str, Any]:
    """Atomic + idempotent prepare on the source Phase 7I lock.
    NEVER calls any provider; NEVER mutates business rows; NEVER
    edits any ``.env*`` file.
    """
    eligibility = _validate_eligibility(
        phase7i_lock_id=phase7i_lock_id, require_env_flag=True
    )
    if (
        not eligibility["eligible"]
        or eligibility["phase7i_lock"] is None
    ):
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 8A prepare blocked phase7i_lock_id="
                f"{phase7i_lock_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7i_lock_id": phase7i_lock_id,
                    "blockers": list(eligibility["blockers"]),
                    "kill_switch_state_at_emit": _kill_switch_state(),
                }
            ),
        )
        return {
            "phase": "8A",
            "created": False,
            "reused": False,
            "gate": None,
            "blockers": list(eligibility["blockers"]),
            "warnings": [PHASE_8A_WARNING],
            "nextAction": (
                "fix_phase8a_eligibility_blockers_or_enable_phase8a_flag"
            ),
        }

    phase7i_lock = eligibility["phase7i_lock"]
    phase7d = eligibility["phase7d"]
    before = _business_row_counts()

    with transaction.atomic():
        existing = (
            RazorpayPaymentOrderMutationSandboxGate.objects.filter(
                source_phase7i_lock=phase7i_lock
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "8A",
                "created": False,
                "reused": True,
                "gate": serialize_phase8a_gate(existing),
                "blockers": [],
                "warnings": [PHASE_8A_WARNING],
                "nextAction": (
                    "phase8a_gate_pending_manual_review"
                    if existing.status
                    == RazorpayPaymentOrderMutationSandboxGate.Status.PENDING_MANUAL_REVIEW
                    else f"phase8a_gate_status_{existing.status}"
                ),
            }

        gate = RazorpayPaymentOrderMutationSandboxGate(
            source_phase7i_lock=phase7i_lock,
            source_phase7d_attempt=phase7d,
            status=(
                RazorpayPaymentOrderMutationSandboxGate.Status.PENDING_MANUAL_REVIEW
            ),
            sandbox_only=True,
            real_business_mutation_allowed=False,
            real_order_mutation_allowed=False,
            real_payment_mutation_allowed=False,
            customer_notification_allowed=False,
            whatsapp_allowed=False,
            courier_allowed=False,
            synthetic_order_required=True,
            manual_review_required=True,
            claim_vault_not_required_for_payment_status=True,
            evidence_json=_build_evidence_json(
                phase7i_lock=phase7i_lock, phase7d=phase7d
            ),
            blockers=[],
            warnings=[PHASE_8A_WARNING],
            next_action="phase8a_gate_pending_manual_review",
        )
        assert_phase8a_no_business_mutation(
            gate, before_counts=before
        )
        try:
            gate.save()
        except IntegrityError:  # pragma: no cover - defensive
            gate = (
                RazorpayPaymentOrderMutationSandboxGate.objects.get(
                    source_phase7i_lock=phase7i_lock
                )
            )
            return {
                "phase": "8A",
                "created": False,
                "reused": True,
                "gate": serialize_phase8a_gate(gate),
                "blockers": [],
                "warnings": [PHASE_8A_WARNING],
                "nextAction": "phase8a_gate_pending_manual_review",
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 8A gate prepared gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(gate),
    )
    return {
        "phase": "8A",
        "created": True,
        "reused": False,
        "gate": serialize_phase8a_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8A_WARNING],
        "nextAction": "phase8a_gate_pending_manual_review",
    }


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def _validate_synthetic_reference(reference: str) -> list[str]:
    blockers: list[str] = []
    if not (reference or "").strip():
        blockers.append(
            "phase8a_dry_run_synthetic_order_reference_required"
        )
        return blockers
    if not any(
        reference.startswith(prefix)
        for prefix in _SYNTHETIC_REFERENCE_PREFIXES
    ):
        blockers.append(
            "phase8a_dry_run_synthetic_order_reference_must_start_with_known_prefix"
        )
    if len(reference) > 120:
        blockers.append(
            "phase8a_dry_run_synthetic_order_reference_too_long"
        )
    return blockers


def dry_run_phase8a_payment_order_mutation_sandbox(
    gate_id: int,
    synthetic_order_reference: str = "",
) -> dict[str, Any]:
    """Sandbox dry-run. NEVER mutates real rows. Requires a
    synthetic-only ``synthetic_order_reference`` (one of the known
    prefixes)."""
    gate = (
        RazorpayPaymentOrderMutationSandboxGate.objects.filter(
            pk=gate_id
        ).first()
    )
    if gate is None:
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "dryRun": None,
            "blockers": ["phase8a_gate_not_found"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_id",
        }

    if gate.status not in {
        RazorpayPaymentOrderMutationSandboxGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderMutationSandboxGate.Status.DRY_RUN_PASSED,
    }:
        return {
            "phase": "8A",
            "ok": False,
            "gate": serialize_phase8a_gate(gate),
            "dryRun": None,
            "blockers": [
                f"phase8a_gate_status_{gate.status}_not_dry_runnable"
            ],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_status",
        }

    eligibility = _validate_eligibility(
        phase7i_lock_id=gate.source_phase7i_lock_id,
        require_env_flag=True,
    )
    blockers: list[str] = list(eligibility["blockers"])
    blockers += _validate_synthetic_reference(
        synthetic_order_reference
    )

    if blockers:
        # Persist a failed dry-run record so the operator can see why.
        before = _business_row_counts()
        record = RazorpayPaymentOrderMutationDryRun.objects.create(
            gate=gate,
            source_phase7i_lock=gate.source_phase7i_lock,
            source_phase7d_attempt=gate.source_phase7d_attempt,
            proposed_source_payment_reference=(
                getattr(
                    gate.source_phase7d_attempt,
                    "provider_object_id",
                    "",
                )
                or ""
            )[:120],
            proposed_target_order_reference=(
                synthetic_order_reference or ""
            )[:120],
            proposed_target_order_is_synthetic=True,
            proposed_old_order_status="",
            proposed_new_order_status="",
            proposed_old_payment_status="",
            proposed_new_payment_status="",
            would_mutate_order=False,
            would_mutate_payment=False,
            would_send_customer_notification=False,
            would_send_whatsapp=False,
            would_call_courier=False,
            before_counts=before,
            after_counts=before,
            count_deltas={},
            passed=False,
            blockers=list(blockers),
            warnings=[PHASE_8A_WARNING],
        )
        write_event(
            kind=AUDIT_KIND_DRY_RUN_FAILED,
            text=(
                f"Phase 8A dry-run failed gate_id={gate.pk} "
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
            "phase": "8A",
            "ok": False,
            "gate": serialize_phase8a_gate(gate),
            "dryRun": serialize_phase8a_dry_run(record),
            "blockers": list(blockers),
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "fix_phase8a_dry_run_blockers",
        }

    # Eligible. Execute the sandbox dry-run with no mutation.
    before = _business_row_counts()
    record = RazorpayPaymentOrderMutationDryRun.objects.create(
        gate=gate,
        source_phase7i_lock=gate.source_phase7i_lock,
        source_phase7d_attempt=gate.source_phase7d_attempt,
        proposed_source_payment_reference=(
            getattr(
                gate.source_phase7d_attempt,
                "provider_object_id",
                "",
            )
            or ""
        )[:120],
        proposed_target_order_reference=(
            synthetic_order_reference or ""
        )[:120],
        proposed_target_order_is_synthetic=True,
        proposed_old_order_status="paid_sandbox_candidate",
        proposed_new_order_status="paid_sandbox_candidate",
        proposed_old_payment_status="paid_sandbox_candidate",
        proposed_new_payment_status="paid_sandbox_candidate",
        would_mutate_order=False,
        would_mutate_payment=False,
        would_send_customer_notification=False,
        would_send_whatsapp=False,
        would_call_courier=False,
        before_counts=before,
        after_counts=before,
        count_deltas={},
        passed=False,  # Filled below.
        blockers=[],
        warnings=[PHASE_8A_WARNING],
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
            "phase8a_dry_run_business_row_count_changed",
        ]
    record.save()

    # Guard re-checks the locked-False contract + counts.
    try:
        assert_phase8a_no_business_mutation(
            gate, before_counts=before, dry_run=record
        )
    except ValueError as exc:  # pragma: no cover - defensive
        record.passed = False
        record.blockers = list(record.blockers or []) + [str(exc)]
        record.save()

    if passed and record.passed:
        gate.status = (
            RazorpayPaymentOrderMutationSandboxGate.Status.DRY_RUN_PASSED
        )
        gate.next_action = "phase8a_gate_dry_run_passed_awaiting_approve"
        gate.save(update_fields=["status", "next_action", "updated_at"])

    write_event(
        kind=(
            AUDIT_KIND_DRY_RUN_PASSED
            if passed and record.passed
            else AUDIT_KIND_DRY_RUN_FAILED
        ),
        text=(
            f"Phase 8A dry-run "
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
        "phase": "8A",
        "ok": bool(passed and record.passed),
        "gate": serialize_phase8a_gate(gate),
        "dryRun": serialize_phase8a_dry_run(record),
        "blockers": list(record.blockers or []),
        "warnings": [PHASE_8A_WARNING],
        "nextAction": (
            "phase8a_gate_dry_run_passed_awaiting_approve"
            if (passed and record.passed)
            else "fix_phase8a_dry_run_blockers"
        ),
    }


def rollback_dry_run_phase8a_payment_order_mutation_sandbox(
    dry_run_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Record-only rollback for a dry-run. NEVER calls a provider;
    NEVER mutates business rows."""
    if not reason.strip():
        return {
            "phase": "8A",
            "ok": False,
            "dryRun": None,
            "blockers": [
                "phase8a_dry_run_rollback_reason_required"
            ],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "supply_reason",
        }
    record = (
        RazorpayPaymentOrderMutationDryRun.objects.filter(
            pk=dry_run_id
        ).first()
    )
    if record is None:
        return {
            "phase": "8A",
            "ok": False,
            "dryRun": None,
            "blockers": ["phase8a_dry_run_not_found"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_dry_run_id",
        }
    record.rolled_back_at = timezone.now()
    record.rollback_reason = (reason or "")[:1000]
    record.save(
        update_fields=["rolled_back_at", "rollback_reason"]
    )
    write_event(
        kind=AUDIT_KIND_ROLLBACK_RECORDED,
        text=(
            f"Phase 8A dry-run rollback recorded record_id="
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
        "phase": "8A",
        "ok": True,
        "dryRun": serialize_phase8a_dry_run(record),
        "blockers": [],
        "warnings": [PHASE_8A_WARNING],
        "nextAction": "phase8a_dry_run_rollback_recorded",
    }


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


def _gate_lookup(
    gate_id: int,
) -> Optional[RazorpayPaymentOrderMutationSandboxGate]:
    return (
        RazorpayPaymentOrderMutationSandboxGate.objects.filter(
            pk=gate_id
        ).first()
    )


def _reviewer_username(reviewed_by) -> str:
    return getattr(reviewed_by, "username", "") or ""


def approve_phase8a_payment_order_mutation_sandbox(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    """Flip status to ``approved_for_future_phase8b_review``. Non-
    empty reason + at least one passed dry-run required. Approval
    does NOT enable any mutation."""
    if not reason.strip():
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "blockers": ["phase8a_approve_reason_required"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "blockers": ["phase8a_gate_not_found"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_id",
        }
    if (
        gate.status
        != RazorpayPaymentOrderMutationSandboxGate.Status.DRY_RUN_PASSED
    ):
        return {
            "phase": "8A",
            "ok": False,
            "gate": serialize_phase8a_gate(gate),
            "blockers": [
                f"phase8a_gate_status_{gate.status}_not_transitionable_to_approved"
            ],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "run_phase8a_dry_run_first",
        }
    if not gate.dry_runs.filter(passed=True).exists():
        return {
            "phase": "8A",
            "ok": False,
            "gate": serialize_phase8a_gate(gate),
            "blockers": ["phase8a_no_passed_dry_run_present"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "run_phase8a_dry_run_first",
        }

    before = _business_row_counts()
    assert_phase8a_no_business_mutation(
        gate, before_counts=before
    )

    gate.status = (
        RazorpayPaymentOrderMutationSandboxGate.Status.APPROVED_FOR_FUTURE_PHASE8B_REVIEW
    )
    gate.approved_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.review_reason = (reason or "")[:1000]
    gate.next_action = "phase8a_gate_approved_for_future_phase8b_review"
    gate.save()

    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            f"Phase 8A approved-for-future-phase8b gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8A",
        "ok": True,
        "gate": serialize_phase8a_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8A_WARNING],
        "nextAction": "phase8a_gate_approved_for_future_phase8b_review",
    }


def reject_phase8a_payment_order_mutation_sandbox(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "blockers": ["phase8a_reject_reason_required"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "blockers": ["phase8a_gate_not_found"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status not in {
        RazorpayPaymentOrderMutationSandboxGate.Status.DRAFT,
        RazorpayPaymentOrderMutationSandboxGate.Status.PENDING_MANUAL_REVIEW,
        RazorpayPaymentOrderMutationSandboxGate.Status.DRY_RUN_PASSED,
        RazorpayPaymentOrderMutationSandboxGate.Status.BLOCKED,
    }:
        return {
            "phase": "8A",
            "ok": False,
            "gate": serialize_phase8a_gate(gate),
            "blockers": [
                f"phase8a_reject_refused_for_status_{gate.status}"
            ],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_status",
        }

    before = _business_row_counts()
    assert_phase8a_no_business_mutation(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayPaymentOrderMutationSandboxGate.Status.REJECTED
    )
    gate.rejected_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.reject_reason = (reason or "")[:1000]
    gate.next_action = "phase8a_gate_rejected"
    gate.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=f"Phase 8A rejected gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8A",
        "ok": True,
        "gate": serialize_phase8a_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8A_WARNING],
        "nextAction": "phase8a_gate_rejected",
    }


def archive_phase8a_payment_order_mutation_sandbox(
    gate_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "blockers": ["phase8a_archive_reason_required"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "supply_reason",
        }
    gate = _gate_lookup(gate_id)
    if gate is None:
        return {
            "phase": "8A",
            "ok": False,
            "gate": None,
            "blockers": ["phase8a_gate_not_found"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_id",
        }
    if gate.status == (
        RazorpayPaymentOrderMutationSandboxGate.Status.ARCHIVED
    ):
        return {
            "phase": "8A",
            "ok": False,
            "gate": serialize_phase8a_gate(gate),
            "blockers": ["phase8a_gate_already_archived"],
            "warnings": [PHASE_8A_WARNING],
            "nextAction": "verify_gate_status",
        }
    before = _business_row_counts()
    assert_phase8a_no_business_mutation(
        gate, before_counts=before
    )
    gate.status = (
        RazorpayPaymentOrderMutationSandboxGate.Status.ARCHIVED
    )
    gate.archived_at = timezone.now()
    gate.reviewed_by = reviewed_by
    gate.reviewed_by_username = _reviewer_username(reviewed_by)
    gate.reviewed_at = timezone.now()
    gate.archive_reason = (reason or "")[:1000]
    gate.next_action = "phase8a_gate_archived"
    gate.save()

    write_event(
        kind=AUDIT_KIND_ARCHIVED,
        text=f"Phase 8A archived gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate, extra={"reason_excerpt": (reason or "")[:120]}
        ),
    )
    return {
        "phase": "8A",
        "ok": True,
        "gate": serialize_phase8a_gate(gate),
        "blockers": [],
        "warnings": [PHASE_8A_WARNING],
        "nextAction": "phase8a_gate_archived",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase8a_gates(limit: int = 25) -> dict[str, Any]:
    qs = RazorpayPaymentOrderMutationSandboxGate.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value
        for s in RazorpayPaymentOrderMutationSandboxGate.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase8a_gate(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "8A", "counts": counts, "items": items}


def inspect_phase8a_payment_order_mutation_sandbox_readiness() -> (
    dict[str, Any]
):
    summary = summarize_phase8a_gates(limit=10)
    counts = summary["counts"]
    kill = _kill_switch_state()

    eligible_phase7i_locks = (
        RazorpayPhase7FinalAuditLock.objects.filter(
            status=RazorpayPhase7FinalAuditLock.Status.LOCKED,
            phase7d_business_mutation_was_made_snapshot=False,
            phase7d_customer_notification_sent_snapshot=False,
            phase7e_live_business_mutation_was_made_snapshot=False,
            phase7e_live_customer_notification_sent_snapshot=False,
            phase7e_live_real_customer_phone_used_snapshot=False,
            phase7g_business_mutation_was_made_snapshot=False,
            phase7g_shipment_created_snapshot=False,
            phase7g_customer_notification_sent_snapshot=False,
            phase7h_business_mutation_was_made_snapshot=False,
            phase7h_shipment_created_snapshot=False,
            phase7h_customer_notification_sent_snapshot=False,
        ).count()
    )

    blockers: list[str] = []
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    if blockers:
        next_action = "fix_phase8a_safety_blockers"
    elif not _flag_phase8a_enabled():
        next_action = (
            "enable_phase8a_payment_order_mutation_sandbox_flag"
        )
    elif eligible_phase7i_locks == 0:
        next_action = "no_eligible_phase7i_lock_present"
    elif counts.get("pending_manual_review", 0) > 0:
        next_action = "phase8a_gates_pending_manual_review"
    elif counts.get("dry_run_passed", 0) > 0:
        next_action = "phase8a_gates_dry_run_passed_awaiting_approve"
    elif (
        counts.get("approved_for_future_phase8b_review", 0) > 0
    ):
        next_action = "phase8a_gates_approved_for_future_phase8b_review"
    else:
        next_action = (
            "ready_to_prepare_phase8a_payment_order_mutation_sandbox_gate"
        )

    return {
        "phase": "8A",
        "status": "payment_order_mutation_sandbox_only",
        "latestCompletedPhase": "7I",
        "nextPhase": (
            "phase8b_planning_or_real_mutation_not_approved"
        ),
        "phase8APaymentOrderMutationSandboxEnabled": (
            _flag_phase8a_enabled()
        ),
        "killSwitch": kill,
        "eligiblePhase7ILockCount": eligible_phase7i_locks,
        "phase8AGateCounts": counts,
        "items": summary["items"],
        "phase8ACallsRazorpay": False,
        "phase8ACallsMetaCloud": False,
        "phase8ACallsDelhivery": False,
        "phase8ACallsVapi": False,
        "phase8ASendsWhatsApp": False,
        "phase8AQueuesWhatsApp": False,
        "phase8ACreatesShipmentRow": False,
        "phase8ACreatesAwb": False,
        "phase8ACreatesPaymentLink": False,
        "phase8ACapturesPayment": False,
        "phase8ARefundsPayment": False,
        "phase8ASendsCustomerNotification": False,
        "phase8AMutatesBusinessRow": False,
        "phase8AMutatesRealOrder": False,
        "phase8AMutatesRealPayment": False,
        "phase8ARealCustomerAutomationApproved": False,
        "phase7ELiveBApproved": False,
        "phase7GLiveApproved": False,
        "executionPath": "sandbox_dry_run_only_cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "blockers": blockers,
        "warnings": [PHASE_8A_WARNING],
        "nextAction": next_action,
        "forbiddenActions": list(PHASE_8A_FORBIDDEN_ACTIONS),
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    write_event(
        kind=AUDIT_KIND_READINESS,
        text=(
            "Phase 8A payment-order mutation sandbox readiness "
            "inspected"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "eligible_phase7i_lock_count": int(
                    report.get("eligiblePhase7ILockCount") or 0
                ),
                "phase8a_enabled": bool(
                    report.get(
                        "phase8APaymentOrderMutationSandboxEnabled"
                    )
                ),
                "gate_counts": report.get("phase8AGateCounts") or {},
                "next_action": report.get("nextAction") or "",
                "kill_switch_enabled": (
                    report.get("killSwitch", {}) or {}
                ).get("enabled", True),
            }
        ),
    )


__all__ = (
    "PHASE_8A_WARNING",
    "PHASE_8A_FORBIDDEN_ACTIONS",
    "PHASE_8A_FORBIDDEN_PAYLOAD_KEYS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_DRY_RUN_PASSED",
    "AUDIT_KIND_DRY_RUN_FAILED",
    "AUDIT_KIND_ROLLBACK_RECORDED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_ARCHIVED",
    "AUDIT_KIND_BLOCKED",
    "assert_phase8a_no_business_mutation",
    "preview_phase8a_payment_order_mutation_sandbox",
    "prepare_phase8a_payment_order_mutation_sandbox",
    "dry_run_phase8a_payment_order_mutation_sandbox",
    "rollback_dry_run_phase8a_payment_order_mutation_sandbox",
    "approve_phase8a_payment_order_mutation_sandbox",
    "reject_phase8a_payment_order_mutation_sandbox",
    "archive_phase8a_payment_order_mutation_sandbox",
    "inspect_phase8a_payment_order_mutation_sandbox_readiness",
    "summarize_phase8a_gates",
    "serialize_phase8a_gate",
    "serialize_phase8a_dry_run",
    "emit_readiness_inspected_audit",
)
