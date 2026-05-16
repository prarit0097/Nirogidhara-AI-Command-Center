"""Phase 10C — Razorpay Payment Link Refresh Gate service layer.

Test mode is the default; live mode is gated with the same structured
Director directive + UTC window + runtime env flag pattern as Phase
7E-Live-B / 7G-Live. Phase 10C is the only path to write
``Payment.payment_url`` from a fresh Razorpay link; the previous URL
is archived to ``Phase10CPaymentLinkRefreshGate.previous_payment_url``
so rollback can restore it.

Phase 10C NEVER:
- Sends WhatsApp / freeform messages (Phase 7E-Live-B owns delivery).
- Makes a call.
- Mutates ``Order`` state or any other business row beyond
  ``Payment.payment_url`` (asserted in tests by checking row counts +
  patching the outbound funcs).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order
from apps.payments.integrations.razorpay_client import (
    PaymentLinkResult,
    RazorpayClientError,
    cancel_payment_link,
    create_payment_link_for_refresh,
)
from apps.payments.models import Payment, Phase10CPaymentLinkRefreshGate
from apps.saas.utc_window import (
    parse_director_signoff_window,
    validate_execution_window,
)


PHASE = "10C"
ENV_FLAG = "PHASE10C_PAYMENT_LINK_REFRESH_ENABLED"
SANDBOX_PHONE_PLACEHOLDER = "0000000000"

ALLOWED_STAGES: frozenset[str] = frozenset(
    {
        Order.Stage.CONFIRMED.value,
        Order.Stage.ORDER_PUNCHED.value,
        Order.Stage.INTERESTED.value,
        Order.Stage.CONFIRMATION_PENDING.value,
    }
)
BLOCKED_STAGES: frozenset[str] = frozenset(
    {
        Order.Stage.RTO.value,
        Order.Stage.OUT_FOR_DELIVERY.value,
        Order.Stage.CANCELLED.value,
        Order.Stage.DELIVERED.value,
        Order.Stage.DISPATCHED.value,
        Order.Stage.PAYMENT_LINK_SENT.value,
        Order.Stage.NEW_LEAD.value,
        "internal_sandbox",
    }
)
PROCEEDABLE_PAYMENT_STATUSES: frozenset[str] = frozenset(
    {
        Payment.Status.PENDING.value,
        Payment.Status.PARTIAL.value,
    }
)

AUDIT_PREPARED = "phase10c.gate.prepared"
AUDIT_APPROVED = "phase10c.gate.approved"
AUDIT_EXECUTE_REQUESTED = "phase10c.gate.execute.requested"
AUDIT_EXECUTE_SUCCESS = "phase10c.gate.execute.success"
AUDIT_EXECUTE_FAILED = "phase10c.gate.execute.failed"
AUDIT_ROLLBACK_SUCCESS = "phase10c.gate.rollback.success"
AUDIT_ROLLBACK_FAILED = "phase10c.gate.rollback.failed"
AUDIT_CANCELLED = "phase10c.gate.cancelled"
AUDIT_LIVE_REFUSED = "phase10c.live_mode.refused"


@dataclass(frozen=True)
class Phase10CGateResult:
    ok: bool
    gate_id: int | None
    status: str
    mode: str
    blockers: list[str]
    next_action: str
    payload: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "ok": self.ok,
            "gate_id": self.gate_id,
            "status": self.status,
            "mode": self.mode,
            "blockers": list(self.blockers),
            "next_action": self.next_action,
            **self.payload,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag_enabled() -> bool:
    return bool(
        getattr(settings, ENV_FLAG, False)
        or str(os.environ.get(ENV_FLAG, "")).lower() == "true"
    )


def _runtime_razorpay_mode() -> str:
    return (
        str(getattr(settings, "RAZORPAY_MODE", "mock") or "mock").lower()
    )


def _kill_switch_state() -> dict[str, Any]:
    """Phase 7E-Live-B Hotfix-1 Postgres-safe pattern."""
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
    return {
        "enabled": bool(row.enabled),
        "model": "RuntimeKillSwitch",
        "id": row.pk,
    }


def _validate_payment_for_refresh(payment: Payment) -> list[str]:
    blockers: list[str] = []
    if payment.status not in PROCEEDABLE_PAYMENT_STATUSES:
        blockers.append(
            f"payment_status_not_proceedable:{payment.status}"
        )
    if not payment.amount or int(payment.amount) <= 0:
        blockers.append("payment_amount_invalid")
    return blockers


def _validate_stage(order: Order) -> str | None:
    stage = (order.stage or "").strip()
    if stage in BLOCKED_STAGES:
        return f"stage_blocked:{stage}"
    if stage not in ALLOWED_STAGES:
        return f"stage_not_in_allow_list:{stage}"
    return None


def _resolve_customer_phone(payment: Payment, order: Order) -> str:
    """Reuse the Phase 10A fallback chain locally."""
    candidates = [
        (payment.customer_phone or "").strip(),
        (order.phone or "").strip(),
    ]
    return next((p for p in candidates if p), "")


def _is_sandbox() -> bool:
    try:
        from apps.ai_governance.sandbox import is_sandbox_enabled

        return bool(is_sandbox_enabled())
    except Exception:  # pragma: no cover - defensive
        return False


def _serialize_gate(gate: Phase10CPaymentLinkRefreshGate) -> dict[str, Any]:
    return {
        "gate_id": gate.pk,
        "payment_id": gate.payment_id,
        "mode": gate.mode,
        "status": gate.status,
        "operator_name": gate.operator_name,
        "operator_note": gate.operator_note,
        "intent": gate.intent,
        "force_replace": gate.force_replace,
        "previous_payment_url": gate.previous_payment_url,
        "new_payment_url": gate.new_payment_url,
        "razorpay_link_id": gate.razorpay_link_id,
        "razorpay_short_url": gate.razorpay_short_url,
        "recorded_signoff_window_valid": gate.recorded_signoff_window_valid,
        "prepared_at": gate.prepared_at,
        "approved_at": gate.approved_at,
        "executed_at": gate.executed_at,
        "rolled_back_at": gate.rolled_back_at,
        "cancelled_at": gate.cancelled_at,
        "sandbox": gate.sandbox,
    }


# ---------------------------------------------------------------------------
# prepare_gate
# ---------------------------------------------------------------------------


def prepare_gate(
    *,
    payment_id: str,
    mode: str = "test",
    force_replace: bool = False,
    operator_name: str,
    operator_note: str = "",
) -> Phase10CGateResult:
    blockers: list[str] = []
    mode = (mode or "test").strip().lower()
    if mode not in {"test", "live"}:
        blockers.append(f"mode_invalid:{mode}")
    if not (operator_name or "").strip():
        blockers.append("operator_name_required")
    payment_id = (payment_id or "").strip()
    if not payment_id:
        blockers.append("payment_id_required")

    if blockers:
        return Phase10CGateResult(
            ok=False,
            gate_id=None,
            status="blocked",
            mode=mode,
            blockers=blockers,
            next_action="fix_phase10c_prepare_blockers",
            payload={},
        )

    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None:
        return Phase10CGateResult(
            ok=False,
            gate_id=None,
            status="blocked",
            mode=mode,
            blockers=[f"payment_not_found:{payment_id}"],
            next_action="fix_phase10c_prepare_blockers",
            payload={},
        )

    blockers.extend(_validate_payment_for_refresh(payment))

    order = Order.objects.filter(pk=payment.order_id).first()
    if order is None:
        blockers.append(f"order_not_found:{payment.order_id}")
    else:
        stage_problem = _validate_stage(order)
        if stage_problem:
            blockers.append(stage_problem)

    if (payment.payment_url or "").strip() and not force_replace:
        blockers.append("payment_url_already_present_use_force_replace")

    if blockers:
        return Phase10CGateResult(
            ok=False,
            gate_id=None,
            status="blocked",
            mode=mode,
            blockers=blockers,
            next_action="fix_phase10c_prepare_blockers",
            payload={},
        )

    gate = Phase10CPaymentLinkRefreshGate.objects.create(
        payment=payment,
        mode=mode,
        status=Phase10CPaymentLinkRefreshGate.Status.DRAFT,
        operator_name=(operator_name or "").strip()[:120],
        operator_note=(operator_note or "")[:4000],
        force_replace=bool(force_replace),
        prepared_at=timezone.now(),
        sandbox=_is_sandbox(),
        metadata={
            "payment_id": payment.id,
            "order_id": payment.order_id,
            "stage": order.stage if order else "",
            "amount": int(payment.amount or 0),
            "customer_name": (
                (order.customer_name or "").strip()
                if order
                else (payment.customer or "").strip()
            ),
            "previous_url_was_empty": not bool(payment.payment_url),
        },
    )
    write_event(
        kind=AUDIT_PREPARED,
        text=(
            f"Phase 10C gate {gate.pk} prepared for payment {payment.id} "
            f"(mode={mode}, force_replace={force_replace})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "payment_id": payment.id,
            "order_id": payment.order_id,
            "mode": mode,
            "force_replace": bool(force_replace),
        },
    )
    return Phase10CGateResult(
        ok=True,
        gate_id=gate.pk,
        status=gate.status,
        mode=mode,
        blockers=[],
        next_action="approve_phase10c_payment_link_refresh_gate",
        payload=_serialize_gate(gate),
    )


# ---------------------------------------------------------------------------
# approve_gate
# ---------------------------------------------------------------------------


def approve_gate(
    *,
    gate_id: int,
    operator_name: str,
    intent: str,
    director_signoff: str,
) -> Phase10CGateResult:
    gate = Phase10CPaymentLinkRefreshGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return Phase10CGateResult(
            ok=False,
            gate_id=gate_id,
            status="not_found",
            mode="",
            blockers=["gate_not_found"],
            next_action="fix_phase10c_approve_blockers",
            payload={},
        )
    blockers: list[str] = []
    if gate.status != Phase10CPaymentLinkRefreshGate.Status.DRAFT:
        blockers.append(
            f"gate_status_{gate.status}_not_draft"
        )
    if not (operator_name or "").strip():
        blockers.append("operator_name_required")
    if not (intent or "").strip():
        blockers.append("intent_required")

    parsed_window = None
    if gate.mode == Phase10CPaymentLinkRefreshGate.Mode.LIVE.value:
        parsed_window = parse_director_signoff_window(director_signoff or "")
        validation = validate_execution_window(parsed_window)
        if not validation.valid:
            for entry in validation.blockers:
                blockers.append(f"phase10c_{entry}")
    else:
        # Test mode: free-text signoff is acceptable. Require non-empty.
        if not (director_signoff or "").strip():
            blockers.append("director_signoff_required")

    if blockers:
        write_event(
            kind="phase10c.gate.approve.blocked",
            text=f"Phase 10C gate {gate.pk} approve blocked",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": PHASE,
                "gate_id": gate.pk,
                "blockers": blockers,
            },
        )
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=blockers,
            next_action="fix_phase10c_approve_blockers",
            payload=_serialize_gate(gate),
        )

    gate.status = Phase10CPaymentLinkRefreshGate.Status.APPROVED
    gate.operator_name = (operator_name or "").strip()[:120]
    gate.intent = (intent or "")[:4000]
    gate.director_signoff = director_signoff or ""
    if parsed_window is not None:
        gate.recorded_signoff_window_start_utc = parsed_window.window_start_utc
        gate.recorded_signoff_window_end_utc = parsed_window.window_end_utc
        gate.recorded_signoff_window_valid = True
    gate.approved_at = timezone.now()
    gate.save()
    write_event(
        kind=AUDIT_APPROVED,
        text=f"Phase 10C gate {gate.pk} approved (mode={gate.mode}).",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "mode": gate.mode,
        },
    )
    return Phase10CGateResult(
        ok=True,
        gate_id=gate.pk,
        status=gate.status,
        mode=gate.mode,
        blockers=[],
        next_action="execute_phase10c_payment_link_refresh_gate",
        payload=_serialize_gate(gate),
    )


# ---------------------------------------------------------------------------
# execute_gate
# ---------------------------------------------------------------------------


def _validate_live_mode_preconditions(
    gate: Phase10CPaymentLinkRefreshGate, *, confirm_live: bool
) -> list[str]:
    blockers: list[str] = []
    if not _flag_enabled():
        blockers.append(f"{ENV_FLAG}_must_be_true")
    if not confirm_live:
        blockers.append("confirm_phase10c_payment_link_refresh_live_required")
    if not _kill_switch_state().get("enabled", True):
        blockers.append("runtime_kill_switch_disabled")
    if not gate.recorded_signoff_window_valid:
        blockers.append("recorded_signoff_window_invalid")
    else:
        validation = validate_execution_window(
            parse_director_signoff_window(gate.director_signoff or "")
        )
        if not validation.valid:
            for entry in validation.blockers:
                blockers.append(f"phase10c_runtime_{entry}")
    if _runtime_razorpay_mode() != "live":
        blockers.append(
            f"razorpay_mode_runtime_{_runtime_razorpay_mode()}_not_live"
        )
    return blockers


def _validate_test_mode_preconditions(
    gate: Phase10CPaymentLinkRefreshGate,
) -> list[str]:
    blockers: list[str] = []
    runtime_mode = _runtime_razorpay_mode()
    if runtime_mode == "live":
        # Refuse running a test-mode gate against the live Razorpay account.
        blockers.append("razorpay_mode_runtime_live_but_gate_mode_test")
    return blockers


def execute_gate(
    *,
    gate_id: int,
    operator_name: str,
    confirm_live: bool = False,
) -> Phase10CGateResult:
    gate = Phase10CPaymentLinkRefreshGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return Phase10CGateResult(
            ok=False,
            gate_id=gate_id,
            status="not_found",
            mode="",
            blockers=["gate_not_found"],
            next_action="fix_phase10c_execute_blockers",
            payload={},
        )
    blockers: list[str] = []
    if gate.status != Phase10CPaymentLinkRefreshGate.Status.APPROVED:
        blockers.append(f"gate_status_{gate.status}_not_approved")
    if not (operator_name or "").strip():
        blockers.append("operator_name_required")

    write_event(
        kind=AUDIT_EXECUTE_REQUESTED,
        text=f"Phase 10C gate {gate.pk} execute requested (mode={gate.mode}).",
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "mode": gate.mode,
        },
    )

    if gate.mode == Phase10CPaymentLinkRefreshGate.Mode.LIVE.value:
        live_blockers = _validate_live_mode_preconditions(
            gate, confirm_live=confirm_live
        )
        blockers.extend(live_blockers)
    else:
        blockers.extend(_validate_test_mode_preconditions(gate))

    payment = gate.payment
    order = Order.objects.filter(pk=payment.order_id).first()
    if order is None:
        blockers.append(f"order_not_found:{payment.order_id}")
    else:
        stage_problem = _validate_stage(order)
        if stage_problem:
            blockers.append(stage_problem)

    if blockers:
        if gate.mode == Phase10CPaymentLinkRefreshGate.Mode.LIVE.value:
            write_event(
                kind=AUDIT_LIVE_REFUSED,
                text=f"Phase 10C live execute refused gate {gate.pk}",
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "phase": PHASE,
                    "gate_id": gate.pk,
                    "blockers": blockers,
                },
            )
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=blockers,
            next_action="fix_phase10c_execute_blockers",
            payload=_serialize_gate(gate),
        )

    customer_phone = _resolve_customer_phone(payment, order)
    customer_name = (
        (order.customer_name or "").strip()
        or (payment.customer or "").strip()
        or "Customer"
    )

    try:
        with transaction.atomic():
            result: PaymentLinkResult = create_payment_link_for_refresh(
                payment_id=payment.id,
                order_id=payment.order_id,
                amount=int(payment.amount or 0),
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=(payment.customer_email or "").strip(),
                operator_name=operator_name,
            )
            gate.previous_payment_url = (payment.payment_url or "")
            gate.new_payment_url = result.short_url
            gate.razorpay_link_id = result.plink_id
            gate.razorpay_short_url = result.short_url
            gate.operator_name = (operator_name or "").strip()[:120]
            gate.status = Phase10CPaymentLinkRefreshGate.Status.EXECUTED
            gate.executed_at = timezone.now()
            gate.metadata = {
                **(gate.metadata or {}),
                "razorpay_status": result.status,
                "executed_runtime_mode": _runtime_razorpay_mode(),
            }
            gate.save()
            payment.payment_url = result.short_url
            payment.save(update_fields=["payment_url", "updated_at"])
    except RazorpayClientError as exc:
        gate.status = Phase10CPaymentLinkRefreshGate.Status.FAILED
        gate.metadata = {
            **(gate.metadata or {}),
            "execute_error": str(exc),
        }
        gate.save(update_fields=["status", "metadata", "updated_at"])
        write_event(
            kind=AUDIT_EXECUTE_FAILED,
            text=f"Phase 10C gate {gate.pk} execute failed: {exc}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": PHASE,
                "gate_id": gate.pk,
                "error": str(exc),
            },
        )
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=[f"razorpay_error:{exc}"],
            next_action="review_phase10c_failed_gate",
            payload=_serialize_gate(gate),
        )

    write_event(
        kind=AUDIT_EXECUTE_SUCCESS,
        text=(
            f"Phase 10C gate {gate.pk} executed; payment "
            f"{payment.id} link refreshed."
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "payment_id": payment.id,
            "razorpay_link_id": gate.razorpay_link_id,
            "mode": gate.mode,
            "force_replace": gate.force_replace,
        },
    )
    return Phase10CGateResult(
        ok=True,
        gate_id=gate.pk,
        status=gate.status,
        mode=gate.mode,
        blockers=[],
        next_action="phase10c_executed_payment_url_updated",
        payload=_serialize_gate(gate),
    )


# ---------------------------------------------------------------------------
# rollback_gate
# ---------------------------------------------------------------------------


def rollback_gate(
    *, gate_id: int, operator_name: str
) -> Phase10CGateResult:
    gate = Phase10CPaymentLinkRefreshGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return Phase10CGateResult(
            ok=False,
            gate_id=gate_id,
            status="not_found",
            mode="",
            blockers=["gate_not_found"],
            next_action="fix_phase10c_rollback_blockers",
            payload={},
        )
    if gate.status != Phase10CPaymentLinkRefreshGate.Status.EXECUTED:
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=[f"gate_status_{gate.status}_not_executed"],
            next_action="fix_phase10c_rollback_blockers",
            payload=_serialize_gate(gate),
        )
    if not (operator_name or "").strip():
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=["operator_name_required"],
            next_action="fix_phase10c_rollback_blockers",
            payload=_serialize_gate(gate),
        )

    cancel_result = cancel_payment_link(plink_id=gate.razorpay_link_id)
    razorpay_cancelled = cancel_result.get("status") in {"cancelled", "mocked"}

    payment = gate.payment
    with transaction.atomic():
        payment.payment_url = gate.previous_payment_url or ""
        payment.save(update_fields=["payment_url", "updated_at"])
        gate.status = Phase10CPaymentLinkRefreshGate.Status.ROLLED_BACK
        gate.rolled_back_at = timezone.now()
        gate.operator_name = (operator_name or "").strip()[:120]
        gate.metadata = {
            **(gate.metadata or {}),
            "rollback_razorpay_status": cancel_result.get("status"),
            "rollback_razorpay_provider_status": cancel_result.get(
                "provider_status"
            ),
        }
        gate.save()

    if razorpay_cancelled:
        write_event(
            kind=AUDIT_ROLLBACK_SUCCESS,
            text=(
                f"Phase 10C gate {gate.pk} rolled back; Razorpay link "
                f"{gate.razorpay_link_id} cancelled."
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phase": PHASE,
                "gate_id": gate.pk,
                "payment_id": payment.id,
                "razorpay_status": cancel_result.get("status"),
            },
        )
    else:
        write_event(
            kind=AUDIT_ROLLBACK_FAILED,
            text=(
                f"Phase 10C gate {gate.pk} rollback recorded BUT Razorpay "
                f"refused to cancel link {gate.razorpay_link_id}: "
                f"{cancel_result.get('raw')}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": PHASE,
                "gate_id": gate.pk,
                "razorpay_status": cancel_result.get("status"),
                "raw": cancel_result.get("raw"),
            },
        )
    return Phase10CGateResult(
        ok=True,
        gate_id=gate.pk,
        status=gate.status,
        mode=gate.mode,
        blockers=[],
        next_action="phase10c_rollback_recorded",
        payload={
            **_serialize_gate(gate),
            "razorpay_cancel_status": cancel_result.get("status"),
        },
    )


# ---------------------------------------------------------------------------
# cancel_gate
# ---------------------------------------------------------------------------


def cancel_gate(
    *, gate_id: int, operator_name: str, reason: str = ""
) -> Phase10CGateResult:
    gate = Phase10CPaymentLinkRefreshGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return Phase10CGateResult(
            ok=False,
            gate_id=gate_id,
            status="not_found",
            mode="",
            blockers=["gate_not_found"],
            next_action="fix_phase10c_cancel_blockers",
            payload={},
        )
    if gate.status not in {
        Phase10CPaymentLinkRefreshGate.Status.DRAFT,
        Phase10CPaymentLinkRefreshGate.Status.APPROVED,
    }:
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=[
                f"gate_status_{gate.status}_not_cancellable_use_rollback"
            ],
            next_action="fix_phase10c_cancel_blockers",
            payload=_serialize_gate(gate),
        )
    if not (operator_name or "").strip():
        return Phase10CGateResult(
            ok=False,
            gate_id=gate.pk,
            status=gate.status,
            mode=gate.mode,
            blockers=["operator_name_required"],
            next_action="fix_phase10c_cancel_blockers",
            payload=_serialize_gate(gate),
        )
    gate.status = Phase10CPaymentLinkRefreshGate.Status.CANCELLED
    gate.cancelled_at = timezone.now()
    gate.operator_name = (operator_name or "").strip()[:120]
    gate.metadata = {
        **(gate.metadata or {}),
        "cancel_reason": (reason or "")[:1000],
    }
    gate.save()
    write_event(
        kind=AUDIT_CANCELLED,
        text=f"Phase 10C gate {gate.pk} cancelled.",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": PHASE,
            "gate_id": gate.pk,
            "reason": (reason or "")[:200],
        },
    )
    return Phase10CGateResult(
        ok=True,
        gate_id=gate.pk,
        status=gate.status,
        mode=gate.mode,
        blockers=[],
        next_action="phase10c_gate_cancelled",
        payload=_serialize_gate(gate),
    )


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def inspect_gate(*, gate_id: int) -> dict[str, Any]:
    gate = Phase10CPaymentLinkRefreshGate.objects.filter(pk=gate_id).first()
    if gate is None:
        return {
            "phase": PHASE,
            "ok": False,
            "gate_id": gate_id,
            "error": "gate_not_found",
        }
    payment = gate.payment
    order = Order.objects.filter(pk=payment.order_id).first()
    return {
        "phase": PHASE,
        "ok": True,
        **_serialize_gate(gate),
        "payment_amount": int(payment.amount or 0),
        "payment_status": payment.status,
        "order_stage": order.stage if order else None,
        "customer_name": (
            (order.customer_name or "").strip()
            if order
            else (payment.customer or "").strip()
        ),
        "runtime_razorpay_mode": _runtime_razorpay_mode(),
        "env_flag_enabled": _flag_enabled(),
        "kill_switch": _kill_switch_state(),
    }
