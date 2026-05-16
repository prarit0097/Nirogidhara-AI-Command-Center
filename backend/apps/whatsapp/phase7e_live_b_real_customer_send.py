"""Phase 7E-Live-B real-customer WhatsApp send gate.

This module owns the CLI-only governance flow for one approved template
send per gate to one real customer phone. It never exposes an
approve/execute API surface and never edits ``.env*`` files.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer
from apps.saas.utc_window import (
    parse_director_signoff_window,
    validate_within_director_window,
)

from . import services as whatsapp_services
from .models import Phase7ELiveBRealCustomerSendGate, WhatsAppMessage
from .tasks import send_whatsapp_message


PHASE = "7E-Live-B"
ENV_FLAG = "PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED"
APPROVED_TEMPLATE_NAMES = {
    "confirmation_reminder",
    "delivery_reminder",
    "rto_rescue",
    "reorder_reminder",
    "payment_reminder",
    "usage_explanation",
}
FORBIDDEN_ACTIONS = (
    "broadcast",
    "campaign",
    "bulk_send",
    "ai_freeform",
    "order_mutation",
    "payment_mutation",
    "courier_call",
    "frontend_execute",
    "api_execute",
)

AUDIT_KIND_INSPECTED = "phase7e.live_b.readiness_inspected"
AUDIT_KIND_PREPARED = "phase7e.live_b.prepared"
AUDIT_KIND_APPROVED = "phase7e.live_b.approved"
AUDIT_KIND_EXECUTED = "phase7e.live_b.executed"
AUDIT_KIND_FAILED = "phase7e.live_b.failed"
AUDIT_KIND_CANCELLED = "phase7e.live_b.cancelled"
AUDIT_KIND_BLOCKED = "phase7e.live_b.blocked"


def _flag_enabled() -> bool:
    return bool(
        getattr(settings, ENV_FLAG, False)
        or str(os.environ.get(ENV_FLAG, "")).lower() == "true"
    )


def _kill_switch_state() -> dict[str, Any]:
    # Phase 7E-Live-B Hotfix-1: an explicitly disabled global kill
    # switch row anywhere in the table means the kill switch is OFF
    # (no longer protecting). The legacy ``.first()`` lookup returned
    # undefined ordering across DB engines, so a seeded ``enabled=True``
    # row could mask a freshly created ``enabled=False`` row on
    # Postgres. Returning the disabled row whenever one exists is the
    # safety-correct semantic.
    try:
        from apps.saas.models import RuntimeKillSwitch

        disabled = (
            RuntimeKillSwitch.objects.filter(scope="global", enabled=False)
            .order_by("-pk")
            .first()
        )
        if disabled is not None:
            return {
                "enabled": False,
                "model": "RuntimeKillSwitch",
                "id": disabled.pk,
            }
        row = RuntimeKillSwitch.objects.filter(scope="global").order_by("-pk").first()
    except Exception:  # pragma: no cover - defensive
        return {"enabled": True, "model": "lookup_failed_treated_as_enabled"}
    if row is None:
        return {"enabled": True, "model": "no_row_treated_as_enabled"}
    return {"enabled": bool(row.enabled), "model": "RuntimeKillSwitch", "id": row.pk}


def _last4(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits


def _normalise_phone(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _mask_phone(phone: str) -> str:
    last = _last4(phone)
    return f"***{last}" if last else ""


def _hash_signoff(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def _execution_context_key(gate: Phase7ELiveBRealCustomerSendGate) -> str:
    params = dict(gate.template_params or {})
    if gate.template_name == "payment_reminder":
        return str(params.get("payment_id") or params.get("payment_url") or "").strip()
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def _prior_executed_duplicate_gate_exists(
    gate: Phase7ELiveBRealCustomerSendGate,
) -> bool:
    target_phone = _normalise_phone(gate.target_phone)
    target_context = _execution_context_key(gate)
    candidates = (
        Phase7ELiveBRealCustomerSendGate.objects.filter(
            status=Phase7ELiveBRealCustomerSendGate.Status.EXECUTED,
            template_name=gate.template_name,
        )
        .exclude(pk=gate.pk)
        .only("target_phone", "template_name", "template_params")
    )
    for existing in candidates:
        if _normalise_phone(existing.target_phone) != target_phone:
            continue
        if _execution_context_key(existing) == target_context:
            return True
    return False


def _gate_counts() -> dict[str, int]:
    return {
        status: Phase7ELiveBRealCustomerSendGate.objects.filter(status=status).count()
        for status in Phase7ELiveBRealCustomerSendGate.Status.values
    }


def _locked_flags_all_false() -> bool:
    return not Phase7ELiveBRealCustomerSendGate.objects.filter(
        payment_mutation_made=True
    ).exists() and not Phase7ELiveBRealCustomerSendGate.objects.filter(
        order_mutation_made=True
    ).exists() and not Phase7ELiveBRealCustomerSendGate.objects.filter(
        courier_called=True
    ).exists()


def serialize_gate(gate: Phase7ELiveBRealCustomerSendGate) -> dict[str, Any]:
    return {
        "id": gate.pk,
        "status": gate.status,
        "targetMasked": _mask_phone(gate.target_phone),
        "targetCustomerName": gate.target_customer_name,
        "templateName": gate.template_name,
        "operatorName": gate.operator_name,
        "recordedSignoffWindowStartUtc": gate.recorded_signoff_window_start_utc,
        "recordedSignoffWindowEndUtc": gate.recorded_signoff_window_end_utc,
        "executedAt": gate.executed_at,
        "failedAt": gate.failed_at,
        "cancelledAt": gate.cancelled_at,
        "metaMessageId": gate.meta_message_id,
        "blockers": list(gate.blockers or []),
        "nextAction": gate.next_action,
        "customerNotificationSent": gate.customer_notification_sent,
        "paymentMutationMade": gate.payment_mutation_made,
        "orderMutationMade": gate.order_mutation_made,
        "courierCalled": gate.courier_called,
        "createdAt": gate.created_at,
        "updatedAt": gate.updated_at,
    }


def summarize_gates(*, limit: int = 25) -> dict[str, Any]:
    rows = Phase7ELiveBRealCustomerSendGate.objects.order_by("-created_at")[
        : max(1, min(limit, 200))
    ]
    return {
        "phase": PHASE,
        "counts": _gate_counts(),
        "items": [serialize_gate(row) for row in rows],
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
    }


def inspect_gate_readiness(*, emit_audit: bool = True) -> dict[str, Any]:
    flag = _flag_enabled()
    kill = _kill_switch_state()
    blockers: list[str] = []
    if not flag:
        blockers.append(f"{ENV_FLAG}_must_be_true")
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    report = {
        "phase": PHASE,
        "status": "ready" if not blockers else "blocked",
        "flagEnabled": flag,
        "killSwitch": kill,
        "gateCounts": _gate_counts(),
        "lockedFlagsAllFalse": _locked_flags_all_false(),
        "forbiddenActions": list(FORBIDDEN_ACTIONS),
        "warnings": [
            "CLI-only one-shot real-customer WhatsApp send; no rollback is possible."
        ],
        "blockers": blockers,
        "nextAction": (
            "prepare_phase7e_live_b_real_customer_gate"
            if not blockers
            else "fix_phase7e_live_b_readiness_blockers"
        ),
    }
    if emit_audit:
        write_event(
            kind=AUDIT_KIND_INSPECTED,
            text="Phase 7E-Live-B readiness inspected",
            tone=AuditEvent.Tone.INFO,
            payload={"phase": PHASE, "status": report["status"], "blockers": blockers},
        )
    return report


def _parse_template_params(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("template_params_must_be_json_object")
    return parsed


def prepare_gate(
    *,
    target_phone: str,
    target_customer_name: str,
    template_name: str,
    template_params: str | dict[str, Any] | None = None,
    operator_name: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    phone = (target_phone or "").strip()
    customer_name = (target_customer_name or "").strip()
    template = (template_name or "").strip()
    operator = (operator_name or "").strip()
    params: dict[str, Any] = {}
    if not phone:
        blockers.append("target_phone_required")
    if not customer_name:
        blockers.append("target_customer_name_required")
    if not operator:
        blockers.append("operator_name_must_be_non_empty")
    if template not in APPROVED_TEMPLATE_NAMES:
        blockers.append("phase7e_live_b_template_name_not_approved")
    try:
        params = _parse_template_params(template_params)
    except (TypeError, ValueError, json.JSONDecodeError):
        blockers.append("template_params_must_be_json_object")
    if blockers:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="Phase 7E-Live-B prepare blocked",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": PHASE, "blockers": blockers, "template_name": template},
        )
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": None,
            "status": "blocked",
            "blockers": blockers,
            "nextAction": "fix_phase7e_live_b_prepare_blockers",
        }
    gate = Phase7ELiveBRealCustomerSendGate.objects.create(
        target_phone=phone,
        target_customer_name=customer_name,
        template_name=template,
        template_params=params,
        operator_name=operator,
        next_action="approve_phase7e_live_b_real_customer_gate",
    )
    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 7E-Live-B gate prepared gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={"phase": PHASE, "gate_id": gate.pk, "template_name": template},
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "status": gate.status,
        "templateName": gate.template_name,
        "targetMasked": _mask_phone(gate.target_phone),
        "blockers": [],
        "nextAction": gate.next_action,
    }


def _approval_blockers(
    gate: Phase7ELiveBRealCustomerSendGate | None,
    *,
    director_signoff: str,
    operator_name: str,
    confirm: bool,
    required_status: str,
) -> tuple[list[str], Any]:
    blockers: list[str] = []
    parsed_window = None
    if not _flag_enabled():
        blockers.append(f"{ENV_FLAG}_must_be_true")
    if not _kill_switch_state().get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if not confirm:
        blockers.append("confirm_phase7e_live_b_real_customer_send_must_be_true")
    if not (operator_name or "").strip():
        blockers.append("operator_name_must_be_non_empty")
    if gate is None:
        blockers.append("phase7e_live_b_gate_not_found")
        return blockers, parsed_window
    if gate.status != required_status:
        blockers.append(f"phase7e_live_b_gate_status_{gate.status}_not_{required_status}")
    if gate.template_name not in APPROVED_TEMPLATE_NAMES:
        blockers.append("phase7e_live_b_template_name_not_approved")
    if _prior_executed_duplicate_gate_exists(gate):
        blockers.append("phase7e_live_b_duplicate_executed_gate_exists")
    signoff = director_signoff or ""
    required = [
        f"phase7e_live_b_gate_id_{gate.pk}",
        f"target_phone_{_last4(gate.target_phone)}",
        f"template_{gate.template_name}",
        "phase7eLiveBApproval",
    ]
    for phrase in required:
        if phrase not in signoff:
            blockers.append(f"phase7e_live_b_director_signoff_missing_{phrase}")
    parsed_window = parse_director_signoff_window(signoff)
    validation = validate_within_director_window(parsed_window)
    if not validation.valid:
        for entry in validation.blockers:
            blockers.append(f"phase7e_live_b_{entry}")
    return blockers, parsed_window


def approve_gate(
    gate_id: int,
    *,
    director_signoff: str,
    operator_name: str,
    confirm: bool,
) -> dict[str, Any]:
    gate = Phase7ELiveBRealCustomerSendGate.objects.filter(pk=gate_id).first()
    blockers, parsed_window = _approval_blockers(
        gate,
        director_signoff=director_signoff,
        operator_name=operator_name,
        confirm=confirm,
        required_status=Phase7ELiveBRealCustomerSendGate.Status.DRAFT,
    )
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate_id,
            "status": "not_found",
            "blockers": blockers,
            "nextAction": "fix_phase7e_live_b_approval_blockers",
        }
    if blockers:
        gate.blockers = blockers
        gate.next_action = "fix_phase7e_live_b_approval_blockers"
        gate.save(update_fields=["blockers", "next_action", "updated_at"])
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7E-Live-B approval blocked gate_id={gate.pk}",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": PHASE, "gate_id": gate.pk, "blockers": blockers},
        )
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate.pk,
            "status": gate.status,
            "blockers": blockers,
            "nextAction": gate.next_action,
        }
    gate.status = Phase7ELiveBRealCustomerSendGate.Status.APPROVED
    gate.operator_name = (operator_name or "").strip()[:120]
    gate.director_signoff_text_hash = _hash_signoff(director_signoff)
    gate.recorded_signoff_window_start_utc = parsed_window.window_start_utc
    gate.recorded_signoff_window_end_utc = parsed_window.window_end_utc
    gate.blockers = []
    gate.next_action = "execute_phase7e_live_b_real_customer_send"
    gate.save()
    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=f"Phase 7E-Live-B gate approved gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={"phase": PHASE, "gate_id": gate.pk, "template_name": gate.template_name},
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "status": gate.status,
        "blockers": [],
        "nextAction": gate.next_action,
    }


def _extract_message_id(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("message_id") or result.get("metaMessageId") or "")
    message = getattr(result, "message", None)
    if message is None:
        return ""
    return str(getattr(message, "provider_message_id", "") or getattr(message, "id", ""))


def execute_gate(
    gate_id: int,
    *,
    director_signoff: str,
    operator_name: str,
    confirm: bool,
) -> dict[str, Any]:
    gate = Phase7ELiveBRealCustomerSendGate.objects.filter(pk=gate_id).first()
    blockers, parsed_window = _approval_blockers(
        gate,
        director_signoff=director_signoff,
        operator_name=operator_name,
        confirm=confirm,
        required_status=Phase7ELiveBRealCustomerSendGate.Status.APPROVED,
    )
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate_id,
            "status": "not_found",
            "blockers": blockers,
            "nextAction": "fix_phase7e_live_b_execute_blockers",
        }
    customer = Customer.objects.filter(phone=gate.target_phone).first()
    if customer is None:
        blockers.append("phase7e_live_b_target_customer_not_found")
    if blockers:
        gate.blockers = blockers
        gate.next_action = "fix_phase7e_live_b_execute_blockers"
        gate.save(update_fields=["blockers", "next_action", "updated_at"])
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7E-Live-B execute blocked gate_id={gate.pk}",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": PHASE, "gate_id": gate.pk, "blockers": blockers},
        )
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate.pk,
            "status": gate.status,
            "blockers": blockers,
            "nextAction": gate.next_action,
        }
    try:
        with transaction.atomic():
            queued = whatsapp_services.queue_template_message(
                customer=customer,
                action_key=f"whatsapp.{gate.template_name}",
                variables=gate.template_params or {},
                triggered_by="phase7e_live_b_cli_execute",
                actor_role="director",
                actor_agent="phase7e_live_b",
                idempotency_key=f"phase7e_live_b::gate::{gate.pk}",
                extra_metadata={
                    "phase": PHASE,
                    "gate_id": gate.pk,
                    "one_shot_real_customer_send": True,
                },
                override_limited_test_mode=True,
            )
            meta_message_id = _extract_message_id(queued)
            message = getattr(queued, "message", None)
            if message is not None:
                send_whatsapp_message.delay(message.id)
                sent = WhatsAppMessage.objects.filter(pk=message.id).first()
                if sent is not None:
                    meta_message_id = sent.provider_message_id or sent.id
            gate.status = Phase7ELiveBRealCustomerSendGate.Status.EXECUTED
            gate.executed_at = timezone.now()
            gate.operator_name = (operator_name or "").strip()[:120]
            gate.director_signoff_text_hash = _hash_signoff(director_signoff)
            gate.recorded_signoff_window_start_utc = parsed_window.window_start_utc
            gate.recorded_signoff_window_end_utc = parsed_window.window_end_utc
            gate.meta_message_id = meta_message_id
            gate.customer_notification_sent = True
            gate.blockers = []
            gate.next_action = "phase7e_live_b_completed_no_rollback_possible"
            if gate.payment_mutation_made or gate.order_mutation_made or gate.courier_called:
                raise RuntimeError("phase7e_live_b_locked_false_flag_changed")
            gate.save()
    except Exception as exc:
        gate.status = Phase7ELiveBRealCustomerSendGate.Status.FAILED
        gate.failed_at = timezone.now()
        gate.blockers = [f"phase7e_live_b_execute_failed:{exc.__class__.__name__}"]
        gate.next_action = "phase7e_live_b_execute_failed_manual_review"
        gate.save()
        write_event(
            kind=AUDIT_KIND_FAILED,
            text=f"Phase 7E-Live-B execute failed gate_id={gate.pk}",
            tone=AuditEvent.Tone.WARNING,
            payload={"phase": PHASE, "gate_id": gate.pk, "blockers": gate.blockers},
        )
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate.pk,
            "status": gate.status,
            "blockers": gate.blockers,
            "nextAction": gate.next_action,
        }
    write_event(
        kind=AUDIT_KIND_EXECUTED,
        text=f"Phase 7E-Live-B execute succeeded gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "template_name": gate.template_name,
            "meta_message_id": gate.meta_message_id,
        },
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "metaMessageId": gate.meta_message_id,
        "status": gate.status,
        "blockers": [],
        "nextAction": gate.next_action,
    }


def cancel_gate(gate_id: int, *, reason: str, operator_name: str) -> dict[str, Any]:
    gate = Phase7ELiveBRealCustomerSendGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate_id,
            "status": "not_found",
            "blockers": ["phase7e_live_b_gate_not_found"],
            "nextAction": "fix_phase7e_live_b_cancel_blockers",
        }
    blockers: list[str] = []
    if gate.status == Phase7ELiveBRealCustomerSendGate.Status.EXECUTED:
        blockers.append("phase7e_live_b_executed_gate_cannot_be_cancelled")
    if not (reason or "").strip():
        blockers.append("phase7e_live_b_cancel_reason_required")
    if not (operator_name or "").strip():
        blockers.append("operator_name_must_be_non_empty")
    if blockers:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate.pk,
            "status": gate.status,
            "blockers": blockers,
            "nextAction": "fix_phase7e_live_b_cancel_blockers",
        }
    gate.status = Phase7ELiveBRealCustomerSendGate.Status.CANCELLED
    gate.cancelled_at = timezone.now()
    gate.operator_name = (operator_name or "").strip()[:120]
    gate.blockers = []
    gate.next_action = "phase7e_live_b_gate_cancelled"
    gate.save()
    write_event(
        kind=AUDIT_KIND_CANCELLED,
        text=f"Phase 7E-Live-B gate cancelled gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload={"phase": PHASE, "gate_id": gate.pk, "reason": reason[:200]},
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "status": gate.status,
        "blockers": [],
        "nextAction": gate.next_action,
    }
