"""Phase 7E-Live-A - Internal allowed-list WhatsApp one-shot send gate.

This service implements a *single* future Meta Cloud WhatsApp
template send to a recipient on
``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS``, derived from an
approved Phase 7E gate. The send is the **only currently approved
design path** for a real Meta Cloud HTTP send in this controlled
Phase 7 chain after fresh Director approval. Phase 7E-Live-A is
**internal-staff-only**; the recipient MUST be on the existing
allow-list, the message MUST use an approved Meta template (no
freeform medical text), Claim Vault grounding MUST be ``True`` at
prepare time, and ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE`` MUST be
``True``.

Phase 7E-Live-A **never** sends to a real customer phone, **never**
queues broad automation, **never** mutates ``Order`` / ``Payment``
/ ``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead``
rows, **never** edits any ``.env*`` file. The execute path is
CLI-only and requires a structured ``BEGIN_UTC=`` / ``END_UTC=``
Director sign-off window (≤ 15 minutes; reuses
``apps.saas.utc_window.validate_within_director_window``).

Hard scope rule (asserted by static-file scan tests): this module
does NOT have a top-level
``from apps.whatsapp.integrations.whatsapp.meta_cloud_client import ...``
nor ``from apps.whatsapp.services import send_freeform_text_message``
import. The Meta Cloud client is reached **lazily** via
:func:`_send_internal_template_via_meta_cloud` only, which itself
runs only inside the guarded :func:`execute_phase7e_live_internal_send`
path after every gate is green. Tests ``mock.patch`` this wrapper
so the real network is never hit.

Public surface:

- :func:`inspect_phase7e_live_internal_send_readiness`
- :func:`preview_phase7e_live_internal_send`
- :func:`prepare_phase7e_live_internal_send`
- :func:`approve_phase7e_live_internal_send`
- :func:`execute_phase7e_live_internal_send` -- the only callable
  that may issue a Meta Cloud HTTP request, after every gate
  passes.
- :func:`rollback_phase7e_live_internal_send`
- :func:`reject_phase7e_live_internal_send`
- :func:`assert_phase7e_live_no_business_mutation`
- :func:`serialize_phase7e_live_internal_send_attempt`
- :func:`summarize_phase7e_live_internal_send_attempts`
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
    RazorpayPhase6FinalAuditLock,
    RazorpayWhatsAppInternalNotificationGate,
    RazorpayWhatsAppInternalSendAttempt,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_7E_LIVE_WARNING = (
    "Phase 7E-Live-A is the Internal Allowed-list WhatsApp One-shot "
    "Send Gate. The recipient MUST be on "
    "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS; the template MUST be "
    "approved with Claim Vault grounding; the execute path is "
    "CLI-only and requires three Phase 7E-Live env flags + a fresh "
    "Director sign-off with BEGIN_UTC/END_UTC structured window "
    "(<= 15 min). Phase 7E-Live-A NEVER sends to a real customer "
    "phone, NEVER queues broad automation, NEVER calls Meta Cloud / "
    "Razorpay / Delhivery / Vapi outside the dedicated wrapper, "
    "NEVER mutates real Order / Payment / Customer / Lead / "
    "DiscountOfferLog rows, NEVER edits any .env file. Phase "
    "7E-Live-B (real customer WhatsApp send) remains NOT approved."
)


AUDIT_KIND_READINESS = "phase7e.internal_send.readiness_inspected"
AUDIT_KIND_PREVIEWED = "phase7e.internal_send.previewed"
AUDIT_KIND_PREPARED = "phase7e.internal_send.prepared"
AUDIT_KIND_APPROVED = "phase7e.internal_send.approved"
AUDIT_KIND_EXECUTED = "phase7e.internal_send.executed"
AUDIT_KIND_FAILED = "phase7e.internal_send.failed"
AUDIT_KIND_ROLLBACK_RECORDED = (
    "phase7e.internal_send.rollback_recorded"
)
AUDIT_KIND_REJECTED = "phase7e.internal_send.rejected"
AUDIT_KIND_BLOCKED = "phase7e.internal_send.blocked"


PHASE_7E_LIVE_FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
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


_LOCKED_FALSE_FIELDS: tuple[str, ...] = (
    "customer_notification_sent",
    "business_mutation_was_made",
    "real_customer_allowed",
    "real_customer_phone_used",
)


# ---------------------------------------------------------------------------
# Flag readers (read-only; never edits .env)
# ---------------------------------------------------------------------------


def _flag_phase7e_live_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED",
            False,
        )
    )


def _flag_whatsapp_limited_test_mode() -> bool:
    return bool(
        getattr(settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False)
    )


def _allowed_test_numbers() -> list[str]:
    raw = getattr(
        settings, "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS", None
    ) or []
    if isinstance(raw, str):
        raw = [n.strip() for n in raw.split(",") if n.strip()]
    return [str(n) for n in raw]


def _digits_only(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _last4(value: str) -> str:
    digits = _digits_only(value)
    return digits[-4:] if len(digits) >= 4 else digits


def _phone_is_on_allow_list(phone: str) -> bool:
    target = _digits_only(phone)
    if not target:
        return False
    for allowed in _allowed_test_numbers():
        if _digits_only(allowed) == target:
            return True
    return False


def _capture_env_flag_snapshot() -> dict[str, Any]:
    return {
        "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED": (
            _flag_phase7e_live_enabled()
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
        "PHASE7G_COURIER_EXECUTION_ENABLED": bool(
            getattr(
                settings, "PHASE7G_COURIER_EXECUTION_ENABLED", False
            )
        ),
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": (
            _flag_whatsapp_limited_test_mode()
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
    }


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


# ---------------------------------------------------------------------------
# Business-row count + defensive guard
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


def _audit_locked_false_payload() -> dict[str, bool]:
    return {field: False for field in _LOCKED_FALSE_FIELDS}


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"phase": "7E-Live-A"}
    forbidden = set(PHASE_7E_LIVE_FORBIDDEN_PAYLOAD_KEYS)
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


def assert_phase7e_live_no_business_mutation(
    attempt: RazorpayWhatsAppInternalSendAttempt,
    *,
    before_counts: Optional[dict[str, int]] = None,
) -> None:
    """Refuse if any of the locked-False booleans on the attempt has
    flipped to True, or any non-WhatsApp business-row count has
    moved (the WhatsApp outbound is created post-execute in
    Phase 7E-Live-A, so its delta is allowed; everything else MUST
    stay constant).
    """
    flipped: list[str] = []
    for field in _LOCKED_FALSE_FIELDS:
        if getattr(attempt, field, False) is True:
            flipped.append(field)

    delta_keys: list[str] = []
    if before_counts is not None:
        current = _business_row_counts()
        for key, count_before in before_counts.items():
            count_after = current.get(key, count_before)
            if count_after != count_before:
                if key == "whatsapp_message" and (
                    count_after > count_before
                ):
                    # Outbound message row is allowed to grow once.
                    continue
                delta_keys.append(
                    f"phase7e_live_business_row_count_changed_for_{key}"
                )

    if not flipped and not delta_keys:
        return

    write_event(
        kind=AUDIT_KIND_BLOCKED,
        text=(
            f"Phase 7E-Live invariant violation attempt_id={attempt.pk}"
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
        "Phase 7E-Live-A invariant violation: "
        f"flipped={flipped} deltas={delta_keys}"
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _validate_gate(
    gate_id: Optional[int],
    *,
    require_env_flag: bool = True,
) -> tuple[list[str], Optional[RazorpayWhatsAppInternalNotificationGate]]:
    blockers: list[str] = []
    if require_env_flag and not _flag_phase7e_live_enabled():
        blockers.append(
            "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED_must_be_true"
        )
    if not _flag_whatsapp_limited_test_mode():
        blockers.append(
            "WHATSAPP_LIVE_META_LIMITED_TEST_MODE_must_be_true"
        )

    gate: Optional[RazorpayWhatsAppInternalNotificationGate] = None
    if gate_id:
        gate = (
            RazorpayWhatsAppInternalNotificationGate.objects.filter(
                pk=gate_id
            )
            .select_related(
                "source_phase7d_attempt",
                "source_phase7b_gate",
                "source_phase6t_lock",
            )
            .first()
        )

    if gate is None:
        blockers.append("phase_7e_source_gate_not_found")
        return blockers, None

    if (
        gate.status
        != RazorpayWhatsAppInternalNotificationGate.Status.APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW
    ):
        blockers.append(
            "phase_7e_gate_status_must_be_approved_for_future_phase7f_or_7e_send_review"
        )
    if not gate.dry_run_passed:
        blockers.append("phase_7e_gate_dry_run_passed_must_be_true")
    if not gate.rollback_dry_run_passed:
        blockers.append(
            "phase_7e_gate_rollback_dry_run_passed_must_be_true"
        )
    if not gate.claim_vault_grounded:
        blockers.append(
            "phase_7e_gate_claim_vault_grounded_must_be_true"
        )

    snapshot = _capture_env_flag_snapshot()
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

    return blockers, gate


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def serialize_phase7e_live_internal_send_attempt(
    row: RazorpayWhatsAppInternalSendAttempt,
) -> dict[str, Any]:
    """Whitelisted serializer. NEVER returns raw token / full phone /
    raw provider response / Director signoff text."""
    return {
        "id": row.pk,
        "status": row.status,
        "sourcePhase7EGateId": row.source_phase7e_gate_id,
        "sourcePhase7DAttemptId": row.source_phase7d_attempt_id,
        "sourcePhase7BGateId": row.source_phase7b_gate_id,
        "sourcePhase6TLockId": row.source_phase6t_lock_id,
        "templateName": row.template_name,
        "templateLanguage": row.template_language,
        "allowedRecipientLast4": row.allowed_recipient_last4,
        "recipientScope": row.recipient_scope,
        "providerMessageId": row.provider_message_id,
        "providerStatus": row.provider_status,
        "safeRequestSummary": row.safe_request_summary or {},
        "safeResponseSummary": row.safe_response_summary or {},
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
        # Allowed-True booleans.
        "providerCallAttempted": bool(row.provider_call_attempted),
        "metaCloudCallAttempted": bool(row.meta_cloud_call_attempted),
        "whatsAppMessageCreated": bool(row.whatsapp_message_created),
        "whatsAppMessageQueued": bool(row.whatsapp_message_queued),
        # Locked-False booleans (always returned False).
        "customerNotificationSent": False,
        "businessMutationWasMade": False,
        "realCustomerAllowed": False,
        "realCustomerPhoneUsed": False,
        "claimVaultGrounded": bool(row.claim_vault_grounded),
        "idempotencyKey": row.idempotency_key,
        "idempotencyLockAcquired": bool(row.idempotency_lock_acquired),
        "directorSignoffPresent": bool(row.director_signoff_present),
        "operatorName": row.operator_name,
        "confirmInternalWhatsAppSend": bool(
            row.confirm_internal_whatsapp_send
        ),
        "rollbackReasonPresent": bool(
            (row.rollback_reason or "").strip()
        ),
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
        "approvedAt": (
            row.approved_at.isoformat() if row.approved_at else None
        ),
        "executedAt": (
            row.executed_at.isoformat() if row.executed_at else None
        ),
        "failedAt": (
            row.failed_at.isoformat() if row.failed_at else None
        ),
        "rolledBackAt": (
            row.rolled_back_at.isoformat()
            if row.rolled_back_at
            else None
        ),
        "rejectedAt": (
            row.rejected_at.isoformat() if row.rejected_at else None
        ),
        "archivedAt": (
            row.archived_at.isoformat() if row.archived_at else None
        ),
    }


def _audit_attempt_payload(
    attempt: RazorpayWhatsAppInternalSendAttempt,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "attempt_id": attempt.pk,
        "status": attempt.status,
        "phase7e_gate_id": attempt.source_phase7e_gate_id,
        "phase7d_attempt_id": attempt.source_phase7d_attempt_id,
        "phase7b_gate_id": attempt.source_phase7b_gate_id,
        "template_name": attempt.template_name,
        "template_language": attempt.template_language,
        "recipient_scope": attempt.recipient_scope,
        "allowed_recipient_last4": attempt.allowed_recipient_last4,
        "provider_message_id_or_empty": (
            attempt.provider_message_id or ""
        ),
        "provider_call_attempted": bool(attempt.provider_call_attempted),
        "meta_cloud_call_attempted": bool(
            attempt.meta_cloud_call_attempted
        ),
        "whatsapp_message_created": bool(
            attempt.whatsapp_message_created
        ),
        "whatsapp_message_queued": bool(
            attempt.whatsapp_message_queued
        ),
        "kill_switch_state_at_emit": _kill_switch_state(),
        **_audit_locked_false_payload(),
    }
    if extra:
        payload.update(extra)
    return _safe_audit_payload(payload)


# ---------------------------------------------------------------------------
# Synthetic recipient / lazy Meta wrapper
# ---------------------------------------------------------------------------


class Phase7ELiveExecutionError(Exception):
    """Raised when execute_phase7e_live_internal_send refuses or the
    Meta Cloud wrapper fails. NEVER echoes raw token / phone / body
    material verbatim."""


def _resolve_allowed_recipient(
    last4: str,
) -> Optional[str]:
    """Return the full E.164 allow-list entry whose last 4 digits
    match ``last4``. Returns ``None`` when no match exists."""
    target = _digits_only(last4)
    if not target or len(target) < 4:
        return None
    target_last4 = target[-4:]
    for allowed in _allowed_test_numbers():
        if _digits_only(allowed).endswith(target_last4):
            return allowed
    return None


def _send_internal_template_via_meta_cloud(
    *,
    to_e164: str,
    template_name: str,
    template_language: str,
    attempt_id: int,
) -> dict[str, Any]:
    """Lazy-import wrapper around the Meta Cloud client.

    The real ``apps.whatsapp.integrations.whatsapp.meta_cloud_client``
    is imported **only inside this function** so the Phase 7E-Live-A
    service module surface contains no top-level Meta Cloud import
    (asserted by static-file scan tests). The actual Meta Cloud HTTP
    send is made here, once, after every gate in
    :func:`execute_phase7e_live_internal_send` is green. Tests
    ``mock.patch`` this function so the real network is never hit.

    The Meta Cloud client exposes the send entry point as
    :meth:`MetaCloudProvider.send_template_message` (a method on the
    class, not a module-level function). The wrapper instantiates the
    provider, calls the method with the production-aligned keyword
    arguments
    (``to_phone`` / ``template_name`` / ``language`` /
    ``components`` / ``idempotency_key``), and reduces the returned
    :class:`apps.whatsapp.integrations.whatsapp.base.ProviderSendResult`
    dataclass to the Phase 7E-Live-A safe summary shape
    ``{"message_id": str, "status": str}`` so the rest of the
    service code path is unchanged.
    """
    try:
        from apps.whatsapp.integrations.whatsapp.meta_cloud_client import (
            MetaCloudProvider,
        )
    except ImportError as exc:  # pragma: no cover
        raise Phase7ELiveExecutionError(
            "Meta Cloud client is not importable."
        ) from exc

    provider = MetaCloudProvider()
    idempotency_key = (
        f"phase7e_live::internal_send::attempt::{attempt_id}"
    )
    try:
        result = provider.send_template_message(
            to_phone=to_e164,
            template_name=template_name,
            language=template_language or "en",
            components=[],
            idempotency_key=idempotency_key,
        )
    except Phase7ELiveExecutionError:
        raise
    except Exception as exc:  # pragma: no cover - real network only
        raise Phase7ELiveExecutionError(
            f"Meta Cloud send error: {exc.__class__.__name__}"
        ) from exc
    return _summarize_meta_send_result(result)


def _summarize_meta_send_result(result: Any) -> dict[str, Any]:
    """Reduce a Meta Cloud send result to the Phase 7E-Live-A safe
    summary shape ``{"message_id": str, "status": str}``.

    Accepts either a
    :class:`apps.whatsapp.integrations.whatsapp.base.ProviderSendResult`
    dataclass (the production return type) or a plain dict (the test
    return type used by ``mock.patch`` callers). Never stores the raw
    Meta Graph API response body; ``request_payload`` /
    ``response_payload`` / ``response_status`` / ``error_code`` /
    ``latency_ms`` are deliberately dropped.
    """
    if result is None:
        return {"message_id": "", "status": ""}
    if isinstance(result, dict):
        return {
            "message_id": str(result.get("message_id") or "")[:64],
            "status": str(result.get("status") or "")[:64],
        }
    return {
        "message_id": str(
            getattr(result, "provider_message_id", "") or ""
        )[:64],
        "status": str(getattr(result, "status", "") or "")[:64],
    }


# Backwards-compatible alias for any existing call site / test that
# still references the old summary helper. The previous helper only
# accepted a dict; the new helper also handles the production
# ``ProviderSendResult`` dataclass.
_summarize_meta_response = _summarize_meta_send_result


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_phase7e_live_internal_send(
    gate_id: int,
) -> dict[str, Any]:
    blockers, gate = _validate_gate(gate_id, require_env_flag=False)
    write_event(
        kind=AUDIT_KIND_PREVIEWED,
        text=f"Phase 7E-Live preview gate_id={gate_id}",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7e_gate_id": gate_id,
                "eligible": not blockers,
                "blockers": list(blockers),
                "allowed_test_numbers_count": len(
                    _allowed_test_numbers()
                ),
                "kill_switch_state_at_emit": _kill_switch_state(),
            }
        ),
    )
    return {
        "phase": "7E-Live-A",
        "found": gate is not None,
        "sourcePhase7EGateId": gate_id,
        "recipientScope": "internal_staff_allow_list",
        "allowedTestNumbersCount": len(_allowed_test_numbers()),
        "eligible": not blockers,
        "blockers": list(blockers),
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": (
            "ready_to_prepare_phase7e_live_internal_send"
            if not blockers and _flag_phase7e_live_enabled()
            else (
                "fix_phase7e_live_eligibility_blockers_or_enable_phase7e_live_flag"
            )
        ),
    }


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


_TEMPLATE_NAME_RE = re.compile(r"^[a-z][a-z0-9_.]{2,119}$")


def _idempotency_key(gate_id: int) -> str:
    return f"phase7e_live::internal_send::phase7e_gate::{gate_id}"


def prepare_phase7e_live_internal_send(
    gate_id: int,
    *,
    template_name: str,
    template_language: str,
    allowed_recipient_last4: str,
    requested_by=None,
) -> dict[str, Any]:
    """Atomic + idempotent prepare. NEVER calls Meta Cloud, NEVER
    creates a WhatsApp message row, NEVER mutates business rows,
    NEVER edits any ``.env*`` file.
    """
    blockers, gate = _validate_gate(gate_id, require_env_flag=True)
    template_name = (template_name or "").strip()
    template_language = (template_language or "").strip()
    last4 = _digits_only(allowed_recipient_last4 or "")

    if not template_name or not _TEMPLATE_NAME_RE.match(template_name):
        blockers.append(
            "phase7e_live_template_name_must_be_valid"
        )
    if not template_language or len(template_language) > 16:
        blockers.append(
            "phase7e_live_template_language_must_be_present"
        )
    if not last4 or len(last4) != 4:
        blockers.append(
            "phase7e_live_allowed_recipient_last4_must_be_4_digits"
        )
    allowed_full = _resolve_allowed_recipient(last4) if last4 else None
    if allowed_full is None:
        blockers.append(
            "phase7e_live_recipient_must_be_on_allowed_test_numbers"
        )

    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    if blockers or gate is None:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7E-Live prepare blocked gate_id={gate_id}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_safe_audit_payload(
                {
                    "phase7e_gate_id": gate_id,
                    "blockers": list(blockers),
                    "kill_switch_state_at_emit": kill,
                    **_audit_locked_false_payload(),
                }
            ),
        )
        return {
            "phase": "7E-Live-A",
            "created": False,
            "reused": False,
            "attempt": None,
            "blockers": list(blockers),
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": (
                "fix_phase7e_live_eligibility_blockers_or_enable_phase7e_live_flag"
            ),
        }

    before = _business_row_counts()
    snapshot = _capture_env_flag_snapshot()
    idempotency = _idempotency_key(gate.pk)

    with transaction.atomic():
        existing = (
            RazorpayWhatsAppInternalSendAttempt.objects.filter(
                idempotency_key=idempotency
            )
            .select_for_update()
            .first()
        )
        if existing is not None:
            return {
                "phase": "7E-Live-A",
                "created": False,
                "reused": True,
                "attempt": (
                    serialize_phase7e_live_internal_send_attempt(
                        existing
                    )
                ),
                "blockers": [],
                "warnings": [PHASE_7E_LIVE_WARNING],
                "nextAction": (
                    "phase7e_live_attempt_pending_director_signoff"
                ),
            }

        attempt = RazorpayWhatsAppInternalSendAttempt(
            source_phase7e_gate=gate,
            source_phase7d_attempt=gate.source_phase7d_attempt,
            source_phase7b_gate=gate.source_phase7b_gate,
            source_phase6t_lock=gate.source_phase6t_lock,
            status=(
                RazorpayWhatsAppInternalSendAttempt.Status.PENDING_DIRECTOR_SIGNOFF
            ),
            template_name=template_name[:120],
            template_language=template_language[:16],
            allowed_recipient_last4=last4,
            recipient_scope=(
                RazorpayWhatsAppInternalSendAttempt.RecipientScope.INTERNAL_STAFF_ALLOW_LIST
            ),
            provider_message_id="",
            provider_status="",
            safe_request_summary={
                "template_name": template_name[:120],
                "template_language": template_language[:16],
                "recipient_scope": "internal_staff_allow_list",
                "allowed_recipient_last4": last4,
                "internal_test_only": True,
            },
            safe_response_summary={},
            recorded_signoff_window_valid=None,
            recorded_signoff_window_start_utc=None,
            recorded_signoff_window_end_utc=None,
            provider_call_attempted=False,
            meta_cloud_call_attempted=False,
            whatsapp_message_created=False,
            whatsapp_message_queued=False,
            customer_notification_sent=False,
            business_mutation_was_made=False,
            real_customer_allowed=False,
            real_customer_phone_used=False,
            claim_vault_grounded=bool(gate.claim_vault_grounded),
            idempotency_key=idempotency,
            idempotency_lock_acquired=False,
            director_signoff_text="",
            director_signoff_present=False,
            operator_name="",
            confirm_internal_whatsapp_send=False,
            env_flag_snapshot_at_each_step={"prepare": snapshot},
            kill_switch_snapshot_at_each_step={"prepare": kill},
            safety_invariants_snapshot={
                "phase": "7E-Live-A",
                "internalStaffOnly": True,
                "approvedTemplateOnly": True,
                "freeformMedicalTextAllowed": False,
            },
            before_counts=before,
            after_counts=before,
            blockers=[],
            warnings=[PHASE_7E_LIVE_WARNING],
            next_action=(
                "phase7e_live_attempt_pending_director_signoff"
            ),
            requested_by=requested_by,
        )
        assert_phase7e_live_no_business_mutation(
            attempt, before_counts=before
        )
        try:
            attempt.save()
        except IntegrityError:
            attempt = (
                RazorpayWhatsAppInternalSendAttempt.objects.get(
                    idempotency_key=idempotency
                )
            )
            return {
                "phase": "7E-Live-A",
                "created": False,
                "reused": True,
                "attempt": (
                    serialize_phase7e_live_internal_send_attempt(
                        attempt
                    )
                ),
                "blockers": [],
                "warnings": [PHASE_7E_LIVE_WARNING],
                "nextAction": (
                    "phase7e_live_attempt_pending_director_signoff"
                ),
            }

    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=(
            f"Phase 7E-Live attempt prepared attempt_id={attempt.pk} "
            f"phase7e_gate_id={gate.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7E-Live-A",
        "created": True,
        "reused": False,
        "attempt": (
            serialize_phase7e_live_internal_send_attempt(attempt)
        ),
        "blockers": [],
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": (
            "phase7e_live_attempt_pending_director_signoff"
        ),
    }


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


def _attempt_lookup(
    attempt_id: int,
) -> Optional[RazorpayWhatsAppInternalSendAttempt]:
    return (
        RazorpayWhatsAppInternalSendAttempt.objects.filter(
            pk=attempt_id
        ).first()
    )


def approve_phase7e_live_internal_send(
    attempt_id: int,
    *,
    reviewed_by=None,
    reason: str = "",
    director_signoff: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_approve_reason_required"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "supply_reason",
        }
    if not director_signoff.strip():
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": [
                "phase7e_live_approve_director_signoff_required"
            ],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "supply_director_signoff",
        }
    if not _flag_phase7e_live_enabled():
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": [
                "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED_must_be_true"
            ],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "enable_phase7e_live_lifecycle_flag",
        }

    attempt = _attempt_lookup(attempt_id)
    if attempt is None:
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_attempt_not_found"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if (
        attempt.status
        != RazorpayWhatsAppInternalSendAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    ):
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": (
                serialize_phase7e_live_internal_send_attempt(attempt)
            ),
            "blockers": [
                f"phase7e_live_attempt_status_{attempt.status}_not_transitionable"
            ],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_status",
        }

    before = _business_row_counts()
    assert_phase7e_live_no_business_mutation(
        attempt, before_counts=before
    )

    attempt.status = (
        RazorpayWhatsAppInternalSendAttempt.Status.APPROVED_FOR_INTERNAL_ONE_SHOT_SEND
    )
    attempt.approved_at = timezone.now()
    attempt.reviewed_by = reviewed_by
    attempt.next_action = (
        "approved_for_internal_one_shot_send_execute_via_cli_only"
    )
    attempt.save()

    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            f"Phase 7E-Live attempt approved attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(
            attempt,
            extra={
                "reason_excerpt": (reason or "")[:120],
                "director_signoff_present": True,
            },
        ),
    )
    return {
        "phase": "7E-Live-A",
        "ok": True,
        "attempt": serialize_phase7e_live_internal_send_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": (
            "approved_for_internal_one_shot_send_execute_via_cli_only"
        ),
    }


def reject_phase7e_live_internal_send(
    attempt_id: int,
    *,
    rejected_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_reject_reason_required"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "supply_reason",
        }
    attempt = _attempt_lookup(attempt_id)
    if attempt is None:
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_attempt_not_found"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status not in {
        RazorpayWhatsAppInternalSendAttempt.Status.DRAFT,
        RazorpayWhatsAppInternalSendAttempt.Status.PENDING_DIRECTOR_SIGNOFF,
        RazorpayWhatsAppInternalSendAttempt.Status.APPROVED_FOR_INTERNAL_ONE_SHOT_SEND,
        RazorpayWhatsAppInternalSendAttempt.Status.BLOCKED,
    }:
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": (
                serialize_phase7e_live_internal_send_attempt(attempt)
            ),
            "blockers": [
                f"phase7e_live_reject_refused_for_status_{attempt.status}"
            ],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_status",
        }

    before = _business_row_counts()
    assert_phase7e_live_no_business_mutation(
        attempt, before_counts=before
    )
    attempt.status = (
        RazorpayWhatsAppInternalSendAttempt.Status.REJECTED
    )
    attempt.rejected_at = timezone.now()
    attempt.rejected_by = rejected_by
    attempt.reject_reason = (reason or "")[:1000]
    attempt.next_action = "phase7e_live_attempt_rejected"
    attempt.save()

    write_event(
        kind=AUDIT_KIND_REJECTED,
        text=(
            f"Phase 7E-Live attempt rejected attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload=_audit_attempt_payload(
            attempt,
            extra={"reason_excerpt": (reason or "")[:120]},
        ),
    )
    return {
        "phase": "7E-Live-A",
        "ok": True,
        "attempt": serialize_phase7e_live_internal_send_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": "phase7e_live_attempt_rejected",
    }


# ---------------------------------------------------------------------------
# Execute (CLI-only)
# ---------------------------------------------------------------------------


def execute_phase7e_live_internal_send(
    attempt_id: int,
    *,
    confirmed_by=None,
    director_signoff: str = "",
    operator_name: str = "",
    confirm_internal_whatsapp_send: bool = False,
) -> dict[str, Any]:
    """The ONLY callable that may issue a Meta Cloud WhatsApp send in
    Phase 7E-Live-A.

    Refuses unless EVERY pre-condition holds:

    1. ``PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED=True``
    2. ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE=True``
    3. attempt status == ``approved_for_internal_one_shot_send``
    4. attempt is allow-list scoped (recipient_scope =
       ``internal_staff_allow_list``)
    5. recipient last-4 resolves to an allow-list E.164 number
    6. non-empty ``director_signoff`` with structured
       ``BEGIN_UTC=...`` / ``END_UTC=...`` markers; window ≤ 15 min;
       window ≥ now - 24h; ``now ∈ [window_start, window_end]``
    7. non-empty ``operator_name``
    8. ``confirm_internal_whatsapp_send=True``
    9. ``RuntimeKillSwitch.enabled`` true
    10. all six WhatsApp broad-automation flags are false
    11. attempt has no prior ``provider_call_attempted=True``
        (idempotency lock)

    On success: ONE Meta Cloud template send via the lazy-import
    :func:`_send_internal_template_via_meta_cloud`. Records the safe
    summary on the attempt row only; sets ``provider_call_attempted=True``,
    ``meta_cloud_call_attempted=True``, ``whatsapp_message_created=True``
    when the provider returned a message id. NEVER queues broad
    automation. NEVER mutates real ``Order`` / ``Payment`` /
    ``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead`` rows.
    """
    attempt = _attempt_lookup(attempt_id)
    if attempt is None:
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_attempt_not_found"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_id",
        }

    blockers: list[str] = []
    if not _flag_phase7e_live_enabled():
        blockers.append(
            "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED_must_be_true"
        )
    if not _flag_whatsapp_limited_test_mode():
        blockers.append(
            "WHATSAPP_LIVE_META_LIMITED_TEST_MODE_must_be_true"
        )
    if (
        attempt.status
        != RazorpayWhatsAppInternalSendAttempt.Status.APPROVED_FOR_INTERNAL_ONE_SHOT_SEND
    ):
        blockers.append(
            f"phase7e_live_attempt_status_must_be_approved_was_{attempt.status}"
        )
    if attempt.provider_call_attempted:
        blockers.append(
            "phase7e_live_attempt_already_executed_idempotency_lock"
        )
    if (
        attempt.recipient_scope
        != RazorpayWhatsAppInternalSendAttempt.RecipientScope.INTERNAL_STAFF_ALLOW_LIST
    ):
        blockers.append(
            "phase7e_live_recipient_scope_must_be_internal_staff_allow_list"
        )

    allowed_full = _resolve_allowed_recipient(
        attempt.allowed_recipient_last4 or ""
    )
    if allowed_full is None:
        blockers.append(
            "phase7e_live_recipient_last4_no_longer_on_allow_list"
        )

    if not director_signoff.strip():
        blockers.append("director_signoff_must_be_non_empty")

    # Phase 7D-Hotfix-1: structured UTC window guard (15-min cap).
    parsed_window = parse_director_signoff_window(director_signoff)
    if parsed_window is None:
        if director_signoff.strip():
            blockers.append(
                "phase7e_live_director_signoff_missing_structured_utc_window"
            )
    else:
        window_validation = validate_within_director_window(
            parsed_window
        )
        if not window_validation.valid:
            for entry in window_validation.blockers:
                if entry == "director_signoff_window_end_must_be_after_start":
                    blockers.append(
                        "phase7e_live_director_signoff_malformed_structured_utc_window"
                    )
                elif entry.startswith(
                    "director_signoff_window_too_long"
                ):
                    blockers.append(
                        "phase7e_live_director_signoff_window_too_long_max_15_min"
                    )
                elif entry == (
                    "director_signoff_window_stale_more_than_24h_old"
                ):
                    blockers.append(
                        "phase7e_live_director_signoff_window_stale_more_than_24h_old"
                    )
                elif entry == (
                    "now_outside_director_signoff_utc_window_before_start"
                ):
                    blockers.append(
                        "phase7e_live_now_before_director_signoff_utc_window_start"
                    )
                elif entry == (
                    "now_outside_director_signoff_utc_window_after_end"
                ):
                    blockers.append(
                        "phase7e_live_now_after_director_signoff_utc_window_end"
                    )
                else:
                    blockers.append(f"phase7e_live_{entry}")

    if not operator_name.strip():
        blockers.append("operator_name_must_be_non_empty")
    if not confirm_internal_whatsapp_send:
        blockers.append(
            "confirm_internal_whatsapp_send_must_be_true"
        )

    snapshot = _capture_env_flag_snapshot()
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

    kill = _kill_switch_state()
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")

    attempt.env_flag_snapshot_at_each_step = {
        **(attempt.env_flag_snapshot_at_each_step or {}),
        "execute_start": snapshot,
    }
    attempt.kill_switch_snapshot_at_each_step = {
        **(attempt.kill_switch_snapshot_at_each_step or {}),
        "execute_start": kill,
    }

    if blockers:
        attempt.blockers = list(blockers)
        attempt.status = (
            RazorpayWhatsAppInternalSendAttempt.Status.BLOCKED
        )
        attempt.save(
            update_fields=[
                "blockers",
                "status",
                "env_flag_snapshot_at_each_step",
                "kill_switch_snapshot_at_each_step",
                "updated_at",
            ]
        )
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=(
                f"Phase 7E-Live execute blocked attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_attempt_payload(
                attempt, extra={"blockers": list(blockers)}
            ),
        )
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": (
                serialize_phase7e_live_internal_send_attempt(attempt)
            ),
            "blockers": list(blockers),
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "fix_phase7e_live_execute_blockers",
        }

    # All gates green. Acquire idempotency lock + persist signoff window.
    attempt.idempotency_lock_acquired = True
    attempt.director_signoff_text = (director_signoff or "")[:1000]
    attempt.director_signoff_present = True
    attempt.operator_name = (operator_name or "")[:120]
    attempt.confirm_internal_whatsapp_send = True
    attempt.executed_by = confirmed_by
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
            "confirm_internal_whatsapp_send",
            "executed_by",
            "env_flag_snapshot_at_each_step",
            "kill_switch_snapshot_at_each_step",
            "recorded_signoff_window_valid",
            "recorded_signoff_window_start_utc",
            "recorded_signoff_window_end_utc",
            "updated_at",
        ]
    )

    before = _business_row_counts()
    summary: dict[str, Any] = {}
    sdk_error: Optional[str] = None
    try:
        attempt.provider_call_attempted = True
        attempt.meta_cloud_call_attempted = True
        attempt.save(
            update_fields=[
                "provider_call_attempted",
                "meta_cloud_call_attempted",
                "updated_at",
            ]
        )
        response = _send_internal_template_via_meta_cloud(
            to_e164=allowed_full or "",
            template_name=attempt.template_name,
            template_language=attempt.template_language,
            attempt_id=attempt.pk,
        )
        summary = _summarize_meta_response(response)
    except Phase7ELiveExecutionError as exc:
        sdk_error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        sdk_error = f"unexpected:{exc.__class__.__name__}"

    attempt.env_flag_snapshot_at_each_step = {
        **(attempt.env_flag_snapshot_at_each_step or {}),
        "execute_end": _capture_env_flag_snapshot(),
    }
    attempt.kill_switch_snapshot_at_each_step = {
        **(attempt.kill_switch_snapshot_at_each_step or {}),
        "execute_end": _kill_switch_state(),
    }
    attempt.after_counts = _business_row_counts()

    if sdk_error or not summary.get("message_id"):
        attempt.status = (
            RazorpayWhatsAppInternalSendAttempt.Status.FAILED
        )
        attempt.failed_at = timezone.now()
        attempt.warnings = list(attempt.warnings or []) + (
            [f"phase7e_live_execute_failed:{sdk_error}"]
            if sdk_error
            else ["phase7e_live_execute_succeeded_with_no_message_id"]
        )
        attempt.save()
        try:
            assert_phase7e_live_no_business_mutation(
                attempt, before_counts=attempt.before_counts or {}
            )
        except ValueError:  # pragma: no cover - already audited
            pass
        write_event(
            kind=AUDIT_KIND_FAILED,
            text=(
                f"Phase 7E-Live execute failed attempt_id={attempt.pk}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload=_audit_attempt_payload(attempt),
        )
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": (
                serialize_phase7e_live_internal_send_attempt(attempt)
            ),
            "blockers": (
                [f"phase7e_live_execute_failed:{sdk_error}"]
                if sdk_error
                else ["phase7e_live_execute_succeeded_with_no_message_id"]
            ),
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "phase7e_live_execute_failed_review_attempt",
        }

    attempt.provider_message_id = summary["message_id"]
    attempt.provider_status = summary["status"] or "sent"
    attempt.safe_response_summary = summary
    attempt.whatsapp_message_created = True
    attempt.status = (
        RazorpayWhatsAppInternalSendAttempt.Status.EXECUTED
    )
    attempt.executed_at = timezone.now()
    attempt.next_action = (
        "phase7e_live_executed_record_rollback_when_director_directs"
    )
    attempt.save()

    assert_phase7e_live_no_business_mutation(
        attempt, before_counts=attempt.before_counts or {}
    )

    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=(
            f"Phase 7E-Live execute succeeded attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(attempt),
    )
    return {
        "phase": "7E-Live-A",
        "ok": True,
        "attempt": serialize_phase7e_live_internal_send_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": (
            "phase7e_live_executed_record_rollback_when_director_directs"
        ),
    }


# ---------------------------------------------------------------------------
# Rollback (record-only)
# ---------------------------------------------------------------------------


def rollback_phase7e_live_internal_send(
    attempt_id: int,
    *,
    rolled_back_by=None,
    reason: str = "",
) -> dict[str, Any]:
    if not reason.strip():
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_rollback_reason_required"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "supply_reason",
        }
    attempt = _attempt_lookup(attempt_id)
    if attempt is None:
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": None,
            "blockers": ["phase7e_live_attempt_not_found"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_id",
        }
    if attempt.status == (
        RazorpayWhatsAppInternalSendAttempt.Status.ARCHIVED
    ):
        return {
            "phase": "7E-Live-A",
            "ok": False,
            "attempt": (
                serialize_phase7e_live_internal_send_attempt(attempt)
            ),
            "blockers": ["phase7e_live_attempt_already_archived"],
            "warnings": [PHASE_7E_LIVE_WARNING],
            "nextAction": "verify_attempt_status",
        }

    attempt.rolled_back_at = timezone.now()
    attempt.rollback_reason = (reason or "")[:1000]
    attempt.rolled_back_by = rolled_back_by
    if attempt.status != (
        RazorpayWhatsAppInternalSendAttempt.Status.ROLLBACK_RECORDED
    ):
        attempt.status = (
            RazorpayWhatsAppInternalSendAttempt.Status.ROLLBACK_RECORDED
        )
    attempt.next_action = "phase7e_live_rollback_recorded"
    attempt.save()

    assert_phase7e_live_no_business_mutation(
        attempt, before_counts=attempt.before_counts or {}
    )

    write_event(
        kind=AUDIT_KIND_ROLLBACK_RECORDED,
        text=(
            f"Phase 7E-Live rollback recorded attempt_id={attempt.pk}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_attempt_payload(
            attempt,
            extra={"reason_excerpt": (reason or "")[:120]},
        ),
    )
    return {
        "phase": "7E-Live-A",
        "ok": True,
        "attempt": serialize_phase7e_live_internal_send_attempt(attempt),
        "blockers": [],
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": "phase7e_live_rollback_recorded",
    }


# ---------------------------------------------------------------------------
# Summary / readiness
# ---------------------------------------------------------------------------


def summarize_phase7e_live_internal_send_attempts(
    limit: int = 25,
) -> dict[str, Any]:
    qs = RazorpayWhatsAppInternalSendAttempt.objects.all().order_by(
        "-created_at"
    )
    statuses = [
        s.value
        for s in RazorpayWhatsAppInternalSendAttempt.Status
    ]
    counts = {s: qs.filter(status=s).count() for s in statuses}
    items = [
        serialize_phase7e_live_internal_send_attempt(row)
        for row in qs[: max(1, min(limit, 200))]
    ]
    return {"phase": "7E-Live-A", "counts": counts, "items": items}


def inspect_phase7e_live_internal_send_readiness() -> dict[str, Any]:
    summary = summarize_phase7e_live_internal_send_attempts(limit=10)
    counts = summary["counts"]
    snapshot = _capture_env_flag_snapshot()
    kill = _kill_switch_state()
    allowed_size = len(_allowed_test_numbers())

    blockers: list[str] = []
    if not _flag_whatsapp_limited_test_mode():
        blockers.append(
            "WHATSAPP_LIVE_META_LIMITED_TEST_MODE_must_be_true"
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
    if allowed_size == 0:
        blockers.append(
            "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS_must_contain_at_least_one_entry"
        )

    if blockers:
        next_action = "fix_phase7e_live_safety_blockers"
    elif not _flag_phase7e_live_enabled():
        next_action = (
            "enable_phase7e_live_internal_whatsapp_send_flag_for_review_only"
        )
    elif (
        counts.get("pending_director_signoff", 0) == 0
        and counts.get("approved_for_internal_one_shot_send", 0) == 0
    ):
        next_action = (
            "prepare_phase7e_live_internal_send_attempt_against_approved_phase7e_gate"
        )
    elif counts.get("approved_for_internal_one_shot_send", 0) == 0:
        next_action = "approve_phase7e_live_internal_send_attempt"
    else:
        next_action = (
            "phase7e_live_attempt_approved_execute_only_with_separate_director_window"
        )

    safe_to_run = bool(
        not blockers
        and counts.get("approved_for_internal_one_shot_send", 0) >= 1
        and _flag_phase7e_live_enabled()
    )

    return {
        "phase": "7E-Live-A",
        "status": (
            "internal_allowed_list_whatsapp_one_shot_send_only"
        ),
        "latestCompletedPhase": "7E",
        "nextPhase": (
            "phase_7e_live_a_executed_or_phase_7e_live_b_not_approved"
        ),
        "phase7ELiveInternalWhatsAppSendEnabled": (
            _flag_phase7e_live_enabled()
        ),
        "whatsAppLiveMetaLimitedTestMode": (
            _flag_whatsapp_limited_test_mode()
        ),
        "allowedTestNumbersCount": allowed_size,
        "envFlagSnapshot": snapshot,
        "killSwitch": kill,
        "attemptCounts": counts,
        "items": summary["items"],
        "phase7ELiveSendsToRealCustomer": False,
        "phase7ELiveMutatesBusinessRow": False,
        "phase7ELiveCustomerNotification": False,
        "phase7ELiveSupportsFreeformMedicalText": False,
        "phase7ELiveRecipientScope": "internal_staff_allow_list",
        "executionPath": "cli_only",
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "safeToRunPhase7ELiveSend": safe_to_run,
        "blockers": blockers,
        "warnings": [PHASE_7E_LIVE_WARNING],
        "nextAction": next_action,
        "recentAttempts": summary["items"][:10],
    }


def emit_readiness_inspected_audit(report: dict[str, Any]) -> None:
    counts = report.get("attemptCounts") or {}
    write_event(
        kind=AUDIT_KIND_READINESS,
        text="Phase 7E-Live internal WhatsApp send readiness inspected",
        tone=AuditEvent.Tone.INFO,
        payload=_safe_audit_payload(
            {
                "phase7e_live_send_enabled": bool(
                    report.get(
                        "phase7ELiveInternalWhatsAppSendEnabled"
                    )
                ),
                "limited_test_mode": bool(
                    report.get("whatsAppLiveMetaLimitedTestMode")
                ),
                "allowed_test_numbers_count": int(
                    report.get("allowedTestNumbersCount") or 0
                ),
                "pending_director_signoff": int(
                    counts.get("pending_director_signoff") or 0
                ),
                "approved": int(
                    counts.get("approved_for_internal_one_shot_send")
                    or 0
                ),
                "executed": int(counts.get("executed") or 0),
                "failed": int(counts.get("failed") or 0),
                "rollback_recorded": int(
                    counts.get("rollback_recorded") or 0
                ),
                "blockers": list(report.get("blockers") or []),
                "next_action": report.get("nextAction") or "",
                "kill_switch_enabled": (
                    report.get("killSwitch", {}) or {}
                ).get("enabled", True),
            }
        ),
    )


__all__ = (
    "PHASE_7E_LIVE_WARNING",
    "PHASE_7E_LIVE_FORBIDDEN_PAYLOAD_KEYS",
    "AUDIT_KIND_READINESS",
    "AUDIT_KIND_PREVIEWED",
    "AUDIT_KIND_PREPARED",
    "AUDIT_KIND_APPROVED",
    "AUDIT_KIND_EXECUTED",
    "AUDIT_KIND_FAILED",
    "AUDIT_KIND_ROLLBACK_RECORDED",
    "AUDIT_KIND_REJECTED",
    "AUDIT_KIND_BLOCKED",
    "Phase7ELiveExecutionError",
    "assert_phase7e_live_no_business_mutation",
    "preview_phase7e_live_internal_send",
    "prepare_phase7e_live_internal_send",
    "approve_phase7e_live_internal_send",
    "reject_phase7e_live_internal_send",
    "execute_phase7e_live_internal_send",
    "rollback_phase7e_live_internal_send",
    "inspect_phase7e_live_internal_send_readiness",
    "summarize_phase7e_live_internal_send_attempts",
    "serialize_phase7e_live_internal_send_attempt",
    "emit_readiness_inspected_audit",
)
