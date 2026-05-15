"""Phase 7G-Live real-customer Delhivery dispatch one-shot controlled gate.

CLI-only governance flow for exactly one Delhivery live AWB creation
against exactly one confirmed customer order per approved gate.
Rollback attempts the Delhivery cancellation API and records the
result honestly — Delhivery may refuse cancellation if the AWB is
already in transit.

This module follows the Phase 7E-Live-B Hotfix-1 fixed kill-switch
helper pattern: an explicit ``scope="global", enabled=False`` row
wins over any seeded ``enabled=True`` default, ordered by ``-pk``
for determinism across DB engines.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order
from apps.saas.utc_window import (
    parse_director_signoff_window,
    validate_within_director_window,
)

from .models import Phase7GLiveRealCustomerDispatchGate, Shipment


PHASE = "7G-Live"
ENV_FLAG = "PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED"
DISPATCH_READY_STAGES = {Order.Stage.CONFIRMED.value}
FORBIDDEN_ACTIONS = (
    "broadcast",
    "bulk_dispatch",
    "auto_dispatch",
    "ai_dispatch",
    "payment_mutation",
    "order_payment_status_mutation",
    "whatsapp_send",
    "razorpay_call",
    "frontend_execute",
    "api_execute",
)

AUDIT_KIND_INSPECTED = "phase7g.live.readiness_inspected"
AUDIT_KIND_PREPARED = "phase7g.live.prepared"
AUDIT_KIND_APPROVED = "phase7g.live.approved"
AUDIT_KIND_EXECUTED = "phase7g.live.executed"
AUDIT_KIND_FAILED = "phase7g.live.failed"
AUDIT_KIND_CANCELLED = "phase7g.live.cancelled"
AUDIT_KIND_ROLLED_BACK = "phase7g.live.rolled_back"
AUDIT_KIND_BLOCKED = "phase7g.live.blocked"


def _flag_enabled() -> bool:
    return bool(
        getattr(settings, ENV_FLAG, False)
        or str(os.environ.get(ENV_FLAG, "")).lower() == "true"
    )


def _delhivery_mode() -> str:
    return str(getattr(settings, "DELHIVERY_MODE", "mock") or "mock").lower()


def _kill_switch_state() -> dict[str, Any]:
    """Phase 7E-Live-B Hotfix-1 pattern.

    An explicit ``scope="global"`` row with ``enabled=False`` always
    wins over any seeded enabled default. Ordered by ``-pk`` to keep
    behaviour deterministic on Postgres and SQLite alike.
    """
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
        row = (
            RuntimeKillSwitch.objects.filter(scope="global")
            .order_by("-pk")
            .first()
        )
    except Exception:  # pragma: no cover - defensive
        return {"enabled": True, "model": "lookup_failed_treated_as_enabled"}
    if row is None:
        return {"enabled": True, "model": "no_row_treated_as_enabled"}
    return {"enabled": bool(row.enabled), "model": "RuntimeKillSwitch", "id": row.pk}


def _hash_signoff(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def _gate_counts() -> dict[str, int]:
    return {
        status: Phase7GLiveRealCustomerDispatchGate.objects.filter(
            status=status
        ).count()
        for status in Phase7GLiveRealCustomerDispatchGate.Status.values
    }


def _locked_flags_all_false() -> bool:
    return not Phase7GLiveRealCustomerDispatchGate.objects.filter(
        payment_mutation_made=True
    ).exists() and not Phase7GLiveRealCustomerDispatchGate.objects.filter(
        order_payment_status_changed=True
    ).exists() and not Phase7GLiveRealCustomerDispatchGate.objects.filter(
        whatsapp_sent=True
    ).exists() and not Phase7GLiveRealCustomerDispatchGate.objects.filter(
        razorpay_called=True
    ).exists()


def serialize_gate(gate: Phase7GLiveRealCustomerDispatchGate) -> dict[str, Any]:
    return {
        "id": gate.pk,
        "status": gate.status,
        "targetOrderId": gate.target_order_id,
        "operatorName": gate.operator_name,
        "recordedSignoffWindowStartUtc": gate.recorded_signoff_window_start_utc,
        "recordedSignoffWindowEndUtc": gate.recorded_signoff_window_end_utc,
        "executedAt": gate.executed_at,
        "failedAt": gate.failed_at,
        "cancelledAt": gate.cancelled_at,
        "awbNumber": gate.awb_number,
        "delhiveryShipmentId": gate.delhivery_shipment_id,
        "cancellationAttemptedAt": gate.cancellation_attempted_at,
        "cancellationResult": dict(gate.cancellation_result or {}),
        "blockers": list(gate.blockers or []),
        "nextAction": gate.next_action,
        "paymentMutationMade": gate.payment_mutation_made,
        "orderPaymentStatusChanged": gate.order_payment_status_changed,
        "whatsappSent": gate.whatsapp_sent,
        "razorpayCalled": gate.razorpay_called,
        "createdAt": gate.created_at,
        "updatedAt": gate.updated_at,
    }


def summarize_gates(*, limit: int = 25) -> dict[str, Any]:
    rows = Phase7GLiveRealCustomerDispatchGate.objects.order_by("-created_at")[
        : max(1, min(limit, 200))
    ]
    return {
        "phase": PHASE,
        "counts": _gate_counts(),
        "items": [serialize_gate(row) for row in rows],
        "frontendCanExecute": False,
        "apiEndpointCanExecute": False,
        "apiEndpointCanApprove": False,
        "apiEndpointCanRollback": False,
    }


def inspect_gate_readiness(*, emit_audit: bool = True) -> dict[str, Any]:
    flag = _flag_enabled()
    kill = _kill_switch_state()
    mode = _delhivery_mode()
    blockers: list[str] = []
    if not flag:
        blockers.append(f"{ENV_FLAG}_must_be_true")
    if not kill.get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if mode != "live":
        blockers.append("delhivery_mode_must_be_live_for_execute")
    report = {
        "phase": PHASE,
        "status": "ready" if not blockers else "blocked",
        "flagEnabled": flag,
        "delhiveryMode": mode,
        "killSwitch": kill,
        "gateCounts": _gate_counts(),
        "lockedFlagsAllFalse": _locked_flags_all_false(),
        "forbiddenActions": list(FORBIDDEN_ACTIONS),
        "warnings": [
            "CLI-only one-shot real-customer Delhivery dispatch; rollback "
            "attempts AWB cancellation but Delhivery may refuse if already "
            "in transit."
        ],
        "blockers": blockers,
        "nextAction": (
            "prepare_phase7g_live_real_customer_gate"
            if not blockers
            else "fix_phase7g_live_readiness_blockers"
        ),
    }
    if emit_audit:
        write_event(
            kind=AUDIT_KIND_INSPECTED,
            text="Phase 7G-Live readiness inspected",
            tone=AuditEvent.Tone.INFO,
            payload={"phase": PHASE, "status": report["status"], "blockers": blockers},
        )
    return report


def _order_dispatch_ready(order: Order) -> bool:
    return order.stage in DISPATCH_READY_STAGES


def prepare_gate(
    *,
    order_id: str,
    operator_name: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    target_order_id = (order_id or "").strip()
    operator = (operator_name or "").strip()
    if not target_order_id:
        blockers.append("order_id_required")
    if not operator:
        blockers.append("operator_name_must_be_non_empty")
    order = (
        Order.objects.filter(pk=target_order_id).first() if target_order_id else None
    )
    if target_order_id and order is None:
        blockers.append("phase7g_live_target_order_not_found")
    elif order is not None and not _order_dispatch_ready(order):
        blockers.append(
            f"phase7g_live_order_stage_{order.stage}_not_dispatch_ready"
        )
    if blockers:
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text="Phase 7G-Live prepare blocked",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": PHASE,
                "blockers": blockers,
                "target_order_id": target_order_id,
            },
        )
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": None,
            "status": "blocked",
            "blockers": blockers,
            "nextAction": "fix_phase7g_live_prepare_blockers",
        }
    gate = Phase7GLiveRealCustomerDispatchGate.objects.create(
        target_order_id=target_order_id,
        operator_name=operator,
        next_action="approve_phase7g_live_real_customer_gate",
    )
    write_event(
        kind=AUDIT_KIND_PREPARED,
        text=f"Phase 7G-Live gate prepared gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "target_order_id": target_order_id,
        },
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "status": gate.status,
        "orderId": gate.target_order_id,
        "orderState": order.stage if order is not None else "",
        "blockers": [],
        "nextAction": gate.next_action,
    }


def _precondition_blockers(
    gate: Phase7GLiveRealCustomerDispatchGate | None,
    *,
    director_signoff: str,
    operator_name: str,
    confirm: bool,
    required_status: str,
    require_live_mode: bool,
) -> tuple[list[str], Any]:
    blockers: list[str] = []
    parsed_window = None
    if not _flag_enabled():
        blockers.append(f"{ENV_FLAG}_must_be_true")
    if require_live_mode and _delhivery_mode() != "live":
        blockers.append("delhivery_mode_must_be_live_for_execute")
    if not _kill_switch_state().get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if not confirm:
        blockers.append(
            "confirm_phase7g_live_real_customer_dispatch_must_be_true"
        )
    if not (operator_name or "").strip():
        blockers.append("operator_name_must_be_non_empty")
    if gate is None:
        blockers.append("phase7g_live_gate_not_found")
        return blockers, parsed_window
    if gate.status != required_status:
        blockers.append(
            f"phase7g_live_gate_status_{gate.status}_not_{required_status}"
        )
    if (
        Phase7GLiveRealCustomerDispatchGate.objects.filter(
            status=Phase7GLiveRealCustomerDispatchGate.Status.EXECUTED,
            target_order_id=gate.target_order_id,
        )
        .exclude(pk=gate.pk)
        .exists()
    ):
        blockers.append("phase7g_live_prior_executed_gate_for_same_order")
    order = Order.objects.filter(pk=gate.target_order_id).first()
    if order is None:
        blockers.append("phase7g_live_target_order_not_found")
    elif not _order_dispatch_ready(order):
        blockers.append(
            f"phase7g_live_order_stage_{order.stage}_not_dispatch_ready"
        )
    signoff = director_signoff or ""
    required = [
        f"phase7g_live_gate_id_{gate.pk}",
        f"target_order_{gate.target_order_id}",
        "phase7gLiveApproval",
    ]
    for phrase in required:
        if phrase not in signoff:
            blockers.append(f"phase7g_live_director_signoff_missing_{phrase}")
    parsed_window = parse_director_signoff_window(signoff)
    validation = validate_within_director_window(parsed_window)
    if not validation.valid:
        for entry in validation.blockers:
            blockers.append(f"phase7g_live_{entry}")
    return blockers, parsed_window


def approve_gate(
    gate_id: int,
    *,
    director_signoff: str,
    operator_name: str,
    confirm: bool,
) -> dict[str, Any]:
    gate = Phase7GLiveRealCustomerDispatchGate.objects.filter(pk=gate_id).first()
    blockers, parsed_window = _precondition_blockers(
        gate,
        director_signoff=director_signoff,
        operator_name=operator_name,
        confirm=confirm,
        required_status=Phase7GLiveRealCustomerDispatchGate.Status.DRAFT,
        require_live_mode=False,
    )
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate_id,
            "status": "not_found",
            "blockers": blockers,
            "nextAction": "fix_phase7g_live_approval_blockers",
        }
    if blockers:
        gate.blockers = blockers
        gate.next_action = "fix_phase7g_live_approval_blockers"
        gate.save(update_fields=["blockers", "next_action", "updated_at"])
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7G-Live approval blocked gate_id={gate.pk}",
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
    gate.status = Phase7GLiveRealCustomerDispatchGate.Status.APPROVED
    gate.operator_name = (operator_name or "").strip()[:120]
    gate.director_signoff_text_hash = _hash_signoff(director_signoff)
    gate.recorded_signoff_window_start_utc = parsed_window.window_start_utc
    gate.recorded_signoff_window_end_utc = parsed_window.window_end_utc
    gate.blockers = []
    gate.next_action = "execute_phase7g_live_real_customer_dispatch"
    gate.save()
    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=f"Phase 7G-Live gate approved gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "target_order_id": gate.target_order_id,
        },
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "status": gate.status,
        "blockers": [],
        "nextAction": gate.next_action,
    }


def _extract_awb_and_shipment_id(result: Any) -> tuple[str, str]:
    awb = ""
    shipment_id = ""
    if hasattr(result, "awb"):
        awb = str(getattr(result, "awb", "") or "")
    elif isinstance(result, dict):
        awb = str(result.get("awb") or "")
    if hasattr(result, "raw"):
        raw = getattr(result, "raw", None) or {}
        if isinstance(raw, dict):
            packages = raw.get("packages") or []
            if packages and isinstance(packages[0], dict):
                shipment_id = str(
                    packages[0].get("refnum")
                    or packages[0].get("shipment_id")
                    or ""
                )
    return awb, shipment_id


def execute_gate(
    gate_id: int,
    *,
    director_signoff: str,
    operator_name: str,
    confirm: bool,
) -> dict[str, Any]:
    gate = Phase7GLiveRealCustomerDispatchGate.objects.filter(pk=gate_id).first()
    blockers, parsed_window = _precondition_blockers(
        gate,
        director_signoff=director_signoff,
        operator_name=operator_name,
        confirm=confirm,
        required_status=Phase7GLiveRealCustomerDispatchGate.Status.APPROVED,
        require_live_mode=True,
    )
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate_id,
            "status": "not_found",
            "blockers": blockers,
            "nextAction": "fix_phase7g_live_execute_blockers",
        }
    if blockers:
        gate.blockers = blockers
        gate.next_action = "fix_phase7g_live_execute_blockers"
        gate.save(update_fields=["blockers", "next_action", "updated_at"])
        write_event(
            kind=AUDIT_KIND_BLOCKED,
            text=f"Phase 7G-Live execute blocked gate_id={gate.pk}",
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
        order = Order.objects.get(pk=gate.target_order_id)
        # Lazy import — the Delhivery client touches the network only here.
        from apps.shipments import services as _shipments_services

        with transaction.atomic():
            shipment: Shipment = _shipments_services.create_shipment(
                order=order, by_user=None
            )
            awb, shipment_id = _extract_awb_and_shipment_id(shipment)
            if not awb:
                awb = shipment.awb
                shipment_id = (
                    (shipment.raw_response or {}).get("packages", [{}])[0].get(
                        "refnum", ""
                    )
                    if isinstance(shipment.raw_response, dict)
                    else ""
                )
            gate.status = Phase7GLiveRealCustomerDispatchGate.Status.EXECUTED
            gate.executed_at = timezone.now()
            gate.operator_name = (operator_name or "").strip()[:120]
            gate.director_signoff_text_hash = _hash_signoff(director_signoff)
            gate.recorded_signoff_window_start_utc = parsed_window.window_start_utc
            gate.recorded_signoff_window_end_utc = parsed_window.window_end_utc
            gate.awb_number = awb
            gate.delhivery_shipment_id = shipment_id
            gate.blockers = []
            gate.next_action = (
                "rollback_phase7g_live_real_customer_dispatch_optional"
            )
            if (
                gate.payment_mutation_made
                or gate.order_payment_status_changed
                or gate.whatsapp_sent
                or gate.razorpay_called
            ):
                raise RuntimeError("phase7g_live_locked_false_flag_changed")
            gate.save()
    except Exception as exc:
        gate.status = Phase7GLiveRealCustomerDispatchGate.Status.FAILED
        gate.failed_at = timezone.now()
        gate.blockers = [f"phase7g_live_execute_failed:{exc.__class__.__name__}"]
        gate.next_action = "phase7g_live_execute_failed_manual_review"
        gate.save()
        write_event(
            kind=AUDIT_KIND_FAILED,
            text=f"Phase 7G-Live execute failed gate_id={gate.pk}",
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
        text=f"Phase 7G-Live execute succeeded gate_id={gate.pk}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "target_order_id": gate.target_order_id,
            "awb_number": gate.awb_number,
        },
    )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "awbNumber": gate.awb_number,
        "status": gate.status,
        "blockers": [],
        "nextAction": gate.next_action,
    }


def rollback_gate(
    gate_id: int,
    *,
    reason: str,
    operator_name: str,
) -> dict[str, Any]:
    gate = Phase7GLiveRealCustomerDispatchGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate_id,
            "status": "not_found",
            "blockers": ["phase7g_live_gate_not_found"],
            "nextAction": "fix_phase7g_live_rollback_blockers",
        }
    blockers: list[str] = []
    if gate.status != Phase7GLiveRealCustomerDispatchGate.Status.EXECUTED:
        blockers.append(
            f"phase7g_live_gate_status_{gate.status}_not_executed"
        )
    if not (reason or "").strip():
        blockers.append("phase7g_live_rollback_reason_required")
    if not (operator_name or "").strip():
        blockers.append("operator_name_must_be_non_empty")
    if not gate.awb_number:
        blockers.append("phase7g_live_no_awb_to_cancel")
    if blockers:
        return {
            "phase": PHASE,
            "ok": False,
            "gateId": gate.pk,
            "status": gate.status,
            "blockers": blockers,
            "nextAction": "fix_phase7g_live_rollback_blockers",
        }
    # Lazy import keeps the static-file scan honest.
    from apps.shipments.integrations.delhivery_client import cancel_awb

    cancel_result = cancel_awb(awb=gate.awb_number)
    gate.cancellation_attempted_at = timezone.now()
    gate.cancellation_result = dict(cancel_result or {})
    gate.status = (
        Phase7GLiveRealCustomerDispatchGate.Status.ROLLBACK_RECORDED
    )
    gate.operator_name = (operator_name or "").strip()[:120]
    gate.next_action = "phase7g_live_rollback_recorded_no_further_action"
    gate.save()
    write_event(
        kind=AUDIT_KIND_ROLLED_BACK,
        text=f"Phase 7G-Live rollback recorded gate_id={gate.pk}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "awb_number": gate.awb_number,
            "cancellation_status": cancel_result.get("status", ""),
            "reason": (reason or "")[:200],
        },
    )
    note = ""
    status = cancel_result.get("status", "")
    if status not in {"cancelled", "mocked"}:
        note = (
            "Delhivery cancellation rejected or errored; shipment may still "
            "be in transit. Rollback is recorded honestly."
        )
    return {
        "phase": PHASE,
        "ok": True,
        "gateId": gate.pk,
        "awbNumber": gate.awb_number,
        "cancellationResult": gate.cancellation_result,
        "status": gate.status,
        "blockers": [],
        "nextAction": gate.next_action,
        "note": note,
    }
